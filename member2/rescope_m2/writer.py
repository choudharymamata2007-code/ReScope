"""Task 2.11: discovery writer. Produces the 8 required elements as validated JSON.
Every figure is read from the quantitative engine's series; a model may only re-word text and may not add numbers."""
from __future__ import annotations
import re
from typing import Optional

from . import llm
from .common import MetricBook, fmt, label, trend, median

DISCLAIMER = "Research findings for a human to verify; not investment advice or a recommendation."
ELEMENTS = ["discovery", "why_it_matters", "evidence", "timeline", "numbers", "counterargument",
            "falsification", "evidence_strength"]
BANNED = re.compile(r"\b(buy|sell|hold|target price|outperform|underperform|overweight|underweight|recommend\w*)\b", re.I)


def _numbers(hyp: dict, book: MetricBook, benchmark: Optional[dict]) -> list[dict]:
    comp = {c["metric"]: c for c in (benchmark or {}).get("comparisons", [])}
    out = []
    for r in hyp["results"]:
        if not r.get("available"):
            continue
        m = r["metric"]
        pts = book.points(book.company, m)
        if len(pts) < 2:
            continue
        first, last = pts[0], pts[-1]
        c = comp.get(m, {})
        out.append({"metric": m, "label": label(m), "first_period": first["period"], "last_period": last["period"],
                    "first": first["value"], "last": last["value"],
                    "first_display": fmt(m, first["value"]), "last_display": fmt(m, last["value"]),
                    "direction": trend(book.values(book.company, m))["direction"],
                    "peer_median_change": c.get("peer_median_change"), "peers_same_direction": c.get("peers_same_direction"),
                    "peers_total": c.get("peers_total"), "locator": last.get("locator"),
                    "is_proxy": any(p.get("is_proxy") for p in pts), "series": [(p["period"], p["value"]) for p in pts]})
    return out


def _sentence(hyp: dict, nums: list[dict], skeptic: dict) -> str:
    def part(n):
        return (f"{n['label']} moved from {n['first_display']} ({n['first_period']}) to "
                f"{n['last_display']} ({n['last_period']})")
    if not nums:
        return "No pattern could be tested because the needed metrics were not disclosed."
    body = part(nums[0]) + (f" while {part(nums[1])}" if len(nums) > 1 else "")
    s = skeptic["sector"]
    if s["verdict"] == "company_specific" and s.get("peers_total"):
        tail = f"only {s['peers_same_direction']} of {s['peers_total']} peers moved the same way"
    elif s["verdict"] in ("sector_wide", "mixed") and s.get("peers_total"):
        tail = f"{s['peers_same_direction']} of {s['peers_total']} peers moved the same way"
    else:
        tail = "the peer comparison could not be completed"
    return f"{body}; {tail}."


def _evidence_items(sources: list[dict], counter: list[dict], contradictions: list[dict], claims: list) -> list[dict]:
    by_ev = {}
    for c in claims:
        by_ev.setdefault(c.evidence_id, c.text)
    items = []
    for s in sources:
        passage = s.get("text", "")
        hl = by_ev.get(str(s["id"]))
        items.append({"id": s["id"], "title": s.get("title", ""), "source_type": s["source_type"],
                      "tier": s["source_tier"], "date": str(s.get("date") or ""), "url": s["url"],
                      "locator": s.get("locator"), "role": s["role"], "entity": s.get("entity"),
                      "period": s.get("period"), "passage": passage, "highlight": hl if hl and hl in passage else "",
                      "why": s.get("why", ""), "independent": s.get("independent", True),
                      "flags": s.get("flags", []), "stance": "supports"})
    for c in counter:
        items.append({"id": f"counter-{c['evidence_id']}", "title": "Counter-evidence", "source_type": c["source_type"],
                      "tier": 3, "date": "", "url": c["url"], "locator": c.get("locator"), "role": c["role"],
                      "entity": "", "period": c.get("period"), "passage": c["text"], "highlight": c["text"],
                      "why": "points the other way", "independent": c["independent"], "flags": [], "stance": "counter"})
    return items


