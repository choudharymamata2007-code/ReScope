import pytest
from rescope.analysis import disclosure_change as dcg
from rescope.analysis import say_vs_do as sdo
from rescope.analysis import triangulation as tri
from rescope.analysis.sufficiency import coverage_report
from rescope.api import Member1API
from rescope.intake.listings import parse_listing_csv
from rescope.quant import benchmark as bm
from rescope.quant import metrics as m
from rescope.quant.extract import (extract_rows, extract_volume_growth_from_text, parse_number, parse_table_text)
from rescope.quant.series import (build_metric_series, check_total_consistency, cross_check, raw_from_extracted, sort_periods)
from rescope.sample_data import FICTIONAL_UNIVERSE_CSV, PERIODS, build_sample_store, table_evidence
from rescope.schema import MetricPoint, MetricSeries, Role


def ms(name, values, role=Role.company):
    return MetricSeries(name=name, entity="e", role=role,
                        points=[MetricPoint(period=f"Q{(i % 4) + 1} FY{24 + i // 4}", value=v) for i, v in enumerate(values)])


# ---------------- metrics ----------------
def test_price_volume_split_adds_up():
    r = m.price_volume_split(1000, 1100, 100, 95)             # +10% revenue, -5% volume
    assert r["revenue_growth"] == pytest.approx(0.10)
    assert r["volume_effect"] == pytest.approx(-0.05)
    assert r["volume_effect"] + r["price_mix_effect"] == pytest.approx(r["revenue_growth"])
    assert (1 + r["volume_growth"]) * (1 + r["price_mix_growth"]) - 1 == pytest.approx(0.10)
    assert r["price_share_of_growth"] == pytest.approx(1.5)   # price explains more than all growth
    assert m.price_volume_split(1000, 1100, None, None) is None


def test_proxy_is_labelled():
    r = m.proxy_volume_from_deflator(0.10, 0.06)
    assert r["is_proxy"] and r["volume_growth"] == pytest.approx(1.10 / 1.06 - 1)
    assert m.proxy_volume_from_deflator(None, 0.06) is None


def test_days_metrics():
    assert m.receivable_days(500, 1000, 91.25) == pytest.approx(45.625)
    assert m.receivable_days(500, 0) is None and m.receivable_days(None, 100) is None
    assert m.inventory_days(300, 600, 91.25) == pytest.approx(45.625)
    assert m.cash_conversion_cycle(40, 45, 30) == 55 and m.cash_conversion_cycle(None, 45, 30) is None
    assert m.gross_margin(100, 60) == pytest.approx(0.4)
    assert m.mix_shares({"a": 30, "b": 70, "c": None}) == {"a": 0.3, "b": 0.7}
    assert m.mix_shares({"a": None}) is None
    assert m.growth(0, 5) is None and m.growth(100, 110) == pytest.approx(0.1)


# ---------------- extraction & series ----------------
def test_parse_number():
    assert parse_number("1,234.5") == 1234.5 and parse_number("(12.3)") == -12.3
    assert parse_number("-") is None and parse_number("12.5%") == 12.5 and parse_number("abc") is None


def test_extract_rows_from_table_with_locator():
    table = parse_table_text("Particulars | Q1 FY25 | Q2 FY25\nRevenue from operations | 1,000 | 1,100\nTrade receivables | 250 | (n/a)\nOther | 1 | 2")
    rows = extract_rows(table, "doc.pdf#p.5 table 1", "ev1")
    by = {r.metric: r for r in rows}
    assert by["revenue"].values == {"Q1 FY25": 1000.0, "Q2 FY25": 1100.0}
    assert by["receivables"].values["Q1 FY25"] == 250.0 and by["revenue"].locator.endswith("p.5 table 1")


def test_volume_from_text():
    assert extract_volume_growth_from_text("Underlying volume growth of 3.5% in the quarter") == pytest.approx(0.035)
    assert extract_volume_growth_from_text("volumes declined by 2% year on year") == pytest.approx(-0.02)
    assert extract_volume_growth_from_text("no numbers here") is None


