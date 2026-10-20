"""FICTIONAL sample data (no real company or figure) so Member 2 can start on day 1 and the tests run
offline. Mirrors the shape of the brief's worked example: price-led growth, falling volumes, rising
receivable days. All names are invented."""
from __future__ import annotations
import datetime as dt
from .schema import Evidence, MetricPoint, MetricSeries, Role, SourceType
from .store import EvidenceStore
from .tagging.tagger import make_evidence

PERIODS = [f"Q{q} FY{fy}" for fy in (24, 25, 26) for q in (1, 2, 3, 4)]
_Q_END = {1: (6, 30), 2: (9, 30), 3: (12, 31), 4: (3, 31)}


def period_end(period: str) -> dt.date:
    q, fy = int(period[1]), 2000 + int(period.split("FY")[1])
    m, d = _Q_END[q]
    return dt.date(fy if q == 4 else fy - 1, m, d)


FICTIONAL_UNIVERSE_CSV = """NAME OF COMPANY,SYMBOL,SERIES,ISIN NUMBER,Industry
Northwind Foods Ltd,NWFOODS,EQ,INE000A01011,Fast Moving Consumer Goods
Evergreen Staples Limited,EVRGRN,EQ,INE000A01012,Fast Moving Consumer Goods
Harbor Home Care Ltd,HBRHOME,EQ,INE000A01013,Fast Moving Consumer Goods
Sunrise Beverages Limited,SUNBEV,EQ,INE000A01014,Fast Moving Consumer Goods
Maple Personal Care Ltd,MAPLEPC,EQ,INE000A01015,Fast Moving Consumer Goods
Granite Steel Works Ltd,GRNSTEEL,EQ,INE000A01016,Metals
Urban Fashion Retail Limited,URBFASH,EQ,INE000A01017,Retail
"""

# (volume path, receivable days start/end) per fictional company
PROFILES = {
    "Northwind Foods Ltd": dict(vol=[100, 101, 102, 103, 103, 102, 101, 100, 99, 98, 97, 96], dso=(28, 46), pricing=0.020),
    "Evergreen Staples Limited": dict(vol=[100, 100, 101, 101, 101, 100, 99, 98, 98, 97, 96, 96], dso=(30, 31), pricing=0.019),
    "Harbor Home Care Ltd": dict(vol=[100, 101, 101, 102, 101, 100, 99, 99, 98, 97, 97, 96], dso=(29, 29), pricing=0.021),
    "Sunrise Beverages Limited": dict(vol=[100, 102, 104, 107, 111, 115, 119, 124, 129, 135, 141, 148], dso=(27, 28), pricing=0.012),
}


def synthetic_quarterly(name: str) -> dict[str, dict[str, float]]:
    p = PROFILES[name]
    out = {}
    for i, per in enumerate(PERIODS):
        price = 10 * (1 + p["pricing"]) ** i
        vol = p["vol"][i]
        rev = price * vol
        dso = p["dso"][0] + (p["dso"][1] - p["dso"][0]) * i / (len(PERIODS) - 1)
        cogs = 0.6 * rev
        out[per] = dict(revenue=round(rev, 2), cogs=round(cogs, 2), receivables=round(rev * dso / 91.25, 2),
                        inventory=round(cogs * 45 / 91.25, 2), payables=round(cogs * 30 / 91.25, 2), volume=vol)
    return out


def table_evidence(name: str, role: Role) -> Evidence:
    data = synthetic_quarterly(name)
    rows = ["Particulars | " + " | ".join(PERIODS)]
    for label, key in (("Revenue from operations", "revenue"), ("Cost of materials consumed", "cogs"),
                       ("Trade receivables", "receivables"), ("Inventories", "inventory"),
                       ("Trade payables", "payables"), ("Sales volume (index)", "volume")):
        rows.append(f"{label} | " + " | ".join(f"{data[p][key]:,.2f}" for p in PERIODS))
    slug = name.lower().replace(" ", "-")
    return make_evidence(title=f"{name} fictional multi-quarter results summary", text="\n".join(rows),
                         url=f"https://filings.example.invalid/{slug}/results.pdf", entity=name, role=role,
                         locator="p.5 table 1", source_type=SourceType.results, tier=1,
                         date=dt.date(2026, 5, 15), period="Q4 FY26")


