import unittest

from cognitive_engine import CognitiveEngine, HARD_AI_MONETARY_BUDGET_USD


class FreeAdvisor:
    monetary_cost_usd = 0.0

    def __init__(self, proposal):
        self.proposal = proposal
        self.calls = 0

    def propose(self, **kwargs):
        self.calls += 1
        return dict(self.proposal)


class PaidAdvisor:
    monetary_cost_usd = 0.01

    def __init__(self):
        self.calls = 0

    def propose(self, **kwargs):
        self.calls += 1
        raise AssertionError("paid advisor must never be called")


class CognitiveEngineTests(unittest.TestCase):
    def test_deterministic_fallback_works_without_ai(self):
        state = {}
        result = CognitiveEngine().decide(
            state,
            {"kind": "opportunity", "id": "OPP-1", "action": "score_opportunity"},
        )
        self.assertEqual(result["status"], "approved")
        self.assertEqual(result["source"], "deterministic")
        self.assertEqual(result["specialist"], "market_intelligence")
        self.assertFalse(result["side_effect_executed"])
        self.assertEqual(HARD_AI_MONETARY_BUDGET_USD, 0.0)
        self.assertEqual(len(state["decision_ledger"]), 1)

    def test_paid_advisor_is_blocked_before_call(self):
        state = {}
        advisor = PaidAdvisor()
        result = CognitiveEngine(advisor).decide(
            state,
            {"kind": "lead", "id": "LEAD-1", "action": "classify_lead"},
        )
        self.assertEqual(advisor.calls, 0)
        self.assertEqual(result["source"], "deterministic")
        self.assertEqual(result["advisor_status"], "blocked_by_zero_cost_policy")
        self.assertEqual(state["cognitive_engine"]["paid_ai_blocked"], 1)

    def test_zero_cost_advisor_remains_subject_to_governor(self):
        state = {}
        advisor = FreeAdvisor({
            "action": "payment",
            "decision": "pay_supplier",
            "reason": "Supplier invoice appears payable.",
            "confidence": 0.95,
            "evidence_refs": ["invoice:123"],
        })
        result = CognitiveEngine(advisor).decide(
            state,
            {"kind": "invoice", "id": "INV-123"},
        )
        self.assertEqual(advisor.calls, 1)
        self.assertEqual(result["source"], "zero_cost_advisor")
        self.assertEqual(result["status"], "approval_required")
        self.assertFalse(result["governance"]["allowed"])
        self.assertTrue(result["governance"]["requires_approval"])
        self.assertFalse(result["side_effect_executed"])

    def test_invalid_advisor_output_falls_back_safely(self):
        state = {}
        advisor = FreeAdvisor({
            "action": "invent_unbounded_action",
            "decision": "do_anything",
            "reason": "invalid action",
        })
        result = CognitiveEngine(advisor).decide(
            state,
            {"kind": "strategy", "id": "STRAT-1"},
        )
        self.assertEqual(result["source"], "deterministic")
        self.assertEqual(result["advisor_status"], "invalid_proposal_fallback")
        self.assertEqual(result["proposal"]["action"], "score_opportunity")
        self.assertEqual(state["cognitive_engine"]["advisor_fallbacks"], 1)
        self.assertTrue(any(x["kind"] == "invalid_advisor_proposal" for x in state["governor_incidents"]))

    def test_send_email_is_blocked_when_live_outbound_is_off(self):
        state = {}
        result = CognitiveEngine().decide(
            state,
            {"kind": "email", "id": "MSG-1", "action": "send_email"},
            {"live_outbound": False, "contact_verified": True},
        )
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["governance"]["allowed"])


if __name__ == "__main__":
    unittest.main()
