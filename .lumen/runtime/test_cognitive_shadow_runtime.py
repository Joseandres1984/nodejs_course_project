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

    def _fake_master(self, state, db_status, preflight=None):
        return {
            "company_mode": "REVENUE_EXECUTION",
            "winning_engine": "Autonomous Revenue Factory",
            "reason": "Revenue gap is the current priority.",
            "signals": {
                "revenue_directive": "increase_verified_demand",
                "strategy_mode": "convert_pipeline",
            },
        }

    def test_shadow_observes_master_without_becoming_authoritative(self):
        shadow_runtime._ORIGINAL_MASTER_TICK = self._fake_master
        state = {}
        report = shadow_runtime.master_orchestrator_with_cognitive_shadow(state, {"connected": True})

        self.assertEqual(report["company_mode"], "REVENUE_EXECUTION")
        self.assertEqual(report["winning_engine"], "Autonomous Revenue Factory")
        self.assertFalse(report["cognitive_shadow"]["authoritative"])
        self.assertFalse(report["cognitive_shadow"]["side_effect_executed"])
        self.assertEqual(report["cognitive_shadow"]["hard_ai_monetary_budget_usd"], 0.0)
        self.assertEqual(report["cognitive_shadow"]["master_company_mode"], "REVENUE_EXECUTION")
        self.assertEqual(len(state["decision_ledger"]), 1)

    def test_cognitive_failure_does_not_break_master_result(self):
        shadow_runtime._ORIGINAL_MASTER_TICK = self._fake_master
        shadow_runtime._ENGINE = BrokenEngine()
        state = {}
        report = shadow_runtime.master_orchestrator_with_cognitive_shadow(state, {"connected": True})

        self.assertEqual(report["company_mode"], "REVENUE_EXECUTION")
        self.assertEqual(report["cognitive_shadow"]["status"], "degraded_fail_open")
        self.assertFalse(report["cognitive_shadow"]["authoritative"])
        self.assertFalse(report["cognitive_shadow"]["side_effect_executed"])


if __name__ == "__main__":
    unittest.main()
