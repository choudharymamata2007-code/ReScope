import pandas as pd
import pytest
from rescope.api import Member1API
from rescope.cache import DiskCache
from rescope.collectors.structured import StructuredCollector, build_table
from rescope.schema import Role
from rescope.store import EvidenceStore

DATES = pd.to_datetime(["2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30", "2025-03-31"])      # newest first, like the library


class FakeTicker:
    def __init__(self, inc=True, bal=True):
        rev = [1200.0, 1150.0, 1100.0, 1050.0, 1000.0]
        self.quarterly_income_stmt = pd.DataFrame(
            {d: {"Total Revenue": r, "Cost Of Revenue": r * 0.6, "EBITDA": r * 0.25} for d, r in zip(DATES, rev)}) if inc else pd.DataFrame()
        self.quarterly_balance_sheet = pd.DataFrame(
            {d: {"Accounts Receivable": r * 0.3, "Inventory": r * 0.6 * 0.5, "Accounts Payable": r * 0.6 * 0.33}
             for d, r in zip(DATES, rev)}) if bal else pd.DataFrame()


def test_build_table_labels_and_periods():
    t = FakeTicker()
    rows, notes = build_table(t.quarterly_income_stmt, t.quarterly_balance_sheet)
    assert rows[0] == "Particulars | Q4 FY25 | Q1 FY26 | Q2 FY26 | Q3 FY26 | Q4 FY26" and not notes
    assert any(r.startswith("Trade receivables | ") for r in rows) and any(r.startswith("Cost of goods sold | ") for r in rows)
    rows2, notes2 = build_table(t.quarterly_income_stmt, None)
    assert any("Trade receivables" in n for n in notes2)
    assert build_table(None, pd.DataFrame())[0] == []


def test_collect_labels_it_as_unofficial_and_feeds_the_engine(tmp_path):
    store = EvidenceStore(":memory:")
    sc = StructuredCollector(DiskCache(tmp_path), ticker_factory=lambda sym: FakeTicker(), store=store)
    res = sc.collect("ABC", "Some Company Ltd.", Role.company)
    ev = res.items[0]
    assert ev.source_tier == 3 and {"aggregator", "unofficial_data"} <= set(ev.flags) and "yahoo" in ev.url
    api = Member1API(store=store, cache=None)
    s = api.build_metrics("Some Company Ltd.", Role.company)
    dso = s["receivable_days"].points
    assert dso[-1].value == pytest.approx(0.3 * 91.25, rel=1e-6)                 # receivables / revenue x 91.25
    assert s["inventory_days"].points[-1].value == pytest.approx(0.5 * 91.25, rel=1e-6)
    assert s["revenue_growth_yoy"].points[-1].value == pytest.approx(0.2)
    assert "volume_growth_yoy" not in s                                           # aggregator has no volume: nothing invented
    assert dso[-1].locator and "aggregator" in dso[-1].locator
    sc.collect("ABC", "Some Company Ltd.", Role.company)                          # second call comes from the cache
    sc2 = StructuredCollector(DiskCache(tmp_path), ticker_factory=lambda sym: (_ for _ in ()).throw(RuntimeError("must not be called")))
    assert sc2.collect("ABC", "Some Company Ltd.", Role.company).items


def test_failures_are_reported_not_raised(tmp_path):
    def boom(sym):
        raise RuntimeError("rate limited")
    r = StructuredCollector(DiskCache(tmp_path / "a"), ticker_factory=boom).collect("ABC", "Co", Role.company)
    assert not r.items and "rate limited" in r.errors[0]
    r2 = StructuredCollector(DiskCache(tmp_path / "b"), ticker_factory=lambda s: FakeTicker(False, False)).collect("ABC", "Co", Role.company)
    assert not r2.items and r2.errors
    def missing(sym):
        raise ImportError("no yfinance")
    r3 = StructuredCollector(DiskCache(tmp_path / "c"), ticker_factory=missing).collect("ABC", "Co", Role.company)
    assert "pip install yfinance" in r3.errors[0]


def test_aggregator_numbers_anchor_and_other_documents_merge_only_when_units_are_proven():
    """A research report in other units must never be mixed in unless the unit change is a proven power of ten."""
    from rescope.quant.extract import ExtractedRow
    from rescope.quant.series import raw_from_extracted
    q = {"Q1 FY26": 1000.0, "Q2 FY26": 1100.0, "Q3 FY26": 1150.0, "Q4 FY26": 1200.0}
    agg = [ExtractedRow("revenue", "r", q, "AGG#t", "e1"), ExtractedRow("receivables", "r", {k: v * 0.3 for k, v in q.items()}, "AGG#t", "e1"),
           ExtractedRow("inventory", "r", {k: v * 0.3 for k, v in q.items()}, "AGG#t", "e1")]
    odd = agg + [ExtractedRow("revenue", "r", {k: v / 7 for k, v in q.items()}, "BROKER#t", "e2"),
                 ExtractedRow("ebitda", "r", {k: v / 40 for k, v in q.items()}, "BROKER#t", "e2")]
    raw = raw_from_extracted(odd)
    assert "ebitda" not in raw.columns and raw.at["Q1 FY26", "revenue"] == 1000.0           # /7 is not a unit change
    tenth = agg + [ExtractedRow("revenue", "r", {k: v / 10 for k, v in q.items()}, "BROKER#t", "e2"),
                   ExtractedRow("ebitda", "r", {k: v / 40 for k, v in q.items()}, "BROKER#t", "e2")]
    raw2 = raw_from_extracted(tenth)
    assert raw2.at["Q4 FY26", "ebitda"] == 300.0 and raw2.at["Q1 FY26", "revenue"] == 1000.0   # /10 is proven on 4 cells: rescaled
