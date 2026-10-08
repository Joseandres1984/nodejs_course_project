import unittest
from unittest.mock import patch

import a2a_procurement_contact_bridge_runtime as bridge
import outbound_engine as outbound


class ProcurementContactBridgeTests(unittest.TestCase):
    def row(self, **overrides):
        base = {
            "sourceId": "ted_eu_public_procurement",
            "opportunityId": "SRC-TED-694245-2026",
            "remoteId": "694245-2026",
            "evidenceUrl": "https://ted.europa.eu/en/notice/-/detail/694245-2026",
            "name": "Software support services",
            "description": "Published public procurement tender",
            "score": 96,
            "fit": "PUBLIC_PROCUREMENT",
            "demandSignal": 1,
            "buyer": "Example Public Authority",
            "buyerEmail": "procurement@authority.example",
            "buyerWebsite": "https://authority.example/",
            "buyerContactPoint": "Procurement office",
            "buyerIdentifier": "AUTH-123",
            "buyerCountry": "DE",
            "contactSource": "official_ted_notice",
        }
        base.update(overrides)
        return base

    def test_imports_contact_ready_buyer_from_official_notice(self):
        state = {"candidate_accounts": []}
        stats = bridge.import_procurement_contacts(state, [self.row()])
        self.assertEqual(stats["created"], 1)
        self.assertEqual(stats["contact_ready"], 1)
        account = state["candidate_accounts"][0]
        self.assertTrue(account["verified_company"])
        self.assertTrue(account["verified_contact"])
        self.assertTrue(account["demand_signal"])
        self.assertTrue(account["controlled_outbound_only"])
        self.assertEqual(account["commercial_email"], "procurement@authority.example")
        self.assertEqual(account["contact_scope"], "exact_public_procurement_notice_only")

    def test_mismatched_email_domain_is_not_contact_ready(self):
        state = {"candidate_accounts": []}
        bridge.import_procurement_contacts(state, [self.row(buyerEmail="procurement@other.example")])
        account = state["candidate_accounts"][0]
        self.assertFalse(account["verified_contact"])
        self.assertFalse(account["commercial_channel_verified"])

    def test_no_address_inference(self):
        state = {"candidate_accounts": []}
        bridge.import_procurement_contacts(state, [self.row(buyerEmail=None)])
        account = state["candidate_accounts"][0]
        self.assertFalse(account["verified_contact"])
        self.assertFalse(account.get("commercial_email"))

    def test_controlled_procurement_account_does_not_enter_normal_outbound(self):
        state = {
            "candidate_accounts": [],
            "opt_out": [],
            "email_suppression": [],
            "commercial_relationships": [],
            "counterparty_risk_index": {},
            "outbox": [],
            "outbound_sequences": [],
            "acquisition_campaigns": [],
        }
        bridge.import_procurement_contacts(state, [self.row()])
        with patch.object(outbound, "MIN_SCORE", 0):
            prospects = outbound._eligible(state)
        self.assertEqual(len(prospects), 1)
        self.assertTrue(prospects[0]["explicit_demand_fallback"])
        self.assertEqual(prospects[0]["controlled_approval_id"], outbound.CONTROLLED_EXPLICIT_DEMAND_APPROVAL_ID)


if __name__ == "__main__":
    unittest.main()
