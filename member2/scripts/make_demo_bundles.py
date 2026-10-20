"""Build the FICTIONAL demo companies: data/bundles/<slug>/bundle.json.
Reads demo/demo_companies.json (data, not code), shapes it like Member 1's output, and runs the real
Member 2 pipeline on it so every chart in the dashboard comes from the same code path as a live run.
    python scripts/make_demo_bundles.py"""
import datetime as dt
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rescope_m2 import claims as claims_mod, pipeline
from rescope_m2.common import MetricBook, median, sort_periods, trend

NOW = dt.date(2026, 10, 18)
EXPECTED = ["revenue_growth_yoy", "volume_growth_yoy", "price_mix_growth_yoy", "receivable_days", "inventory_days", "gross_margin"]


def hid(*parts) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:16]


def periods(n: int, last: str) -> list[str]:
    from rescope_m2.common import parse_period
    fy, q = parse_period(last)
    out = []
    for _ in range(n):
        out.append(f"Q{q} FY{str(fy)[2:]}")
        q -= 1
        if q == 0:
            q, fy = 4, fy - 1
    return out[::-1]


def shape(spec, n, rng, scale=1.0):
    a, b, kind, noise = spec
    vals = []
    for i in range(n):
        t = i / max(1, n - 1)
        v = a + (b - a) * (t if kind == "lin" else 0 if kind == "flat" else t)
        vals.append(v + rng.uniform(-noise, noise))
    return vals


def peer_values(spec, n, rng, mode, idx):
    a, b, kind, noise = spec
    follow = mode == "follow" or (mode == "mixed" and idx % 2 == 0)
    end = a + (b - a) * 0.8 if follow else a + (b - a) * 0.05
    return shape([a, end, "lin" if follow else "flat", noise], n, rng)


def pts(metric, ps, vals, entity_slug, ev_for, unit):
    return [{"period": p, "value": round(v, 5), "unit": unit, "locator": f"p.5 table 1 ({p})",
             "evidence_id": ev_for(p), "is_proxy": False, "note": ""} for p, v in zip(ps, vals)]


def metric_block(spec, n, rng, ps, ev_for, peer_mode=None, idx=0):
    block = {}
    vals = {}
    for m, s in spec.items():
        vals[m] = peer_values(s, n, rng, peer_mode, idx) if peer_mode else shape(s, n, rng)
    if "volume_growth_yoy" in vals and "price_mix_growth_yoy" in vals:
        vals["revenue_growth_yoy"] = [v + p for v, p in zip(vals["volume_growth_yoy"], vals["price_mix_growth_yoy"])]
        vals["price_share_of_growth"] = [p / r if abs(r) > 0.01 else None for p, r in zip(vals["price_mix_growth_yoy"], vals["revenue_growth_yoy"])]
    if all(k in vals for k in ("receivable_days", "inventory_days", "payable_days")):
        vals["cash_conversion_cycle"] = [a + b - c for a, b, c in zip(vals["receivable_days"], vals["inventory_days"], vals["payable_days"])]
    for m, v in vals.items():
        unit = "days" if m.endswith("days") or m == "cash_conversion_cycle" else "ratio"
        block[m] = {"name": m, "unit": unit, "points": [
            {"period": p, "value": None if x is None else round(x, 5), "unit": unit,
             "locator": f"p.5 table 1 ({p})", "evidence_id": ev_for(p), "is_proxy": False, "note": ""}
            for p, x in zip(ps, v)]}
    return block


