import os
import unittest
from unittest.mock import patch

os.environ.setdefault("LUMEN_OUTBOUND_LIVE", "false")

import outbound_engine as oe


class ExplicitDemandFallbackTests(unittest.TestCase):
    def base_state(self):
        return {
            "candidate_accounts": [],
            "opt_out": [],
            "email_suppression": [],
            "commercial_relationships": [],
            "counterparty_risk_index": {},
            "outbox": [],
            "outbound_sequences": [],
            "acquisition_campaigns": [],
        }

    def buyer(self, **overrides):
        row = {
            "id": "B1",
            "type": "buyer",
            "verified_company": False,
            "verified_contact": True,
            "commercial_email": "procurement@acme.example",
            "domain": "acme.example",
            "contact_policy": "public_corporate_channels_only",
            "direct_inbound_demand": True,
            "demand_signal": 1,
            "category": "industrial",
            "commercial_contact_evidence": ["https://acme.example/contact"],
        }
        row.update(overrides)
        return row

    def test_rescues_exactly_one_explicit_demand_verified_channel(self):
        state = self.base_state()
        state["candidate_accounts"] = [self.buyer(id="B1"), self.buyer(id="B2", commercial_email="rfq@beta.example", domain="beta.example")]
        prospects = oe._eligible(state)
        self.assertEqual(len(prospects), 1)
        self.assertTrue(prospects[0]["explicit_demand_fallback"])
        self.assertEqual(prospects[0]["controlled_approval_id"], oe.CONTROLLED_EXPLICIT_DEMAND_APPROVAL_ID)

    def test_suppression_and_cooldown_still_block(self):
        state = self.base_state()
        state["candidate_accounts"] = [self.buyer()]
        state["opt_out"] = ["procurement@acme.example"]
        self.assertEqual(oe._eligible(state), [])
        state["opt_out"] = []
        state["commercial_relationships"] = [{"account_id":"B1","relationship_state":"cooldown"}]
        self.assertEqual(oe._eligible(state), [])

    def test_no_explicit_demand_does_not_fallback(self):
        state = self.base_state()
        state["candidate_accounts"] = [self.buyer(direct_inbound_demand=False, demand_signal=0)]
        self.assertEqual(oe._eligible(state), [])

    def test_unknown_domain_unverified_company_remains_blocked(self):
        state = self.base_state()
        state["candidate_accounts"] = [self.buyer(domain="", official_domain="")]
        self.assertEqual(oe._eligible(state), [])

    def test_owner_approval_is_consumed_after_queue(self):
        state = self.base_state()
        state["candidate_accounts"] = [self.buyer()]
        prospects = oe._eligible(state)
        with patch.object(oe, "LIVE", True), patch.object(oe, "MAX_NEW_PER_CYCLE", 1), patch.object(oe, "MAX_NEW_PER_DAY", 3):
            queued = oe._queue_new(state, prospects)
        self.assertEqual(queued, 1)
        self.assertIn(oe.CONTROLLED_EXPLICIT_DEMAND_APPROVAL_ID, state["controlled_outbound_approvals_consumed"])
        msg = state["outbox"][-1]
        self.assertTrue(msg["human_approved_controlled_batch"])
        self.assertTrue(msg["explicit_demand_fallback"])
        self.assertEqual(oe._eligible(state), [])


if __name__ == "__main__":
    unittest.main()
