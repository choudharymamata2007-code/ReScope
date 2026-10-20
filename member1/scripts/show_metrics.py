"""Print the computed metric series for one entity, with their sources.   python scripts/show_metrics.py "Company Ltd." """
import sys
sys.path.insert(0, ".")
from rescope.store import EvidenceStore

name = sys.argv[1]
sample_flag = "--sample" in sys.argv
s = EvidenceStore()
series = s.load_series(name)
if (not series or sample_flag) and (sample_flag or "northwind" in name.lower()):
    from rescope.sample_data import build_sample_store
    s = build_sample_store()
    from rescope.api import Member1API
    api = Member1API(store=s, cache=None)
    series = api.build_metrics(name)
print("series built:", sorted(series))
for k in ("receivable_days", "inventory_days", "cash_conversion_cycle", "gross_margin", "revenue_growth_yoy",
          "volume_growth_yoy", "price_mix_growth_yoy", "price_share_of_growth"):
    if k in series:
        print("\n" + k)
        for p in series[k].points:
            if p.value is not None:
                tag = " PROXY" if p.is_proxy else ""
                print(f"   {p.period}  {p.value:.3f}{tag}  | {(p.locator or '')[:70]} | {p.note[:60]}")
agg = [e for e in s.query(entity=name) if "aggregator" in e.flags]
print("\naggregator evidence items:", len(agg))
for e in agg:
    print(e.text)
