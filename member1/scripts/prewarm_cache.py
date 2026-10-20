"""Finals preparation (Tasks 1.12 / 1.14): run the normal pipeline for a list of names so fetched pages,
PDFs and search results are in the shared cache. This only WARMS THE CACHE; the live demo still runs the
full pipeline from a cold company name, and any cached result must be labelled 'Cached backup' if shown.
Usage: python scripts/prewarm_cache.py names.txt [--universe data/equity_list.csv]   (one company name per line)"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rescope.api import Member1API
from rescope.collectors.industry import load_series_config
from rescope.intake.listings import load_universe
from rescope.schema import Role


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("names_file")
    ap.add_argument("--universe")
    ap.add_argument("--all-listed", default=None)
    ap.add_argument("--years", nargs="*", default=["FY26", "FY25"])
    a = ap.parse_args(argv)
    api = Member1API(universe=load_universe(a.universe), all_listed=load_universe(a.all_listed) if a.all_listed else None)
    names = [n.strip() for n in Path(a.names_file).read_text().splitlines() if n.strip() and not n.startswith("#")]
    for n in names:
        t0 = time.time()
        try:
            profile = api.resolve(n)
            summary = api.collect(profile, years=a.years, industry_cfg=load_series_config())
            for name, role in [(profile.name, Role.company)] + [(p.name, Role.peer) for p in profile.peers]:
                api.build_metrics(name, role)
            print(f"{n}: ok in {time.time() - t0:.0f}s, new items {summary['new_items']}, errors {len(summary['errors'])}")
        except Exception as exc:
            print(f"{n}: FAILED ({exc})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
