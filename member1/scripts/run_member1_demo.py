"""Offline demo on FICTIONAL data. Runs the whole Member 1 chain end to end and (re)writes:
  data/sample_equity_list.csv   fictional exchange list
  data/sample_evidence.json     evidence items in the shared contract (for Member 2 to load on day 1)
  data/sample_outputs.json      profile, metric series, benchmark, coverage, say-vs-do, disclosure changes
Usage: python scripts/run_member1_demo.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rescope import config
from rescope.analysis import say_vs_do as sdo
from rescope.analysis import triangulation as tri
from rescope.api import Member1API
from rescope.intake.listings import parse_listing_csv
from rescope.sample_data import FICTIONAL_UNIVERSE_CSV, build_sample_store
from rescope.schema import Role

data = config.ROOT / "data"
data.mkdir(exist_ok=True)
(data / "sample_equity_list.csv").write_text(FICTIONAL_UNIVERSE_CSV)
store = build_sample_store()
api = Member1API(store=store, universe=parse_listing_csv(FICTIONAL_UNIVERSE_CSV), cache=None)

profile = api.resolve("northwind foods", business_text=["packaged foods and personal care FMCG"])
for name, role in [(profile.name, Role.company)] + [(p.name, Role.peer) for p in profile.peers]:
    api.build_metrics(name, role)
company_series = store.load_series(profile.name)

ev = store.all()
by_type = {e.source_type.value: e for e in ev}
claims = [tri.ClaimRef("Receivable days rose steadily while volumes declined", by_type["results"].id),
          tri.ClaimRef("Distributor payment cycles lengthened and receivable days rose across the sector", by_type["news"].id),
          tri.ClaimRef("Management describes a volume-led premium growth story", by_type["transcript"].id)]
statements = [sdo.Statement("We are a volume-led growth story", by_type["transcript"].id),
              sdo.Statement("Our channel is healthy", by_type["presentation"].id),
              sdo.Statement("Inventory is under control", by_type["presentation"].id)]

out = {
    "profile": json.loads(profile.model_dump_json()),
    "benchmark": api.benchmark(profile),
    "coverage": api.coverage(profile),
    "say_vs_do": api.say_vs_do(statements, profile.name),
    "disclosure_changes": api.disclosure_changes(profile.name),
    "triangulation": api.triangulate(claims, embed=tri.get_embedder("tfidf")),
    "metrics": {k: [{"period": p.period, "value": p.value, "locator": p.locator} for p in s.points]
                for k, s in company_series.items() if k in ("receivable_days", "volume_growth_yoy", "price_share_of_growth")},
}
(data / "sample_outputs.json").write_text(json.dumps(out, indent=2, default=str))
n = store.export_json(data / "sample_evidence.json")
print(f"profile: {profile.name} | archetype={profile.archetype} | peers={[p.name for p in profile.peers]}")
print(f"benchmark overall: {out['benchmark']['overall']}")
print(f"coverage: score={out['coverage']['coverage_score']} sufficient={out['coverage']['sufficient']}")
print(f"say-vs-do: {[(r['rule'], r['verdict']) for r in out['say_vs_do']]}")
print(f"disclosure changes: {[(c['kind'], c['term']) for c in out['disclosure_changes']]}")
print(f"wrote {n} evidence items to data/sample_evidence.json and data/sample_outputs.json")
