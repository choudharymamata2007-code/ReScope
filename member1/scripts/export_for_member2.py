"""Hand-over for Member 2: writes profile, evidence, metric series, benchmark and coverage JSON files.
python scripts/export_for_member2.py "Company Name" --universe data/equity_list.csv   ->  handover/<slug>/*.json"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rescope import config
from rescope.api import Member1API
from rescope.intake.listings import load_universe

ap = argparse.ArgumentParser()
ap.add_argument("name")
ap.add_argument("--universe")
ap.add_argument("--sample", action="store_true", help="use built-in sample store (for offline test handovers)")
a = ap.parse_args()
store = None
if a.sample:
    from rescope.sample_data import build_sample_store
    store = build_sample_store()
api = Member1API(store=store, universe=load_universe(a.universe))
profile = api.resolve(a.name)
out = config.ROOT / "handover" / re.sub(r"[^a-z0-9]+", "-", profile.name.lower()).strip("-")
out.mkdir(parents=True, exist_ok=True)
(out / "profile.json").write_text(profile.model_dump_json(indent=2))
n = api.store.export_json(out / "evidence_company.json", entity=profile.name)
for p in profile.peers:
    api.store.export_json(out / f"evidence_peer_{re.sub(r'[^a-z0-9]+', '-', p.name.lower()).strip('-')}.json", entity=p.name)
metrics = {ent: {k: json.loads(v.model_dump_json()) for k, v in api.store.load_series(ent).items()}
           for ent in [profile.name, "industry"] + [p.name for p in profile.peers]}
(out / "metrics.json").write_text(json.dumps(metrics, indent=2))
(out / "benchmark.json").write_text(json.dumps(api.benchmark(profile), indent=2, default=str))
(out / "coverage.json").write_text(json.dumps(api.coverage(profile), indent=2, default=str))
print(f"wrote {n} company evidence items and metrics/benchmark/coverage to {out}")
