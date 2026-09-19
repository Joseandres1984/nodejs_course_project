import os
import unittest
from types import SimpleNamespace

os.environ["LUMEN_REVENUE_OS_V31_AUTORUN"] = "false"

import revenue_os_v31_alignment_runtime as alignment


class RevenueOSV31AlignmentTests(unittest.TestCase):
    def test_existing_sequence_is_not_queueable_new_revenue_slot(self):
        state = {
            "outbound_sequences": [
                {"id": "SEQ-A1-a@example.com"},
            ]
        }
        prospects = [
            {"account": {"id": "A1"}, "email": "a@example.com", "score": 80},
            {"account": {"id": "A2"}, "email": "b@example.com", "score": 70},
        ]

        def sequence_id(aid, email):
            return f"SEQ-{aid}-{email}"

        result = alignment._queueable_new_prospects(state, prospects, sequence_id)
        self.assertEqual([x["account"]["id"] for x in result], ["A2"])

    def test_strict_candidate_replaces_nonqueueable_proactive_attention(self):
        state = {
            "service_revenue_opportunities": [{"id": "O1"}, {"id": "O2"}],
            "service_sales_pipeline": [
                {
                    "id": "P-OLD",
                    "source": "verified_account_fit",
                    "account_id": "OLD",
                    "email": "old@example.com",
                    "service_id": "SRV-SOURCING-EXPRESS",
                    "qualification_score": 95,
                    "stage": "outreach_prepared",
                    "proactive_attention_active": True,
                    "contact_truth": "not_contacted",
                },
                {
                    "id": "P-NEW",
                    "source": "intelligence_product_fit",
                    "account_id": "NEW",
                    "email": "new@example.com",
                    "service_id": "SRV-QUOTECHECK",
                    "qualification_score": 80,
                    "stage": "qualified",
                    "proactive_attention_active": False,
                    "contact_truth": "not_contacted",
                },
            ],
        }

        def advance(row, stage, reason):
            row["stage"] = stage
            row["stage_reason"] = reason

        fake_runtime = SimpleNamespace(
            SERVICE_LANE_SHARE_CAP=0.35,
            _advance=advance,
            _service_for=lambda account: {"id": "SRV-SOURCING-EXPRESS", "name": "Sourcing", "audience": "buyer"},
            _score=lambda account: 60.0,
        )
        strict = [{
            "account": {"id": "NEW", "type": "buyer"},
            "email": "new@example.com",
            "score": 72,
        }]

        report = alignment.align_strict_service_attention(state, strict, fake_runtime)
        rows = {x["id"]: x for x in state["service_sales_pipeline"]}
        self.assertFalse(rows["P-OLD"]["proactive_attention_active"])
        self.assertTrue(rows["P-NEW"]["proactive_attention_active"])
        self.assertEqual(rows["P-NEW"]["stage"], "outreach_prepared")
        self.assertEqual(rows["P-NEW"]["contact_truth"], "not_contacted")
        self.assertEqual(report["selected_service_candidates"], 1)
        self.assertEqual(report["released_nonqueueable_attention"], 1)

    def test_priority_prefers_low_friction_intelligence_service_when_other_scores_equal(self):
        quotecheck = alignment._rank_candidate({"score": 70}, "SRV-QUOTECHECK", 80)
        sourcing = alignment._rank_candidate({"score": 70}, "SRV-SOURCING-EXPRESS", 80)
        self.assertGreater(quotecheck, sourcing)

    def test_alignment_never_marks_contact_reply_or_revenue(self):
        state = {
            "service_revenue_opportunities": [{"id": "O1"}],
            "service_sales_pipeline": [{
                "id": "P1",
                "source": "verified_account_fit",
                "account_id": "A1",
                "email": "a1@example.com",
                "service_id": "SRV-SOURCING-EXPRESS",
                "qualification_score": 80,
                "stage": "qualified",
                "proactive_attention_active": False,
                "contact_truth": "not_contacted",
            }],
        }

        def advance(row, stage, reason):
            row["stage"] = stage

        fake_runtime = SimpleNamespace(
            SERVICE_LANE_SHARE_CAP=0.35,
            _advance=advance,
            _service_for=lambda account: {"id": "SRV-SOURCING-EXPRESS", "name": "Sourcing", "audience": "buyer"},
            _score=lambda account: 80.0,
        )
        strict = [{"account": {"id": "A1", "type": "buyer"}, "email": "a1@example.com", "score": 80}]
        alignment.align_strict_service_attention(state, strict, fake_runtime)
        row = state["service_sales_pipeline"][0]
        self.assertEqual(row["contact_truth"], "not_contacted")
        self.assertNotIn("replied_at", row)
        self.assertNotIn("revenue", row)


if __name__ == "__main__":
    unittest.main()