def test_consistency_and_cross_check():
    assert check_total_consistency({"a": 40, "b": 60}, 100) and not check_total_consistency({"a": 40, "b": 50}, 100)
    assert check_total_consistency({"a": 40, "b": None}, 100)                  # unverifiable is not rejected
    assert cross_check({"Q1 FY25": 100}, {"Q1 FY25": 110}) == ["Q1 FY25"]
    assert cross_check({"Q1 FY25": 100}, {"Q1 FY25": 101}) == []
    assert sort_periods(["Q1 FY26", "Q4 FY25", "Q2 FY25"]) == ["Q2 FY25", "Q4 FY25", "Q1 FY26"]


def test_series_from_sample_matches_known_values():
    from rescope.quant.extract import extract_from_evidence
    ev = table_evidence("Northwind Foods Ltd", Role.company)
    raw = raw_from_extracted(extract_from_evidence([ev]))
    assert list(raw.index) == PERIODS
    s = build_metric_series(raw, "Northwind Foods Ltd")
    dso = s["receivable_days"]
    assert dso.points[0].value == pytest.approx(28.0, abs=0.05) and dso.points[-1].value == pytest.approx(46.0, abs=0.05)
    assert dso.points[0].locator.endswith("p.5 table 1")                         # every number points to its table
    vol = s["volume_growth_yoy"]
    assert vol.points[3].value is None and vol.points[4].value == pytest.approx(0.03, abs=1e-3)
    assert vol.points[-1].value < 0 and not vol.has_proxy
    assert s["price_share_of_growth"].points[-1].value > 1


def test_proxy_series_when_volume_missing():
    ev = table_evidence("Northwind Foods Ltd", Role.company)
    from rescope.quant.extract import extract_from_evidence
    raw = raw_from_extracted(extract_from_evidence([ev])).drop(columns=["volume", "loc_volume", "ev_volume"])
    s = build_metric_series(raw, "Northwind Foods Ltd", inflation_by_period={p: 0.05 for p in PERIODS})
    assert s["volume_growth_yoy"].has_proxy and "PROXY" in s["volume_growth_yoy"].points[-1].note
    s2 = build_metric_series(raw, "Northwind Foods Ltd")
    assert "volume_growth_yoy" not in s2                                          # no proxy, no volume: no series, no invention


# ---------------- benchmark ----------------
def test_trend_directions():
    assert bm.trend([1, 2, 3, 4, 5, 6])["direction"] == "up"
    assert bm.trend([6, 5, 4, 3, 2, 1])["direction"] == "down"
    assert bm.trend([10, 10.1, 10, 10.2, 10.1, 10])["direction"] == "flat"
    assert bm.trend([1, 2, 3]) is None


def test_benchmark_sector_vs_company():
    up, down = [10, 11, 12, 13, 14, 15, 16, 17], [17, 16, 15, 14, 13, 12, 11, 10]
    company = {"x": ms("x", up)}
    sector = bm.benchmark("e", company, {f"p{i}": {"x": ms("x", up)} for i in range(3)})
    assert sector.overall == "sector_wide"
    specific = bm.benchmark("e", company, {f"p{i}": {"x": ms("x", down)} for i in range(3)})
    assert specific.overall == "company_specific"
    thin = bm.benchmark("e", company, {"p0": {"x": ms("x", up)}})
    assert thin.overall == "insufficient" and thin.warnings
    ind = ms("ind", up, Role.industry)
    mixed = bm.benchmark("e", company, {"a": {"x": ms("x", up)}, "b": {"x": ms("x", down)}, "c": {"x": ms("x", down)}}, {"ind": ind}, {"x": "ind"})
    assert mixed.comparisons[0].verdict in ("mixed", "company_specific")
    assert isinstance(sector.to_dict(), dict)


# ---------------- triangulation ----------------
def test_triangulation_counts_independent_types():
    store = build_sample_store()
    ev = store.all()
    pick = lambda t: next(e for e in ev if e.source_type.value == t)
    claims = [tri.ClaimRef("Receivable days rose steadily while volumes declined", pick("results").id),
              tri.ClaimRef("Distributor payment cycles lengthened and receivable days rose across the sector", pick("news").id),
              tri.ClaimRef("Management describes a volume-led premium growth story", pick("transcript").id),
              tri.ClaimRef("Monsoon rainfall deficits hit rural demand in the Himalayan region", pick("gov_macro").id)]
    out = tri.corroboration_map(claims, ev, embed=tri.get_embedder("tfidf"), threshold=0.2)
    top = next(c for c in out if len(c.claim_texts) >= 2)
    assert {"results", "news"} <= set(top.independent_source_types) and top.meets_triangulation
    lone = next(c for c in out if "Monsoon" in c.representative)
    assert not lone.meets_triangulation
    assert tri.cluster_claims([]) == []


