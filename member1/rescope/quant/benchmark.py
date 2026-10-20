"""Task 1.9: run the same metric comparison on peers and industry series and decide whether a
pattern is company-specific or sector-wide. Output is plain JSON-able data for Member 2's skeptic."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from statistics import median
from typing import Optional
import numpy as np
from ..schema import MetricSeries

FLAT_BAND = 0.05          # |relative change| below this counts as 'flat'


def trend(values: list[float], window: int = 8, min_points: int = 4) -> Optional[dict]:
    """Direction of a series: mean of last third vs first third over the last `window` points,
    plus least-squares slope per period. Returns None if fewer than `min_points` (default 4) points."""
    v = [x for x in values if x is not None][-window:]
    if len(v) < max(2, min_points):
        return None
    k = max(1, len(v) // 3)
    first, last = float(np.mean(v[:k])), float(np.mean(v[-k:]))
    scale = abs(first) if abs(first) > 1e-9 else (abs(last) if abs(last) > 1e-9 else 1.0)
    change = (last - first) / scale
    slope = float(np.polyfit(range(len(v)), v, 1)[0])
    direction = "flat" if abs(change) < FLAT_BAND else ("up" if change > 0 else "down")
    return {"first": first, "last": last, "relative_change": change, "slope": slope,
            "direction": direction, "n": len(v)}


@dataclass
class MetricComparison:
    metric: str
    company: Optional[dict]
    peer_median_change: Optional[float]
    peers_same_direction: int
    peers_total: int
    industry: Optional[dict] = None
    verdict: str = "insufficient"            # company_specific | sector_wide | mixed | insufficient
    note: str = ""


@dataclass
class Benchmark:
    entity: str
    peers: list[str]
    comparisons: list[MetricComparison] = field(default_factory=list)
    overall: str = "insufficient"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def compare_metric(metric: str, company: MetricSeries, peers: dict[str, MetricSeries],
                   industry: Optional[MetricSeries] = None) -> MetricComparison:
    c = trend(company.values(), min_points=2)
    if c is None:
        return MetricComparison(metric, None, None, 0, len(peers), verdict="insufficient", note="too few company points")
    same, changes = 0, []
    for name, s in peers.items():
        t = trend(s.values(), min_points=2)
        if t is None:
            continue
        changes.append(t["relative_change"])
        if t["direction"] == c["direction"] and c["direction"] != "flat":
            same += 1
    n_used = len(changes)
    ind = trend(industry.values(), min_points=2) if industry else None
    if n_used < 2:
        verdict, note = "insufficient", f"only {n_used} comparable peers"
    elif c["direction"] == "flat":
        verdict, note = "company_specific", "company flat; nothing to attribute to the sector"
    else:
        share = same / n_used
        ind_same = ind is not None and ind["direction"] == c["direction"]
        if share >= 0.67 or (share >= 0.5 and ind_same):
            verdict, note = "sector_wide", f"{same}/{n_used} peers moved the same way" + (" and the industry series agrees" if ind_same else "")
        elif share <= 0.25 and not ind_same:
            verdict, note = "company_specific", f"only {same}/{n_used} peers moved the same way"
        else:
            verdict, note = "mixed", f"{same}/{n_used} peers moved the same way"
    if c and c["n"] < 4:
        note += f" (short series: company has only {c['n']} points, treat as weak)"
    return MetricComparison(metric, c, float(median(changes)) if changes else None, same, n_used, ind, verdict, note)


def benchmark(entity: str, company_series: dict[str, MetricSeries], peer_series: dict[str, dict[str, MetricSeries]],
              industry_series: Optional[dict[str, MetricSeries]] = None,
              industry_map: Optional[dict[str, str]] = None, metrics: Optional[list[str]] = None) -> Benchmark:
    """peer_series: {peer_name: {metric_name: MetricSeries}}.
    industry_map: {company_metric_name: industry_series_name} to pair an industry series with a metric."""
    b = Benchmark(entity=entity, peers=sorted(peer_series))
    if len(peer_series) < 3:
        b.warnings.append(f"only {len(peer_series)} peers with data; benchmark has thin coverage")
    for metric in metrics or sorted(company_series):
        peers = {p: s[metric] for p, s in peer_series.items() if metric in s}
        ind = (industry_series or {}).get((industry_map or {}).get(metric, ""))
        b.comparisons.append(compare_metric(metric, company_series[metric], peers, ind))
    decisive = [c.verdict for c in b.comparisons if c.verdict != "insufficient"]
    if not decisive:
        b.overall = "insufficient"
    elif all(v == "sector_wide" for v in decisive):
        b.overall = "sector_wide"
    elif all(v == "company_specific" for v in decisive):
        b.overall = "company_specific"
    else:
        b.overall = "mixed"
    return b
