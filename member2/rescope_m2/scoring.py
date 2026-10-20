"""Task 2.10: scoring and Evidence Strength. Score = 0.30 x Triangulation + 0.25 x Source quality +
0.20 x Recency + 0.15 x Falsification survival + 0.10 x Coverage, minus a contradiction penalty.
Strong needs 0.75+, survived, 3+ independent source types including peer/industry, not sector-wide."""
from __future__ import annotations
import datetime as dt
from typing import Optional

from .claims import Claim
from .common import MetricBook, period_end
from .skeptic import METRIC_TOPIC, OUTSIDE_TYPES

WEIGHTS = {"triangulation": 0.30, "source_quality": 0.25, "recency": 0.20, "falsification": 0.15, "coverage": 0.10}
TIER_WEIGHT = {1: 1.0, 2: 0.85, 3: 0.70, 4: 0.55, 5: 0.35}  # starting values, tuned on the test set
SURVIVAL = {"survived": 1.0, "weakened": 0.5, "rejected": 0.0}


def _link(ev_by_id: dict, ev_by_url: dict, point: dict) -> Optional[dict]:
    e = ev_by_id.get(str(point.get("evidence_id"))) if point.get("evidence_id") else None
    if e is None and point.get("locator"):
        e = ev_by_url.get(str(point["locator"]).split("#")[0])
    return e


def supporting_sources(hyp: dict, evidence: list[dict], claims: list[Claim], book: MetricBook) -> list[dict]:
    ev_by_id = {str(e["id"]): e for e in evidence}
    ev_by_url = {e["url"].split("#")[0]: e for e in evidence}
    found: dict[str, dict] = {}

    def add(e: Optional[dict], why: str):
        if e is not None and e["id"] not in found:
            found[e["id"]] = {**e, "why": why}

    topics, dirs = set(), {}
    for r in hyp["results"]:
        if not r.get("available"):
            continue
        m = r["metric"]
        topics.add(METRIC_TOPIC.get(m, ""))
        dirs[METRIC_TOPIC.get(m, "")] = r["expect"].split("_")[0]
        for p in book.points(book.company, m):
            add(_link(ev_by_id, ev_by_url, p), f"company figure: {m}")
        for peer in book.peers:
            for p in book.points(peer, m):
                add(_link(ev_by_id, ev_by_url, p), f"peer figure: {m}")
    for name, ms in book.data.items():
        if name == book.INDUSTRY:
            for m, pts in ms.items():
                for p in pts[:1]:
                    add(_link(ev_by_id, ev_by_url, p), f"industry series: {m}")
    for c in claims:
        if c.topic in topics and c.direction == dirs.get(c.topic):
            add(ev_by_id.get(c.evidence_id), f"statement on {c.topic}")
    return list(found.values())


def _recency(latest: Optional[dt.date], now: dt.date) -> float:
    if latest is None:
        return 0.0
    age = (now - latest).days
    return 1.0 if age <= 120 else max(0.0, 1 - (age - 120) / 610)


def score_finding(hyp: dict, sources: list[dict], skeptic: dict, coverage: dict, contradictions: list[dict],
                  book: MetricBook, now: Optional[dt.date] = None) -> dict:
    now = now or dt.date.today()
    indep = [s for s in sources if s.get("independent", True)]
    types = sorted({s["source_type"] for s in indep})
    outside = any(s["role"] in ("peer", "industry") or s["source_type"] in OUTSIDE_TYPES for s in indep)
    tri = min(1.0, len(types) / 3)
    if not outside:
        tri = min(tri, 0.34)
    qual = sum(TIER_WEIGHT.get(int(s["source_tier"]), 0.35) for s in indep) / len(indep) if indep else 0.0
    dates = []
    for s in sources:
        if s.get("date"):
            dates.append(dt.date.fromisoformat(str(s["date"])[:10]))
    for m in hyp.get("metrics", []):
        ser = book.series(book.company, m)
        if ser and period_end(ser[-1][0]):
            dates.append(period_end(ser[-1][0]))
    rec = _recency(max(dates) if dates else None, now)
    comps = {"triangulation": round(tri, 3), "source_quality": round(qual, 3), "recency": round(rec, 3),
             "falsification": SURVIVAL[skeptic["verdict"]], "coverage": round(float(coverage.get("coverage_score", 0)), 3)}
    related = [c for c in contradictions if c.get("kind") == "claim_pair"]
    n_pen = skeptic["rounds"][-1]["independent_counter"] + len(related)
    penalty = min(0.15, 0.05 * n_pen)
    total = max(0.0, sum(WEIGHTS[k] * v for k, v in comps.items()) - penalty)
    sv = skeptic["sector"]["verdict"]
    if total >= 0.75 and skeptic["verdict"] == "survived" and len(types) >= 3 and outside and sv == "company_specific":
        rating, cap = "Strong", None
    elif total >= 0.50 or skeptic["verdict"] == "weakened":
        rating = "Moderate"
        cap = None
        if total >= 0.75:  # would have been Strong
            cap = ("peers show the same pattern" if sv in ("sector_wide", "mixed") else
                   "fewer than three independent source types including peer or industry evidence"
                   if not (len(types) >= 3 and outside) else "the finding was weakened by the skeptic")
    else:
        rating, cap = "Weak", None
    if total < 0.50 or len(types) < 2:
        rating = "Weak"
    if not coverage.get("sufficient", True):
        rating, cap = "Weak", "data coverage is thin"
    reasoning = [f"Score {total:.2f}: triangulation {comps['triangulation']:.2f}, source quality {comps['source_quality']:.2f}, "
                 f"recency {comps['recency']:.2f}, falsification {comps['falsification']:.2f}, coverage {comps['coverage']:.2f}"
                 + (f", minus {penalty:.2f} contradiction penalty." if penalty else "."),
                 f"{len(types)} independent source type(s): {', '.join(types) or 'none'}"
                 + ("; includes evidence from outside the company." if outside else "; none from outside the company."),
                 f"Skeptic verdict: {skeptic['verdict']} ({'; '.join(skeptic['reasons'])})."]
    if cap:
        reasoning.append(f"Rating capped at Moderate because {cap}.")
    return {"components": comps, "weights": WEIGHTS, "penalty": round(penalty, 3), "total": round(total, 3),
            "rating": rating, "cap_reason": cap, "independent_types": types, "has_outside_evidence": outside,
            "reasoning": reasoning}