# ---------------- say vs do ----------------
def test_say_vs_do_alignment():
    store = build_sample_store()
    api = Member1API(store=store, cache=None)
    api.build_metrics("Northwind Foods Ltd", Role.company)
    stmts = [sdo.Statement("We are a volume-led growth story", "e1"), sdo.Statement("Our channel is healthy", "e2"),
             sdo.Statement("Inventory is under control", "e3"), sdo.Statement("Margin resilience remains", "e4"),
             sdo.Statement("Rural recovery is coming", "e5")]
    rows = {r.rule: r for r in sdo.evaluate(stmts, store.load_series("Northwind Foods Ltd"))}
    assert rows["volume_led_growth"].verdict == "misaligned"       # volumes fell
    assert rows["channel_health"].verdict == "misaligned"          # receivable days rose
    assert rows["inventory_control"].verdict == "aligned"          # inventory days flat
    assert rows["margin_resilience"].verdict == "aligned"
    assert all(r.rule != "rural_recovery" for r in rows.values())  # no rule, no verdict
    assert sdo.evaluate([sdo.Statement("volume-led growth", "e")], {})[0].verdict == "insufficient"


# ---------------- disclosure change ----------------
def test_disclosure_changes_detected():
    store = build_sample_store()
    out = dcg.detect_disclosure_changes(store.query(entity="Northwind Foods Ltd"))
    kinds = {(c.kind, c.term) for c in out}
    assert ("dropped", "underlying volume growth") in kinds or any(c.kind == "renamed" for c in out)
    assert any(c.kind == "redefinition_language" for c in out)
    assert dcg.detect_disclosure_changes([]) == []
    assert "volume growth" in " ".join(dcg.extract_terms("Underlying volume growth was strong"))


# ---------------- coverage ----------------
def test_coverage_full_and_thin():
    store = build_sample_store()
    api = Member1API(store=store, cache=None)
    for n, r in (("Northwind Foods Ltd", Role.company), ("Evergreen Staples Limited", Role.peer),
                 ("Harbor Home Care Ltd", Role.peer), ("Sunrise Beverages Limited", Role.peer)):
        api.build_metrics(n, r)
    full = coverage_report(store.all(), store.load_series("Northwind Foods Ltd"), peers_with_data=3)
    assert full.sufficient and full.quarters_covered == 12 and full.coverage_score > 0.8
    thin = coverage_report([store.all()[-1]], {}, peers_with_data=0)
    assert not thin.sufficient and thin.coverage_score < 0.4 and thin.warnings
    proxy_series = {"volume_growth_yoy": MetricSeries(name="volume_growth_yoy", entity="e", role=Role.company,
                    points=[MetricPoint(period="Q1 FY25", value=0.01, is_proxy=True)])}
    assert coverage_report(store.all(), proxy_series, 3).proxies_used == ["volume_growth_yoy"]


# ---------------- end-to-end on the public API ----------------
def test_api_end_to_end_offline():
    store = build_sample_store()
    api = Member1API(store=store, universe=parse_listing_csv(FICTIONAL_UNIVERSE_CSV), cache=None)
    prof = api.resolve("northwind foods", business_text=["packaged foods and personal care"])
    for n, r in [(prof.name, Role.company)] + [(p.name, Role.peer) for p in prof.peers]:
        api.build_metrics(n, r)
    bmk = api.benchmark(prof)
    verdicts = {c["metric"]: c["verdict"] for c in bmk["comparisons"]}
    assert verdicts["receivable_days"] == "company_specific" and verdicts["volume_growth_yoy"] in ("sector_wide", "mixed")
    cov = api.coverage(prof)
    assert cov["sufficient"] and cov["peers_with_data"] >= 3
    assert api.say_vs_do([sdo.Statement("Our channel is healthy", "x")], prof.name)[0]["verdict"] == "misaligned"


