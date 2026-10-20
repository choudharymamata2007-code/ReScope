import datetime as dt
import io
import json
import pytest
from rescope.cache import DiskCache
from rescope.collectors import search as srch
from rescope.collectors.documents import DocumentCollector, find_pdf_links, html_to_text
from rescope.collectors.industry import IndustryCollector, NewsCollector, parse_csv_series, parse_world_bank
from rescope.collectors.local_ingest import ingest_inbox
from rescope.collectors.pdf_utils import chunk_text, is_pdf
from rescope.collectors.search import SearchClient, SearchHit
from rescope.http import Fetcher, FetchResult
from rescope.intake.archetype import detect_archetype
from rescope.intake.listings import match_company, normalise_name, parse_listing_csv
from rescope.intake.resolver import find_mentions, resolve_company, resolve_peers
from rescope.api import validate_company_input
from rescope.sample_data import FICTIONAL_UNIVERSE_CSV
from rescope.schema import Role
from rescope.store import EvidenceStore

UNI = parse_listing_csv(FICTIONAL_UNIVERSE_CSV)


def test_normalise_and_match():
    assert normalise_name("Northwind Foods Limited") == "northwind foods"
    assert match_company("NWFOODS", UNI)[0].score == 100
    assert match_company("northwind food", UNI)[0].company.symbol == "NWFOODS"


def test_archetype_rules_and_fallback():
    a, c, terms = detect_archetype(["packaged foods, personal care and home care products across FMCG"])
    assert a == "packaged_staples" and c > 0.4 and terms
    a2, _, _ = detect_archetype(["store network expansion, same-store growth, omnichannel and e-commerce"], "Retail")
    assert a2 == "organised_retail"
    a3, c3, _ = detect_archetype(["steel and cement"], llm_fallback=lambda t, i: "discretionary_durables")
    assert a3 == "discretionary_durables"
    assert detect_archetype(["nothing relevant"])[0] == "unclassified"


def test_peers_from_industry_and_mentions():
    target = next(c for c in UNI if c.symbol == "NWFOODS")
    peers = resolve_peers(target, UNI, competition_text="We compete with Urban Fashion Retail and others.")
    names = [p.name for p in peers]
    assert "Urban Fashion Retail Limited" in names                # named in competition text, other industry
    assert "Granite Steel Works Ltd" not in names
    assert all(p.symbol != "NWFOODS" for p in peers)
    assert "URBFASH" in find_mentions("Urban Fashion Retail is a rival", UNI, "NWFOODS")
    only_avail = resolve_peers(target, UNI, has_filings=lambda c: c.symbol != "EVRGRN")
    assert "Evergreen Staples Limited" not in [p.name for p in only_avail]


def test_resolve_company_warnings_and_errors():
    p = resolve_company("Northwind Foods", UNI, ["packaged foods FMCG"])
    assert p.nse_symbol == "NWFOODS" and p.archetype == "packaged_staples" and len(p.peers) >= 3
    assert resolve_company("zzzz qqqq", UNI).warnings                      # low-score warning
    with pytest.raises(ValueError):
        resolve_company("  ", UNI)


def test_input_validation():
    assert validate_company_input("  Some Company ") == "Some Company"
    for bad in ("", "a", "x" * 100, "name; DROP TABLE", "<script>"):
        with pytest.raises(ValueError):
            validate_company_input(bad)


def _fake_pdf():
    from reportlab.pdfgen import canvas       # test-only helper
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 750, "Quarter ended 30 September 2025 results")
    c.drawString(72, 730, "Revenue from operations 1,000")
    c.showPage()
    c.save()
    return buf.getvalue()


def test_pdf_pages_with_locators(tmp_path):
    pytest.importorskip("reportlab")
    from rescope.collectors.pdf_utils import extract_pdf
    pages = extract_pdf(_fake_pdf())
    assert pages and "Revenue from operations" in pages[0].text
    dc = DocumentCollector(Fetcher(DiskCache(tmp_path), transport=lambda *a: None, min_interval=0), SearchClient(DiskCache(tmp_path)))
    items = dc.ingest_bytes(_fake_pdf(), "https://example.invalid/r.pdf", "Co", Role.company, "results", "application/pdf", "Co results")
    assert items[0].locator == "p.1" and items[0].source_type.value == "results"
    assert items[0].source_tier == 3 and "unverified_host" in items[0].flags      # unknown host never earns tier 1
    assert is_pdf(b"%PDF-1.4", "", "")


