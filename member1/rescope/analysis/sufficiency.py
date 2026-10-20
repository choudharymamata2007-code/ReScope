"""Task 1.11 (part 3): data sufficiency warning and coverage meter. The score feeds Member 2's
Evidence Strength rating (Coverage weight 0.10) and the dashboard coverage panel."""
from __future__ import annotations
from dataclasses import dataclass, asdict, field
from typing import Optional
from urllib.parse import urlparse
from .. import config
from ..quant.series import sort_periods
from ..schema import Evidence, MetricSeries, Role, SourceType

CORE_METRICS = ["receivable_days", "inventory_days", "revenue_growth_yoy", "volume_growth_yoy",
                "price_mix_growth_yoy", "gross_margin"]
# weight of each source type in the 'source types present' component
TYPE_WEIGHTS = {SourceType.results: 2.0, SourceType.annual_report: 1.5, SourceType.presentation: 1.5,
                SourceType.transcript: 1.0, SourceType.news: 0.5, SourceType.gov_macro: 1.0,
                SourceType.filing: 1.0}


@dataclass
class CoverageReport:
    coverage_score: float
    sufficient: bool
    components: dict
    source_types_found: list[str]
    source_types_missing: list[str]
    quarters_covered: int
    metrics_disclosed: list[str]
    metrics_missing: list[str]
    proxies_used: list[str]
    peers_with_data: int
    has_outside_company_evidence: bool
    official_filings_found: bool = False
    missing_quarters: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _next_quarter(p: str) -> str:
    q, fy = p.split()
    n = int(q[1:])
    return f"Q{n + 1} {fy}" if n < 4 else f"Q1 FY{int(fy[2:]) + 1:02d}"


def _prev_quarter(p: str) -> str:
    q, fy = p.split()
    n = int(q[1:])
    return f"Q{n - 1} {fy}" if n > 1 else f"Q4 FY{int(fy[2:]) - 1:02d}"


def missing_quarters(quarters: set[str], window: Optional[int] = None) -> list[str]:
    """Quarters absent from the series. window=None: gaps between the first and last quarter present.
    window=8: gaps inside the latest 8 quarters (older stray points do not create long 'missing' lists)."""
    qs = sort_periods([q for q in quarters if q.startswith("Q")])
    if len(qs) < 2:
        return []
    if window:
        expected = [qs[-1]]
        while len(expected) < window:
            expected.append(_prev_quarter(expected[-1]))
        return sort_periods([q for q in expected if q not in quarters])
    out, cur = [], qs[0]
    while cur != qs[-1]:
        cur = _next_quarter(cur)
        if cur not in quarters:
            out.append(cur)
    return out


def coverage_report(evidence: list[Evidence], series: dict[str, MetricSeries], peers_with_data: int = 0,
                    required_metrics: Optional[list[str]] = None, min_quarters: int = config.MIN_QUARTERS_TARGET,
                    sufficiency_threshold: float = 0.5) -> CoverageReport:
    required = required_metrics or CORE_METRICS
    found_types = {e.source_type for e in evidence}
    total_w = sum(TYPE_WEIGHTS.values())
    type_score = sum(w for t, w in TYPE_WEIGHTS.items() if t in found_types) / total_w
    quarters = {p.period for s in series.values() for p in s.points if p.value is not None}
    q_n = len(quarters)
    q_score = min(1.0, q_n / min_quarters)
    disclosed = [m for m in required if m in series and series[m].values()]
    metric_score = len(disclosed) / len(required) if required else 1.0
    proxies = sorted(n for n, s in series.items() if s.has_proxy)
    outside = any(e.role in (Role.peer, Role.industry) or e.source_type in (SourceType.gov_macro, SourceType.news)
                  for e in evidence)
    peer_score = min(1.0, peers_with_data / 3)
    comp = {"source_types": round(type_score, 3), "quarters": round(q_score, 3), "metrics_disclosed": round(metric_score, 3),
            "peer_data": round(peer_score, 3), "outside_evidence": 1.0 if outside else 0.0}
    score = 0.25 * type_score + 0.25 * q_score + 0.25 * metric_score + 0.15 * peer_score + 0.10 * (1.0 if outside else 0.0)
    score -= 0.05 * len(proxies)                              # proxies lower coverage
    def verified_official_filing(e: Evidence) -> bool:
        if e.source_tier != 1 or e.source_type not in (
            SourceType.results, SourceType.filing, SourceType.annual_report
        ):
            return False

        flags = set(e.flags)
        if flags.intersection({
            "unverified_host", "third_party_host", "aggregator", "unofficial_data"
        }):
            return False

        host = (urlparse(e.url).hostname or "").lower().rstrip(".")
        if host.startswith("www."):
            host = host[4:]

        trusted_exchange_domains = ("bseindia.com", "nseindia.com", "sebi.gov.in")
        is_exchange = any(
            host == domain or host.endswith("." + domain)
            for domain in trusted_exchange_domains
        )

        # Company-domain allowlisting alone is not proof of ownership.
        # Reject documents whose title/text clearly indicates they are not
        # financial results, even if hosted on an exchange domain.
        explicitly_verified = "verified_official_source" in flags
        if not (is_exchange or explicitly_verified):
            return False

        content = f"{e.title} {e.text[:5000]}".lower()
        irrelevant_terms = (
            "scheme of arrangement",
            "scheme timetable",
            "board of directors and committees",
            "media statement and presentation",
        )
        if any(term in content for term in irrelevant_terms):
            # A media statement is not automatically a financial-results filing.
            return False

        return True

    official = any(verified_official_filing(e) for e in evidence)
    if not official:
        score -= 0.10                                          # no official filing was read: lower confidence
    gaps = missing_quarters(quarters, window=min_quarters)
    score = round(max(0.0, min(1.0, score)), 3)
    warn: list[str] = []
    if q_n < min_quarters:
        warn.append(f"only {q_n} quarters of data (target {min_quarters})")
    missing_m = [m for m in required if m not in disclosed]
    if missing_m:
        warn.append("metrics not available: " + ", ".join(missing_m))
    if proxies:
        warn.append("proxy values used for: " + ", ".join(proxies))
    if not outside:
        warn.append("no evidence from outside the company's own communication")
    if peers_with_data < 3:
        warn.append(f"only {peers_with_data} peers with data")
    if not official:
        warn.append("no official filing was read: quarterly figures come from an unofficial aggregator or third parties (tier 3 or lower)")
    if gaps:
        warn.append(f"missing quarters in the latest {min_quarters}: " + ", ".join(gaps))
    if SourceType.results not in found_types:
        warn.append("no quarterly results found")
    return CoverageReport(score, score >= sufficiency_threshold and SourceType.results in found_types, comp,
                          sorted(t.value for t in found_types),
                          sorted(t.value for t in TYPE_WEIGHTS if t not in found_types), q_n, disclosed, missing_m,
                          proxies, peers_with_data, outside, official, gaps, warn)
