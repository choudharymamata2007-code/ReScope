"""Segment / channel mix shares (plan Task 1.8: 'mix and channel shares'). Conservative on purpose: a table counts
only if it has a 'segment revenue' (or 'sales by segment/channel') heading, two or more segment rows and a total row
whose value equals the sum of the segments (check_total_consistency), per quarter. Shares are ratios, so units cancel."""
from __future__ import annotations
import re
from ..schema import Evidence, MetricPoint, MetricSeries, Role
from . import metrics as m
from .extract import _header_periods, parse_number, parse_table_text
from .series import check_total_consistency, sort_periods

HEADING = re.compile(r"segment\s+(revenue|revenues|sales|income)|revenue\s+by\s+segment|sales\s+by\s+(segment|category|channel|region)", re.I)
TOTAL = re.compile(r"^(total|net sales|revenue from operations|segment total)", re.I)
_QP = re.compile(r"^Q[1-4] FY\d{2}$")


def extract_mix(table: list[list[str]]) -> dict[str, dict[str, float]]:
    """{segment label: {period: share}} from one table, or {} if it does not pass the checks."""
    periods = _header_periods(table)
    start = next((i for i, r in enumerate(table) if any(HEADING.search(c or "") for c in r[:2])), None)
    if start is None or not periods:
        return {}
    segs: dict[str, tuple[int, list]] = {}
    total = None
    for row in table[start + 1:]:
        cells = [c.strip() for c in row]
        label = next((c for c in cells if c), "")
        if not label:
            continue
        base = cells.index(label) + 1                        # column of the first value
        vals = [parse_number(c) for c in cells[base:]]
        if not any(v is not None for v in vals):
            continue
        if TOTAL.search(label):
            total = (base, vals)
            break
        segs[label] = (base, vals)
    if total is None or len(segs) < 2:
        return {}
    out: dict[str, dict[str, float]] = {}
    tbase, tvals = total
    for j, tv in enumerate(tvals):
        col = tbase + j
        period = periods[col] if col < len(periods) else None
        if not period or not _QP.match(period) or not tv:
            continue
        parts = {}
        for k, (b, v) in segs.items():
            parts[k] = v[col - b] if 0 <= col - b < len(v) else None
        if any(x is None for x in parts.values()) or not check_total_consistency(parts, tv):
            continue
        for k, sh in (m.mix_shares(parts) or {}).items():
            out.setdefault(k, {})[period] = sh
    return out


def extract_mix_series(evidence: list[Evidence], entity: str, role: Role) -> list[MetricSeries]:
    acc: dict[str, dict[str, MetricPoint]] = {}
    for ev in evidence:
        if not (ev.locator and "table" in ev.locator):
            continue
        for label, by_p in extract_mix(parse_table_text(ev.text)).items():
            slot = acc.setdefault(label, {})
            for p, sh in by_p.items():
                slot.setdefault(p, MetricPoint(period=p, value=sh, unit="share", locator=f"{ev.url}#{ev.locator}", evidence_id=ev.id))
    out = []
    for label, pts in acc.items():
        if len(pts) >= 2:
            name = "mix_share:" + re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
            out.append(MetricSeries(name=name, entity=entity, role=role, unit="share",
                                    points=[pts[p] for p in sort_periods(list(pts))]))
    return out