def test_html_ingest_and_ir_links(tmp_path):
    html = ('<html><body><nav>menu</nav><p>Investor presentation Q2 FY26</p>'
            '<a href="/docs/Q2-FY26-presentation.pdf">Q2 presentation</a><a href="/other.html">x</a></body></html>')
    assert "menu" not in html_to_text(html)
    assert find_pdf_links(html, "https://ir.example.invalid/page", ("presentation",))[0][1] == "https://ir.example.invalid/docs/Q2-FY26-presentation.pdf"
    assert len(chunk_text("a\n\n" + "b" * 2000 + "\n\nc", 1800)) >= 2


def test_document_collector_failure_tolerance(tmp_path):
    def transport(url, params, headers):
        if "good" in url:
            return FetchResult(url, 200, b"<html><body>Revenue grew in Q2 FY26</body></html>", "text/html")
        return FetchResult(url, 404, b"")
    fetcher = Fetcher(DiskCache(tmp_path), transport=transport, min_interval=0, sleep=lambda s: None)
    backend = lambda q, n: [SearchHit("good doc", "https://example.invalid/good", "s"), SearchHit("bad doc", "https://example.invalid/bad", "s")]
    sc = SearchClient(DiskCache(tmp_path / "s"), fetcher, backend=backend)
    store = EvidenceStore(":memory:")
    res = DocumentCollector(fetcher, sc, store).collect("Co", "Co", Role.company, kinds=["presentation"], years=["FY26"])
    assert res.items and res.errors                 # good doc ingested, bad doc recorded as error, no exception
    assert store.count() == len(res.items)


def test_search_fallback_and_hooks(tmp_path):
    def broken(q, n):
        raise RuntimeError("quota")
    calls = {"n": 0}

    def ok(q, n):
        calls["n"] += 1
        return [SearchHit("Analysts question price-led growth", "https://news1.example.invalid/a", "Growth is price led, volumes weak.",
                          dt.date(2026, 4, 1)),
                SearchHit("Another view", "https://news2.example.invalid/b", "Distributor days stretched across sector.", dt.date(2026, 4, 5))]
    c = SearchClient(DiskCache(tmp_path), backend=broken, tavily_key="")
    c._ddgs = lambda q, n: ok(q, n)                # simulate the no-key fallback provider
    hits = c.search("anything")
    assert hits and c.last_provider == "ddgs" and any("quota" in e for e in c.errors)
    c.search("anything")                           # served from cache
    assert calls["n"] == 1
    qs = srch.build_disconfirming_queries({"text": "growth is volume led and rising", "metrics": ["volume_growth_yoy"]}, "Co", ["Peer"])
    assert any("criticism" in q for q in qs) and any("Peer" in q for q in qs) and len(set(qs)) == len(qs)
    dis = srch.find_disconfirming(c, {"text": "volume led growth", "metrics": ["volume_growth_yoy"]}, "Co")
    assert dis and all("disconfirming_search" in e.flags for e in dis)
    prior = srch.find_prior_coverage(c, "price led growth with stretched receivables", "Co", before=dt.date(2026, 6, 1))
    assert prior["independent_count"] == 2 and len(prior["publishers"]) == 2
    none_before = srch.find_prior_coverage(c, "price led growth", "Co", before=dt.date(2026, 3, 1))
    assert none_before["items"] == []