# ---------------- unit safety when several documents are merged (found in the first live run) ----------------
from rescope.quant.extract import ExtractedRow


def _rows(doc, metric, vals):
    return ExtractedRow(metric, metric, dict(vals), f"{doc}#p.1 table 1", f"ev-{doc}")


def test_annual_columns_are_ignored_and_one_anchor_is_used():
    q = {"Q1 FY25": 100.0, "Q2 FY25": 110.0, "Q3 FY25": 120.0}
    rows = [_rows("A", "revenue", {**q, "FY25": 999.0}), _rows("A", "cogs", {k: v * 0.6 for k, v in q.items()})]
    raw = raw_from_extracted(rows)
    assert list(raw.index) == list(q) and "FY25" not in raw.index
    assert raw.attrs["notes"][0].startswith("anchor document: A")


def test_second_document_merged_only_when_units_match():
    q = {"Q1 FY25": 100.0, "Q2 FY25": 110.0, "Q3 FY25": 120.0}
    same_units = [_rows("A", "revenue", q), _rows("B", "revenue", q), _rows("B", "receivables", {k: v * 0.25 for k, v in q.items()})]
    raw = raw_from_extracted(same_units)
    assert "receivables" in raw.columns and raw.at["Q1 FY25", "receivables"] == 25.0
    other_units = [_rows("A", "revenue", q), _rows("A", "cogs", {k: v * 0.6 for k, v in q.items()}),
                   _rows("A", "inventory", {k: v * 0.2 for k, v in q.items()}),
                   _rows("B", "revenue", {k: v * 10 for k, v in q.items()}),
                   _rows("B", "receivables", {k: v * 2.5 for k, v in q.items()})]
    raw2 = raw_from_extracted(other_units)                                    # x10 apart: a power of ten, proven on 3 cells -> rescaled
    assert raw2.at["Q1 FY25", "receivables"] == pytest.approx(25.0)
    assert any("rescaled B" in n for n in raw2.attrs["notes"])
    not_a_power = [_rows("A", "revenue", q), _rows("A", "cogs", {k: v * 0.6 for k, v in q.items()}),
                   _rows("A", "inventory", {k: v * 0.2 for k, v in q.items()}),
                   _rows("B", "revenue", {k: v * 7 for k, v in q.items()}), _rows("B", "receivables", {k: v * 2.5 for k, v in q.items()})]
    raw3 = raw_from_extracted(not_a_power)                                    # x7 is not a unit change: never mixed in
    assert "receivables" not in raw3.columns and any("skipped B" in n for n in raw3.attrs["notes"])
    uneven = [_rows("A", "revenue", q), _rows("A", "cogs", {k: v * 0.6 for k, v in q.items()}),
              _rows("A", "inventory", {k: v * 0.2 for k, v in q.items()}),
              _rows("B", "revenue", {"Q1 FY25": 1000.0, "Q2 FY25": 1100.0, "Q3 FY25": 9999.0}), _rows("B", "receivables", q)]
    assert "receivables" not in raw_from_extracted(uneven).columns            # cells disagree: no proof, skipped
    no_overlap = [_rows("A", "revenue", q), _rows("B", "receivables", q)]
    assert "receivables" not in raw_from_extracted(no_overlap).columns         # cannot verify units, so do not use
    assert raw_from_extracted([]).empty and raw_from_extracted([]).attrs["notes"]


# ---------------- year-on-year must use the SAME quarter a year earlier (bug found in the live run) ----------------
from rescope.quant.series import prior_year
from rescope.quant.volume_claims import apply_stated_volume, extract_volume_claims
from rescope.analysis.sufficiency import missing_quarters
from rescope.sample_data import narrative_evidence
import pandas as pd


def test_prior_year_and_gap_safe_growth():
    assert prior_year("Q1 FY27") == "Q1 FY26" and prior_year("Q4 FY25") == "Q4 FY24"
    # a gap: Q2 FY26 is missing, so Q1 FY27 vs the previous index position would be WRONG
    raw = pd.DataFrame({"revenue": [100.0, 110.0, 130.0, 135.0, 121.0]},
                       index=["Q4 FY25", "Q1 FY26", "Q3 FY26", "Q4 FY26", "Q1 FY27"])
    s = build_metric_series(raw, "e")["revenue_growth_yoy"]
    vals = {p.period: p.value for p in s.points}
    assert vals["Q1 FY27"] == pytest.approx(121 / 110 - 1)           # vs Q1 FY26, not vs Q4 FY25 (which would give 0.21)
    assert vals["Q4 FY26"] == pytest.approx(135 / 100 - 1)           # vs Q4 FY25
    assert vals["Q3 FY26"] is None                                    # Q3 FY25 not present: no value, no guess


