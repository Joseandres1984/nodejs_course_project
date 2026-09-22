from __future__ import annotations

import unittest

import revenue_expansion_runtime as revenue


class RevenueExpansionRuntimeTests(unittest.TestCase):
    def test_catalog_contains_three_new_monetization_lanes(self):
        catalog = revenue.build_catalog()
        self.assertEqual(catalog["sourcing_success"]["id"], "REV-SOURCING-SUCCESS")
        self.assertGreaterEqual(len(catalog["subscriptions"]), 4)
        self.assertGreaterEqual(len(catalog["agent_apis"]), 6)

    def test_sourcing_success_never_claims_transaction_ready_without_verified_demand(self):
        state = {"operational_truth_auditor": {"counts": {"verified_buyers": 24, "buyers_with_verified_demand": 0}}}
        report = revenue.run_once(state)
        sourcing = [row for row in report["lane_priority"] if row["lane"] == "sourcing_success"][0]
        self.assertIn("prepare_success_fee_lane", sourcing["reason"])
        self.assertEqual(report["counts"]["buyers_with_verified_demand"], 0)

    def test_sourcing_success_becomes_top_priority_when_verified_demand_exists(self):
        state = {"operational_truth_auditor": {"counts": {"verified_buyers": 24, "buyers_with_verified_demand": 2}}}
        report = revenue.run_once(state)
        self.assertEqual(report["lane_priority"][0]["lane"], "sourcing_success")
        self.assertEqual(report["lane_priority"][0]["priority"], 100)

    def test_guardrails_remain_unchanged(self):
        report = revenue.run_once({})
        self.assertEqual(report["monetary_budget_usd"], 0)
        self.assertFalse(report["search_cap_changed"])
        self.assertFalse(report["outbound_caps_changed"])
        self.assertFalse(report["evidence_thresholds_changed"])
        self.assertFalse(report["autonomous_discount"])
        self.assertFalse(report["autonomous_contract"])
        self.assertFalse(report["autonomous_payment"])
        self.assertFalse(report["binding_authority_changed"])

    def test_prices_are_fixed_launch_prices_and_nonbinding(self):
        catalog = revenue.build_catalog()
        self.assertTrue(catalog["price_changes_require_human_review"])
        self.assertTrue(all(row["price_usd_month"] > 0 for row in catalog["subscriptions"]))
        self.assertTrue(all(row["unit_price_usd"] > 0 for row in catalog["agent_apis"]))
        self.assertEqual(catalog["agent_apis"][0]["id"], "MP-SUPPLIER-SNAPSHOT")


if __name__ == "__main__":
    unittest.main()