def test_industry_and_news_parsers(tmp_path):
    df = parse_csv_series("Date,Index\n31/03/2025,100\n30/06/2025,101.5\n30/09/2025,102\n", "Date", "Index")
    assert len(df) == 3 and df["value"].iloc[1] == 101.5
    wb = parse_world_bank([{"page": 1}, [{"date": "2024", "value": 5.0}, {"date": "2023", "value": None}]])
    assert len(wb) == 1
    cfg = [{"kind": "csv", "id": "cpi_test", "title": "CPI test", "url": "https://example.invalid/cpi.csv", "date_col": "Date",
            "value_col": "Index", "unit": "index"}]
    csv_bytes = b"Date,Index\n31/03/2025,100\n30/06/2025,101.5\n30/09/2025,102\n31/12/2025,103\n31/03/2026,104\n"
    fetcher = Fetcher(DiskCache(tmp_path), transport=lambda u, p, h: FetchResult(u, 200, csv_bytes, "text/csv"), min_interval=0)
    store = EvidenceStore(":memory:")
    res, series = IndustryCollector(fetcher, store).collect(cfg)
    assert not res.errors and series[0].role == Role.industry and series[0].points[-1].period == "Q4 FY26"
    assert store.query(role="industry")[0].source_tier == 2
    bad_res, _ = IndustryCollector(fetcher, store).collect([{"kind": "nope", "id": "x", "url": "https://example.invalid"}])
    assert bad_res.errors
    rss = b"""<?xml version='1.0'?><rss version='2.0'><channel><title>t</title><item><title>Co posts results</title>
        <link>https://news.example.invalid/1</link><description>Co revenue up</description><pubDate>Mon, 04 May 2026 10:00:00 GMT</pubDate></item>
        <item><title>Other</title><link>https://news.example.invalid/2</link><description>unrelated</description></item></channel></rss>"""
    nf = Fetcher(DiskCache(tmp_path / "n"), transport=lambda u, p, h: FetchResult(u, 200, rss, "text/xml"), min_interval=0)
    items = NewsCollector(nf).from_rss("https://feed.example.invalid/rss", "Co", keyword="Co")
    assert len(items) == 1 and items[0].source_type.value == "news"


def test_local_inbox_ingest(tmp_path):
    pytest.importorskip("reportlab")
    d = tmp_path / "inbox" / "results"
    d.mkdir(parents=True)
    (d / "Co_results_Q2_FY26.pdf").write_bytes(_fake_pdf())
    store = EvidenceStore(":memory:")
    dc = DocumentCollector(Fetcher(DiskCache(tmp_path / "c"), transport=lambda *a: None, min_interval=0), SearchClient(DiskCache(tmp_path / "s")))
    n = ingest_inbox(dc, tmp_path / "inbox", "Co", Role.company, store)
    assert n >= 1 and "manual_download" in store.all()[0].flags


# ---------------- provenance (found in the first live run) ----------------
from rescope.collectors.documents import classify_document, is_exchange_host, likely_official_host, looks_like_research
from rescope.schema import SourceType

RESEARCH = "Result Update | Rating: BUY | Target price Rs 2,900 | CMP Rs 2,400 | upside to target 20% | Disclosures and Disclaimers"


def test_research_reports_are_not_filings():
    assert looks_like_research(RESEARCH)
    st, tier, flags = classify_document("https://broker.example.invalid/hul-3q-update.pdf", "Some Company Ltd.", "results", RESEARCH)
    assert st == SourceType.news and tier == 4 and flags == ["third_party_research"]
    assert not looks_like_research("Unaudited financial results for the quarter ended 30 September 2025")


def test_only_exchange_or_own_site_earn_filing_tier():
    text = "Unaudited financial results for the quarter ended 30 September 2025. Revenue from operations 1,000"
    assert classify_document("https://www.bseindia.com/x.pdf", "Some Company Ltd.", "results", text)[1] == 1
    assert is_exchange_host("www.bseindia.com") and is_exchange_host("bseindia.com") and not is_exchange_host("notbseindia.com")
    assert classify_document("https://bseindia.com/x.pdf", "Some Company Ltd.", "results", text) == (SourceType.results, 1, [])
    assert classify_document("https://www.somecompany.example.invalid/ir.pdf", "Some Company Ltd.", "results", text)[1] == 1
    st, tier, flags = classify_document("https://random-blog.example.invalid/a.pdf", "Some Company Ltd.", "annual_report", text)
    assert tier == 3 and flags == ["unverified_host"]
    assert classify_document("https://callsite.example.invalid/t", "Some Company Ltd.", "transcript", text)[2] == ["third_party_host"]