def test_missing_quarters_detected():
    assert missing_quarters({"Q4 FY25", "Q1 FY26", "Q3 FY26", "Q4 FY26", "Q1 FY27"}) == ["Q2 FY26"]
    assert missing_quarters({"Q1 FY26", "Q2 FY26"}) == [] and missing_quarters({"Q1 FY26"}) == []


# ---------------- management-stated volume ----------------
from rescope.tagging.tagger import make_evidence
from rescope.schema import SourceType


def _ev(text, st=SourceType.transcript, tier=3, period=None, url="https://c.example.invalid/t", loc="section 2", title="t"):
    return make_evidence(title=title, text=text, url=url, entity="Co", role=Role.company, locator=loc, source_type=st, tier=tier, period=period)


def test_volume_claim_patterns():
    cl = extract_volume_claims([_ev("In Q3 FY26 we delivered an underlying volume growth of 4%, driven by broad-based growth. "
                                    "Home Care posted mid single digit UVG on a base of high single digit UVG USG at 3%. "
                                    "Revenue grew 5% led by volume growth at 4% in FY26. Volume declined 2% in Q1 FY25. "
                                    "Growth with 2% underlying sales growth and 3% volume growth was solid."),
                                _ev("UVG of 3.0% YoY", st=SourceType.news, tier=4, title="Company Q1 FY26 result update")])
    got = {(c.period, round(c.value, 3), c.basis) for c in cl}
    assert ("Q3 FY26", 0.04, "quarter") in got and ("FY26", 0.04, "annual") in got
    assert ("Q1 FY25", -0.02, "quarter") in got and ("Q1 FY26", 0.03, "quarter") in got
    assert not any(c.value == 0.03 and c.period is None for c in cl)          # 'USG at 3%' and '3% volume growth' are not volume claims


def test_stated_volume_feeds_series_and_conflicts_are_dropped():
    good = [_ev("In Q3 FY26 underlying volume growth of 4% was delivered"),
            _ev("Q3 FY26: UVG of 4% YoY", st=SourceType.news, tier=4, url="https://n.example.invalid/a")]
    conflict = [_ev("In Q4 FY26 underlying volume growth of 4%"),
                _ev("Q4 FY26 volume growth of 2%", st=SourceType.news, tier=4, url="https://n.example.invalid/b")]
    annual = [_ev("Volume growth at 4% in FY26")]
    raw = pd.DataFrame({"revenue": [100.0, 108.0]}, index=["Q3 FY25", "Q3 FY26"])
    out = apply_stated_volume(raw, extract_volume_claims(good + conflict + annual))
    assert out.at["Q3 FY26", "volume_growth"] == pytest.approx(0.04)
    assert "Q4 FY26" not in out.index and any("Q4 FY26" in n and "disagree" in n for n in out.attrs["notes"])
    s = build_metric_series(out, "e")
    pt = {p.period: p for p in s["volume_growth_yoy"].points}["Q3 FY26"]
    assert pt.value == pytest.approx(0.04) and "STATED" in pt.note and not pt.is_proxy
    assert pt.locator.startswith("https://c.example.invalid/t")                # points at the best-tier source
    assert {p.period: p for p in s["price_mix_growth_yoy"].points}["Q3 FY26"].value == pytest.approx(1.08 / 1.04 - 1)


def test_coverage_warns_without_official_filing():
    from rescope.analysis.sufficiency import coverage_report
    agg = _ev("Particulars | Q1 FY26\nRevenue from operations | 1", st=SourceType.results, tier=3)
    agg.flags += ["aggregator", "unofficial_data"]
    rep = coverage_report([agg], {}, 0)
    assert not rep.official_filings_found and any("official filing" in w for w in rep.warnings)


