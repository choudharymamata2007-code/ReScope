"""What is in the evidence store: per URL type, tier, flags, tables and periods.   python scripts/inspect_store.py "Company Ltd." """
import collections, sys
sys.path.insert(0, ".")
from rescope.store import EvidenceStore

s = EvidenceStore()
ev = s.query(entity=sys.argv[1]) if len(sys.argv) > 1 else s.all()
by = collections.defaultdict(lambda: {"n": 0, "tables": 0, "type": "", "tier": 0, "flags": set()})
for e in ev:
    d = by[e.url]
    d["n"] += 1
    d["type"], d["tier"] = e.source_type.value, e.source_tier
    d["flags"] |= set(e.flags)
    d["tables"] += bool(e.locator and "table" in e.locator)
print("total evidence:", len(ev))
for url, d in sorted(by.items(), key=lambda x: -x[1]["n"])[:25]:
    print(f'{d["type"]:13} tier{d["tier"]} items={d["n"]:3} tables={d["tables"]:2} {sorted(d["flags"])}  {url[:90]}')
