"""Show management-stated volume claims the engine found (with quarter and source).  python scripts/show_volume_mentions.py "Company Ltd." """
import sys
sys.path.insert(0, ".")
from rescope.store import EvidenceStore
from rescope.quant.volume_claims import extract_volume_claims

name = sys.argv[1]
sample_flag = "--sample" in sys.argv
s = EvidenceStore()
items = s.query(entity=name)
if (not items or sample_flag) and (sample_flag or "northwind" in name.lower()):
    from rescope.sample_data import build_sample_store
    s = build_sample_store()
    items = s.query(entity=name)
claims = extract_volume_claims(items)
for c in sorted(claims, key=lambda c: (c.basis, str(c.period))):
    print(f"[{c.basis:7}] {str(c.period):8} {c.value:+.1%}  tier{c.tier} {c.source_type:12} {c.url[:60]} | {c.text[:80]}")
print(len(claims), "claims;", sum(c.basis == "quarter" for c in claims), "with a quarter")
