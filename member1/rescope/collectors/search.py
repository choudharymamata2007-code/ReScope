"""Task 1.6: web search (Tavily, with a no-key DuckDuckGo fallback) and the two hooks Member 2 calls:
  - find_disconfirming(hypothesis, ...)  -> evidence that may contradict a hypothesis (skeptic)
  - find_prior_coverage(finding, ...)    -> evidence of prior news coverage (novelty check)
Both return tagged Evidence and also use the shared cache."""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Callable, Optional
from .. import config
from ..cache import DiskCache
from ..http import Fetcher
from ..schema import Evidence, Role, SourceType
from ..tagging.dedupe import independent_sources
from ..tagging.tagger import make_evidence, parse_date


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str
    published: Optional[dt.date] = None
    score: float = 0.0
    provider: str = ""


class SearchClient:
    """provider order: injected backend -> Tavily (if key) -> ddgs (if installed)."""

    def __init__(self, cache: Optional[DiskCache] = None, fetcher: Optional[Fetcher] = None,
                 backend: Optional[Callable[[str, int], list[SearchHit]]] = None,
                 tavily_key: Optional[str] = None):
        self.cache = cache or DiskCache()
        self.fetcher = fetcher or Fetcher(self.cache)
        self.backend = backend
        self.tavily_key = tavily_key if tavily_key is not None else config.TAVILY_API_KEY
        self.last_provider = ""
        self.errors: list[str] = []

    def _tavily(self, query: str, n: int) -> list[SearchHit]:
        import requests
        r = requests.post(config.URLS["tavily_search"], timeout=config.HTTP_TIMEOUT, json={
            "api_key": self.tavily_key, "query": query, "max_results": n, "search_depth": "basic"},
            headers={"User-Agent": config.USER_AGENT})
        r.raise_for_status()
        out = []
        for h in r.json().get("results", []):
            out.append(SearchHit(h.get("title", ""), h.get("url", ""), h.get("content", ""),
                                 parse_date(h.get("published_date", "") or ""), float(h.get("score", 0) or 0), "tavily"))
        return out

    def _ddgs(self, query: str, n: int) -> list[SearchHit]:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS          # older package name
        out = []
        with DDGS(timeout=5) as d:
            for h in d.text(query, max_results=n):
                out.append(SearchHit(h.get("title", ""), h.get("href", ""), h.get("body", ""), None, 0.0, "ddgs"))
        return out

    def search(self, query: str, n: int = 8) -> list[SearchHit]:
        key = "search:" + hashlib.sha1(f"{query}|{n}".encode()).hexdigest()
        cached = self.cache.get_json(key, ttl=3 * 86400)
        if cached is not None:
            self.last_provider = "cache"
            return [SearchHit(**{**h, "published": parse_date(h["published"]) if h.get("published") else None})
                    for h in cached]
        providers: list[tuple[str, Callable]] = []
        if self.backend:
            providers.append(("backend", self.backend))
        if self.tavily_key:
            providers.append(("tavily", self._tavily))
        providers.append(("ddgs", self._ddgs))
        for name, fn in providers:
            try:
                hits = fn(query, n)
                if hits:
                    self.last_provider = name
                    self.cache.set_json(key, [{**h.__dict__, "published": h.published.isoformat() if h.published else None}
                                              for h in hits])
                    return hits
            except Exception as exc:                    # quota, network, missing package: try the next provider
                self.errors.append(f"{name}: {exc}")
        return []

    def search_evidence(self, query: str, entity: str, role: Role = Role.company, n: int = 8,
                        hint: SourceType = SourceType.news, drop_before: Optional[dt.date] = None) -> list[Evidence]:
        items = []
        for h in self.search(query, n):
            if not h.url:
                continue
            if drop_before and h.published and h.published < drop_before:
                continue
            ev = make_evidence(title=h.title or h.url, text=(h.snippet or h.title or h.url), url=h.url,
                               entity=entity, role=role, date=h.published, hint=hint,
                               locator=f"search:{self.last_provider or h.provider}")
            items.append(ev)
        return items


# ---------- hooks used by Member 2 ----------

_OPPOSITE = {"increase": "decline", "rise": "fall", "growth": "decline", "up": "down", "higher": "lower",
             "improve": "deteriorate", "expand": "contract", "strong": "weak", "stable": "volatile"}


def build_disconfirming_queries(hypothesis: dict, entity: str, peers: list[str] | None = None) -> list[str]:
    """hypothesis: {'text': str, 'metrics': [str], 'direction': optional str}. Returns neutral, company-free queries
    (the entity name is the only company-specific token and comes from the profile at run time)."""
    text = hypothesis.get("text", "")
    metrics = hypothesis.get("metrics", []) or []
    qs = [f"{entity} {text} criticism OR contradicts OR despite",
          f"{entity} {text} alternative explanation"]
    for m in metrics[:3]:
        qs.append(f"{entity} {m.replace('_', ' ')} trend analyst concern")
    flipped = text
    for k, v in _OPPOSITE.items():
        flipped = re.sub(rf"\b{k}\w*", v, flipped, flags=re.I)
    if flipped != text:
        qs.append(f"{entity} {flipped}")
    for p in (peers or [])[:2]:
        qs.append(f"{p} {' '.join(m.replace('_', ' ') for m in metrics[:2])} same trend industry")
    return list(dict.fromkeys(q.strip() for q in qs if q.strip()))


def find_disconfirming(client: SearchClient, hypothesis: dict, entity: str, peers: list[str] | None = None,
                       per_query: int = 5) -> list[Evidence]:
    out: list[Evidence] = []
    seen = set()
    for q in build_disconfirming_queries(hypothesis, entity, peers):
        for ev in client.search_evidence(q, entity, Role.company, per_query):
            if ev.url not in seen:
                seen.add(ev.url)
                ev.flags.append("disconfirming_search")
                out.append(ev)
    return out


def find_prior_coverage(client: SearchClient, finding: str, entity: str, before: Optional[dt.date] = None,
                        per_query: int = 8) -> dict:
    """For the novelty check. Returns {'items': [Evidence], 'independent_count': int, 'publishers': [...]}.
    Member 2 decides New / Partly reported / Known from the count and content similarity."""
    before = before or dt.date.today()
    keywords = " ".join(re.findall(r"[A-Za-z][A-Za-z\-]{3,}", finding)[:12])
    items: list[Evidence] = []
    for q in (f"{entity} {keywords}", f"{entity} {keywords} news analysis"):
        items += client.search_evidence(q, entity, Role.company, per_query, hint=SourceType.news)
    items = [e for e in items if not e.date or e.date <= before]
    indep = independent_sources(items)
    return {"items": items, "independent_count": len(indep),
            "publishers": sorted({e.publisher or "" for e in indep})}
