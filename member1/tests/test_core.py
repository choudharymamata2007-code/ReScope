import datetime as dt
import pytest
from rescope.cache import DiskCache
from rescope.http import Fetcher, FetchError, FetchResult
from rescope.sample_data import build_sample_store, table_evidence
from rescope.schema import Evidence, Role, SourceType
from rescope.store import EvidenceStore
from rescope.tagging import dedupe
from rescope.tagging.tagger import (classify_source, fiscal_period_for_date, make_evidence, parse_date, parse_period)


def test_evidence_requires_url():
    with pytest.raises(Exception):
        Evidence(id="x", title="t", text="t", url="  ", source_type=SourceType.news, source_tier=4,
                 entity="e", role=Role.company)


def test_store_roundtrip_and_query(tmp_path):
    s = EvidenceStore(tmp_path / "t.db")
    ev = table_evidence("Northwind Foods Ltd", Role.company)
    assert s.add(ev) is True
    assert s.add(ev) is False                      # same id: not new
    assert s.count() == 1
    assert s.get(ev.id).entity == "Northwind Foods Ltd"
    assert len(s.query(role="company", source_type="results")) == 1
    assert s.query(entity="nobody") == []
    out = tmp_path / "e.json"
    s.export_json(out)
    assert EvidenceStore.load_json(out)[0].id == ev.id


def test_sample_store_has_all_roles():
    s = build_sample_store()
    roles = {e.role for e in s.all()}
    assert roles == {Role.company, Role.peer, Role.industry}
    assert s.load_series("industry")["food_cpi"].values()


def test_cache_ttl(tmp_path):
    c = DiskCache(tmp_path)
    c.set("k", b"v")
    assert c.get("k") == b"v"
    assert c.get("k", ttl=-1) is None
    c.set_json("j", {"a": 1})
    assert c.get_json("j") == {"a": 1}


def test_fetcher_retry_cache_and_failure(tmp_path):
    calls = []

    def flaky(url, params, headers):
        calls.append(url)
        if len(calls) < 3:
            return FetchResult(url, 503, b"")
        return FetchResult(url, 200, b"hello", "text/plain")

    f = Fetcher(DiskCache(tmp_path), transport=flaky, min_interval=0, sleep=lambda s: None)
    r = f.get("https://example.invalid/a")
    assert r.ok and r.text == "hello" and len(calls) == 3
    r2 = f.get("https://example.invalid/a")                 # second call served from cache
    assert r2.from_cache and len(calls) == 3
    bad = Fetcher(DiskCache(tmp_path / "b"), transport=lambda u, p, h: FetchResult(u, 500, b""),
                  min_interval=0, sleep=lambda s: None)
    with pytest.raises(FetchError):
        bad.get("https://example.invalid/z")


@pytest.mark.parametrize("text,expected", [
    ("Results for Q2 FY26", "Q2 FY26"), ("Q3FY2025 presentation", "Q3 FY25"), ("2QFY26 update", "Q2 FY26"),
    ("for the quarter ended 30 September 2025", "Q2 FY26"), ("three months ended June 30, 2025", "Q1 FY26"),
    ("quarter ended 31 March 2026", "Q4 FY26"), ("Annual report FY2025-26", "FY26"), ("nothing here", None)])
def test_parse_period(text, expected):
    assert parse_period(text) == expected


def test_dates_and_fiscal_period():
    assert parse_date("filed on 30 September 2025") == dt.date(2025, 9, 30)
    assert parse_date("September 30, 2025") == dt.date(2025, 9, 30)
    assert parse_date("2025-12-31") == dt.date(2025, 12, 31)
    assert parse_date("31/03/2026") == dt.date(2026, 3, 31)
    assert fiscal_period_for_date(dt.date(2026, 3, 31)) == "Q4 FY26"
    assert fiscal_period_for_date(dt.date(2025, 4, 15)) == "Q1 FY26"


def test_classify_source():
    assert classify_source("https://www.bseindia.com/x.pdf", "")[0] == SourceType.filing
    assert classify_source("https://example.com/annual-report-2025.pdf")[0] == SourceType.annual_report
    assert classify_source("https://example.com/q2-earnings-call-transcript")[0] == SourceType.transcript
    assert classify_source("https://www.mospi.gov.in/cpi")[1] == 2
    assert classify_source("https://reddit.com/r/x")[1] == 5
    assert classify_source("https://news.example.com/story")[1] == 4


def _news(i, text, url, period="Q4 FY26", pub=None, d=None):
    return make_evidence(title=f"n{i}", text=text, url=url, entity="E", role=Role.company, period=period,
                         hint=SourceType.news, date=d or dt.date(2026, 5, 1 + i), publisher=pub)


def test_origin_hash_and_near_duplicates():
    a = "Company revenue rose on price increases while volumes declined in the quarter according to analysts"
    assert dedupe.origin_hash(a) == dedupe.origin_hash(a.upper() + "!!")
    assert dedupe.near_duplicate(a, a + " today")
    assert not dedupe.near_duplicate(a, "Completely unrelated text about rainfall and monsoon forecasts for the coming week")


def test_syndication_same_publisher_and_statement_only():
    base = "Company revenue rose on price increases while volumes declined in the quarter according to analysts"
    items = [_news(1, base, "https://a.example/1"), _news(2, base + " said a reporter", "https://b.example/2"),
             _news(3, "Distinct analysis of distributor payment cycles lengthening across the sector", "https://c.example/3"),
             _news(4, "Another distinct note on channel inventory levels and dealer financing trends here", "https://c.example/4"),
             _news(5, "The company said in a statement that growth remains strong and broad based across segments", "https://d.example/5")]
    out = dedupe.mark_independence(items)
    assert out[0].independent and not out[1].independent and "syndicated" in out[1].flags
    assert out[2].independent and not out[3].independent and "same_publisher" in out[3].flags
    assert not out[4].independent and "company_statement_only" in out[4].flags
    assert len(dedupe.independent_sources(items)) == 2


def test_temporal_flag():
    e = _news(1, "x y z", "https://a.example/1", d=dt.date(2026, 1, 1))
    assert dedupe.check_temporal_consistency(e, dt.date(2026, 3, 1)) == "dated_before_event"
    assert "dated_before_event" in e.flags
