"""Task 2.2 / 1.13 joint rule: fail if any prompt or Member 2 code names a listed company.
    python scripts/check_no_names.py ../member1/data/equity_list.csv"""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rescope_m2 import prompts

names = []
with open(sys.argv[1], newline="", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        names += [row.get("Company Name", ""), row.get("Symbol", "")]
        names.append((row.get("Company Name", "").split() or [""])[0])
names = [n for n in names if len(n) > 3]
problems = prompts.check_company_neutral(names)
for f in (ROOT / "rescope_m2").rglob("*.py"):
    t = f.read_text(encoding="utf-8").lower()
    problems += [f"{f.name}: contains '{n}'" for n in set(names) if f" {n.lower()} " in f" {t} " and len(n) > 5]
print("\n".join(problems) or "0 hit(s)")
sys.exit(1 if problems else 0)
