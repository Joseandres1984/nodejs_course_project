from __future__ import annotations

import unittest
from unittest import mock

import a2a_global_sales_runtime as sales


def card(description: str = "procurement buyer RFQ x402"):
    return {
        "name": "Buyer Agent",
        "description": description,
        "supportedInterfaces": [
            {"url": "https://buyer.example/a2a", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}
        ],
        "skills": [],
        "securityRequirements": [],
        "securitySchemes": {},
    }


class A2AGlobalSalesTests(unittest.TestCase):
    def test_product_fit_is_specific(self):
        code, label = sales._product_fit(card("RFQ quotation pricing assistant"))
        self.assertEqual(code, "quote_review")
        self.assertIn("quotation", label)

    def test_authenticated_card_is_not_followed(self):
        secured = card()
        secured["securityRequirements"] = [{"oauth": []}]
        self.assertFalse(sales._eligible_card(secured))

    def test_transport_response_triggers_only_nonbinding_followup(self):
        state = {}
        network = {
            "discovered_agents": [{"domain": "buyer.example", "agent": card()}],
            "handshakes": [{
                "id": "A2AHS-1",
                "domain": "buyer.example",
                "agent_name": "Buyer Agent",
                "status": "response_received",
            }],
            "sales_followups": [],
        }
        with mock.patch.object(sales, "_ORIGINAL_TICK", return_value=network), mock.patch.object(
            sales,
            "_followup_payload",
            return_value=({"result": "protocol response"}, "ok", "tender_intelligence"),
        ):
            result = sales._global_sales_tick(state)

        snap = result["a2a_global_sales"]
        self.assertEqual(snap["followups_sent_this_tick"], 1)
        self.assertEqual(snap["followup_responses_this_tick"], 1)
        self.assertEqual(snap["funnel"]["explicit_quote_requests"], 0)
        self.assertEqual(snap["funnel"]["orders_created"], 0)
        self.assertEqual(snap["funnel"]["payments_verified"], 0)
        self.assertEqual(snap["guardrails"]["outgoing_spend_usd"], 0)
        row = result["sales_followups"][0]
        self.assertFalse(row["commercial_intent_verified"])
        self.assertFalse(row["order_created"])
        self.assertFalse(row["payment_verified"])

    def test_followup_is_deduplicated_per_domain(self):
        state = {}
        network = {
            "discovered_agents": [{"domain": "buyer.example", "agent": card()}],
            "handshakes": [{"id": "A2AHS-1", "domain": "buyer.example", "status": "response_received"}],
            "sales_followups": [{"domain": "buyer.example", "response_received": True}],
        }
        with mock.patch.object(sales, "_ORIGINAL_TICK", return_value=network), mock.patch.object(
            sales, "_followup_payload"
        ) as follow:
            result = sales._global_sales_tick(state)
        follow.assert_not_called()
        self.assertEqual(result["a2a_global_sales"]["followups_sent_this_tick"], 0)

    def test_query_vocabulary_does_not_change_caps(self):
        self.assertIn("buyer", sales.GLOBAL_HIGH_INTENT_QUERIES)
        self.assertIn("tender", sales.GLOBAL_HIGH_INTENT_QUERIES)
        self.assertEqual(sales.MAX_FOLLOWUPS_PER_TICK, 1)
        self.assertEqual(sales.MIN_BUYER_INTENT_SCORE, 25)


if __name__ == "__main__":
    unittest.main()
