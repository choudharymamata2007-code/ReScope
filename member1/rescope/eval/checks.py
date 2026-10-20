"""Task 1.13: (1) scan code and prompts for company names or tickers taken from the live universe
file, so nothing company-specific can creep in; (2) append one row per test run to an evaluation
sheet (CSV) with failures recorded.

Usage:
  python -m rescope.eval.checks --universe path/to/equity_list.csv [--paths rescope prompts]
Exit code 1 if any hit is found (use it as a pre-commit / pre-submission gate)."""
from __future__ import annotations
import argparse
import csv
import re
import sys
import time
from pathlib import Path
from typing import Iterable
from .. import config
from ..intake.listings import ListedCompany, load_universe, normalise_name

CODE_SUFFIXES = {".py", ".yaml", ".yml", ".md", ".txt", ".json", ".toml"}
SKIP_DIRS = {"__pycache__", ".git", "cache", "tests", "data", "eval_runs", ".pytest_cache"}


def forbidden_terms(universe: Iterable[ListedCompany], min_len: int = 5) -> dict[str, str]:
    """term -> kind. Names are matched case-insensitively as whole words; tickers case-sensitively."""
    terms: dict[str, str] = {}
    for c in universe:
        n = normalise_name(c.name)
        if len(n) >= min_len and " " in n or len(n) >= 8:
            terms[n] = f"name of {c.symbol}"
        if len(c.symbol) >= min_len:
            terms[c.symbol] = "ticker"
    return terms


def scan_paths(paths: Iterable[Path | str], terms: dict[str, str]) -> list[tuple[str, int, str, str]]:
    hits = []
    for root in map(Path, paths):
        files = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
        for f in files:
            if f.suffix not in CODE_SUFFIXES or any(part in SKIP_DIRS for part in f.parts):
                continue
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                low = " ".join(re.sub(r"[^\w\s&]", " ", line.lower()).split())
                for term, kind in terms.items():
                    if kind == "ticker":
                        if re.search(rf"\b{re.escape(term)}\b", line):
                            hits.append((str(f), i, term, kind))
                    elif re.search(rf"\b{re.escape(term)}\b", low):
                        hits.append((str(f), i, term, kind))
    return hits


SHEET_FIELDS = ["timestamp", "company", "evidence_items", "source_types", "quarters_covered", "metrics_computed",
                "peers_with_data", "coverage_score", "sufficient", "proxies", "collector_errors", "failures", "notes"]


def append_run(row: dict, path: Path | str | None = None) -> Path:
    p = Path(path or config.ROOT / "eval_runs" / "evaluation_sheet.csv")
    p.parent.mkdir(parents=True, exist_ok=True)
    new = not p.exists()
    with p.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SHEET_FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow({"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), **row})
    return p


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", required=True, help="exchange equity list CSV (real list; not committed)")
    ap.add_argument("--paths", nargs="*", default=[str(config.ROOT / "rescope"), str(config.ROOT / "prompts")])
    a = ap.parse_args(argv)
    terms = forbidden_terms(load_universe(a.universe))
    hits = scan_paths([p for p in a.paths if Path(p).exists()], terms)
    for f, line, term, kind in hits:
        print(f"HARD-CODING? {f}:{line}: '{term}' ({kind})")
    print(f"{len(hits)} hit(s) across {len(terms)} forbidden terms")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
