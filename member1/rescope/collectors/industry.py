"""Task 1.5/1.6: industry and macro series (role=industry, tier 2), news (RSS + GDELT) and light
alternative data. Series are configured in config/industry_series.json so the team fills in verified
IDs/URLs; nothing here is company-specific."""
from __future__ import annotations
import io
import json
from pathlib import Path
from typing import Optional
import feedparser
import pandas as pd
from .. import config
from ..http import Fetcher
from ..schema import CollectorResult, Evidence, MetricPoint, MetricSeries, Role, SourceType
from ..store import EvidenceStore
from ..tagging.tagger import fiscal_period_for_date, make_evidence, parse_date


def load_series_config(path: Path | str | None = None) -> list[dict]:
    p = Path(path or config.ROOT / "config" / "industry_series.json")
    return json.loads(p.read_text()) if p.exists() else []


def _series_to_outputs(series_id: str, title: str, url: str, df: pd.DataFrame, unit: str,
                       publisher: Optional[str] = None) -> tuple[MetricSeries, Evidence]:
    """df has columns date (datetime-like) and value (float)."""
    df = df.dropna().sort_values("date")
    pts = [MetricPoint(period=fiscal_period_for_date(d.date()), value=float(v), unit=unit,
                       locator=f"series:{series_id}") for d, v in zip(df["date"], df["value"])]
    # keep the last observation per fiscal quarter
    seen: dict[str, MetricPoint] = {}
    for p in pts:
        seen[p.period] = p
    series = MetricSeries(name=series_id, entity="industry", role=Role.industry, unit=unit, points=list(seen.values()))
    last = list(seen.values())[-8:]
    text = f"{title}: " + "; ".join(f"{p.period}={p.value:g}" for p in last) + (f" ({unit})" if unit else "")
    ev = make_evidence(title=title, text=text, url=url, entity="industry", role=Role.industry,
                       locator=f"series:{series_id}", source_type=SourceType.gov_macro, tier=2, publisher=publisher)
    return series, ev


def parse_csv_series(content: bytes | str, date_col: str, value_col: str) -> pd.DataFrame:
    raw = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
    df = pd.read_csv(io.StringIO(raw))
    out = pd.DataFrame({"date": pd.to_datetime(df[date_col], errors="coerce", dayfirst=True),
                        "value": pd.to_numeric(df[value_col], errors="coerce")})
    return out.dropna()


def parse_world_bank(payload: list) -> pd.DataFrame:
    rows = payload[1] if isinstance(payload, list) and len(payload) > 1 else []
    return pd.DataFrame({"date": pd.to_datetime([f"{r['date']}-03-31" if len(str(r["date"])) == 4 else r["date"]
                                                for r in rows], errors="coerce"),
                         "value": pd.to_numeric([r.get("value") for r in rows], errors="coerce")}).dropna()


class IndustryCollector:
    def __init__(self, fetcher: Fetcher, store: Optional[EvidenceStore] = None):
        self.fetcher, self.store = fetcher, store

    def collect(self, series_cfg: list[dict] | None = None) -> tuple[CollectorResult, list[MetricSeries]]:
        res, all_series = CollectorResult(source="industry"), []
        for cfg in series_cfg if series_cfg is not None else load_series_config():
            try:
                kind, sid, url = cfg["kind"], cfg["id"], cfg["url"]
                if cfg.get("path"):          # an UNEDITED official download saved by hand; url stays the public source page
                    content, text = Path(cfg["path"]).read_bytes(), Path(cfg["path"]).read_text(encoding="utf-8-sig", errors="replace")
                else:
                    r = self.fetcher.get(url, params=cfg.get("params"), ttl=14 * 86400)
                    if not r.ok:
                        raise RuntimeError(f"HTTP {r.status}")
                    content, text = r.content, r.text
                if kind == "csv":
                    df = parse_csv_series(content, cfg["date_col"], cfg["value_col"])
                elif kind == "world_bank":
                    df = parse_world_bank(json.loads(text))
                else:
                    raise ValueError(f"unknown series kind {kind}")
                s, ev = _series_to_outputs(sid, cfg.get("title", sid), url, df, cfg.get("unit", ""))
                if cfg.get("path"):
                    ev.flags.append("manual_download")
                if cfg.get("price_index"):
                    ev.flags.append("price_index")                       # used to deflate revenue growth when volume is not disclosed
                if cfg.get("pairs_with"):
                    ev.flags.append(f"pairs_with:{cfg['pairs_with']}")   # compared with this company metric in the benchmark
                res.items.append(ev)
                all_series.append(s)
                if self.store:
                    self.store.add(ev)
                    self.store.save_series(s)
            except Exception as exc:
                res.errors.append(f"{cfg.get('id', '?')}: {exc}")
        return res, all_series


