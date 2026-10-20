"""Task 2.14: extra analysis features: management language drift (27), peer heatmap (31), why-not explainer (29),
run-to-run diff (33). The falsification monitor (25) lives in falsify.evaluate_falsification."""
from __future__ import annotations
import re
from typing import Optional

from .common import MetricBook, fmt, label, mean, sort_periods, trend, get

THEMES = {"volume": ["volume", "volumes", "units"], "pricing": ["price", "pricing", "realisation", "premium"],
          "quick commerce": ["quick commerce", "q-commerce", "e-commerce"], "rural": ["rural"],
          "channel": ["distributor", "channel", "trade"], "cost": ["cost", "inflation", "commodity"]}


def language_drift(evidence: list[dict]) -> dict:
    """Mentions per 1,000 words of management text (calls, presentations) by period and theme."""
    by_p: dict[str, list[str]] = {}
    for e in evidence:
        if e.get("role") == "company" and e.get("source_type") in ("transcript", "presentation") and e.get("period"):
            by_p.setdefault(e["period"], []).append(e.get("text", ""))
    periods = sort_periods(by_p)
    out = {t: [] for t in THEMES}
    for p in periods:
        text = " ".join(by_p[p]).lower()
        words = max(1, len(re.findall(r"\w+", text)))
        for t, keys in THEMES.items():
            out[t].append(round(1000 * sum(text.count(k) for k in keys) / words, 2))
    return {"periods": periods, "themes": out}


def peer_heatmap(book: MetricBook, metrics: Optional[list[str]] = None) -> dict:
    metrics = metrics or [m for m in book.metric_names() if len(book.values(book.company, m)) >= 4]
    ents = [book.company] + book.peers
    cells, text = [], []
    for m in metrics:
        deltas = []
        for e in ents:
            t = trend(book.values(e, m))
            deltas.append(t.get("delta"))
        known = [d for d in deltas if d is not None]
        mu = mean(known) if known else 0
        sd = (sum((d - mu) ** 2 for d in known) / len(known)) ** 0.5 if len(known) > 1 else 0
        cells.append([None if d is None else (0.0 if sd == 0 else round((d - mu) / sd, 2)) for d in deltas])
        text.append(["n/a" if d is None else
                     (f"{d * 100:+.1f} pp" if m.endswith("_yoy") or m in ("gross_margin", "price_share_of_growth")
                      else f"{d:+.1f}") for d in deltas])
    return {"entities": ents, "metrics": metrics, "labels": [label(m) for m in metrics], "z": cells, "text": text}


def why_not(plan: dict, skeptic_runs: list[dict]) -> list[dict]:
    out = []
    by_id = {s["hypothesis_id"]: s for s in skeptic_runs}
    for h in plan.get("untestable", []):
        need = ", ".join(sorted({a for r in h["results"] for a in (r.get("wanted") or [])}))
        out.append({"id": h["id"], "statement": h["statement"], "outcome": "untestable",
                    "reason": f"the metric(s) needed were not disclosed or not collected ({need})"})
    for h in plan.get("hypotheses", []):
        s = by_id.get(h["id"])
        if s and s["verdict"] == "rejected":
            out.append({"id": h["id"], "statement": h["statement"], "outcome": "rejected", "reason": "; ".join(s["reasons"])})
        elif h["id"] not in by_id:
            out.append({"id": h["id"], "statement": h["statement"], "outcome": "ranked lower",
                        "reason": "a higher-ranked hypothesis survived, so this one was not taken further"})
    return out


def run_diff(old: dict, new: dict) -> dict:
    """What changed since the last analysis of the same company."""
    if not old:
        return {"has_previous": False, "changes": []}
    ch = []
    o, n = old.get("score", {}) or {}, new.get("score", {}) or {}
    if o.get("rating") != n.get("rating"):
        ch.append(f"Evidence Strength changed from {o.get('rating')} to {n.get('rating')}.")
    if old.get("discovery", {}).get("hypothesis_id") != new.get("discovery", {}).get("hypothesis_id"):
        ch.append("The leading hypothesis changed.")
    oc, nc = (old.get("coverage") or {}).get("coverage_score"), (new.get("coverage") or {}).get("coverage_score")
    if oc is not None and nc is not None and abs(oc - nc) > 0.02:
        ch.append(f"Coverage moved from {oc:.2f} to {nc:.2f}.")
    return {"has_previous": True, "changes": ch or ["No material change since the last run."]}