# ---------------- period attribution rules (second live run: a table cell was given the wrong quarter) ----------
from rescope.quant.volume_claims import reported_quarter
import datetime as dt


def test_table_cells_and_unlabelled_text_never_get_a_guessed_quarter():
    table = _ev("Volume growth 2.0% 2", st=SourceType.news, tier=4, loc="p.6 table 1", period="Q2 FY24", title="Broker note Q3 FY26")
    prose = _ev("UVG of 4% YoY in the quarter", st=SourceType.news, tier=4, loc="p.1", period="Q2 FY24", title="Broker note")
    cl = extract_volume_claims([table, prose])
    assert [c.basis for c in cl] == ["unknown", "unknown"]                 # the stored chunk period is NOT trusted
    titled = _ev("UVG of 4% YoY in the quarter", st=SourceType.news, tier=4, loc="p.1", title="HUL 3QFY26 result update")
    c = extract_volume_claims([titled])[0]
    assert c.period == "Q3 FY26" and c.inferred and c.basis == "quarter"


def test_transcript_quarter_from_call_date():
    assert reported_quarter(dt.date(2026, 2, 12)) == "Q3 FY26"
    assert reported_quarter(dt.date(2026, 5, 20)) == "Q4 FY26"
    assert reported_quarter(dt.date(2026, 8, 5)) == "Q1 FY27"
    t = _ev("In this backdrop we delivered an underlying volume growth of 4%", title="earnings call transcript",
            url="https://calls.example.invalid/x_transcript_2026-02-12")
    c = extract_volume_claims([t])[0]
    assert c.period == "Q3 FY26" and c.inferred
    stated = _ev("In Q3 FY26 underlying volume growth of 4%", url="https://calls.example.invalid/other")
    out = apply_stated_volume(pd.DataFrame({"revenue": [100.0]}, index=["Q3 FY26"]), extract_volume_claims([t, stated]))
    assert out.at["Q3 FY26", "loc_volume_growth"].startswith("https://calls.example.invalid/other")      # stated beats inferred


def test_missing_quarters_window_ignores_old_strays():
    have = {"Q2 FY24", "Q4 FY25", "Q1 FY26", "Q3 FY26", "Q4 FY26", "Q1 FY27"}
    assert missing_quarters(have, window=8) == ["Q2 FY25", "Q3 FY25", "Q2 FY26"]
    assert "Q3 FY24" in missing_quarters(have)                              # old behaviour (no window) lists everything
    assert missing_quarters({"Q1 FY26"}, window=8) == []


# ---------------- price/mix from management-stated sales growth (run 4: no quarter had both revenue growth and volume) ----------------
from rescope.quant.volume_claims import apply_stated_sales


def test_stated_sales_growth_gives_price_mix_only_from_the_same_sentence():
    good = _ev("In Q3 FY26 we delivered an underlying sales growth of 5%, driven by an underlying volume growth of 4%.")
    segment = _ev("Home Care posted mid single digit UVG on a base of high single digit UVG. USG at 3% reflects price cuts in Q3 FY26.")
    lone_sales = _ev("In Q2 FY26 underlying sales growth of 9% was strong.")
    cl = extract_volume_claims([good, segment, lone_sales])
    assert {(c.kind, c.period, round(c.value, 3)) for c in cl} == {("volume", "Q3 FY26", 0.04), ("sales", "Q3 FY26", 0.05)}
    raw = apply_stated_sales(apply_stated_volume(pd.DataFrame(), cl), cl)
    s = build_metric_series(raw, "e")
    pm = {p.period: p for p in s["price_mix_growth_yoy"].points}["Q3 FY26"]
    assert pm.value == pytest.approx(1.05 / 1.04 - 1) and "stated sales growth" in pm.note
    # when computed revenue growth exists it is preferred over the stated figure
    raw2 = pd.DataFrame({"revenue": [100.0, 108.0]}, index=["Q3 FY25", "Q3 FY26"])
    raw2 = apply_stated_sales(apply_stated_volume(raw2, cl), cl)
    pm2 = {p.period: p for p in build_metric_series(raw2, "e")["price_mix_growth_yoy"].points}["Q3 FY26"]
    assert pm2.value == pytest.approx(1.08 / 1.04 - 1) and "stated sales growth" not in pm2.note
