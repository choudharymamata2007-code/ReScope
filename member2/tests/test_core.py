"""Offline tests for Member 2's core (standard library only).  python -m unittest discover -s tests -v   (or pytest)"""
import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from rescope_m2 import claims, common, contradictions, falsify, llm, pipeline, planner, prompts, scoring, skeptic, writer
from rescope_m2.common import MetricBook

NOW = dt.date(2026, 10, 18)


def mk_book(company="Acme", rec=(28, 46), vol=(0.05, -0.03), peers_flat=True):
    n = 12
    lin = lambda a, b: [a + (b - a) * i / (n - 1) for i in range(n)]
    ps = [f"Q{(i % 4) + 1} FY{24 + i // 4}" for i in range(n)]
    pts = lambda vals: [{"period": p, "value": v} for p, v in zip(ps, vals)]
    m = {company: {"receivable_days": pts(lin(*rec)), "volume_growth_yoy": pts(lin(*vol))}}
    for i in range(3):
        m[f"Peer{i}"] = {"receivable_days": pts(lin(30, 30.5) if peers_flat else lin(*rec)),
                         "volume_growth_yoy": pts(lin(0.03, 0.03) if peers_flat else lin(*vol))}
    return MetricBook(m, company)


class TestCommon(unittest.TestCase):
    def test_periods(self):
        self.assertEqual(common.parse_period("Q3 FY26"), (2026, 3))
        self.assertEqual(common.period_end("Q4 FY26"), dt.date(2026, 3, 31))
        self.assertEqual(common.sort_periods(["Q1 FY26", "Q4 FY25"]), ["Q4 FY25", "Q1 FY26"])

    def test_trend_directions(self):
        self.assertEqual(common.trend([1, 2, 3, 4, 5, 6, 7, 8])["direction"], "up")
        self.assertEqual(common.trend([8, 7, 6, 5, 4, 3, 2, 1])["direction"], "down")
        self.assertEqual(common.trend([5, 5.01, 4.99, 5, 5.02, 4.98])["direction"], "flat")
        self.assertEqual(common.trend([1, 2])["direction"], "insufficient")

    def test_change_point(self):
        cp = common.detect_change_point([1, 1, 1, 1, 3, 3, 3, 3])
        self.assertEqual(cp["index"], 4)
        self.assertIsNone(common.detect_change_point([1, 1.01, 0.99, 1, 1.01, 0.99, 1, 1]))

    def test_metricbook_accepts_both_formats(self):
        a = MetricBook({"X": {"m": {"points": [{"period": "Q1 FY24", "value": 1.0}]}}}, "X")
        b = MetricBook({"X": {"m": [{"period": "Q1 FY24", "value": 1.0}]}}, "X")
        self.assertEqual(a.series("X", "m"), b.series("X", "m"))
        c = MetricBook({"m": [{"period": "Q1 FY24", "value": 1.0}]}, "X")
        self.assertEqual(c.series("X", "m"), a.series("X", "m"))


class TestLLM(unittest.TestCase):
    def test_unavailable_without_keys(self):
        import os
        for k in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY"):
            os.environ.pop(k, None)
        self.assertIsNone(llm.try_call("falsification", {"metric": "m", "operator": ">", "threshold": 1, "periods": 2}))

    def test_fallback_retry_validation_and_log(self):
        calls = []
        def bad(system, user, post, timeout):
            calls.append("bad"); return "not json at all", {"model": "x"}
        def good(system, user, post, timeout):
            calls.append("good"); return '```json\n{"statement": "ok"}\n```', {"model": "y", "tokens_in": 3, "tokens_out": 4}
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "log.db"
            out = llm.call("falsification", {"metric": "m", "operator": ">", "threshold": 1, "periods": 2}, {"statement": str},
                           providers={"a": bad, "b": good}, order=["a", "b"], max_retries=0, db_path=db)
            self.assertEqual(out["statement"], "ok")
            self.assertEqual(calls, ["bad", "good"])
            rows = llm.read_log(db_path=db)
            self.assertEqual(len(rows), 2)
            self.assertEqual(sorted(r["ok"] for r in rows), [0, 1])

    def test_number_guard(self):
        self.assertTrue(llm.numbers_grounded("rose from 28 to 46", "28 days 46 days"))
        self.assertFalse(llm.numbers_grounded("rose by 99", "28 days 46 days"))


