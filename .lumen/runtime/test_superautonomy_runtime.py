from __future__ import annotations

import importlib
import sys
import types
import unittest


class _AutonomyCoreStub(types.ModuleType):
    ROLE_BOOST_CAP = 0.12

    def __init__(self):
        super().__init__("autonomy_core_runtime")

    @staticmethod
    def _metric_snapshot(state):
        return dict(state.get("_metrics", {}))

    @staticmethod
    def autonomy_core_prepare(state):
        core = state.setdefault("autonomy_core", {})
        core.setdefault("policy_hints", {})
        core.setdefault("role_attention", {})
        return core

    @staticmethod
    def autonomy_core_tick(state):
        return _AutonomyCoreStub.autonomy_core_prepare(state)


class _DirectorStub(types.ModuleType):
    def __init__(self):
        super().__init__("autonomous_director_runtime")

    @staticmethod
    def _expanded_metrics(state):
        return dict(state.get("_metrics", {}))

    @staticmethod
    def _expanded_bottleneck(metrics):
        if metrics.get("canonical_opportunities", 0) <= 0:
            return "opportunity_creation", "canonical_opportunities"
        if metrics.get("requirements_ready_for_rfq", 0) <= 0:
            return "requirement_completion", "requirements_ready_for_rfq"
        if metrics.get("canonical_real_offers", 0) <= 0:
            return "quote_capture", "canonical_real_offers"
        if metrics.get("canonical_proposals", 0) <= 0:
            return "proposal_creation", "canonical_proposals"
        if metrics.get("canonical_close_ready", 0) <= 0:
            return "close_path", "canonical_close_ready"
        return "realized_revenue", "realized_profit_usd"


class SuperautonomyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.modules["autonomy_core_runtime"] = _AutonomyCoreStub()
        sys.modules["autonomous_director_runtime"] = _DirectorStub()
        sys.modules.pop("superautonomy_runtime", None)
        cls.mod = importlib.import_module("superautonomy_runtime")

    def test_quote_capture_is_selected_from_verified_funnel(self):
        state = {
            "ticks": 4,
            "_metrics": {
                "canonical_opportunities": 1,
                "requirements_ready_for_rfq": 1,
                "canonical_real_offers": 0,
                "canonical_proposals": 0,
                "canonical_close_ready": 0,
                "realized_profit_usd": 0,
            },
            "search_budget_governor": {"effective_total_remaining": 0},
            "autonomy_core": {"policy_hints": {}, "role_attention": {}},
        }
        row = self.mod.superautonomy_prepare(state)
        self.assertEqual(row["bottleneck"], "quote_capture")
        self.assertEqual(row["current_action"], "prepare_comparable_rfq")
        self.assertFalse(row["guardrails"]["outgoing_spend_enabled"])
        self.assertTrue(row["guardrails"]["binding_actions_human_gated"])

    def test_search_exhaustion_prefers_offline_action(self):
        sup = {"decision_memory": {}}
        action = self.mod._select_action(sup, "opportunity_creation", 0)
        self.assertFalse(action["needs_search"])
        self.assertEqual(action["id"], "promote_verified_inventory")

    def test_role_attention_never_exceeds_cap(self):
        core = {"role_attention": {"revops": 0.11}}
        action = {"roles": ["revops", "research_analyst"]}
        boosts = self.mod._apply_attention(core, action, 99, None)
        self.assertLessEqual(boosts["revops"], self.mod.ROLE_BOOST_CAP)
        self.assertLessEqual(boosts["research_analyst"], self.mod.ROLE_BOOST_CAP)

    def test_explicit_payment_approval_surfaces_human_gate(self):
        state = {
            "ticks": 8,
            "_metrics": {"canonical_opportunities": 0},
            "search_budget_governor": {"effective_total_remaining": 0},
            "autonomy_core": {"policy_hints": {}, "role_attention": {}},
            "approvals": [{
                "id": "APR-1",
                "status": "pending",
                "type": "payment",
                "reason": "Execute outgoing payment",
            }],
        }
        row = self.mod.superautonomy_prepare(state)
        self.assertEqual(row["stage"], "HUMAN_APPROVAL_REQUIRED")
        self.assertEqual(row["human_gate"]["id"], "APR-1")

    def test_verified_progress_teaches_action_memory(self):
        state = {
            "ticks": 10,
            "_metrics": {"canonical_opportunities": 1},
            "autonomy_core": {"policy_hints": {}, "role_attention": {}},
            "superautonomy": {
                "decision_memory": {"promote_verified_inventory": {"score": 1.0, "attempts": 1, "wins": 0, "losses": 0}},
                "outcomes": [],
                "active_decision": {
                    "id": "SUPER-9-x",
                    "action_id": "promote_verified_inventory",
                    "target_metric": "canonical_opportunities",
                    "baseline": 0,
                    "samples": 1,
                    "status": "TESTING",
                },
            },
        }
        sup = state["superautonomy"]
        outcome = self.mod._evaluate_previous(state, sup, state["_metrics"])
        self.assertEqual(outcome["status"], "SUPPORTED")
        self.assertGreater(sup["decision_memory"]["promote_verified_inventory"]["score"], 1.0)
        self.assertEqual(sup["decision_memory"]["promote_verified_inventory"]["wins"], 1)


if __name__ == "__main__":
    unittest.main()
