"""Readable summary of a run_company.py output file (handles the UTF-16 file PowerShell may write)."""
import json, sys
raw = open(sys.argv[1], "rb").read()
d = None
for enc in ("utf-8-sig", "utf-16"):
    try:
        d = json.loads(raw.decode(enc))
        break
    except Exception:
        pass
if d is None:
    print("could not read the file. First bytes:", raw[:120])
    sys.exit()
print("ERRORS:")
for e in d["collect"]["errors"]:
    print(" -", e[:220])
print("\nSOURCES:", json.dumps(d["collect"]["sources"], indent=1))
print("\nCOVERAGE:", json.dumps(d["coverage"], indent=1))
print("\nBENCHMARK:", d["benchmark_overall"])
print("\nMETRIC NOTES:", json.dumps(d.get("metric_notes"), indent=1))