def make_evidence(cfg, ps, slug):
    name, ev = cfg["name"], []
    def add(**k):
        k.setdefault("fetched_at", NOW.isoformat() + "T08:00:00Z"); k.setdefault("independent", True); k.setdefault("flags", [])
        k["id"] = hid(k["url"], k.get("period"), k["source_type"], k["entity"]); k["origin_hash"] = hid(k["text"])[:12]
        k["claims"] = []; ev.append(k)
    from rescope_m2.common import period_end
    for p in ps:
        add(title=f"{name} quarterly results {p}", text=f"{name} reported results for {p}. Figures for growth, receivables and inventory are in the segment and working capital tables.",
            url=f"https://filings.example.invalid/{slug}/results-{p.replace(' ', '-')}.pdf", source_type="results", source_tier=1,
            date=str(period_end(p) + dt.timedelta(days=40)), entity=name, role="company", period=p, locator="p.5 table 1", publisher="filings.example.invalid")
    stm_idx = 0
    for i, p in enumerate(ps):
        if i % 2 == 1 or i == len(ps) - 1:
            texts = [s["text"] + "." for s in cfg["statements"]]
            body = " ".join(texts) + " We continue to see broad-based growth across our portfolio."
            add(title=f"{name} investor presentation {p}", text=body, url=f"https://ir.example.invalid/{slug}/presentation-{p.replace(' ', '-')}.pdf",
                source_type="presentation", source_tier=3, date=str(period_end(p) + dt.timedelta(days=35)), entity=name, role="company",
                period=p, locator="p.3", publisher="ir.example.invalid")
    add(title=f"{name} earnings call transcript {ps[-1]}", text=" ".join(s["text"] + "." for s in cfg["statements"][:2]),
        url=f"https://ir.example.invalid/{slug}/transcript-{ps[-1].replace(' ', '-')}.pdf", source_type="transcript", source_tier=3,
        date=str(period_end(ps[-1]) + dt.timedelta(days=38)), entity=name, role="company", period=ps[-1], locator="p.7", publisher="ir.example.invalid")
    for j, t in enumerate(cfg["outside"]):
        add(title=f"Trade press note {j + 1} on {name}", text=t, url=f"https://news.example.invalid/{slug}/story-{j + 1}",
            source_type="news", source_tier=4, date=str(period_end(ps[-1]) - dt.timedelta(days=20 * (j + 1))), entity=name,
            role="company", period=None, locator="para 2", publisher="news.example.invalid")
    add(title="Food price index (official series)", text=cfg["industry_note"], url=f"https://data.example.invalid/{slug}/food-cpi",
        source_type="gov_macro", source_tier=2, date=str(period_end(ps[-1]) + dt.timedelta(days=15)), entity="industry", role="industry",
        period=None, locator="series:food_cpi", publisher="data.example.invalid")
    for p in cfg["peers"]:
        pslug = pipeline.slugify(p["name"])
        add(title=f"{p['name']} results (peer)", text=f"{p['name']} peer results used for the company-versus-sector comparison.",
            url=f"https://filings.example.invalid/{pslug}/results-peer.pdf", source_type="results", source_tier=1,
            date=str(period_end(ps[-1]) + dt.timedelta(days=40)), entity=p["name"], role="peer", period=None, locator="p.5 table 1",
            publisher="filings.example.invalid")
    return ev