class TestPrompts(unittest.TestCase):
    def test_all_prompts_load_and_render(self):
        for pid in prompts.list_ids():
            spec = prompts.load(pid)
            _, user = prompts.render(spec, {k: "x" for k in spec["inputs"]})
            self.assertTrue(user)

    def test_company_name_check(self):
        self.assertEqual(prompts.check_company_neutral(["Hindustan Unilever Limited", "Nestle India Limited"]), [])
        self.assertTrue(prompts.check_company_neutral(["research assistant"]))  # fires if a name appears


class TestPlannerAndSkeptic(unittest.TestCase):
    def setUp(self):
        self.book = mk_book()
        self.profile = {"archetype": "packaged_staples"}

    def test_hypotheses_ranked_by_data(self):
        plan = planner.build_plan(self.profile, self.book, None, use_llm=False)
        ids = [h["id"] for h in plan["hypotheses"]]
        self.assertIn("channel_stretch", ids)
        self.assertIn("margin_squeeze", [h["id"] for h in plan["untestable"]])
        self.assertIn("gross_margin", plan["missing_metrics"])

    def test_wrong_direction_scores_low(self):
        book = mk_book(rec=(46, 28))
        h = [x for x in planner.build_plan(self.profile, book, None, use_llm=False)["hypotheses"] if x["id"] == "channel_stretch"][0]
        self.assertLess(h["support"], 0.6)

    def test_sector_wide_is_weakened_and_company_specific_survives(self):
        for flat, want in ((True, "survived"), (False, "weakened")):
            book = mk_book(peers_flat=flat)
            plan = planner.build_plan(self.profile, book, None, use_llm=False)
            h = [x for x in plan["hypotheses"] if x["id"] == "channel_stretch"][0]
            bm = {"comparisons": [{"metric": "receivable_days", "verdict": "company_specific" if flat else "sector_wide",
                                   "peers_same_direction": 0 if flat else 3, "peers_total": 3}]}
            run = skeptic.run_skeptic(h, book, bm, [], "packaged_staples", {"sufficient": True})
            self.assertEqual(run["verdict"], want)

    def test_one_peer_cannot_run_sector_test(self):
        v = skeptic.sector_verdict({"comparisons": [{"metric": "m", "verdict": "company_specific", "peers_total": 1}]}, "m")
        self.assertEqual(v["verdict"], "insufficient")

    def test_failing_hook_is_recorded_not_raised(self):
        book = mk_book()
        h = planner.build_plan(self.profile, book, None, use_llm=False)["hypotheses"][0]
        run = skeptic.run_skeptic(h, book, None, [], "x", {"sufficient": True}, find_disconfirming=lambda *a: 1 / 0)
        self.assertTrue(run["warnings"])

    def test_at_most_two_rounds(self):
        book = mk_book(peers_flat=False)
        h = planner.build_plan(self.profile, book, None, use_llm=False)["hypotheses"][0]
        bm = {"comparisons": [{"metric": h["metrics"][0], "verdict": "sector_wide", "peers_same_direction": 3, "peers_total": 3}]}
        run = skeptic.run_skeptic(h, book, bm, [], "x", {"sufficient": True}, collect_more=lambda q: [], max_rounds=2)
        self.assertEqual(len(run["rounds"]), 2)


