"""Task 1.13: run several companies in one go and summarise them. One failing company never stops the batch.
Usage: python scripts/run_batch.py names.txt --universe data/equity_list.csv [--no-peers]
names.txt: one company name per line (lines starting with # are ignored). Includes at least one company whose
volume is not disclosed, plus one non-NIFTY name if your list contains it.
Output: a table on screen, eval_runs/batch_summary.csv, and one row per company in eval_runs/evaluation_sheet.csv."""
import argparse
import csv
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from rescope import config
from rescope.api import Member1API
from rescope.collectors.industry import load_series_config
from rescope.eval.checks import append_run
from rescope.intake.listings import load_universe
from run_company import run_one


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("names_file")
    ap.add_argument("--universe")
    ap.add_argument("--all-listed", default=None, help="full NSE equity list CSV (names only), used to find peers named in documents")
    ap.add_argument("--years", nargs="*", default=["FY26", "FY25"])
    ap.add_argument("--no-peers", action="store_true")
    ap.add_argument("--peer-docs", action="store_true")
    a = ap.parse_args(argv)
    api = Member1API(universe=load_universe(a.universe), all_listed=load_universe(a.all_listed) if a.all_listed else None)
    cfg = load_series_config()
    names = [n.strip() for n in Path(a.names_file).read_text(encoding="utf-8-sig").splitlines() if n.strip() and not n.startswith("#")]
    rows = []
    for n in names:
        t0 = time.time()
        try:
            r = run_one(api, n, a.years, (), cfg, None, not a.no_peers, True, a.peer_docs)
            cov = r["coverage"]
            rows.append({"company": r["profile"]["name"], "status": "ok", "quarters": cov["quarters_covered"],
                         "metrics": len(cov["metrics_disclosed"]), "peers_with_data": cov["peers_with_data"],
                         "coverage": cov["coverage_score"], "benchmark": r["benchmark_overall"],
                         "errors": len(r["collect"]["errors"]), "seconds": round(time.time() - t0)})
        except Exception as exc:                                  # record the failure and carry on
            append_run({"company": n, "failures": f"run crashed: {exc}"})
            rows.append({"company": n, "status": f"FAILED: {str(exc)[:80]}", "seconds": round(time.time() - t0)})
    out = config.ROOT / "eval_runs" / "batch_summary.csv"
    out.parent.mkdir(exist_ok=True)
    keys = ["company", "status", "quarters", "metrics", "peers_with_data", "coverage", "benchmark", "errors", "seconds"]
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    print("\n" + " | ".join(keys))
    for r in rows:
        print(" | ".join(str(r.get(k, "")) for k in keys))
    print(f"\nsummary saved to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
