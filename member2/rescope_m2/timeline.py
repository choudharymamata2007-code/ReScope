"""Task 2.6: timeline and change-point builder. Finds when each trend turned and merges dated events
from claims and disclosure changes into one timeline JSON that the dashboard draws."""
from __future__ import annotations
from typing import Optional

from .claims import Claim
from .common import MetricBook, detect_change_point, label, fmt, period_end, sort_periods


def change_points(book: MetricBook, metrics: Optional[list[str]] = None) -> list[dict]:
    out = []
    for m in metrics or book.metric_names():
        series = book.series(book.company, m)
        cp = detect_change_point([v for _, v in series])
        if not cp:
            continue
        idx = cp["index"]
        period = series[idx][0]  # first period of the new regime
        end = period_end(period)
        out.append({"metric": m, "label": label(m), "period": period, "date": str(end) if end else None,
                    "index": idx, "gain": round(cp["gain"], 3), "before": cp["before"], "after": cp["after"],
                    "direction": cp["direction"],
                    "text": f"{label(m)} shifted {cp['direction']} from about {fmt(m, cp['before'])} "
                            f"to about {fmt(m, cp['after'])} from {period}"})
    return sorted(out, key=lambda c: -c["gain"])


def build_timeline(book: MetricBook, claims: list[Claim], disclosure_changes: list[dict],
                   focus_metrics: Optional[list[str]] = None) -> dict:
    cps = change_points(book, book.metric_names())
    focus = [c for c in cps if not focus_metrics or c["metric"] in focus_metrics]
    primary = focus[0] if focus else (cps[0] if cps else None)
    events = []
    for c in cps:
        if c["date"]:
            events.append({"date": c["date"], "period": c["period"], "kind": "change_point", "label": c["text"],
                           "metric": c["metric"], "url": None, "locator": None, "primary": c is primary})
    for cl in claims:
        if cl.date:
            events.append({"date": cl.date, "period": cl.period, "kind": "claim", "label": cl.text[:200],
                           "metric": None, "url": cl.url, "locator": cl.locator, "evidence_id": cl.evidence_id,
                           "role": cl.role, "primary": False})
    for d in disclosure_changes or []:
        per = d.get("first_missing") or d.get("last_seen")
        end = period_end(per)
        if end:
            events.append({"date": str(end), "period": per, "kind": "disclosure", "label": d.get("detail", ""),
                           "metric": None, "url": None, "locator": None, "primary": False})
    events.sort(key=lambda e: (e["date"], e["kind"]))
    periods = sort_periods([p for _, ser in [(m, book.series(book.company, m)) for m in book.metric_names()]
                            for p, _ in ser])
    return {"change_points": cps, "primary_change_point": primary, "events": events,
            "span": {"first": periods[0] if periods else None, "last": periods[-1] if periods else None}}
