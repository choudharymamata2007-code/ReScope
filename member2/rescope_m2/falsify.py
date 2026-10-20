"""Task 2.9: counterargument and falsification condition, plus the falsification monitor (feature 25)."""
from __future__ import annotations
from typing import Optional

from . import llm
from .common import MetricBook, fmt, label, trend

OPERATORS = {">", ">=", "<", "<="}
_CMP = {">": lambda a, b: a > b, ">=": lambda a, b: a >= b, "<": lambda a, b: a < b, "<=": lambda a, b: a <= b}
_WORD = {">": "above", ">=": "at or above", "<": "below", "<=": "at or below"}


def validate_falsification(f: dict) -> dict:
    conds = f.get("conditions") or []
    if not conds:
        raise ValueError("falsification needs at least one condition")
    for c in conds:
        if not c.get("metric") or c.get("operator") not in OPERATORS:
            raise ValueError("condition needs a metric and a valid operator")
        float(c["threshold"])
        if int(c.get("periods", 0)) < 1:
            raise ValueError("condition needs periods >= 1")
    if not f.get("statement"):
        raise ValueError("falsification needs a statement")
    return f


def build_falsification(hyp: dict, book: MetricBook, periods: int = 2, use_llm: bool = True) -> dict:
    """Reversal = every tested metric returns to its start-of-window level for `periods` consecutive quarters."""
    conds = []
    for r in hyp["results"]:
        if not r.get("available"):
            continue
        d = r["expect"].split("_")[0]
        tr = trend(book.values(book.company, r["metric"]))
        base = tr.get("first_avg")
        if base is None:
            continue
        if r["metric"].endswith("_yoy") or r["metric"] == "price_share_of_growth":
            base = max(base, 0.0) if d == "down" else base
        conds.append({"metric": r["metric"], "operator": ">=" if d == "down" else "<=",
                      "threshold": round(float(base), 4), "periods": periods})
    parts = [f"{label(c['metric'])} is {_WORD[c['operator']]} {fmt(c['metric'], c['threshold'])}" for c in conds]
    statement = ("This finding is reversed if " + " and ".join(parts) +
                 f" for {periods} consecutive quarters.") if parts else ""
    f = {"conditions": conds, "statement": statement, "window": f"{periods} consecutive quarters",
         "check_against": "Member 1 metric series (recomputed when new results arrive)"}
    if use_llm and conds:
        c0 = conds[0]
        o = llm.try_call("falsification", {"metric": label(c0["metric"]), "operator": c0["operator"],
                                           "threshold": c0["threshold"], "periods": periods}, {"statement": str})
        # a model restatement is used only if it adds no figure the code did not produce
        if o and llm.numbers_grounded(o["statement"], statement + " " + str(c0["threshold"])):
            f["statement_model"] = o["statement"]
    return validate_falsification(f)


def evaluate_falsification(f: dict, book: MetricBook) -> dict:
    """Feature 25: re-check a stored condition against the current series. confirmed / weakened / reversed."""
    states = []
    for c in f["conditions"]:
        vals = book.values(book.company, c["metric"])
        k = int(c["periods"])
        if len(vals) < k:
            states.append({"metric": c["metric"], "met": None, "latest": None})
            continue
        met = all(_CMP[c["operator"]](v, float(c["threshold"])) for v in vals[-k:])
        states.append({"metric": c["metric"], "met": met, "latest": vals[-1]})
    known = [s for s in states if s["met"] is not None]
    if not known:
        status = "unknown"
    elif all(s["met"] for s in known) and len(known) == len(states):
        status = "reversed"
    elif any(s["met"] for s in known):
        status = "weakened"
    else:
        status = "confirmed"
    return {"status": status, "conditions": states}


def build_counterargument(hyp: dict, skeptic: dict, book: MetricBook, change_point: Optional[dict],
                          disclosure_changes: list[dict], coverage: dict) -> dict:
    """The strongest alternative explanation, picked by strength; the others are kept for the Why-not panel."""
    cands = []
    s = skeptic["sector"]
    if s["verdict"] in ("sector_wide", "mixed") and s.get("peers_total"):
        share = (s["peers_same_direction"] or 0) / max(1, s["peers_total"])
        cands.append((0.5 + 0.5 * share, "Sector conditions",
                      f"{s['peers_same_direction']} of {s['peers_total']} peers show the same pattern, so the cause may be "
                      "sector-wide (for example, channel financing or input costs) rather than specific to this company."))
    for c in skeptic["counter_evidence"][:1]:
        cands.append((0.8 if c["independent"] else 0.45, "Contrary statement",
                      f"A {c['source_type'] or 'source'} says the opposite: \"{c['text'][:200]}\""))
    proxies = [r["metric"] for r in hyp["results"] if r.get("available") and r.get("is_proxy")]
    if proxies:
        cands.append((0.6, "Proxy data", f"{', '.join(label(m) for m in proxies)} is a labelled proxy, "
                      "not a disclosed figure, so the pattern may reflect the proxy."))
    if change_point and change_point.get("index") is not None and change_point["index"] >= len(
            book.series(book.company, change_point["metric"])) - 2:
        cands.append((0.4, "Too recent to call", "The shift is within the last two quarters, so it may be timing or "
                      "seasonality rather than a lasting change."))
    if disclosure_changes:
        d = disclosure_changes[0]
        cands.append((0.35, "Disclosure change", f"Reporting changed ({d.get('detail', 'a metric was dropped or redefined')}), "
                      "so some movement may come from how figures are presented."))
    if coverage.get("warnings"):
        cands.append((0.3, "Thin data", "; ".join(coverage["warnings"][:2])))
    if not cands:
        cands.append((0.2, "Ordinary variation", "No specific alternative was found; ordinary quarter-to-quarter "
                      "variation cannot be excluded."))
    cands.sort(key=lambda x: -x[0])
    top = cands[0]
    return {"title": top[1], "text": top[2], "strength": round(top[0], 2),
            "others": [{"title": t, "text": x, "strength": round(sc, 2)} for sc, t, x in cands[1:4]]}
