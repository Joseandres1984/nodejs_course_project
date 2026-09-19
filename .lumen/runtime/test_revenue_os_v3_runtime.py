import os
import unittest

os.environ["LUMEN_REVENUE_OS_V3_AUTORUN"] = "false"

import revenue_os_v3_runtime as revenue_os


class RevenueOSV3Tests(unittest.TestCase):
    def test_service_candidates_precede_generic_without_changing_eligibility(self):
        generic = {
            "score": 99,
            "account": {"id": "GEN-1"},
            "service_revenue_ready": False,
        }
        quotecheck = {
            "score": 70,
            "account": {"id": "SVC-1"},
            "service_revenue_ready": True,
            "service_revenue_context": {
                "service_id": "SRV-QUOTECHECK",
                "qualification_score": 85,
            },
        }
        ordered = revenue_os.order_revenue_prospects([generic, quotecheck])
        self.assertEqual(ordered[0]["account"]["id"], "SVC-1")
        self.assertEqual(len(ordered), 2)

    def test_first_cash_products_have_explicit_nonempty_ctas(self):
        for service_id in revenue_os.SERVICE_PRIORITY:
            cta = revenue_os.conversion_cta(service_id)
            self.assertTrue(cta)
            self.assertNotIn("garant", cta.lower())
            self.assertNotIn("pagar", cta.lower())

    def test_snapshot_counts_truth_not_preparation_as_contact(self):
        state = {
            "service_sales_pipeline": [
                {"stage": "outreach_prepared", "contact_truth": "not_contacted"},
                {"stage": "contacted", "contact_truth": "provider_accepted"},
                {"stage": "replied", "contact_truth": "replied"},
                {"stage": "verification_required", "contact_truth": "inbound_received"},
                {"stage": "won", "contact_truth": "replied"},
            ]
        }
        snap = revenue_os.pipeline_snapshot(state)
        self.assertEqual(snap["outreach_prepared"], 1)
        self.assertEqual(snap["contacted"], 1)
        self.assertEqual(snap["replied"], 2)
        self.assertEqual(snap["inbound"], 1)
        self.assertEqual(snap["won"], 1)

    def test_unknown_service_gets_no_conversion_cta(self):
        self.assertEqual(revenue_os.conversion_cta("SRV-UNKNOWN"), "")


if __name__ == "__main__":
    unittest.main()