class NewsCollector:
    """RSS feeds (given URLs) and GDELT DOC API. News is tier 4; independence is judged later."""

    def __init__(self, fetcher: Fetcher, store: Optional[EvidenceStore] = None, search=None):
        self.fetcher, self.store, self.search = fetcher, store, search

    def from_rss(self, feed_url: str, entity: str, role: Role = Role.company, keyword: str | None = None) -> list[Evidence]:
        r = self.fetcher.get(feed_url, ttl=6 * 3600)
        feed = feedparser.parse(r.content)
        out = []
        for e in feed.entries:
            blob = f"{e.get('title', '')} {e.get('summary', '')}"
            if keyword and keyword.lower() not in blob.lower():
                continue
            d = parse_date(e.get("published", "") or e.get("updated", "") or "")
            out.append(make_evidence(title=e.get("title", "")[:300], text=blob, url=e.get("link", feed_url),
                                     entity=entity, role=role, date=d, hint=SourceType.news, locator="rss"))
        return out

    def from_gdelt(self, query: str, entity: str, role: Role = Role.company, max_records: int = 25) -> list[Evidence]:
        r = self.fetcher.get(config.URLS["gdelt_doc_api"], ttl=6 * 3600, params={
            "query": query, "mode": "ArtList", "format": "json", "maxrecords": max_records})
        if not r.ok:
            return []
        out = []
        try:
            articles = json.loads(r.text).get("articles", [])
        except ValueError:
            raise RuntimeError("GDELT returned a non-JSON reply (usually a rate limit); using search for news instead")
        for a in articles:
            d = parse_date(a.get("seendate", "")[:8] and f"{a['seendate'][:4]}-{a['seendate'][4:6]}-{a['seendate'][6:8]}")
            out.append(make_evidence(title=a.get("title", ""), text=a.get("title", ""), url=a["url"], entity=entity,
                                     role=role, date=d, hint=SourceType.news, locator="gdelt",
                                     publisher=a.get("domain")))
        return out

    def collect(self, entity: str, query: str, rss_urls: list[str] | None = None) -> CollectorResult:
        res = CollectorResult(source="news")
        for u in rss_urls or []:
            try:
                res.items += self.from_rss(u, entity, keyword=entity)
            except Exception as exc:
                res.errors.append(f"rss {u}: {exc}")
        try:
            res.items += self.from_gdelt(query, entity)
        except Exception as exc:
            res.errors.append(f"gdelt: {exc}")
        if not res.items and self.search is not None:          # fallback: news through the search provider
            try:
                res.items += self.search.search_evidence(f"{entity} latest news analysis", entity, Role.company, 8,
                                                         hint=SourceType.news)
                res.used_fallback = bool(res.items)
            except Exception as exc:
                res.errors.append(f"search fallback: {exc}")
        if self.store:
            self.store.add_many(res.items)
        return res


def wayback_snapshot(fetcher: Fetcher, url: str, timestamp: str | None = None) -> Optional[dict]:
    """Closest archived copy of a page (alt-data: how a careers/IR page looked earlier)."""
    params = {"url": url, **({"timestamp": timestamp} if timestamp else {})}
    r = fetcher.get(config.URLS["wayback_available"], params=params, ttl=30 * 86400)
    if not r.ok:
        return None
    snap = json.loads(r.text).get("archived_snapshots", {}).get("closest")
    return snap if snap and snap.get("available") else None


def trends_series(keyword: str, geo: str = "IN", timeframe: str = "today 5-y") -> Optional[pd.DataFrame]:
    """Optional Google Trends (unofficial, may be rate-limited). Returns None if pytrends is unavailable."""
    try:
        from pytrends.request import TrendReq
    except ImportError:
        return None
    try:
        t = TrendReq(hl="en-IN", tz=330)
        t.build_payload([keyword], geo=geo, timeframe=timeframe)
        df = t.interest_over_time()
        return None if df.empty else df.reset_index().rename(columns={keyword: "value"})[["date", "value"]]
    except Exception:
        return None


def collect_trends(entity: str, fetch=trends_series, keyword: Optional[str] = None):
    """Optional alternative data: search interest (Google Trends, unofficial) as a quarterly series.
    Returns (Evidence, MetricSeries) or None when unavailable. Search interest is a lead, never proof."""
    kw = keyword or " ".join(w for w in entity.split() if w.lower().strip(".") not in ("ltd", "limited", "pvt", "private"))
    df = fetch(kw)
    if df is None or len(df) == 0:
        return None
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["q"] = df["date"].dt.date.map(fiscal_period_for_date)
    q = df.groupby("q")["value"].mean()
    order = sorted(q.index, key=lambda p: (int(p.split("FY")[1]), int(p[1])))
    pts = [MetricPoint(period=p, value=float(q[p]), unit="index 0-100", locator=f"series:search_interest:{kw}") for p in order]
    series = MetricSeries(name="search_interest", entity=entity, role=Role.company, unit="index 0-100", points=pts)
    text = f"Search interest for '{kw}' (Google Trends, unofficial): " + "; ".join(f"{p.period}={p.value:.0f}" for p in pts[-8:])
    ev = make_evidence(title=f"Search interest: {kw}", text=text, url="https://trends.google.com/trends/explore?q=" + kw.replace(" ", "+"),
                       entity=entity, role=Role.company, locator=f"series:search_interest:{kw}",
                       source_type=SourceType.alt_data, tier=4, publisher="trends.google.com")
    ev.flags += ["unofficial_data", "lead_only"]
    return ev, series
