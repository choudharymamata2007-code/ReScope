"""Run the 12-stage pipeline and save a dashboard bundle.
    python scripts/run_pipeline.py --handover ../member1/handover/<slug>        (from Member 1's export)
    python scripts/run_pipeline.py --name "Company Name"                        (live: Member 1 collects first)
Add --no-llm to use only the built-in rules. Result: data/bundles/<slug>/bundle.json (shown in the dashboard)."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rescope_m2 import adapter, pipeline

ap = argparse.ArgumentParser()
ap.add_argument("--handover")
ap.add_argument("--name")
ap.add_argument("--no-llm", action="store_true")
ap.add_argument("--label", default=None)
a = ap.parse_args()
if a.handover:
    inp = adapter.from_handover(a.handover, label=a.label or "Cached backup")
elif a.name:
    adapter.ensure_member1_on_path()
    from rescope.api import Member1API                      # type: ignore
    from rescope.intake.listings import load_universe       # type: ignore
    api = Member1API(universe=load_universe(str(adapter.MEMBER1_DIR / "data" / "equity_list.csv")))
    profile = api.resolve(a.name)
    api.collect(profile)
    inp = adapter.from_member1(api, profile, label=a.label or "Live run")
else:
    sys.exit("give --handover or --name")
bundle = None
for ev in pipeline.stream(inp, use_llm=not a.no_llm):
    if ev["stage"] == "result":
        bundle = ev["bundle"]
    else:
        print(f"[{ev['stage']:>2}/12] {ev['name']:<32} {ev['seconds']:>6.2f}s  {ev['summary'][:90]}")
out = ROOT / "data" / "bundles" / bundle["slug"]
out.mkdir(parents=True, exist_ok=True)
(out / "bundle.json").write_text(json.dumps(bundle, indent=1, default=str), encoding="utf-8")
print("check problems:", bundle["check_problems"] or "none", "->", out / "bundle.json")
