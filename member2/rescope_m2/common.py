"""Shared helpers: fiscal periods, trend statistics, metric labels and metric access.
Nothing here knows any company name; all company detail arrives as data."""
from __future__ import annotations
import datetime as dt
import re
import statistics
from typing import Any, Iterable, Optional

PERIOD_RE = re.compile(r"Q([1-4])\s*FY\s*(\d{2,4})", re.I)


def parse_period(p: Optional[str]) -> Optional[tuple[int, int]]:
    m = PERIOD_RE.search(p or "")
    if not m:
        return None
    fy = int(m.group(2))
    fy = fy + 2000 if fy < 100 else fy
    return fy, int(m.group(1))


def period_key(p: Optional[str]) -> Optional[int]:
    x = parse_period(p)
    return None if x is None else x[0] * 4 + x[1] - 1


def period_end(p: Optional[str]) -> Optional[dt.date]:
    """Indian fiscal year: FY26 runs Apr 2025 to Mar 2026."""
    x = parse_period(p)
    if x is None:
        return None
    fy, q = x
    return {1: dt.date(fy - 1, 6, 30), 2: dt.date(fy - 1, 9, 30),
            3: dt.date(fy - 1, 12, 31), 4: dt.date(fy, 3, 31)}[q]


def sort_periods(periods: Iterable[str]) -> list[str]:
    return sorted(set(periods), key=lambda p: (period_key(p) is None, period_key(p) or 0, p))


# ---------------------------------------------------------------- statistics
def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


def median(xs: list[float]) -> Optional[float]:
    return statistics.median(xs) if xs else None


