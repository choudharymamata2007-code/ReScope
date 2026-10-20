"""Run the analysis modules on REAL stored evidence for one company (Task 1.10 / 1.11 check).
Needs a prior run_company.py run.  python scripts/analyze_company.py "Company Ltd."
Statements are taken from transcripts/presentations by the say-vs-do rule patterns; the same sentences are used as
stand-in claims for triangulation (Member 2's claim extraction will supply the real claims later)."""
import re
import sys
sys.path.insert(0, ".")
from rescope.analysis import disclosure_change as dcg
from rescope.analysis import say_vs_do as sdo
from rescope.analysis import triangulation as tri
from rescope.store import EvidenceStore

name = sys.argv[1]
sample_flag = "--sample" in sys.argv
s = EvidenceStore()
ev = s.query(entity=name)
if (not ev or sample_flag) and (sample_flag or "northwind" in name.lower()):
    from rescope.sample_data import build_sample_store
    s = build_sample_store()
    ev = s.query(entity=name)
series = s.load_series(name)
if not series and ev:
    from rescope.api import Member1API
    api = Member1API(store=s, cache=None)
    series = api.build_metrics(name)
print(f"{len(ev)} evidence items, {len(series)} metric series: {sorted(series)}\n")

sents = []
for e in ev:
    if e.source_type.value in ("transcript", "presentation"):
        for t in re.split(r"(?<=[.!?])\s+|\n+", e.text):
            if 25 < len(t) < 320:
                sents.append((t.strip(), e))
statements = [sdo.Statement(t, e.id, e.period) for t, e in sents if any(r.pattern.search(t) for r in sdo.RULES)]
print(f"== SAY vs DO ({len(statements)} matching statements)")
for r in sdo.evaluate(statements[:60], series)[:15]:
    print(f"[{r.verdict:12}] {r.rule}: {r.statement[:110]!r}\n               {r.detail}")

print("\n== DISCLOSURE CHANGES")
for c in dcg.detect_disclosure_changes(ev)[:15]:
    print(f"[{c.kind}] {c.detail}")

claims = [tri.ClaimRef(t, e.id) for t, e in sents if re.search(r"\d", t)][:80]
print(f"\n== TRIANGULATION ({len(claims)} stand-in claims)")
for c in tri.corroboration_map(claims, s.all(), tri.get_embedder("tfidf"), threshold=0.5)[:6]:
    print(f"- {c.representative[:100]!r}\n  independent={c.independent_count} types={c.independent_source_types} "
          f"outside_company={c.has_outside_company} meets_triangulation={c.meets_triangulation}")
