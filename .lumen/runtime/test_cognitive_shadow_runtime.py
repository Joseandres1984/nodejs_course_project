import unittest

import cognitive_shadow_runtime as shadow_runtime


class BrokenEngine:
    def decide(self, *args, **kwargs):
        raise RuntimeError("synthetic cognitive failure")


class CognitiveShadowRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.original_tick = shadow_runtime._ORIGINAL_MASTER_TICK
        self.original_engine = shadow_runtime._ENGINE

    def tearDown(self):
        shadow_runtime._ORIGINAL_MASTER_TICK = self.original_tick
        shadow_runtime._ENGINE = self.original_engine

    def _fake_master_revenue(self, state, db_status, preflight=None):
        return {
            "company_mode": "REVENUE_EXECUTION",
            "winning_engine": "Autonomous Revenue Factory",
            "reason": "Revenue gap is the current priority.",
            "signals": {
                "revenue_directive": "increase_verified_demand",
                "strategy_mode": "convert_pipeline",
            },
        }

    def _revenue_state(self):
        return {
            "candidate_accounts": [
                {"id": "BUY-1", "verified_company": True, "type": "buyer"},
                {"id": "SUP-1", "verified_company": True, "type": "supplier"},
            ],
            "market_opportunities": [{"id": "OPP-1"}],
            "revenue_factory": {
                "directive": {"code": "increase_verified_demand", "priority": 90},
                "reverse_plan": {"profit_gap_usd": 2500},
            },
        }

    def test_independent_recommendation_detects_recovery(self):
        rec = shadow_runtime.recommend_company_mode({}, {"connected": False})
        self.assertEqual(rec["recommended_mode"], "RECOVERY")
        self.assertGreater(rec["score"], rec["runner_up_score"])
        self.assertGreaterEqual(rec["confidence"], 0.5)

    def test_independent_recommendation_detects_revenue_execution(self):
        rec = shadow_runtime.recommend_company_mode(self._revenue_state(), {"connected": True})
        self.assertEqual(rec["recommended_mode"], "REVENUE_EXECUTION")
        self.assertGreater(rec["scores"]["REVENUE_EXECUTION"], rec["scores"]["BALANCED"])

    def test_shadow_records_agreement_without_becoming_authoritative(self):
        shadow_runtime._ORIGINAL_MASTER_TICK = self._fake_master_revenue
        state = self._revenue_state()
        report = shadow_runtime.master_orchestrator_with_cognitive_shadow(state, {"connected": True})

        shadow = report["cognitive_shadow"]
        self.assertEqual(report["company_mode"], "REVENUE_EXECUTION")
        self.assertEqual(shadow["recommended_company_mode"], "REVENUE_EXECUTION")
        self.assertTrue(shadow["comparison"]["agreed"])
        self.assertEqual(shadow["comparison"]["agreement_rate_pct"], 100.0)
        self.assertFalse(shadow["authoritative"])
        self.assertFalse(shadow["side_effect_executed"])
        self.assertEqual(shadow["hard_ai_monetary_budget_usd"], 0.0)
        self.assertEqual(len(state["decision_ledger"]), 1)

    def test_shadow_records_disagreement_but_master_stays_authoritative(self):
        shadow_runtime._ORIGINAL_MASTER_TICK = self._fake_master_revenue
        state = {}
        report = shadow_runtime.master_orchestrator_with_cognitive_shadow(state, {"connected": True})

        shadow = report["cognitive_shadow"]
        self.assertEqual(report["company_mode"], "REVENUE_EXECUTION")
        self.assertEqual(shadow["recommended_company_mode"], "BUILD_FOUNDATION")
        self.assertFalse(shadow["comparison"]["agreed"])
        self.assertEqual(shadow["comparison"]["disagreements"], 1)
        self.assertEqual(shadow["comparison"]["disagreement_streak"], 1)
        self.assertFalse(shadow["authoritative"])
        self.assertEqual(state["cognitive_shadow_comparison"]["last_disagreement"]["master_mode"], "REVENUE_EXECUTION")

    def test_comparison_metrics_accumulate_across_cycles(self):
        shadow_runtime._ORIGINAL_MASTER_TICK = self._fake_master_revenue
        state = self._revenue_state()
        shadow_runtime.master_orchestrator_with_cognitive_shadow(state, {"connected": True})
        shadow_runtime.master_orchestrator_with_cognitive_shadow(state, {"connected": True})

        metrics = state["cognitive_shadow_comparison"]
        self.assertEqual(metrics["cycles"], 2)
        self.assertEqual(metrics["agreements"], 2)
        self.assertEqual(metrics["agreement_streak"], 2)
        self.assertEqual(metrics["agreement_rate_pct"], 100.0)
        self.assertEqual(len(metrics["history"]), 2)

    def test_cognitive_failure_does_not_break_master_result(self):
        shadow_runtime._ORIGINAL_MASTER_TICK = self._fake_master_revenue
        shadow_runtime._ENGINE = BrokenEngine()
        state = self._revenue_state()
        report = shadow_runtime.master_orchestrator_with_cognitive_shadow(state, {"connected": True})

        self.assertEqual(report["company_mode"], "REVENUE_EXECUTION")
        self.assertEqual(report["cognitive_shadow"]["status"], "degraded_fail_open")
        self.assertEqual(report["cognitive_shadow"]["recommended_company_mode"], "REVENUE_EXECUTION")
        self.assertFalse(report["cognitive_shadow"]["authoritative"])
        self.assertFalse(report["cognitive_shadow"]["side_effect_executed"])


if __name__ == "__main__":
    unittest.main()
