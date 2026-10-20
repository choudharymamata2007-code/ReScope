"""Task 1.8: assemble 8-12 quarter series with source pointers, reject inconsistent totals, label
proxies. Input is a raw table (one row per period) with optional per-column locators."""
from __future__ import annotations
import math
import re
from typing import Optional
import pandas as pd
from ..schema import MetricPoint, MetricSeries, Role
from . import metrics as m
from .extract import ExtractedRow


def sort_periods(periods: list[str]) -> list[str]:
    """Order 'Qn FYyy' chronologically (FY then quarter)."""
    def key(p: str):
        try:
            q, fy = p.split()
            return (int(fy[2:]), int(q[1:]))
        except Exception:
            return (999, 9)
    return sorted(periods, key=key)


_QP = re.compile(r"^Q[1-4] FY\d{2}$")
_MONEY = {"revenue", "cogs", "receivables", "inventory", "payables", "ebitda", "cfo"}


def _unit_factor(ratios: list[float], tol: float) -> Optional[float]:
    """Multiplier that puts another document's money cells in the anchor's units, or None if it cannot be proven.
    Needs >= 2 overlapping cells that all agree on one ratio, and that ratio must be 1 or a power of ten
    (rupees vs crore vs million vs billion)."""
    if len(ratios) < 2:
        return None
    r = sorted(ratios)[len(ratios) // 2]
    if r <= 0 or any(abs(x / r - 1) > tol for x in ratios):
        return None
    k = round(math.log10(r))
    if abs(math.log10(r) - k) > 0.005:
        return None
    return 10.0 ** (-k)


def raw_from_extracted(rows: list[ExtractedRow], scale_tol: float = 0.02) -> pd.DataFrame:
    """Merge extracted rows into a frame: index=quarter, columns=metric plus loc_<metric>/ev_<metric>.

    Safety rules (ratios across documents are only valid if the units match):
      1. Only quarterly periods ('Qn FYyy') are used; annual columns are ignored.
      2. The document with the most cells is the ANCHOR; its numbers are used first.
      3. Cells from another document fill gaps ONLY if at least 2 overlapping cells agree with the
         anchor within scale_tol (proof that both use the same units). Otherwise that document is skipped
         and the reason is recorded in df.attrs['notes'].
    """
    docs: dict[str, dict[tuple[str, str], tuple]] = {}
    for r in rows:
        d = docs.setdefault(r.locator.split("#")[0], {})
        for period, v in r.values.items():
            if v is not None and _QP.match(period) and (r.metric, period) not in d:
                d[(r.metric, period)] = (v, r.locator, r.evidence_id)
    docs = {k: v for k, v in docs.items() if v}
    notes: list[str] = []
    if not docs:
        df = pd.DataFrame()
        df.attrs["notes"] = ["no quarterly figures could be extracted"]
        return df
    ordered = sorted(docs, key=lambda k: -len(docs[k]))
    anchor = ordered[0]
    merged = dict(docs[anchor])
    for d in ordered[1:]:
        ratios = [docs[d][k][0] / merged[k][0] for k in docs[d] if k in merged and merged[k][0] and k[0] in _MONEY]
        factor = _unit_factor(ratios, scale_tol)
        if factor is not None:
            for k, v in docs[d].items():
                if k[0] in _MONEY:                      # money rows only; ratios/percent rows are never rescaled
                    merged.setdefault(k, (v[0] * factor, v[1], v[2]))
            if factor != 1:
                notes.append(f"rescaled {d} by {factor:g}: units differ by a power of ten, verified on {len(ratios)} overlapping cells")
        else:
            notes.append(f"skipped {d}: units not verified against the anchor document ({len(ratios)} overlapping cells)")
    data: dict[str, dict[str, object]] = {}
    for (metric, period), (v, loc, ev) in merged.items():
        cell = data.setdefault(period, {})
        cell[metric], cell[f"loc_{metric}"], cell[f"ev_{metric}"] = v, loc, ev
    df = pd.DataFrame.from_dict(data, orient="index")
    df = df.loc[sort_periods(list(df.index))]
    notes.insert(0, f"anchor document: {anchor}")
    df.attrs["notes"] = notes
    return df


def cross_check(a: dict[str, float], b: dict[str, float], tol: float = 0.02) -> list[str]:
    """Compare the same metric from two independent tables. Returns periods that disagree by more than tol."""
    bad = []
    for p in set(a) & set(b):
        if a[p] is not None and b[p] is not None and a[p] != 0 and abs(a[p] - b[p]) / abs(a[p]) > tol:
            bad.append(p)
    return sorted(bad)


def check_total_consistency(components: dict[str, Optional[float]], total: Optional[float], tol: float = 0.02) -> bool:
    """True if the parts add up to the total within tolerance. Missing data counts as unverifiable (True)."""
    vals = [v for v in components.values() if v is not None]
    if total is None or not vals or len(vals) < len(components):
        return True
    return abs(sum(vals) - total) <= tol * abs(total)


def _pt(period, value, unit, raw, cols, note="", proxy=False) -> MetricPoint:
    loc = next((raw.at[period, f"loc_{c}"] for c in cols if f"loc_{c}" in raw.columns and pd.notna(raw.at[period, f"loc_{c}"])), None)
    evid = next((raw.at[period, f"ev_{c}"] for c in cols if f"ev_{c}" in raw.columns and pd.notna(raw.at[period, f"ev_{c}"])), None)
    return MetricPoint(period=period, value=None if value is None else float(value), unit=unit,
                       locator=loc, evidence_id=evid, is_proxy=proxy, note=note)


def prior_year(period: str) -> str:
    """'Q1 FY27' -> 'Q1 FY26' (the SAME quarter a year earlier, never an index offset: data can have gaps)."""
    q, fy = period.split()
    return f"{q} FY{int(fy[2:]) - 1:02d}"


def build_metric_series(raw: pd.DataFrame, entity: str, role: Role = Role.company,
                        inflation_by_period: Optional[dict[str, float]] = None,
                        revenue_is_quarterly: bool = True) -> dict[str, MetricSeries]:
    """raw columns (all optional): revenue, cogs, receivables, inventory, payables, volume (absolute volume),
    volume_growth (yoy fraction as stated by management), ebitda, cfo.
    Year-on-year growth compares each quarter with the same quarter one year earlier; if that quarter is
    missing the growth value is None (never a different pair of quarters)."""
    days = 91.25 if revenue_is_quarterly else 365.0
    periods = sort_periods(list(raw.index))
    g = lambda c, p: (raw.at[p, c] if c in raw.columns and pd.notna(raw.at[p, c]) else None)
    out: dict[str, list[MetricPoint]] = {k: [] for k in (
        "receivable_days", "inventory_days", "payable_days", "cash_conversion_cycle", "gross_margin",
        "revenue_growth_yoy", "volume_growth_yoy", "price_mix_growth_yoy", "price_share_of_growth")}
    for p in periods:
        rev, cogs = g("revenue", p), g("cogs", p)
        dso = m.receivable_days(g("receivables", p), rev, days)
        dio = m.inventory_days(g("inventory", p), cogs, days)
        dpo = m.payable_days(g("payables", p), cogs, days)
        out["receivable_days"].append(_pt(p, dso, "days", raw, ["receivables", "revenue"]))
        out["inventory_days"].append(_pt(p, dio, "days", raw, ["inventory", "cogs"]))
        out["payable_days"].append(_pt(p, dpo, "days", raw, ["payables", "cogs"]))
        out["cash_conversion_cycle"].append(_pt(p, m.cash_conversion_cycle(dso, dio, dpo), "days", raw, ["receivables", "inventory", "payables"]))
        out["gross_margin"].append(_pt(p, m.gross_margin(rev, cogs), "ratio", raw, ["revenue", "cogs"]))
        prev = prior_year(p)
        has_prev = prev in raw.index
        g_rev = m.growth(g("revenue", prev), rev) if has_prev else None
        out["revenue_growth_yoy"].append(_pt(p, g_rev, "ratio", raw, ["revenue"]))
        split, note = None, ""
        if has_prev:
            split = m.price_volume_split(g("revenue", prev), rev, g("volume", prev), g("volume", p))
        vg, sg = g("volume_growth", p), g("sales_growth", p)
        if split is None and vg is not None:
            vg = float(vg)
            ref = g_rev if g_rev is not None else (float(sg) if sg is not None else None)
            split = {"volume_growth": vg, "is_proxy": False,
                     "price_mix_growth": ((1 + ref) / (1 + vg) - 1) if ref is not None and (1 + vg) != 0 else None,
                     "price_share_of_growth": ((ref - vg) / ref) if ref is not None and abs(ref) > 1e-9 else None}
            note = "volume growth as STATED by management (not computed from volumes)"
            if g_rev is None and sg is not None:
                note += "; price/mix derived from management-stated sales growth for the same quarter"
        if split is None and inflation_by_period and p in inflation_by_period and g_rev is not None:
            split = m.proxy_volume_from_deflator(g_rev, inflation_by_period[p])
            note = "PROXY: revenue growth deflated by a price index; volume not disclosed"
        proxy = bool(split and split.get("is_proxy"))
        for name, key in (("volume_growth_yoy", "volume_growth"), ("price_mix_growth_yoy", "price_mix_growth"),
                          ("price_share_of_growth", "price_share_of_growth")):
            out[name].append(_pt(p, split.get(key) if split else None, "ratio", raw, ["volume", "volume_growth", "sales_growth", "revenue"], note, proxy))
    units = {"receivable_days": "days", "inventory_days": "days", "payable_days": "days", "cash_conversion_cycle": "days"}
    return {name: MetricSeries(name=name, entity=entity, role=role, unit=units.get(name, "ratio"), points=pts)
            for name, pts in out.items() if any(pt.value is not None for pt in pts)}
