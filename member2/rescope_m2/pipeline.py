"""Task 2.4: pipeline orchestrator. The 12 stages are plain functions passing one shared state dict.
Each stage yields a progress event (name, timing, output summary) for the live tracker and the reasoning view."""
from __future__ import annotations
import datetime as dt
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Iterator, Optional

from . import claims as claims_mod, contradictions, extras, falsify, planner, scoring, skeptic as skeptic_mod
from . import timeline as timeline_mod, writer
from .common import MetricBook

STAGES = ["Company intake and peers", "Angle planning", "Evidence collection", "Quantitative engine",
          "Timeline builder", "Triangulation", "Say vs do and contradictions", "Peer and sector test",
          "Skeptic loop", "Falsification condition", "Scoring and Evidence Strength", "Discovery writer"]


@dataclass
class Inputs:
    """Everything Member 1 hands over, plus optional hooks."""
    profile: dict
    evidence: list
    metrics: dict
    benchmark: dict
    coverage: dict
    say_vs_do: list = field(default_factory=list)
    disclosure_changes: list = field(default_factory=list)
    triangulation: list = field(default_factory=list)
    find_disconfirming: Optional[Callable] = None
    collect_more: Optional[Callable] = None
    label: str = "Live run"


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _ev_dicts(evidence: list) -> list[dict]:
    out = []
    for e in evidence:
        d = e if isinstance(e, dict) else e.model_dump(mode="json")
        d = dict(d)
        d["id"] = str(d["id"])
        for k in ("source_type", "role"):
            d[k] = getattr(d[k], "value", d[k])
        for k in ("date", "fetched_at"):
            if d.get(k) is not None:
                d[k] = str(d[k])
        out.append(d)
    return out


