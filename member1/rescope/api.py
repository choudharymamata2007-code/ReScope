"""The one object Member 2 imports. It wires the store, cache, fetcher and search client and exposes
the interfaces agreed in plan Section 6.3:

  resolve(name)                         -> CompanyProfile
  collect(profile, ...)                 -> summary dict (items stored in SQLite; errors listed, never raised)
  build_metrics(entity, role)           -> {metric_name: MetricSeries} (also saved to the store)
  benchmark(profile)                    -> Benchmark dict (company vs peers vs industry)
  triangulate(claims)                   -> corroboration map
  say_vs_do(statements, entity)         -> alignment rows
  disclosure_changes(entity)            -> change flags
  coverage(profile)                     -> coverage report (score, warnings, proxies)
  search(query) / find_disconfirming(hypothesis, entity, peers) / find_prior_coverage(finding, entity)
"""
from __future__ import annotations
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from . import config
from .analysis import disclosure_change as dc
from .analysis import say_vs_do as sd
from .analysis import triangulation as tri
from .analysis.sufficiency import coverage_report
from .cache import DiskCache
from .collectors import search as srch
from .collectors.documents import DocumentCollector, load_official_domains
from .collectors.industry import IndustryCollector, NewsCollector, collect_trends
from .collectors.search import SearchClient
from .collectors.structured import StructuredCollector
from .http import Fetcher
from .intake.listings import ListedCompany
from .intake.resolver import co_mentioned, is_not_a_peer, resolve_company
from .quant import benchmark as bm
from .quant.extract import extract_from_evidence
from .quant.mix import extract_mix_series
from .quant.series import build_metric_series, prior_year, raw_from_extracted
from .quant.volume_claims import apply_stated_sales, apply_stated_volume, extract_volume_claims
from .schema import CompanyProfile, MetricSeries, PeerRef, Role
from .store import EvidenceStore


def validate_company_input(name: str) -> str:
    """Input validation for the live demo: a company name only, short, no markup."""
    n = (name or "").strip()
    if not (2 <= len(n) <= 80):
        raise ValueError("enter a company name between 2 and 80 characters")
    if re.search(r"[<>{};$`\\]", n):
        raise ValueError("company name contains unsupported characters")
    return n