class TestClaimsAndContradictions(unittest.TestCase):
    EV = [{"id": "a", "text": "Our channel is healthy and inventory is under control. Unit volumes grew strongly this year.",
           "url": "https://x/a", "source_type": "presentation", "source_tier": 3, "role": "company", "entity": "Acme", "period": "Q1 FY26"},
          {"id": "b", "text": "Channel inventory rose sharply and stock levels built up.", "url": "https://x/b",
           "source_type": "news", "source_tier": 4, "role": "company", "entity": "Acme", "period": "Q1 FY26"},
          {"id": "c", "text": "Receivable days rose sharply.", "url": "", "source_type": "news", "source_tier": 4, "role": "company", "entity": "Acme"}]

    def test_claims_need_url_and_direction(self):
        cl = claims.extract_claims(self.EV, use_llm=False)
        self.assertTrue(all(c.url for c in cl))
        self.assertNotIn("c", {c.evidence_id for c in cl})
        stress = [c for c in cl if c.topic == "receivables" or c.topic == "inventory"]
        self.assertTrue(any(c.direction == "down" for c in stress))  # "under control" = not rising
        self.assertTrue(any(c.direction == "up" for c in stress))

    def test_contradiction_pair_found_with_both_quotes(self):
        cl = claims.extract_claims(self.EV, use_llm=False)
        con = contradictions.find_claim_conflicts(cl, nli=lambda a, b: None)
        self.assertTrue(con)
        self.assertTrue(con[0]["quote_a"] and con[0]["quote_b"] and con[0]["url_a"] and con[0]["url_b"])

    def test_management_vs_numbers(self):
        sv = [{"verdict": "misaligned", "evidence_id": "a", "statement": "Our channel is healthy", "detail": "receivable days up"},
              {"verdict": "aligned", "evidence_id": "a", "statement": "ok", "detail": ""}]
        self.assertEqual(len(contradictions.claims_vs_numbers(sv, self.EV)), 1)


class TestFalsification(unittest.TestCase):
    def test_build_validate_and_monitor(self):
        book = mk_book()
        plan = planner.build_plan({"archetype": "packaged_staples"}, book, None, use_llm=False)
        h = [x for x in plan["hypotheses"] if x["id"] == "channel_stretch"][0]
        f = falsify.build_falsification(h, book, use_llm=False)
        falsify.validate_falsification(f)
        self.assertEqual(falsify.evaluate_falsification(f, book)["status"], "confirmed")
        recovered = mk_book(rec=(46, 28), vol=(-0.03, 0.05))  # reverses the pattern
        self.assertIn(falsify.evaluate_falsification(f, recovered)["status"], ("reversed", "weakened"))

    def test_validation_rejects_bad_condition(self):
        with self.assertRaises(ValueError):
            falsify.validate_falsification({"conditions": [{"metric": "m", "operator": "~", "threshold": 1, "periods": 2}], "statement": "x"})


class TestScoring(unittest.TestCase):
    def _src(self, types):
        return [{"id": str(i), "source_type": t, "source_tier": 1, "role": "peer" if t == "gov_macro" else "company", "independent": True}
                for i, t in enumerate(types)]

    def test_weights_sum_to_one_and_cap(self):
        self.assertAlmostEqual(sum(scoring.WEIGHTS.values()), 1.0)
        book = mk_book()
        h = {"metrics": ["receivable_days"]}
        sk = {"verdict": "survived", "reasons": [], "sector": {"verdict": "sector_wide"}, "rounds": [{"independent_counter": 0}]}
        s = scoring.score_finding(h, self._src(["results", "gov_macro", "news"]), sk, {"coverage_score": 1, "sufficient": True}, [], book, NOW)
        self.assertEqual(s["rating"], "Moderate")  # sector-wide caps at Moderate
        self.assertIn("peers", s["cap_reason"])

    def test_strong_and_weak(self):
        book = mk_book()
        h = {"metrics": ["receivable_days"]}
        sk = {"verdict": "survived", "reasons": [], "sector": {"verdict": "company_specific"}, "rounds": [{"independent_counter": 0}]}
        cov = {"coverage_score": 1, "sufficient": True}
        self.assertEqual(scoring.score_finding(h, self._src(["results", "gov_macro", "news"]), sk, cov, [], book, NOW)["rating"], "Strong")
        self.assertEqual(scoring.score_finding(h, self._src(["results"]), sk, cov, [], book, NOW)["rating"], "Weak")
        self.assertEqual(scoring.score_finding(h, self._src(["results", "gov_macro", "news"]), sk, {"coverage_score": .3, "sufficient": False}, [], book, NOW)["rating"], "Weak")