def stream(inp: Inputs, use_llm: bool = True, now: Optional[dt.date] = None) -> Iterator[dict]:
    """Yield one event per stage, then a final {'stage': 'result', 'bundle': {...}}."""
    now = now or dt.date.today()
    S: dict = {"events": []}
    company = inp.profile["name"]

    def done(i: int, t0: float, summary: str):
        ev = {"stage": i, "name": STAGES[i - 1], "status": "done", "seconds": round(time.time() - t0, 3),
              "summary": summary}
        S["events"].append(ev)
        return ev

    t = time.time()                                                                  # 1
    S["evidence"] = _ev_dicts(inp.evidence)
    S["book"] = MetricBook(inp.metrics, company)
    yield done(1, t, f"{company}: archetype {inp.profile.get('archetype')}, {len(inp.profile.get('peers', []))} peers")

    t = time.time()                                                                  # 2
    S["plan"] = planner.build_plan(inp.profile, S["book"], inp.benchmark, use_llm=use_llm)
    top = S["plan"]["hypotheses"][0]["statement"] if S["plan"]["hypotheses"] else "none testable"
    yield done(2, t, f"{len(S['plan']['hypotheses'])} testable hypotheses; top: {top}")

    t = time.time()                                                                  # 3
    n_by = {}
    for e in S["evidence"]:
        n_by[e["source_type"]] = n_by.get(e["source_type"], 0) + 1
    yield done(3, t, f"{len(S['evidence'])} evidence items ({', '.join(f'{k} {v}' for k, v in sorted(n_by.items()))})")

    t = time.time()                                                                  # 4
    names = S["book"].metric_names()
    yield done(4, t, f"{len(names)} company metrics, {len(S['book'].peers)} peers with data")

    t = time.time()                                                                  # 5 (claims feed the timeline)
    S["claims"] = claims_mod.extract_claims(S["evidence"], use_llm=use_llm)
    focus = S["plan"]["hypotheses"][0]["metrics"] if S["plan"]["hypotheses"] else None
    S["timeline"] = timeline_mod.build_timeline(S["book"], S["claims"], inp.disclosure_changes, focus)
    cp = S["timeline"]["primary_change_point"]
    yield done(5, t, cp["text"] if cp else "no change point detected")

    t = time.time()                                                                  # 6
    meets = sum(1 for c in inp.triangulation if c.get("meets_triangulation"))
    yield done(6, t, f"{len(inp.triangulation)} claim clusters, {meets} meet the 2-independent-type rule")

    t = time.time()                                                                  # 7
    S["contradictions"] = contradictions.find_contradictions(S["claims"], inp.say_vs_do, S["evidence"])
    yield done(7, t, f"{len(S['contradictions'])} contradictions flagged")

    t = time.time()                                                                  # 8
    verdicts = [c.get("verdict") for c in inp.benchmark.get("comparisons", [])]
    yield done(8, t, f"overall {inp.benchmark.get('overall', 'insufficient')}; "
                     f"{verdicts.count('company_specific')} company-specific, {verdicts.count('sector_wide')} sector-wide metrics")

    t = time.time()                                                                  # 9
    S["skeptic_runs"], lead, lead_skeptic = [], None, None
    for h in S["plan"]["hypotheses"]:
        run = skeptic_mod.run_skeptic(h, S["book"], inp.benchmark, S["claims"], inp.profile.get("archetype", ""),
                                      inp.coverage, inp.find_disconfirming, inp.collect_more, entity=company)
        S["skeptic_runs"].append(run)
        if run["verdict"] != "rejected":
            lead, lead_skeptic = h, run
            break
    S["lead"], S["lead_skeptic"] = lead, lead_skeptic
    yield done(9, t, (f"'{lead['id']}' {lead_skeptic['verdict']} after {len(lead_skeptic['rounds'])} round(s)"
                      if lead else "no hypothesis survived"))

    t = time.time()                                                                  # 10
    S["falsification"] = falsify.build_falsification(lead, S["book"], use_llm=use_llm) if lead else None
    S["counter"] = (falsify.build_counterargument(lead, lead_skeptic, S["book"], cp, inp.disclosure_changes, inp.coverage)
                    if lead else None)
    yield done(10, t, S["falsification"]["statement"] if S["falsification"] else "nothing to falsify")

    t = time.time()                                                                  # 11
    S["sources"] = scoring.supporting_sources(lead, S["evidence"], S["claims"], S["book"]) if lead else []
    S["score"] = (scoring.score_finding(lead, S["sources"], lead_skeptic, inp.coverage, S["contradictions"], S["book"], now)
                  if lead else None)
    yield done(11, t, f"{S['score']['rating']} ({S['score']['total']:.2f})" if S["score"] else "Weak: no surviving finding")

    t = time.time()                                                                  # 12
    S["discovery"] = writer.build_discovery(lead, S["book"], inp.benchmark, lead_skeptic, S["sources"], S["claims"],
                                            S["contradictions"], S["timeline"], S["falsification"], S["counter"],
                                            S["score"], inp.coverage, use_llm=use_llm)
    problems = writer.check_discovery(S["discovery"])
    yield done(12, t, "8-element check passed" if not problems else "8-element check: " + "; ".join(problems))

    S["problems"] = problems
    yield {"stage": "result", "bundle": make_bundle(inp, S, now)}


def make_bundle(inp: Inputs, S: dict, now: dt.date) -> dict:
    book: MetricBook = S["book"]
    return {
        "schema_version": 1, "company": inp.profile["name"], "slug": slugify(inp.profile["name"]),
        "label": inp.label, "generated_at": now.isoformat(), "profile": inp.profile,
        "metrics": book.data, "benchmark": inp.benchmark, "coverage": inp.coverage,
        "say_vs_do": inp.say_vs_do, "disclosure_changes": inp.disclosure_changes, "triangulation": inp.triangulation,
        "evidence": S["evidence"], "plan": S["plan"], "claims": [c.to_dict() for c in S["claims"]],
        "timeline": S["timeline"], "contradictions": S["contradictions"], "skeptic_runs": S["skeptic_runs"],
        "skeptic": S["lead_skeptic"], "falsification": S["falsification"], "counterargument": S["counter"],
        "score": S["score"], "discovery": S["discovery"], "check_problems": S["problems"],
        "events": S["events"],
        "extras": {"language_drift": extras.language_drift(S["evidence"]), "peer_heatmap": extras.peer_heatmap(book),
                   "why_not": extras.why_not(S["plan"], S["skeptic_runs"]),
                   "falsification_monitor": (falsify.evaluate_falsification(S["falsification"], book)
                                             if S["falsification"] else None)},
    }


def run(inp: Inputs, use_llm: bool = True, now: Optional[dt.date] = None) -> dict:
    bundle = None
    for ev in stream(inp, use_llm=use_llm, now=now):
        if ev["stage"] == "result":
            bundle = ev["bundle"]
    return bundle
