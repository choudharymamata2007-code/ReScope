"""LIVE run for one company (needs network access; a Tavily key is optional). Used for Task 1.13 testing:
every failure goes into eval_runs/evaluation_sheet.csv.

Usage:
  python scripts/run_company.py "Company Name" [--universe data/equity_list.csv] [--years FY26 FY25]
        [--rss URL ...] [--series-config config/industry_series.json] [--inbox data/inbox]
        [--no-peers] [--peer-docs] [--no-structured]
Output: JSON summary on stdout (use `| Out-File -Encoding utf8 run.json`), a row in the evaluation sheet."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rescope.api import Member1API
from rescope.collectors.documents import DocumentCollector
from rescope.collectors.industry import load_series_config
from rescope.collectors.local_ingest import ingest_inbox
from rescope.eval.checks import append_run
from rescope.intake.listings import load_universe
from rescope.schema import Role


def run_one(api: Member1API, name: str, years=("FY26", "FY25"), rss=(), series_cfg=None, inbox=None,
            include_peers=True, include_structured=True, peer_docs=False, trends=False) -> dict:
    failures: list[str] = []
    profile = api.resolve(name)
    print(f"resolved: {profile.name} ({profile.nse_symbol}) archetype={profile.archetype} peers={[p.name for p in profile.peers]}", file=sys.stderr)
    summary = api.collect(profile, years=list(years), include_peers=include_peers, include_structured=include_structured,
                          peer_documents=peer_docs, include_trends=trends, rss_urls=list(rss), industry_cfg=series_cfg)
    failures += summary["errors"]
    if inbox:
        dc = DocumentCollector(api.fetcher, api.search_client, api.store)
        print(f"inbox: {ingest_inbox(dc, inbox, profile.name, Role.company, api.store)} items ingested", file=sys.stderr)
    for entity, role in [(profile.name, Role.company)] + [(p.name, Role.peer) for p in profile.peers]:
        if not api.build_metrics(entity, role):
            failures.append(f"no metrics could be built for {entity}")
    bench, cov = api.benchmark(profile), api.coverage(profile)
    result = {"profile": json.loads(profile.model_dump_json()), "collect": summary, "benchmark_overall": bench["overall"],
              "coverage": cov, "metric_notes": api.last_metric_notes}
    append_run({"company": profile.name, "evidence_items": api.store.count(), "source_types": ";".join(cov["source_types_found"]),
                "quarters_covered": cov["quarters_covered"], "metrics_computed": len(api.store.load_series(profile.name)),
                "peers_with_data": cov["peers_with_data"], "coverage_score": cov["coverage_score"], "sufficient": cov["sufficient"],
                "proxies": ";".join(cov["proxies_used"]), "collector_errors": len(summary["errors"]),
                "failures": " | ".join(failures)[:1500]})
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--universe", help="local exchange list CSV; otherwise it is downloaded and cached")
    ap.add_argument("--all-listed", default=None, help="full NSE equity list CSV (names only): lets peers be found from names in the company's documents")
    ap.add_argument("--trends", action="store_true", help="add Google Trends search interest (unofficial; needs pytrends)")
    ap.add_argument("--years", nargs="*", default=["FY26", "FY25"])
    ap.add_argument("--rss", nargs="*", default=[])
    ap.add_argument("--series-config", default=None)
    ap.add_argument("--inbox", default=None, help="folder of manually downloaded PDFs (same pipeline, flagged manual_download)")
    ap.add_argument("--no-peers", action="store_true")
    ap.add_argument("--peer-docs", action="store_true", help="also search and download documents for every peer (slow)")
    ap.add_argument("--no-structured", action="store_true", help="skip the aggregator quarterly-statements collector")
    a = ap.parse_args(argv)
    api = Member1API(universe=load_universe(a.universe), all_listed=load_universe(a.all_listed) if a.all_listed else None)
    result = run_one(api, a.name, a.years, a.rss, load_series_config(a.series_config), a.inbox,
                     not a.no_peers, not a.no_structured, a.peer_docs, a.trends)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
