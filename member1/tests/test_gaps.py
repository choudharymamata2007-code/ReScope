"""Tests for the plan gaps that were closed after the five-company batch run."""
import datetime as dt
import pandas as pd
import pytest
from rescope.api import Member1API
from rescope.cache import DiskCache
from rescope.collectors.industry import IndustryCollector, collect_trends
from rescope.http import Fetcher, FetchError, FetchResult
from rescope.intake.listings import parse_listing_csv
from rescope.intake.resolver import co_mentioned, mention_keys
from rescope.quant.mix import extract_mix, extract_mix_series
from rescope.quant.extract import parse_table_text
from rescope.sample_data import FICTIONAL_UNIVERSE_CSV, build_sample_store, narrative_evidence
from rescope.schema import Role, SourceType
from rescope.store import EvidenceStore
from rescope.tagging.tagger import make_evidence


# ---------- host circuit breaker (batch: 760 s runs, NSE archive timeouts, repeated 403s) ----------
def test_host_is_skipped_after_repeated_refusals(tmp_path):
    calls = []

    def refuse(url, p, h):
        calls.append(url)
        return FetchResult(url, 403, b"")
    f = Fetcher(DiskCache(tmp_path), transport=refuse, min_interval=0, sleep=lambda s: None)
    for i in range(3):
        assert f.get(f"https://blocked.example.invalid/{i}").status == 403
    with pytest.raises(FetchError, match="skipped"):
        f.get("https://blocked.example.invalid/4")
    assert len(calls) == 3                                           # the 4th request was never sent
    assert f.get("https://other.example.invalid/ok").status == 403    # other hosts are unaffected (not skipped yet)


def test_timeouts_trip_the_breaker_and_success_resets_it(tmp_path):
    def timeout(url, p, h):
        raise TimeoutError("read timed out")
    f = Fetcher(DiskCache(tmp_path), transport=timeout, min_interval=0, sleep=lambda s: None)
    with pytest.raises(FetchError):
        f.get("https://slow.example.invalid/a")
    with pytest.raises(FetchError, match="skipped"):
        f.get("https://slow.example.invalid/b")
    ok = Fetcher(DiskCache(tmp_path / "x"), transport=lambda u, p, h: FetchResult(u, 200, b"x"), min_interval=0)
    ok._host_fail["h.example.invalid"] = 2
    ok.get("https://h.example.invalid/a")
    assert ok._host_fail["h.example.invalid"] == 0


def fake_factory(infos):
    class T:
        def __init__(self, sym):
            self.info = infos.get(sym, {})
    return lambda sym: T(sym)


# ---------- peers named in the company's own documents ----------
UNI = parse_listing_csv("NAME OF COMPANY,SYMBOL,Industry\nAlpha Jewels Ltd,ALPHAJ,Jewellery\nKalyan Style Retail Limited,KALSTY,Consumer Durables\n"
                        "Senco Gold Ltd,SENGOLD,Consumer Durables\nRandom Steel Works Ltd,RSTEEL,Metals\nPage Industries Ltd,PAGEIND,Textiles\n")


def test_mention_keys_and_comention():
    c = next(c for c in UNI if c.symbol == "KALSTY")
    assert {"kalyan style retail", "kalyan style"} <= mention_keys(c)
    docs = {"d1": "Competition from Kalyan Style and Senco Gold is rising.", "d2": "Kalyan Style Retail opened stores. Senco Gold too.",
            "d3": "Only Senco Gold is mentioned here.", "d4": "Random Steel Works rose 3%."}
    got = [(c.symbol, n) for c, n in co_mentioned(docs, UNI, {"ALPHAJ"}, min_docs=2)]
    assert got == [("SENGOLD", 3), ("KALSTY", 2)]                   # RSTEEL appears once only; ALPHAJ is the company itself


def test_refine_peers_tops_up_and_flags_availability(tmp_path):
    store = EvidenceStore(":memory:")
    for i, txt in enumerate(["Rivals Kalyan Style and Senco Gold.", "Kalyan Style Retail and Senco Gold expand.", "Senco Gold pricing."]):
        store.add(make_evidence(title=f"d{i}", text=txt, url=f"https://x{i}.example.invalid/a", entity="Alpha Jewels Ltd", role=Role.company,
                                source_type=SourceType.news, tier=4))
    api = Member1API(store=store, cache=DiskCache(tmp_path), universe=UNI, all_listed=UNI, ticker_factory=fake_factory({}))
    prof = api.resolve("Alpha Jewels")
    assert prof.peers == [] or len(prof.peers) < 3
    before = len(prof.peers)
    new = api.refine_peers(prof)
    assert {p.symbol for p in new} >= {"SENGOLD", "KALSTY"} and all(p.mentioned_in_report for p in new)
    assert len(prof.peers) == before + len(new) and any("peers added" in w for w in prof.warnings)


