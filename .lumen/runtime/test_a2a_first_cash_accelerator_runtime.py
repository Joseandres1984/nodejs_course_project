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

    def test_existing_caps_and_truth_rules_are_not_changed(self) -> None:
        self.assertEqual(sales.MAX_FOLLOWUPS_PER_TICK, 1)
        self.assertEqual(sales.MIN_BUYER_INTENT_SCORE, 25)
        self.assertFalse(any(row.get("price_usd", 0) <= 0 for row in accel.FIRST_CASH_OFFERS))


if __name__ == "__main__":
    unittest.main()
