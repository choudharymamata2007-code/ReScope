"""Connect Member 1's output to Member 2's pipeline.

    from_member1(api, profile)   live: reads the evidence store, metrics, benchmark, coverage and analysis through Member1API
    from_handover(folder)        offline: reads the folder written by member1/scripts/export_for_member2.py
Both return pipeline.Inputs. Member 1 must be importable (add member1/ to sys.path)."""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path
from typing import Optional

from .pipeline import Inputs, _ev_dicts

MEMBER1_DIR = Path(__file__).resolve().parents[2] / "member1"


def ensure_member1_on_path(path: Optional[Path] = None) -> None:
    p = str(path or MEMBER1_DIR)
    if p not in sys.path:
        sys.path.insert(0, p)


def from_handover(folder: str | Path, label: str = "Cached backup") -> Inputs:
    """Read profile.json, metrics.json, benchmark.json, coverage.json and every evidence_*.json."""
    f = Path(folder)
    rd = lambda n, default: json.loads((f / n).read_text(encoding="utf-8")) if (f / n).exists() else default
    evidence: list = []
    for p in sorted(f.glob("evidence_*.json")):
        evidence += json.loads(p.read_text(encoding="utf-8"))
    return Inputs(profile=rd("profile.json", {}), evidence=evidence, metrics=rd("metrics.json", {}),
                  benchmark=rd("benchmark.json", {"comparisons": [], "overall": "insufficient"}),
                  coverage=rd("coverage.json", {"coverage_score": 0.0, "sufficient": False, "warnings": []}),
                  say_vs_do=rd("say_vs_do.json", []), disclosure_changes=rd("disclosure_changes.json", []),
                  triangulation=rd("triangulation.json", []), label=label)


def from_member1(api, profile, label: str = "Live run") -> Inputs:
    """Build Inputs from a Member1API whose store already holds the collected evidence (api.collect was run)."""
    ensure_member1_on_path()
    from rescope.analysis import say_vs_do as sdo           # type: ignore
    from rescope.analysis import triangulation as tri       # type: ignore
    name = profile.name
    api.build_metrics(name)
    for p in profile.peers:
        api.build_metrics(p.name, role=__import__("rescope.schema", fromlist=["Role"]).Role.peer)
    ev = api.store.query(entity=name)
    all_ev = api.store.all()
    metrics = {ent: {k: json.loads(v.model_dump_json()) for k, v in api.store.load_series(ent).items()}
               for ent in [name, "industry"] + [p.name for p in profile.peers]}
    sents = []
    for e in ev:
        if e.source_type.value in ("transcript", "presentation"):
            for t in re.split(r"(?<=[.!?])\s+|\n+", e.text):
                if 25 < len(t) < 320:
                    sents.append((t.strip(), e))
    statements = [sdo.Statement(t, e.id, e.period) for t, e in sents if any(r.pattern.search(t) for r in sdo.RULES)]
    claims = [tri.ClaimRef(t, e.id) for t, e in sents if re.search(r"\d", t)][:80]
    return Inputs(
        profile=json.loads(profile.model_dump_json()), evidence=all_ev, metrics=metrics,
        benchmark=api.benchmark(profile), coverage=api.coverage(profile),
        say_vs_do=api.say_vs_do(statements[:60], name), disclosure_changes=api.disclosure_changes(name),
        triangulation=api.triangulate(claims, name) if claims else [],
        find_disconfirming=lambda hyp, entity, peers: api.find_disconfirming(hyp, entity, peers),
        collect_more=None, label=label)