# ---------- industry series: price index feeds the proxy, pairs feed the benchmark ----------
def test_industry_flags_feed_proxy_and_benchmark(tmp_path):
    csv = "Date,Index\n" + "\n".join(f"{d},{v}" for d, v in [
        ("31/03/2024", 100), ("30/06/2024", 101), ("30/09/2024", 102), ("31/12/2024", 103), ("31/03/2025", 104),
        ("30/06/2025", 106), ("30/09/2025", 108), ("31/12/2025", 110), ("31/03/2026", 112)]) + "\n"
    f = tmp_path / "cpi.csv"
    f.write_text(csv)
    cfg = [{"kind": "csv", "id": "cpi_fict", "title": "CPI", "url": "https://stats.example.invalid/cpi", "path": str(f), "date_col": "Date",
            "value_col": "Index", "unit": "index", "price_index": True, "pairs_with": "gross_margin"}]
    store = EvidenceStore(":memory:")
    IndustryCollector(Fetcher(DiskCache(tmp_path / "c"), transport=lambda *a: None, min_interval=0), store).collect(cfg)
    api = Member1API(store=store, cache=None)
    infl, imap = api.industry_helpers()
    assert imap == {"gross_margin": "cpi_fict"}
    assert infl["Q4 FY26"] == pytest.approx(112 / 104 - 1) and infl["Q1 FY26"] == pytest.approx(106 / 101 - 1)


def test_proxy_volume_is_built_automatically_from_the_price_index(tmp_path):
    store = build_sample_store()
    for e in store.query(entity="Northwind Foods Ltd", role="company"):
        pass
    # remove the stated-volume narrative so only the table (without volume) remains
    t = [e for e in store.all() if e.entity == "Northwind Foods Ltd" and e.source_type == SourceType.results][0]
    t.text = "\n".join(l for l in t.text.splitlines() if not l.startswith("Sales volume"))
    store.add(t)
    for e in store.query(entity="Northwind Foods Ltd", source_type="presentation") + store.query(entity="Northwind Foods Ltd", source_type="transcript"):
        e.text = "Revenue discussed."
        store.add(e)
    ind = store.load_series("industry")["food_cpi"]
    ev = [e for e in store.query(role="industry") if e.locator == "series:food_cpi"][0]
    ev.flags.append("price_index")
    store.add(ev)
    api = Member1API(store=store, cache=None)
    s = api.build_metrics("Northwind Foods Ltd", Role.company)
    vol = s["volume_growth_yoy"]
    assert vol.has_proxy and "PROXY" in [p for p in vol.points if p.value is not None][-1].note


# ---------- mix shares (with the totals check) ----------
MIX = ("Particulars | Q1 FY26 | Q2 FY26\nSegment Revenue | |\nHome Care | 400 | 420\nFoods | 300 | 330\nBeauty | 300 | 250\n"
       "Total revenue from operations | 1000 | 1000")


def test_mix_shares_need_a_heading_and_a_matching_total():
    out = extract_mix(parse_table_text(MIX))
    assert out["Home Care"] == {"Q1 FY26": 0.4, "Q2 FY26": 0.42} and out["Foods"]["Q2 FY26"] == pytest.approx(0.33)
    bad_total = MIX.replace("1000 | 1000", "1000 | 1300")                       # Q2 parts add to 1000, total says 1300: rejected
    assert "Q2 FY26" not in extract_mix(parse_table_text(bad_total)).get("Home Care", {})
    assert extract_mix(parse_table_text(MIX.replace("Segment Revenue", "Misc"))) == {}
    ev = make_evidence(title="r", text=MIX, url="https://f.example.invalid/r.pdf", entity="Co", role=Role.company, locator="p.4 table 2",
                       source_type=SourceType.results, tier=1)
    names = {s.name for s in extract_mix_series([ev], "Co", Role.company)}
    assert names == {"mix_share:home_care", "mix_share:foods", "mix_share:beauty"}


# ---------- Google Trends (optional, lead only) ----------
def test_trends_series_is_labelled_lead_only():
    df = pd.DataFrame({"date": pd.date_range("2025-04-01", periods=12, freq="MS"), "value": list(range(10, 22))})
    ev, s = collect_trends("Some Company Ltd.", fetch=lambda kw: df)
    assert "lead_only" in ev.flags and ev.source_type == SourceType.alt_data and ev.source_tier == 4
    assert s.name == "search_interest" and s.points[0].period == "Q1 FY26" and s.points[0].value == pytest.approx(11.0)
    assert collect_trends("X", fetch=lambda kw: None) is None


