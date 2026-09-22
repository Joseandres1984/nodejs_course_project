from __future__ import annotations

import unittest
from unittest import mock

import a2a_global_sales_runtime as sales
import a2a_first_cash_accelerator_runtime as accel


def card(description: str) -> dict:
    return {
        "name": "Buyer Agent",
        "description": description,
        "supportedInterfaces": [
            {
                "url": "https://buyer.example/a2a",
                "protocolBinding": "JSONRPC",
                "protocolVersion": "1.0",
            }
        ],
        "skills": [],
        "securityRequirements": [],
        "securitySchemes": {},
    }


def prior_responder_network(*, machine_offer: bool = False, sent_this_tick: int = 0) -> dict:
    recommended = "MP-QUOTE-SANITY" if machine_offer else "quote_review"
    return {
        "discovered_agents": [
            {
                "domain": "buyer.example",
                "agent": card("procurement buyer RFQ quotation pricing x402"),
            }
        ],
        "handshakes": [
            {
                "id": "A2AHS-1",
                "domain": "buyer.example",
                "agent_name": "Buyer Agent",
                "status": "response_received",
            }
        ],
        "sales_followups": [
            {
                "id": "A2ASALE-OLD",
                "domain": "buyer.example",
                "recommended_service": recommended,
                "response_received": True,
                "commercial_intent_verified": False,
                "order_created": False,
                "payment_verified": False,
            }
        ],
        "a2a_global_sales": {
            "followups_sent_this_tick": sent_this_tick,
            "followup_responses_this_tick": 0,
            "followup_failures_this_tick": 0,
            "funnel": {
                "commercial_followup_attempted": 1,
                "commercial_followup_response_received": 1,
                "explicit_quote_requests": 0,
                "orders_created": 0,
                "payments_verified": 0,
            },
            "guardrails": {
                "max_followups_per_tick": 1,
                "outgoing_spend_usd": 0,
            },
        },
    }


