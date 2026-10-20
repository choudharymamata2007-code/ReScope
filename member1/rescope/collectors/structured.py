"""Structured quarterly statements from a data aggregator (default: the `yfinance` package).

WHY: company and exchange sites block automated downloads, and analyst reports carry no balance-sheet
items. An aggregator gives the last ~4-5 quarters of revenue, cost of revenue, receivables, inventory and
payables in one consistent unit, which is enough for receivable days and inventory days.

HONEST LABELLING (so it can never be mistaken for a filing):
  - tier 3, flags ['aggregator', 'unofficial_data'], publisher = aggregator host
  - ratios from it should be cross-checked against filings or presentations where possible
  - it carries NO volume data, so price/volume still needs presentations/transcripts or a labelled proxy
Terms: this library is unofficial and reads a third-party website. Check its current terms before relying on it,
keep requests few (results are cached for a day), and say in the report that this source is an aggregator.
"""
from __future__ import annotations
import datetime as dt
from typing import Any, Callable, Optional
import pandas as pd
from ..cache import DiskCache
from ..schema import CollectorResult, Evidence, Role, SourceType
from ..store import EvidenceStore
from ..tagging.tagger import fiscal_period_for_date, make_evidence

# our standard row label -> candidate aggregator labels (first one found wins)
LINE_ITEMS: dict[str, list[str]] = {
    "Revenue from operations": ["Total Revenue", "Operating Revenue", "Revenue"],
    "Cost of goods sold": ["Cost Of Revenue", "Reconciled Cost Of Revenue"],
    "EBITDA": ["EBITDA", "Normalized EBITDA"],
    "Trade receivables": ["Accounts Receivable", "Receivables", "Gross Accounts Receivable"],
    "Inventories": ["Inventory", "Inventories"],
    "Trade payables": ["Accounts Payable", "Payables", "Payables And Accrued Expenses"],
}
AGGREGATOR_HOST = "finance.yahoo.com"


def _default_factory(symbol: str):
    import yfinance as yf          # imported lazily so the package stays optional
    return yf.Ticker(symbol)


def build_table(income: Optional[pd.DataFrame], balance: Optional[pd.DataFrame]) -> tuple[list[str], list[str]]:
    """Rows in the 'label | q1 | q2 ...' format the extractor reads, plus notes about missing items."""
    frames = [f for f in (income, balance) if f is not None and not f.empty]
    if not frames:
        return [], ["aggregator returned no quarterly statements"]
    dates: dict[str, pd.Timestamp] = {}                       # fiscal period -> latest date in that period
    for f in frames:
        for c in f.columns:
            d = pd.Timestamp(c)
            period = fiscal_period_for_date(d.date())
            if period not in dates or d > dates[period]:
                dates[period] = d
    periods = sorted(dates, key=lambda p: dates[p])
    rows, notes = ["Particulars | " + " | ".join(periods)], []
    for label, candidates in LINE_ITEMS.items():
        found = None
        for f in frames:
            for cand in candidates:
                if cand in f.index:
                    found = (f, cand)
                    break
            if found:
                break
        if not found:
            notes.append(f"'{label}' not provided by the aggregator")
            continue
        f, cand = found
        vals = []
        for p in periods:
            # the column in this frame that falls in the same fiscal period (if any)
            match = [c for c in f.columns if fiscal_period_for_date(pd.Timestamp(c).date()) == p]
            v = f.at[cand, match[0]] if match else None
            vals.append("-" if v is None or pd.isna(v) else repr(float(v)))
        rows.append(f"{label} | " + " | ".join(vals))
    return rows, notes


class StructuredCollector:
    def __init__(self, cache: Optional[DiskCache] = None, ticker_factory: Optional[Callable[[str], Any]] = None,
                 store: Optional[EvidenceStore] = None, cache_ttl: float = 86400):
        self.cache = cache or DiskCache()
        self.factory = ticker_factory or _default_factory
        self.store, self.cache_ttl = store, cache_ttl

    def classify(self, symbol: str, suffix: str = ".NS") -> dict:
        """{'industry': ..., 'sector': ...} from the aggregator, cached for a week. Empty values if unavailable."""
        ticker = symbol if "." in symbol else symbol + suffix
        key = f"classify:{ticker}"
        cached = self.cache.get_json(key, ttl=7 * 86400)
        if cached is not None:
            return cached
        out = {"industry": None, "sector": None}
        try:
            info = getattr(self.factory(ticker), "info", None) or {}
            out = {"industry": info.get("industry"), "sector": info.get("sector")}
        except Exception:
            pass
        if out["industry"] or out["sector"]:
            self.cache.set_json(key, out)
        return out

    def collect(self, symbol: str, entity: str, role: Role, suffix: str = ".NS") -> CollectorResult:
        res = CollectorResult(source="structured")
        ticker = symbol if "." in symbol else symbol + suffix
        key = f"structured:{ticker}"
        try:
            cached = self.cache.get_json(key, ttl=self.cache_ttl)
            if cached is not None:
                rows, notes = cached["rows"], cached["notes"]
            else:
                t = self.factory(ticker)
                rows, notes = build_table(getattr(t, "quarterly_income_stmt", None), getattr(t, "quarterly_balance_sheet", None))
                if rows:
                    self.cache.set_json(key, {"rows": rows, "notes": notes})
            res.errors += [f"{ticker}: {n}" for n in notes]
            if len(rows) < 2:
                res.errors.append(f"{ticker}: no usable quarterly statements")
                return res
            periods = rows[0].split(" | ")[1:]
            ev = make_evidence(
                title=f"{entity}: quarterly statements from data aggregator ({ticker})", text="\n".join(rows),
                url=f"https://{AGGREGATOR_HOST}/quote/{ticker}/financials", entity=entity, role=role,
                locator="table 1 (aggregator quarterly statements)", source_type=SourceType.results, tier=3,
                period=periods[-1], publisher=AGGREGATOR_HOST)
            ev.flags += ["aggregator", "unofficial_data"]
            res.items.append(ev)
        except ImportError:
            res.errors.append("structured data skipped: run `pip install yfinance` to enable it")
        except Exception as exc:
            res.errors.append(f"{ticker}: structured data failed: {exc}")
        if self.store:
            self.store.add_many(res.items)
        return res