# ---------- manual files live in the shared cache; sample file size ----------
def test_manual_pdf_is_copied_into_the_cache(tmp_path):
    pytest.importorskip("reportlab")
    from rescope.collectors.documents import DocumentCollector
    from rescope.collectors.local_ingest import ingest_inbox
    from rescope.collectors.search import SearchClient
    from tests.test_intake_collectors import _fake_pdf
    d = tmp_path / "inbox" / "results"
    d.mkdir(parents=True)
    (d / "Co_results_Q2_FY26.pdf").write_bytes(_fake_pdf())
    cache = DiskCache(tmp_path / "cache")
    dc = DocumentCollector(Fetcher(cache, transport=lambda *a: None, min_interval=0), SearchClient(cache))
    ingest_inbox(dc, tmp_path / "inbox", "Co", Role.company, EvidenceStore(":memory:"))
    assert cache.has("manual:Co_results_Q2_FY26.pdf") and cache.label("manual:Co_results_Q2_FY26.pdf")["manual"] is True


def test_sample_evidence_has_20_to_30_items():
    n = build_sample_store().count()
    assert 20 <= n <= 30



# ---------- peer quality (batch run: broker firms and group names were added as peers) ----------
from rescope.intake.resolver import is_not_a_peer


def test_research_and_financial_firms_are_never_peers():
    for n in ("Crisil Limited", "Motilal Oswal Financial Services Limited", "Emkay Global Financial Services Limited",
              "HDFC Bank Limited", "CARE Ratings Limited", "ICRA Limited", "Axis Securities Ltd"):
        assert is_not_a_peer(n), n
    for n in ("Berger Paints (I) Limited", "Kalyan Jewellers India Limited", "Tata Consumer Products Ltd.", "Marico Limited"):
        assert not is_not_a_peer(n), n


UNI2 = parse_listing_csv(
    "NAME OF COMPANY,SYMBOL,Industry\n"
    "Alpha Jewels Ltd,ALPHAJ,Consumer Durables\nBeta Paints Ltd,BETAPNT,Consumer Durables\n"
    "Jewel One Ltd,JEWONE,\nJewel Two Ltd,JEWTWO,\nJewel Three Ltd,JEWTHR,\nGamma Steel Works Ltd,GSTEEL,\n"
    "Delta Research and Ratings Ltd,DRATE,\n")
LUX = {"industry": "Luxury Goods", "sector": "Consumer Cyclical"}
INFO = {"ALPHAJ.NS": LUX, "BETAPNT.NS": {"industry": "Specialty Chemicals", "sector": "Basic Materials"},
        "JEWONE.NS": LUX, "JEWTWO.NS": LUX, "JEWTHR.NS": LUX, "GSTEEL.NS": {"industry": "Steel", "sector": "Basic Materials"}}


def _alpha_store():
    store = EvidenceStore(":memory:")
    texts = ["Jewel One, Jewel Two and Jewel Three compete with us. Gamma Steel Works and Delta Research and Ratings are mentioned.",
             "Jewel One and Jewel Two grew faster. Jewel Three too. Gamma Steel Works rose.",
             "Jewel One and Gamma Steel Works and Delta Research and Ratings."]
    for i, t in enumerate(texts):
        store.add(make_evidence(title=f"d{i}", text=t, url=f"https://h{i}.example.invalid/a", entity="Alpha Jewels Ltd",
                                role=Role.company, source_type=SourceType.news, tier=4))
    return store


def test_peers_must_share_the_targets_industry_and_nse_label_peers_are_replaced(tmp_path):
    api = Member1API(store=_alpha_store(), cache=DiskCache(tmp_path), universe=UNI2, all_listed=UNI2, ticker_factory=fake_factory(INFO))
    prof = api.resolve("Alpha Jewels")
    assert [p.name for p in prof.peers] == ["Beta Paints Ltd"]                    # same NSE label, but not the same business
    new = api.refine_peers(prof)
    assert {p.symbol for p in prof.peers} == {"JEWONE", "JEWTWO", "JEWTHR"}        # steel and the rating firm excluded; paints replaced
    assert {p.symbol for p in new} == {"JEWONE", "JEWTWO", "JEWTHR"}
    assert any("peers removed" in w and "Beta Paints" in w for w in prof.warnings)
    assert all("same industry" in p.reason for p in prof.peers)


def test_original_peers_stay_when_too_few_match(tmp_path):
    info = dict(INFO)
    info["JEWTWO.NS"] = info["JEWTHR.NS"] = {"industry": "Apparel", "sector": "Consumer Cyclical"}
    api = Member1API(store=_alpha_store(), cache=DiskCache(tmp_path), universe=UNI2, all_listed=UNI2, ticker_factory=fake_factory(info))
    prof = api.resolve("Alpha Jewels")
    api.refine_peers(prof)
    assert [p.symbol for p in prof.peers] == ["JEWONE", "BETAPNT"]               # one match only: the original peer stays as fallback
