from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import cognitive_core_v1
import cognitive_core_bridge_runtime


class FakeClient:
    def __init__(self, payload):
        self.payload = payload

    def decide(self, observation):
        if isinstance(self.payload, Exception):
            raise self.payload
        return dict(self.payload)


class CognitiveCoreV1Tests(unittest.TestCase):
    def base_state(self):
        return {
            "expansion_revenue_metrics": {
                "opportunities_active": 2,
                "buyers_contacted": 0,
                "replies": 0,
                "negotiations": 0,
                "proposals": 0,
                "revenue_generated_usd": 0,
            },
            "master_governance": {"kill_switches": {}},
        }

    def test_shadow_mode_never_executes_tool(self):
        calls = []
        state = self.base_state()
        result = cognitive_core_v1.run_cognitive_core(
            state,
            mode="shadow",
            model_client=FakeClient({
                "decision": "research",
                "confidence": 0.8,
                "reasons": ["Need market evidence."],
                "next_action": "Research the market.",
            }),
            tool_registry={"public_research": lambda params: calls.append(params)},
        )
        self.assertEqual(result["mode"], "shadow")
        self.assertFalse(result["execution"]["executed"])
        self.assertEqual(calls, [])
        self.assertFalse(result["guardrails"]["human_required_actions_auto_executed"])

    def test_human_required_action_is_blocked_even_in_active_mode(self):
        calls = []
        state = self.base_state()
        result = cognitive_core_v1.run_cognitive_core(
            state,
            mode="active",
            model_client=FakeClient({
                "action_type": "payment",
                "confidence": 0.99,
                "reasons": ["Attempt binding action."],
                "next_action": "Pay supplier.",
            }),
            tool_registry={"payment": lambda params: calls.append(params)},
        )
        self.assertEqual(result["proposal"]["action_type"], "payment")
        self.assertTrue(result["policy"]["requires_approval"])
        self.assertFalse(result["policy"]["allowed"])
        self.assertFalse(result["execution"]["executed"])
        self.assertEqual(calls, [])

    def test_active_mode_executes_only_registered_constitutionally_allowed_tool(self):
        calls = []
        state = self.base_state()
        result = cognitive_core_v1.run_cognitive_core(
            state,
            mode="active",
            model_client=FakeClient({
                "action_type": "public_research",
                "confidence": 0.85,
                "expected_value": 0.7,
                "reasons": ["Need evidence."],
                "parameters": {"query": "industrial sourcing"},
                "next_action": "Research public market evidence.",
            }),
            tool_registry={
                "public_research": lambda params: calls.append(params) or {"ok": True}
            },
        )
        self.assertTrue(result["policy"]["allowed"])
        self.assertFalse(result["policy"]["requires_approval"])
        self.assertTrue(result["execution"]["executed"])
        self.assertEqual(calls, [{"query": "industrial sourcing"}])

    def test_global_pause_blocks_otherwise_autonomous_action(self):
        state = self.base_state()
        state["master_governance"]["kill_switches"]["global_pause"] = True
        result = cognitive_core_v1.run_cognitive_core(
            state,
            mode="active",
            model_client=FakeClient({
                "action_type": "public_research",
                "confidence": 0.8,
                "reasons": ["Need evidence."],
                "next_action": "Research.",
            }),
            tool_registry={"public_research": lambda params: {"ok": True}},
        )
        self.assertFalse(result["policy"]["allowed"])
        self.assertIn("global_pause", result["policy"]["reasons"])
        self.assertFalse(result["execution"]["executed"])

    def test_model_failure_falls_back_without_breaking_cycle(self):
        state = self.base_state()
        result = cognitive_core_v1.run_cognitive_core(
            state,
            mode="shadow",
            model_client=FakeClient(RuntimeError("offline")),
        )
        self.assertEqual(result["provider"], "deterministic")
        self.assertIn("RuntimeError", result["model_error"])
        self.assertIn(result["proposal"]["action_type"], cognitive_core_v1.SUPPORTED_ACTIONS)
        self.assertIn("cognitive_core_v1", state)
        self.assertEqual(len(state["cognitive_core_history"]), 1)

    def test_sensitive_context_is_redacted(self):
        state = self.base_state()
        state["market_intelligence"] = {
            "api_token": "TOP-SECRET",
            "nested": {"password": "abc", "safe": "visible"},
        }
        obs = cognitive_core_v1.build_observation(state)
        encoded = str(obs)
        self.assertNotIn("TOP-SECRET", encoded)
        self.assertNotIn("'abc'", encoded)
        self.assertIn("[redacted]", encoded)
        self.assertIn("visible", encoded)

    def test_bridge_defaults_to_shadow_and_respects_cadence(self):
        state = self.base_state()
        with patch.dict(os.environ, {
            "LUMEN_COGNITIVE_CORE_V1_ENABLED": "true",
            "LUMEN_COGNITIVE_CORE_V1_MODE": "shadow",
            "LUMEN_COGNITIVE_CORE_V1_EVERY_N_TICKS": "3",
            "LUMEN_COGNITIVE_WORKER_URL": "",
        }, clear=False):
            first = cognitive_core_bridge_runtime.cognitive_core_bridge_tick(state)
            second = cognitive_core_bridge_runtime.cognitive_core_bridge_tick(state)
            third = cognitive_core_bridge_runtime.cognitive_core_bridge_tick(state)

        self.assertEqual(first["mode"], "shadow")
        self.assertFalse(first["executed"])
        self.assertEqual(second["status"], "cadence_skip")
        self.assertNotEqual(third["status"], "cadence_skip")
        self.assertFalse(third["executed"])


if __name__ == "__main__":
    unittest.main()
