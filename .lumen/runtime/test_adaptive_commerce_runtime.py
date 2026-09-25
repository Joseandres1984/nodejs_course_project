from __future__ import annotations

import unittest

import adaptive_commerce_runtime as commerce


class AdaptiveCommerceRuntimeTests(unittest.TestCase):
    def _base_state(self):
        return {
            "retail_product_signals": [{
                "key": "auriculares-test",
                "product": "Auriculares Bluetooth Test",
                "velocity_score": 90,
                "commercial_priority_score": 91,
                "source_title": "Auriculares Bluetooth Test $ 10.000",
                "source_snippet": "Más vendido",
                "source_domain": "mercadolibre.com.ar",
            }],
            "retail_market_evidence": [
                {"product": "Auriculares Bluetooth Test", "source_domain": "tienda1.com.ar", "price_mentions": ["$ 10.500"]},
                {"product": "Auriculares Bluetooth Test", "source_domain": "tienda2.com.ar", "price_mentions": ["AR$ 11.000"]},
            ],
            "candidate_accounts": [{
                "id": "SUP-1", "type": "supplier", "verified_company": True,
                "company_name": "Proveedor SA", "supplier_network_profile": {"tier": "A"},
            }],
            "offers": [{
                "id": "OFF-1", "product": "Auriculares Bluetooth Test", "supplier_account_id": "SUP-1",
                "supplier": "Proveedor SA", "source_traceable": True,
                "source_url": "https://supplier.example/product", "dropship_allowed": True,
                "stock_count": 20, "returns_policy": "30 days", "customer_delivered_cost": 6000,
                "payment_fee_pct": 5, "return_reserve_pct": 2, "sales_tax_cost_pct": 3,
                "tax_treatment_verified": True,
            }],
        }

    def test_verified_candidate_becomes_sale_ready_draft(self):
        state = self._base_state()
        report = commerce.commerce_tick(state)
        self.assertEqual(report["metrics"]["sale_ready"], 1)
        self.assertEqual(report["metrics"]["listing_drafts"], 1)
        draft = state["commerce_listing_drafts"][0]
        self.assertEqual(draft["status"], "ready_for_human_publication_review")
        self.assertGreater(draft["economics"]["contribution_margin_pct"], 18)
        self.assertFalse(draft["fulfillment"]["supplier_purchase_automatic"])

    def test_missing_stock_blocks_sale_ready(self):
        state = self._base_state()
        state["offers"][0].pop("stock_count")
        report = commerce.commerce_tick(state)
        self.assertEqual(report["metrics"]["sale_ready"], 0)
        self.assertIn("stock_confirmed", report["top_candidates"][0]["missing_requirements"])

    def test_third_party_copy_and_autopurchase_remain_disabled(self):
        state = self._base_state()
        report = commerce.commerce_tick(state)
        guardrails = report["guardrails"]
        self.assertFalse(guardrails["copies_third_party_listing_text"])
        self.assertFalse(guardrails["copies_third_party_images"])
        self.assertFalse(guardrails["autonomous_supplier_purchase"])
        self.assertEqual(guardrails["autonomous_outgoing_spend_usd"], 0)


if __name__ == "__main__":
    unittest.main()