class A2AFirstCashAcceleratorTests(unittest.TestCase):
    def test_exact_low_ticket_offer_mapping(self) -> None:
        self.assertEqual(accel._select_first_cash_offer(card("RFQ quotation pricing"))["id"], "MP-QUOTE-SANITY")
        self.assertEqual(accel._select_first_cash_offer(card("tender procurement bid"))["id"], "MP-TENDER-SCAN")
        self.assertEqual(accel._select_first_cash_offer(card("supplier verification due diligence"))["id"], "MP-SUPPLIER-SNAPSHOT")

    def test_direct_checkout_is_exact_x402_product_path(self) -> None:
        offer = accel._select_first_cash_offer(card("RFQ quotation"))
        self.assertEqual(
            accel._checkout_url(offer),
            "https://lumen-zero-x402.lumen-b2b.workers.dev/buy/quote-sanity",
        )

    def test_followup_sends_exact_product_price_and_checkout_without_creating_charge(self) -> None:
        buyer = card("RFQ quotation pricing assistant")
        with mock.patch.object(
            sales._base,
            "_safe_post_json",
            return_value=({"result": "ack"}, "ok"),
        ) as post:
            response, status, product_id = accel.accelerated_followup_payload(buyer, "buyer.example")

        self.assertEqual(status, "ok")
        self.assertEqual(product_id, "MP-QUOTE-SANITY")
        self.assertIsNotNone(response)
        args = post.call_args.args
        payload = args[2]
        message = payload["params"]["message"]
        text = message["parts"][0]["text"]
        metadata = message["metadata"]
        self.assertIn("USD 7", text)
        self.assertIn("/buy/quote-sanity", text)
        self.assertEqual(metadata["recommendedMachineProduct"], "MP-QUOTE-SANITY")
        self.assertEqual(metadata["recommendedService"], "SRV-QUOTECHECK")
        self.assertEqual(metadata["priceUsd"], "7")
        self.assertFalse(metadata["chargeCreated"])
        self.assertFalse(metadata["lumenAutonomousSpend"])
        self.assertTrue(metadata["bindingActionsHumanGated"])

    def test_secured_remote_agent_remains_blocked(self) -> None:
        secured = card("tender procurement")
        secured["securityRequirements"] = [{"oauth": []}]
        with mock.patch.object(sales._base, "_safe_post_json") as post:
            response, status, product_id = accel.accelerated_followup_payload(secured, "buyer.example")
        post.assert_not_called()
        self.assertIsNone(response)
        self.assertEqual(status, "not_safe_or_supported")
        self.assertEqual(product_id, "")

    def test_generic_capability_falls_back_to_existing_sales_message(self) -> None:
        generic = card("general business market intelligence")
        with mock.patch.object(
            accel,
            "_ORIGINAL_FOLLOWUP",
            return_value=({"result": "fallback"}, "ok", "market_intelligence"),
        ) as fallback:
            result = accel.accelerated_followup_payload(generic, "buyer.example")
        fallback.assert_called_once()
        self.assertEqual(result[2], "market_intelligence")

    def test_prior_generic_responder_gets_one_exact_first_cash_upgrade(self) -> None:
        state = {}
        network = prior_responder_network()
        with mock.patch.object(accel, "_ORIGINAL_NETWORK_TICK", return_value=network), mock.patch.object(
            sales._base,
            "_safe_post_json",
            return_value=({"result": "ack"}, "ok"),
        ) as post:
            result = accel.first_cash_reengagement_tick(state)

        post.assert_called_once()
        snap = result["a2a_global_sales"]
        self.assertEqual(snap["first_cash_reengagements_sent_this_tick"], 1)
        self.assertEqual(snap["followups_sent_this_tick"], 1)
        row = result["sales_followups"][-1]
        self.assertTrue(row["first_cash_reengagement"])
        self.assertEqual(row["recommended_service"], "MP-QUOTE-SANITY")
        self.assertFalse(row["commercial_intent_verified"])
        self.assertFalse(row["order_created"])
        self.assertFalse(row["payment_verified"])
        self.assertEqual(row["outgoing_spend_usd"], 0)

    def test_existing_machine_offer_is_permanently_deduplicated(self) -> None:
        state = {}
        network = prior_responder_network(machine_offer=True)
        with mock.patch.object(accel, "_ORIGINAL_NETWORK_TICK", return_value=network), mock.patch.object(
            sales._base, "_safe_post_json"
        ) as post:
            result = accel.first_cash_reengagement_tick(state)

        post.assert_not_called()
        self.assertEqual(result["a2a_global_sales"]["first_cash_reengagements_sent_this_tick"], 0)
        self.assertEqual(len(result["sales_followups"]), 1)

    def test_reengagement_never_exceeds_existing_followup_cap(self) -> None:
        state = {}
        network = prior_responder_network(sent_this_tick=1)
        with mock.patch.object(accel, "_ORIGINAL_NETWORK_TICK", return_value=network), mock.patch.object(
            sales._base, "_safe_post_json"
        ) as post:
            result = accel.first_cash_reengagement_tick(state)

        post.assert_not_called()
        self.assertEqual(result["a2a_global_sales"]["followups_sent_this_tick"], 1)
        self.assertEqual(result["a2a_global_sales"]["first_cash_reengagements_sent_this_tick"], 0)

    def test_existing_caps_and_truth_rules_are_not_changed(self) -> None:
        self.assertEqual(sales.MAX_FOLLOWUPS_PER_TICK, 1)
        self.assertEqual(accel.MAX_REENGAGEMENTS_PER_TICK, 1)
        self.assertEqual(sales.MIN_BUYER_INTENT_SCORE, 25)
        self.assertFalse(any(row.get("price_usd", 0) <= 0 for row in accel.FIRST_CASH_OFFERS))


if __name__ == "__main__":
    unittest.main()
