"""Focused reliability and integration edge-case tests for Member 1."""
import concurrent.futures
import pytest
from rescope.analysis.triangulation import ClaimRef, cluster_claims, corroboration_map, get_embedder
from rescope.cache import DiskCache
from rescope.collectors.documents import DocumentCollector
from rescope.collectors.pdf_utils import extract_pdf
from rescope.collectors.search import SearchClient
from rescope.http import Fetcher
from rescope.quant.extract import parse_number
from rescope.quant.series import build_metric_series
from rescope.schema import Evidence, Role, SourceType
from rescope.store import EvidenceStore
import pandas as pd


def test_corrupt_pdf_handled_gracefully():
    # Corrupt PDF header / truncated binary
    corrupt_bytes = b"%PDF-corrupted-binary-trash-\x00\xff\xfe\xca\xfe"
    pages = extract_pdf(corrupt_bytes)
    assert pages == []


def test_html_disguised_as_pdf(tmp_path):
    # Server returns 403 or HTML block page under a .pdf URL
    html_page = b"<html><head><title>Access Denied</title></head><body><p>Cloudflare block</p></body></html>"
    dc = DocumentCollector(Fetcher(DiskCache(tmp_path), transport=lambda *a: None, min_interval=0), SearchClient(DiskCache(tmp_path)))
    items = dc.ingest_bytes(html_page, "https://company.invalid/results.pdf", "TestCo", Role.company, "results", "application/pdf")
    assert len(items) >= 1
    assert "Cloudflare block" in items[0].text or "Access Denied" in items[0].text


def test_empty_kinds_returns_immediately_without_error(tmp_path):
    dc = DocumentCollector(Fetcher(DiskCache(tmp_path), transport=lambda *a: None, min_interval=0), SearchClient(DiskCache(tmp_path)))
    res = dc.collect("TestCo", "TestCo", Role.company, kinds=[])
    assert res.items == []
    assert res.errors == []


def test_currency_symbol_parsing():
    assert parse_number("INR 1,234.5") == 1234.5
    assert parse_number("₹ 5,678.90") == 5678.9
    assert parse_number("Rs. 450") == 450.0
    assert parse_number("Rs 300.25") == 300.25
    assert parse_number("None") is None


def test_negative_100_percent_volume_growth_safety():
    # Volume drops to 0 (growth = -1.0), should not raise ZeroDivisionError
    raw = pd.DataFrame(
        {"revenue": [100.0, 110.0], "volume_growth": [None, -1.0]},
        index=["Q1 FY25", "Q1 FY26"]
    )
    series = build_metric_series(raw, "TestCo")
    assert "volume_growth_yoy" in series
    pts = series["volume_growth_yoy"].points
    assert pts[-1].value == -1.0
    # Because price_mix_growth is undefined/None, it should not produce a bogus series
    assert "price_mix_growth_yoy" not in series


def test_tfidf_embedder_with_stop_words_only():
    embed = get_embedder("tfidf")
    # All stop words: falls back to char_wb analyzer without crashing
    res = embed(["the and", "of in to"])
    assert res.shape[0] == 2 and res.shape[1] > 0
    # Empty claim list
    claims = [ClaimRef("the and", "e1"), ClaimRef("in to", "e2")]
    clusters = cluster_claims(claims, embed=embed)
    assert len(clusters) >= 1


def test_evidence_store_concurrent_threads(tmp_path):
    store = EvidenceStore(tmp_path / "thread_test.db")
    
    def worker(i):
        for j in range(20):
            ev = Evidence(
                id=f"ev_{i}_{j}",
                title=f"Title {i}_{j}",
                text=f"Sample text {i}_{j}",
                url=f"https://example.invalid/{i}/{j}",
                source_type=SourceType.news,
                source_tier=4,
                entity="TestCo",
                role=Role.company
            )
            store.add(ev)
        return True

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(worker, i) for i in range(8)]
        assert all(f.result() for f in futs)
    
    assert store.count() == 160
    assert len(store.query(entity="TestCo")) == 160