def build(cfg):
    rng = random.Random(cfg["seed"])
    slug = pipeline.slugify(cfg["name"])
    ps = periods(cfg["quarters"], cfg["last_period"])
    ev = make_evidence(cfg, ps, slug)
    res = {e["period"]: e["id"] for e in ev if e["source_type"] == "results" and e["role"] == "company"}
    metrics = {cfg["name"]: metric_block(cfg["company"], len(ps), rng, ps, lambda p: res.get(p))}
    for i, pe in enumerate(cfg["peers"]):
        peid = next(e["id"] for e in ev if e["entity"] == pe["name"] and e["role"] == "peer")
        metrics[pe["name"]] = metric_block(cfg["company"], len(ps), rng, ps, lambda p, _i=peid: _i, pe["mode"], i)
    indid = next(e["id"] for e in ev if e["role"] == "industry")
    metrics["industry"] = {"food_cpi": {"name": "food_cpi", "unit": "index", "points": [
        {"period": p, "value": round(100 * 1.012 ** i, 2), "unit": "index", "locator": "series:food_cpi", "evidence_id": indid, "is_proxy": False, "note": ""}
        for i, p in enumerate(ps)]}}
    book = MetricBook(metrics, cfg["name"])
    # benchmark in Member 1's format
    comps = []
    for m in book.metric_names():
        if len(book.values(cfg["name"], m)) < 4:
            continue
        ct = trend(book.values(cfg["name"], m))
        pt = [trend(book.values(pe, m)) for pe in book.peers if len(book.values(pe, m)) >= 4]
        same = sum(1 for t in pt if t["direction"] == ct["direction"] and ct["direction"] != "flat")
        if ct["direction"] == "flat":
            verdict, note = "company_specific", "company flat; nothing to attribute to the sector"
        elif not pt:
            verdict, note = "insufficient", "no peers with data"
        else:
            share = same / len(pt)
            verdict = "sector_wide" if share >= 0.6 else "company_specific" if share <= 0.34 else "mixed"
            note = f"{same}/{len(pt)} peers moved the same way"
        rels = [t["relative_change"] for t in pt if t.get("relative_change") is not None]
        comps.append({"metric": m, "company": {"first": ct["first"], "last": ct["last"], "relative_change": ct["relative_change"],
                      "direction": ct["direction"], "n": ct["n"]}, "peer_median_change": median(rels), "peers_same_direction": same,
                      "peers_total": len(pt), "industry": None, "verdict": verdict, "note": note})
    vs = [c["verdict"] for c in comps]
    overall = "insufficient" if not comps or not book.peers else ("sector_wide" if vs.count("sector_wide") > len(vs) / 2 else
              "company_specific" if vs.count("company_specific") > len(vs) / 2 else "mixed")
    benchmark = {"entity": cfg["name"], "peers": book.peers, "comparisons": comps, "overall": overall, "warnings": []}
    # coverage in Member 1's format
    found = sorted({e["source_type"] for e in ev})
    disclosed = [m for m in EXPECTED if m in book.metric_names()]
    comp = {"source_types": round(len(found) / 7, 3), "quarters": min(1.0, len(ps) / 8), "metrics_disclosed": round(len(disclosed) / len(EXPECTED), 3),
            "peer_data": min(1.0, len(book.peers) / 3), "outside_evidence": 1.0}
    score = round(sum(comp.values()) / 5, 3)
    warns = ([f"only {len(ps)} quarters of data (target 8)"] if len(ps) < 8 else []) + \
            ([f"metrics not available: {', '.join(m for m in EXPECTED if m not in disclosed)}"] if len(disclosed) < len(EXPECTED) else []) + \
            ([f"only {len(book.peers)} peers with data"] if len(book.peers) < 3 else [])
    coverage = {"coverage_score": score, "sufficient": score >= 0.6 and len(ps) >= 6, "components": comp, "source_types_found": found,
                "source_types_missing": sorted({"annual_report", "filing", "results", "presentation", "transcript", "news", "gov_macro"} - set(found)),
                "quarters_covered": len(ps), "metrics_disclosed": disclosed, "metrics_missing": [m for m in EXPECTED if m not in disclosed],
                "proxies_used": [], "peers_with_data": len(book.peers), "has_outside_company_evidence": True, "official_filings_found": True,
                "missing_quarters": [], "warnings": warns}
    # say vs do
    sdo = []
    for s in cfg["statements"]:
        t = trend(book.values(cfg["name"], s["metric"]))
        if t["direction"] == "insufficient":
            continue
        ok = {"up": t["direction"] == "up", "down_or_flat": t["direction"] in ("down", "flat"), "up_or_flat": t["direction"] in ("up", "flat")}[s["expected"]]
        eid = next(e["id"] for e in ev if e["source_type"] == "presentation" and s["text"] in e["text"])
        rel = t["relative_change"] or 0.0
        sdo.append({"statement": s["text"], "evidence_id": eid, "rule": s["rule"], "angle": s["angle"], "expected": s["expected"], "metric": s["metric"],
                    "verdict": "aligned" if ok else "misaligned", "observed_direction": t["direction"], "relative_change": round(rel, 4),
                    "detail": f"{s['metric'].replace('_', ' ')} should be {s['expected'].replace('_', ' ')}; observed {t['direction']} ({rel * 100:+.1f}%)"})
    cl = claims_mod.extract_claims(ev, use_llm=False)
    clusters = []
    for topic in sorted({c.topic for c in cl}):
        g = [c for c in cl if c.topic == topic and c.direction]
        if not g:
            continue
        evs = {c.evidence_id for c in g}
        types = sorted({c.source_type for c in g if c.independent})
        clusters.append({"representative": g[0].text, "claim_texts": [c.text for c in g[:4]], "evidence_ids": sorted(evs),
                         "independent_evidence_ids": sorted(evs), "independent_source_types": types, "independent_count": len(types),
                         "has_outside_company": any(c.role != "company" or c.source_type in ("news", "gov_macro") for c in g),
                         "roles": sorted({c.role for c in g}), "meets_triangulation": len(types) >= 2 and any(c.source_type in ("news", "gov_macro") for c in g), "flags": []})
    profile = {"input_name": cfg["name"], "name": cfg["name"], "nse_symbol": cfg["symbol"], "bse_code": None, "isin": None, "sector": None,
               "industry": cfg["industry"], "archetype": cfg["archetype"], "archetype_confidence": 1.0, "archetype_terms": [], "match_score": 100.0,
               "peers": [{"name": p["name"], "symbol": p["symbol"], "reason": "same industry classification", "mentioned_in_report": False,
                          "filings_available": True, "score": 1.5} for p in cfg["peers"]], "warnings": [], "resolved_at": NOW.isoformat() + "T08:00:00Z"}
    return pipeline.Inputs(profile=profile, evidence=ev, metrics=metrics, benchmark=benchmark, coverage=coverage, say_vs_do=sdo,
                           disclosure_changes=cfg.get("disclosure", []), triangulation=clusters, label="Fictional demo data")


if __name__ == "__main__":
    cfgs = json.loads((ROOT / "demo" / "demo_companies.json").read_text())
    for cfg in cfgs:
        b = pipeline.run(build(cfg), use_llm=False, now=NOW)
        out = ROOT / "data" / "bundles" / b["slug"]
        out.mkdir(parents=True, exist_ok=True)
        (out / "bundle.json").write_text(json.dumps(b, indent=1, default=str), encoding="utf-8")
        sc = b["score"]
        print(f"{b['company']:<26} {sc['rating'] if sc else 'Weak':<9} score={sc['total'] if sc else 0:<5} lead={b['discovery']['hypothesis_id']} problems={b['check_problems']}")