def trend(values: list[Optional[float]]) -> dict:
    """Direction from the mean of the first vs last third of the series, against the series' own spread.
    Scale-free, so it works for days, fractions and indices alike."""
    vals = [v for v in values if v is not None]
    n = len(vals)
    if n < 3:
        return {"n": n, "direction": "insufficient", "first": vals[0] if vals else None,
                "last": vals[-1] if vals else None, "delta": None, "relative_change": None}
    k = max(1, min(3, n // 3))
    first, last = mean(vals[:k]), mean(vals[-k:])
    delta = last - first
    thr = max(0.05 * mean([abs(v) for v in vals]), 0.75 * statistics.pstdev(vals), 1e-9)
    direction = "up" if delta > thr else "down" if delta < -thr else "flat"
    rel = delta / abs(first) if abs(first) > 1e-9 else None
    return {"n": n, "direction": direction, "first": vals[0], "last": vals[-1],
            "first_avg": first, "last_avg": last, "delta": delta, "relative_change": rel}


def detect_change_point(values: list[Optional[float]], min_seg: int = 3,
                        min_gain: float = 0.35) -> Optional[dict]:
    """Single mean-shift change point by minimum total squared error (rolling-window style, no extra deps).
    Returns an index into the NON-NULL list, or None when no split explains enough variance."""
    vals = [v for v in values if v is not None]
    n = len(vals)
    if n < 2 * min_seg:
        return None
    total = sum((v - mean(vals)) ** 2 for v in vals)
    if total <= 1e-12:
        return None
    best = None
    for k in range(min_seg, n - min_seg + 1):
        a, b = vals[:k], vals[k:]
        sse = sum((v - mean(a)) ** 2 for v in a) + sum((v - mean(b)) ** 2 for v in b)
        if best is None or sse < best[1]:
            best = (k, sse)
    k, sse = best
    gain = 1 - sse / total
    if gain < min_gain:
        return None
    before, after = mean(vals[:k]), mean(vals[k:])
    return {"index": k, "gain": gain, "before": before, "after": after,
            "direction": "up" if after > before else "down", "magnitude": after - before}


# ---------------------------------------------------------------- labels
METRIC_LABELS = {
    "revenue_growth_yoy": "Revenue growth (YoY)", "volume_growth_yoy": "Volume growth (YoY)",
    "price_mix_growth_yoy": "Price/mix growth (YoY)", "price_share_of_growth": "Price share of growth",
    "receivable_days": "Receivable days", "inventory_days": "Inventory days",
    "payable_days": "Payable days", "cash_conversion_cycle": "Cash conversion cycle (days)",
    "gross_margin": "Gross margin", "food_cpi": "Food CPI", "cpi_inflation": "CPI inflation",
}
METRIC_KIND = {"revenue_growth_yoy": "pct", "volume_growth_yoy": "pct", "price_mix_growth_yoy": "pct",
               "price_share_of_growth": "share", "gross_margin": "pct", "receivable_days": "days",
               "inventory_days": "days", "payable_days": "days", "cash_conversion_cycle": "days"}


def label(metric: str) -> str:
    return METRIC_LABELS.get(metric, metric.replace("_", " ").capitalize())


def fmt(metric: str, v: Optional[float]) -> str:
    if v is None:
        return "n/a"
    kind = METRIC_KIND.get(metric, "num")
    if kind == "pct":
        return f"{(0.0 if abs(v) < 0.0005 else v) * 100:.1f}%"
    if kind == "share":
        return f"{v * 100:.0f}%"
    if kind == "days":
        return f"{v:.0f} days"
    return f"{v:.1f}"


def get(obj: Any, key: str, default=None):
    """Read a field from a dict or an object (Member 1 returns both)."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    v = getattr(obj, key, default)
    return getattr(v, "value", v)


# ---------------------------------------------------------------- metric access
class MetricBook:
    """Uniform view over Member 1 metric output.
    Accepts {entity: {metric: {points: [...]}}} (export_for_member2) or {metric: [points]} (sample_outputs)."""

    INDUSTRY = "industry"

    def __init__(self, metrics: dict, company: str):
        self.company = company
        self.data: dict[str, dict[str, list[dict]]] = {}
        metrics = metrics or {}
        if metrics and all(isinstance(v, list) for v in metrics.values()):
            metrics = {company: {k: {"points": v} for k, v in metrics.items()}}
        for ent, ms in metrics.items():
            self.data[ent] = {}
            for name, s in (ms or {}).items():
                if isinstance(s, list):          # bundle format: {metric: [points]}
                    pts = s
                else:                            # Member 1 format: {metric: {points: [...]}}
                    pts = s.get("points", []) if isinstance(s, dict) else get(s, "points", [])
                self.data[ent][name] = [p if isinstance(p, dict) else p.model_dump() for p in pts]

    @property
    def peers(self) -> list[str]:
        return [e for e in self.data if e not in (self.company, self.INDUSTRY) and self.data[e]]

    def metric_names(self, entity: Optional[str] = None) -> list[str]:
        return [m for m, pts in self.data.get(entity or self.company, {}).items()
                if any(p.get("value") is not None for p in pts)]

    def points(self, entity: str, metric: str) -> list[dict]:
        pts = [p for p in self.data.get(entity, {}).get(metric, []) if p.get("value") is not None]
        return sorted(pts, key=lambda p: (period_key(p["period"]) is None, period_key(p["period"]) or 0))

    def series(self, entity: str, metric: str) -> list[tuple[str, float]]:
        return [(p["period"], p["value"]) for p in self.points(entity, metric)]

    def values(self, entity: str, metric: str) -> list[float]:
        return [v for _, v in self.series(entity, metric)]

    def has_proxy(self, entity: str, metric: str) -> bool:
        return any(p.get("is_proxy") for p in self.points(entity, metric))

    def peer_median(self, metric: str) -> list[tuple[str, float]]:
        by_p: dict[str, list[float]] = {}
        for pe in self.peers:
            for per, v in self.series(pe, metric):
                by_p.setdefault(per, []).append(v)
        return [(p, median(by_p[p])) for p in sort_periods(by_p)]