def build_discovery(hyp: Optional[dict], book: MetricBook, benchmark: Optional[dict], skeptic: Optional[dict],
                    sources: list[dict], claims: list, contradictions: list[dict], timeline: dict,
                    falsification: Optional[dict], counterargument: Optional[dict], score: Optional[dict],
                    coverage: dict, use_llm: bool = True) -> dict:
    if hyp is None or skeptic is None:
        sc = score or {"rating": "Weak", "total": 0.0, "components": {}, "reasoning": [
            "No hypothesis survived testing; the data may be too thin or the pattern is sector-wide."]}
        return {"discovery": "No non-obvious finding survived testing on the available evidence.",
                "why_it_matters": ["Weak or single-source claims are labelled Weak or not shown.",
                                   "Missing disclosures are reported as gaps, not filled with guesses.",
                                   "Coverage warnings explain what data would be needed."] +
                                  [w for w in coverage.get("warnings", [])[:2]],
                "evidence": [], "timeline": timeline.get("events", [])[:12], "numbers": [],
                "counterargument": counterargument or {"title": "Insufficient data", "text": "; ".join(
                    coverage.get("warnings", [])) or "No hypothesis survived.", "strength": 0.0, "others": []},
                "falsification": falsification or {"conditions": [], "statement": "Not applicable: no finding to reverse.",
                                                   "window": ""},
                "evidence_strength": sc, "hypothesis_id": None, "disclaimer": DISCLAIMER}
    nums = _numbers(hyp, book, benchmark)
    draft = _sentence(hyp, nums, skeptic)
    bullets = list(hyp.get("matters", []))
    cp = timeline.get("primary_change_point")
    if cp:
        bullets.append(f"The shift is dated: {cp['text']}.")
    for n in nums[:1]:
        if n["peer_median_change"] is not None:
            bullets.append(f"The peer median for {n['label']} moved {n['peer_median_change'] * 100:+.1f}% over the window "
                           "(relative change), which is the benchmark for the company-vs-sector test.")
    if score:
        bullets.append(f"{len(score['independent_types'])} independent source type(s) support it: "
                       f"{', '.join(score['independent_types']) or 'none'}.")
    if coverage.get("proxies_used") or not coverage.get("sufficient", True):
        bullets.append("Some inputs are proxies or thinly covered, which lowers confidence; see the coverage meter.")
    bullets = bullets[:5]
    while len(bullets) < 3:
        bullets.append("Every figure links back to the source table it was read from.")
    discovery = draft
    if use_llm:
        figs = draft + " " + " ".join(bullets)
        o = llm.try_call("writer", {"draft_discovery": draft, "draft_bullets": " | ".join(bullets), "figures": figs},
                         {"discovery": str, "why_it_matters": list})
        if o and llm.numbers_grounded(o["discovery"] + " " + " ".join(map(str, o["why_it_matters"])), figs) \
                and 3 <= len(o["why_it_matters"]) <= 5:
            discovery, bullets = o["discovery"], [str(b) for b in o["why_it_matters"]]
    return {"discovery": discovery, "why_it_matters": bullets,
            "evidence": _evidence_items(sources, skeptic["counter_evidence"], contradictions, claims),
            "timeline": timeline.get("events", []), "numbers": nums,
            "counterargument": counterargument, "falsification": falsification, "evidence_strength": score,
            "hypothesis_id": hyp["id"], "hypothesis": hyp["statement"], "disclaimer": DISCLAIMER}


def check_discovery(d: dict) -> list[str]:
    """The 8-element check: all present, every evidence item linked, bullets 3 to 5, no advice wording."""
    problems = [f"missing element: {k}" for k in ELEMENTS if k not in d or d[k] in (None, "")]
    if not (3 <= len(d.get("why_it_matters", [])) <= 5):
        problems.append("why_it_matters needs 3 to 5 bullets")
    for e in d.get("evidence", []):
        if not e.get("url"):
            problems.append(f"evidence {e.get('id')} has no URL")
    for n in d.get("numbers", []):
        if not n.get("locator") and not n.get("is_proxy"):
            problems.append(f"number {n['metric']} has no locator")
    text = " ".join([d.get("discovery", "")] + list(map(str, d.get("why_it_matters", []))))
    if BANNED.search(text):
        problems.append("contains investment-advice wording")
    if "\n" in d.get("discovery", "") or len(d.get("discovery", "")) > 480:
        problems.append("discovery must be one sentence")
    return problems