def narrative_evidence(name: str = "Northwind Foods Ltd") -> list[Evidence]:
    slug = name.lower().replace(" ", "-")
    items = []
    for per in PERIODS[4:]:                         # presentations quarter by quarter
        text = ("We continue to see broad-based growth. Underlying volume growth and distributor days are reported "
                f"in the appendix for {per}. Our channel is healthy and inventory is under control.")
        if per == PERIODS[-1]:
            text = ("We continue to see broad-based growth and strong value growth. Revenue growth is reported in the "
                    f"appendix for {per}. Our channel is healthy. Metrics are now presented on a restated basis.")
        items.append(make_evidence(title=f"{name} investor presentation {per}", text=text,
                                   url=f"https://ir.example.invalid/{slug}/presentation-{per.replace(' ', '-')}.pdf",
                                   entity=name, role=Role.company, locator="p.3", source_type=SourceType.presentation,
                                   tier=3, period=per, date=period_end(per) + dt.timedelta(days=40)))
    items.append(make_evidence(title=f"{name} earnings call transcript Q4 FY26",
                               text="Management said the company is a volume-led premium growth story and premiumisation continues.",
                               url=f"https://calls.example.invalid/{slug}/transcript-q4-fy26", entity=name, role=Role.company,
                               locator="p.2", source_type=SourceType.transcript, tier=3, period="Q4 FY26",
                               date=dt.date(2026, 5, 16)))
    return items


def industry_series() -> MetricSeries:
    pts = [MetricPoint(period=p, value=round(100 * (1.012 ** i), 2), unit="index", locator="series:food_cpi")
           for i, p in enumerate(PERIODS)]
    return MetricSeries(name="food_cpi", entity="industry", role=Role.industry, unit="index", points=pts)


def peer_evidence() -> list[Evidence]:
    """A few fictional peer and news items so the sample file reaches the 20 to 30 items the plan asks for."""
    items = []
    for name in ("Evergreen Staples Limited", "Harbor Home Care Ltd", "Sunrise Beverages Limited"):
        slug = name.lower().replace(" ", "-")
        items.append(make_evidence(title=f"{name} investor presentation Q4 FY26",
                                   text="Volumes were broadly stable this quarter and pricing supported revenue growth.",
                                   url=f"https://ir.example.invalid/{slug}/presentation-q4-fy26.pdf", entity=name, role=Role.peer,
                                   locator="p.2", source_type=SourceType.presentation, tier=3, period="Q4 FY26", date=dt.date(2026, 5, 20)))
    for i, (title, text) in enumerate([
            ("Distributor credit terms widen across packaged foods", "Distributors across packaged foods report longer payment cycles from several manufacturers."),
            ("Rural demand steadies as food inflation cools", "Rural demand steadied while food inflation cooled over the quarter."),
            ("Packaged foods makers lean on pricing", "Several packaged foods makers relied on price increases as unit volumes stayed flat.")]):
        items.append(make_evidence(title=title, text=text, url=f"https://news{i}.example.invalid/story-{i}", entity="Northwind Foods Ltd",
                                   role=Role.company, locator="rss", source_type=SourceType.news, tier=4, period="Q4 FY26",
                                   date=dt.date(2026, 6, 2 + i)))
    return items


def build_sample_store(store: EvidenceStore | None = None) -> EvidenceStore:
    store = store or EvidenceStore(":memory:")
    for name, role in (("Northwind Foods Ltd", Role.company), ("Evergreen Staples Limited", Role.peer),
                       ("Harbor Home Care Ltd", Role.peer), ("Sunrise Beverages Limited", Role.peer)):
        store.add(table_evidence(name, role))
    store.add_many(narrative_evidence())
    store.add_many(peer_evidence())
    ind = industry_series()
    store.save_series(ind)
    store.add(make_evidence(title="Fictional food price index", text="Food CPI index rose steadily over 12 quarters.",
                            url="https://stats.example.invalid/statistics/food-cpi", entity="industry", role=Role.industry,
                            locator="series:food_cpi", source_type=SourceType.gov_macro, tier=2,
                            period="Q4 FY26", date=dt.date(2026, 5, 12)))
    store.add(make_evidence(title="Analyst note on price-led growth in packaged foods",
                            text="Packaged foods companies have leaned on price increases while unit volumes stayed weak, "
                                 "and distributor payment cycles lengthened across the sector.",
                            url="https://news.example.invalid/news/packaged-foods-price-led", entity="Northwind Foods Ltd",
                            role=Role.company, locator="rss", source_type=SourceType.news, tier=4,
                            period="Q4 FY26", date=dt.date(2026, 5, 20)))
    return store