class TestPipelineOnDemo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import make_demo_bundles as m
        cfgs = json.loads((ROOT / "demo" / "demo_companies.json").read_text())
        cls.bundles = [pipeline.run(m.build(c), use_llm=False, now=NOW) for c in cfgs]

    def test_eight_elements_and_links_for_every_company(self):
        for b in self.bundles:
            self.assertEqual(writer.check_discovery(b["discovery"]), [], b["company"])
            for e in b["discovery"]["evidence"]:
                self.assertTrue(e["url"])

    def test_two_companies_no_code_change_differ(self):
        sent = {b["discovery"]["discovery"] for b in self.bundles}
        self.assertEqual(len(sent), len(self.bundles))
        self.assertGreaterEqual(len({b["score"]["rating"] for b in self.bundles}), 3)

    def test_twelve_stage_events(self):
        for b in self.bundles:
            self.assertEqual([e["stage"] for e in b["events"]], list(range(1, 13)))

    def test_no_advice_wording_anywhere(self):
        for b in self.bundles:
            self.assertFalse(writer.BANNED.search(b["discovery"]["discovery"] + " ".join(b["discovery"]["why_it_matters"])))

    def test_no_hardcoded_company_names_in_code_or_prompts(self):
        names = {b["company"] for b in self.bundles} | {p["name"] for b in self.bundles for p in b["profile"]["peers"]}
        hits = []
        for f in list((ROOT / "rescope_m2").rglob("*.py")) + list((ROOT / "rescope_m2" / "prompts").glob("*.yaml")):
            t = f.read_text(encoding="utf-8")
            hits += [f"{f.name}: {n}" for n in names if n in t]
        self.assertEqual(hits, [])

    def test_thin_data_company_is_weak_not_forced(self):
        weak = [b for b in self.bundles if b["company"].startswith("Orchard")][0]
        self.assertEqual(weak["score"]["rating"], "Weak")
        self.assertIn("coverage", weak["score"]["cap_reason"])

    def test_untestable_hypotheses_explained(self):
        for b in self.bundles:
            for w in b["extras"]["why_not"]:
                self.assertTrue(w["reason"])


class TestUiData(unittest.TestCase):
    def test_charts_change_with_company(self):
        from rescope_m2.ui import data
        bs = {x["company"]: data.load_bundle(x["path"]) for x in data.list_bundles(ROOT / "data" / "bundles")}
        self.assertGreaterEqual(len(bs), 5)
        a, c = bs["Northwind Foods Ltd"], bs["Orchard Beverages Ltd"]
        self.assertTrue(data.growth_split(a)["has_split"])
        self.assertFalse(data.growth_split(c)["has_split"])
        fa, fc = data.metric_frame(a, "receivable_days"), data.metric_frame(c, "receivable_days")
        self.assertNotEqual(fa["company"], fc["company"])
        self.assertEqual(len(fa["periods"]), 12)
        self.assertEqual(len(fc["periods"]), 5)
        self.assertNotEqual(data.lead_metrics(a), data.lead_metrics(bs["Lakeside Retail Ltd"]))

    def test_passage_highlight_escapes_html(self):
        from rescope_m2.ui import data
        h = data.passage_html({"passage": "a <b>x</b> y", "highlight": "x"})
        self.assertNotIn("<b>", h)


if __name__ == "__main__":
    unittest.main()