class Member1API:
    def __init__(self, store: Optional[EvidenceStore] = None, cache: Optional[DiskCache] = None,
                 fetcher: Optional[Fetcher] = None, search_client: Optional[SearchClient] = None,
                 universe: Optional[list[ListedCompany]] = None, all_listed: Optional[list[ListedCompany]] = None,
                 ticker_factory=None):
        self.cache = cache or DiskCache()
        self.store = store or EvidenceStore()
        self.fetcher = fetcher or Fetcher(self.cache)
        self.search_client = search_client or SearchClient(self.cache, self.fetcher)
        self.universe = universe or []
        self.ticker_factory = ticker_factory      # None = the aggregator library; injectable for offline tests
        self.all_listed = all_listed or []        # full exchange list (names only): used to find peers named in documents
        self.last_metric_notes: dict[str, list[str]] = {}

    # ---- 1.2 intake ----
    def resolve(self, name: str, business_text: list[str] | None = None, competition_text: str = "") -> CompanyProfile:
        name = validate_company_input(name)
        has = lambda c: True            # replace with a real filings-availability probe once collectors are verified
        return resolve_company(name, self.universe, business_text, competition_text, has)

    # ---- 1.3-1.6 collection (parallel, failure-tolerant) ----
    def collect(self, profile: CompanyProfile, kinds: list[str] | None = None, years: list[str] | None = None,
                include_peers: bool = True, include_structured: bool = True, peer_documents: bool = False,
                refine_peers: bool = True, include_trends: bool = False, news_query: Optional[str] = None, rss_urls: list[str] | None = None,
                industry_cfg: list[dict] | None = None, max_workers: int = 4) -> dict:
        jobs: list[tuple[str, callable]] = []

        def doc_job(label, name, entity, role):
            def run():
                return DocumentCollector(self.fetcher, self.search_client, None, official_domains=load_official_domains(name)).collect(name, entity, role, kinds, years)
            jobs.append((label, run))
        doc_job(f"documents:{profile.name}", profile.name, profile.name, Role.company)
        if include_peers and peer_documents:          # off by default: peers use structured data (faster, fewer blocked downloads)
            for p in profile.peers:
                doc_job(f"documents:{p.name}", p.name, p.name, Role.peer)
        if include_structured:
            def structured_job(label, symbol, entity, role):
                jobs.append((label, lambda: StructuredCollector(self.cache, ticker_factory=self.ticker_factory).collect(symbol, entity, role)))
            if profile.nse_symbol:
                structured_job(f"structured:{profile.name}", profile.nse_symbol, profile.name, Role.company)
            if include_peers:
                for p in profile.peers:
                    if p.symbol:
                        structured_job(f"structured:{p.name}", p.symbol, p.name, Role.peer)
        jobs.append(("news", lambda: NewsCollector(self.fetcher, None, self.search_client).collect(profile.name, news_query or profile.name, rss_urls)))
        ind = IndustryCollector(self.fetcher, None)
        series_out: list[MetricSeries] = []

        def ind_job():
            r, s = ind.collect(industry_cfg)
            series_out.extend(s)
            return r
        jobs.append(("industry", ind_job))

        summary = {"sources": {}, "errors": [], "new_items": 0}
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = [(label, ex.submit(fn)) for label, fn in jobs]
            for label, f in futs:
                try:
                    r = f.result()
                    summary["new_items"] += self.store.add_many(r.items)
                    summary["sources"][label] = {"items": len(r.items), "errors": len(r.errors), "fallback": r.used_fallback}
                    summary["errors"] += [f"{label}: {e}" for e in r.errors]
                except Exception as exc:                     # one failing source never stops the run
                    summary["sources"][label] = {"items": 0, "errors": 1, "fallback": False}
                    summary["errors"].append(f"{label}: {exc}")
        for s in series_out:
            self.store.save_series(s)
        if include_trends:
            ev_s = collect_trends(profile.name)
            if ev_s:
                self.store.add(ev_s[0])
                self.store.save_series(ev_s[1])
        if include_peers and refine_peers and (len(profile.peers) < 3 or self.all_listed):
            new_peers = self.refine_peers(profile)
            summary["new_peers"] = [p.name for p in new_peers]
            if new_peers and include_structured:
                with ThreadPoolExecutor(max_workers=max_workers) as ex:
                    futs = [(p, ex.submit(lambda p=p: StructuredCollector(self.cache, ticker_factory=self.ticker_factory).collect(p.symbol, p.name, Role.peer)))
                            for p in new_peers if p.symbol]
                    for p, f in futs:
                        try:
                            r = f.result()
                            summary["new_items"] += self.store.add_many(r.items)
                            summary["sources"][f"structured:{p.name}"] = {"items": len(r.items), "errors": len(r.errors), "fallback": False}
                            summary["errors"] += [f"structured:{p.name}: {e}" for e in r.errors]
                        except Exception as exc:
                            summary["errors"].append(f"structured:{p.name}: {exc}")
        for p in profile.peers:                      # filings-availability check from what was actually collected
            p.filings_available = bool(self.store.query(entity=p.name))
        return summary

    def refine_peers(self, profile: CompanyProfile, min_docs: int = 2, max_peers: int = 6, min_peers: int = 3) -> list[PeerRef]:
        """Improve the peer list with companies named in at least `min_docs` of the company's own documents.
        Brokers, rating agencies and banks are never peers. When the aggregator gives the target's industry, a peer
        must share it (or, weaker, its sector); NSE same-label peers that do not match are replaced when at least
        `min_peers` matching peers exist. Returns the peers that are new."""
        pool = self.all_listed or self.universe
        if not pool:
            return []
        docs: dict[str, str] = {}
        for e in self.store.query(entity=profile.name):
            docs[e.url] = docs.get(e.url, "") + " " + e.text
        exclude = {x for x in [profile.nse_symbol] if x}
        mentioned = [(c, n) for c, n in co_mentioned(docs, pool, exclude, min_docs) if not is_not_a_peer(c.name)][:15]
        existing = list(profile.peers)
        have = {p.symbol for p in existing}
        cands = list(existing) + [PeerRef(name=c.name, symbol=c.symbol, mentioned_in_report=True, score=float(n),
                                          reason=f"named in {n} of the company's documents") for c, n in mentioned if c.symbol not in have]
        sc = StructuredCollector(self.cache, ticker_factory=self.ticker_factory)
        target = sc.classify(profile.nse_symbol) if profile.nse_symbol else {}
        if not (target.get("industry") or target.get("sector")):
            kept = [p for p in cands if not is_not_a_peer(p.name)]            # no classification: names filtered only
            kept = kept[:max_peers] if len(existing) < min_peers else existing + [p for p in kept if p not in existing][:max_peers - len(existing)]
        else:
            strong, weak = [], []
            for p in cands:
                if not p.symbol or is_not_a_peer(p.name):
                    continue
                cl = sc.classify(p.symbol)
                if target.get("industry") and cl.get("industry") == target["industry"]:
                    p.reason += f"; same industry ({cl['industry']})"
                    strong.append(p)
                elif target.get("sector") and cl.get("sector") == target["sector"] and p.mentioned_in_report and p.score >= 3:
                    p.reason += f"; same sector ({cl['sector']})"
                    weak.append(p)
            kept = (strong + weak)[:max_peers]
            if len(kept) < min_peers:                                           # too few matches: keep the originals as a fallback
                kept += [p for p in existing if p not in kept][:max_peers - len(kept)]
        removed = [p.name for p in existing if p not in kept]
        new = [p for p in kept if p.symbol not in have]
        profile.peers[:] = kept
        if new:
            profile.warnings.append(f"peers added from company documents: {', '.join(p.name for p in new)}")
        if removed:
            profile.warnings.append(f"peers removed (industry does not match): {', '.join(removed)}")
        return new

    def industry_helpers(self) -> tuple[dict[str, float], dict[str, str]]:
        """From the industry series config flags: {period: yoy inflation} from the series marked "price_index",
        and {company metric: industry series} from the series marked "pairs_with"."""
        series = self.store.load_series("industry")
        infl: dict[str, float] = {}
        imap: dict[str, str] = {}
        for ev in self.store.query(role="industry"):
            sid = (ev.locator or "").replace("series:", "")
            if sid not in series:
                continue
            vals = {p.period: p.value for p in series[sid].points if p.value is not None}
            for f in ev.flags:
                if f == "price_index" and not infl:
                    infl = {p: v / vals[prior_year(p)] - 1 for p, v in vals.items() if vals.get(prior_year(p))}
                elif f.startswith("pairs_with:"):
                    imap[f.split(":", 1)[1]] = sid
        return infl, imap

    def build_metrics(self, entity: str, role: Role = Role.company, inflation_by_period: dict[str, float] | None = None,
                      cross_check_tol: float = 0.02) -> dict[str, MetricSeries]:
        items = [e for e in self.store.query(entity=entity, role=role.value)]
        if inflation_by_period is None:
            inflation_by_period = self.industry_helpers()[0] or None        # price index from the industry config, if any
        raw = raw_from_extracted(extract_from_evidence(items))
        claims = extract_volume_claims(items)
        raw = apply_stated_sales(apply_stated_volume(raw, claims), claims)   # management-stated volume and sales growth, quarter-matched
        self.last_metric_notes[entity] = list(raw.attrs.get("notes", []))
        if raw.empty:
            return {}
        series = build_metric_series(raw, entity, role, inflation_by_period)
        for mix in extract_mix_series(items, entity, role):                  # segment / channel shares where a table supports them
            series[mix.name] = mix
        for s in series.values():
            self.store.save_series(s)
        return series

    def get_metrics(self, entity: str) -> dict[str, MetricSeries]:
        return self.store.load_series(entity)

    # ---- 1.9 benchmark ----
    def benchmark(self, profile: CompanyProfile, industry_map: dict[str, str] | None = None) -> dict:
        company = self.store.load_series(profile.name)
        peers = {p.name: self.store.load_series(p.name) for p in profile.peers if self.store.load_series(p.name)}
        industry = self.store.load_series("industry")
        return bm.benchmark(profile.name, company, peers, industry, industry_map or self.industry_helpers()[1]).to_dict()

    # ---- 1.10 / 1.11 analysis ----
    def triangulate(self, claims: list[tri.ClaimRef], entity: Optional[str] = None, embed=None) -> list[dict]:
        ev = self.store.all() if entity is None else self.store.query(entity=entity) + \
            [e for e in self.store.all() if e.role != Role.company]
        return tri.to_dicts(tri.corroboration_map(claims, ev, embed))

    def say_vs_do(self, statements: list[sd.Statement], entity: str) -> list[dict]:
        return sd.to_dicts(sd.evaluate(statements, self.store.load_series(entity)))

    def disclosure_changes(self, entity: str) -> list[dict]:
        return dc.to_dicts(dc.detect_disclosure_changes(self.store.query(entity=entity)))

    def coverage(self, profile: CompanyProfile) -> dict:
        ev = self.store.query(entity=profile.name) + self.store.query(role="industry") + \
            [e for p in profile.peers for e in self.store.query(entity=p.name)]
        peers_with_data = sum(1 for p in profile.peers if self.store.load_series(p.name))
        return coverage_report(ev, self.store.load_series(profile.name), peers_with_data).to_dict()

    # ---- 1.6 hooks for Member 2 ----
    def search(self, query: str, entity: str = "", n: int = 8):
        return self.search_client.search_evidence(query, entity or "unknown", Role.company, n)

    def find_disconfirming(self, hypothesis: dict, entity: str, peers: list[str] | None = None):
        items = srch.find_disconfirming(self.search_client, hypothesis, entity, peers)
        self.store.add_many(items)
        return items

    def find_prior_coverage(self, finding: str, entity: str, before=None) -> dict:
        res = srch.find_prior_coverage(self.search_client, finding, entity, before)
        self.store.add_many(res["items"])
        return res