def test_official_host_from_name_and_initials():
    assert likely_official_host("hul.co.in", "Hindustan Unilever Ltd.")           # initials H-U-L
    assert likely_official_host("unilever.com", "Hindustan Unilever Ltd.")
    assert likely_official_host("nestle.in", "Nestle India Ltd.")
    assert not likely_official_host("jmflresearch.com", "Hindustan Unilever Ltd.")
    assert not likely_official_host("alphastreet.com", "Nestle India Ltd.")


# ---------------- rate limits and the news fallback ----------------
def test_gdelt_429_falls_back_to_search(tmp_path):
    fetcher = Fetcher(DiskCache(tmp_path), transport=lambda u, p, h: FetchResult(u, 429, b""), min_interval=0, sleep=lambda s: None)
    backend = lambda q, n: [SearchHit("Sector note", "https://news.example.invalid/a", "analysis text", dt.date(2026, 4, 1))]
    sc = SearchClient(DiskCache(tmp_path / "s"), fetcher, backend=backend)
    res = NewsCollector(fetcher, None, sc).collect("Co", "Co")
    assert res.items and res.used_fallback and any("gdelt" in e for e in res.errors)


def test_slow_hosts_get_longer_interval(tmp_path):
    waits = []
    f = Fetcher(DiskCache(tmp_path), transport=lambda u, p, h: FetchResult(u, 200, b"{}"), min_interval=1.5,
                sleep=lambda s: waits.append(s))
    f.get("https://api.gdeltproject.org/a?x=1", use_cache=False)
    f.get("https://api.gdeltproject.org/a?x=2", use_cache=False)
    assert max(waits) > 1.5 and max(waits) <= 6.0


def test_industry_series_from_a_local_unedited_download(tmp_path):
    f = tmp_path / "official.csv"
    f.write_text("Date,Index\n31/03/2025,100\n30/06/2025,101.5\n30/09/2025,102\n31/12/2025,103\n31/03/2026,104\n", encoding="utf-8")
    cfg = [{"kind": "csv", "id": "cpi_local", "title": "CPI (official download)", "url": "https://stats.example.invalid/cpi",
            "path": str(f), "date_col": "Date", "value_col": "Index", "unit": "index"}]
    nofetch = Fetcher(DiskCache(tmp_path / "c"), transport=lambda *a: (_ for _ in ()).throw(AssertionError("must not fetch")), min_interval=0)
    store = EvidenceStore(":memory:")
    res, series = IndustryCollector(nofetch, store).collect(cfg)
    assert not res.errors and series[0].points[-1].period == "Q4 FY26"
    ev = store.query(role="industry")[0]
    assert "manual_download" in ev.flags and ev.url == "https://stats.example.invalid/cpi" and ev.source_tier == 2


def test_recent_quarter_labels():
    from rescope.collectors.documents import recent_quarters
    assert recent_quarters(dt.date(2026, 10, 12), 4) == ["Q1 FY27", "Q4 FY26", "Q3 FY26", "Q2 FY26"]
    assert recent_quarters(dt.date(2026, 5, 1), 2) == ["Q3 FY26", "Q2 FY26"]       # Q4 FY26 ended 31 Mar: results not yet assumed out


def test_gdelt_non_json_reply_is_an_error_not_a_crash(tmp_path):
    fetcher = Fetcher(DiskCache(tmp_path), transport=lambda u, p, h: FetchResult(u, 200, b"Please limit requests to one every 5 seconds", "text/plain"), min_interval=0)
    sc = SearchClient(DiskCache(tmp_path / "s"), fetcher, backend=lambda q, n: [SearchHit("note", "https://news.example.invalid/a", "text", dt.date(2026, 4, 1))])
    res = NewsCollector(fetcher, None, sc).collect("Co", "Co")
    assert res.items and res.used_fallback and any("non-JSON" in e for e in res.errors)
