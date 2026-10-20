from rescope.cache import DiskCache
from rescope.collectors.documents import DocumentCollector
from rescope.collectors.search import SearchClient
from rescope.http import Fetcher


def test_results_discovery_includes_bse_and_nse_queries(tmp_path):
    queries = []

    def backend(query, n):
        queries.append(query)
        return []

    fetcher = Fetcher(
        DiskCache(tmp_path / "http"),
        transport=lambda *args: None,
        min_interval=0,
    )
    client = SearchClient(
        DiskCache(tmp_path / "search"),
        fetcher,
        backend=backend,
        tavily_key="",
    )
    client._ddgs = lambda query, n: []

    collector = DocumentCollector(fetcher, client)
    collector.discover_urls("ITC Limited", "results", ["FY26"])

    assert any("site:bseindia.com" in q for q in queries)
    assert any("site:nseindia.com" in q for q in queries)
