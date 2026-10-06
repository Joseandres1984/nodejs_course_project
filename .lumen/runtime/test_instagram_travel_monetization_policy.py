from __future__ import annotations

import copy
import unittest

import zero_instagram_control_bridge_runtime as bridge
import zero_instagram_travel_acquisition_prepare_v1 as acquisition
import instagram_content_dedupe_runtime as dedupe


def safe_job(job_id="IGTRAVEL-TEST-A"):
    return {
        "id": job_id,
        "campaign_id": "IG-TRAVEL-FULL-TRIP-ACQUISITION-V1",
        "variant_id": "IGTRAVEL-GRU-FULLTRIP-V1",
        "audience": "travel_consumers",
        "channel": "instagram",
        "status": "awaiting_human_approval",
        "copy": (
            "¿Viajás a São Paulo? Armá tu viaje. "
            "Transparencia: LUMEN puede utilizar enlaces de afiliado y recibir una comisión "
            "si reservás con un partner, sin costo adicional para vos."
        ),
        "caption": (
            "¿Viajás a São Paulo? Armá tu viaje. "
            "Transparencia: LUMEN puede utilizar enlaces de afiliado y recibir una comisión "
            "si reservás con un partner, sin costo adicional para vos."
        ),
        "content_mode": "travel_affiliate_acquisition",
        "affiliate_disclosure": True,
        "paid_media": False,
        "requires_budget_approval": False,
        "booking_authority": False,
        "payment_authority": False,
        "autonomous_spend_usd": 0,
        "visual_qa_score": 100,
        "tracking_url": "https://lumen-zero-public.lumen-b2b.workers.dev/travel/package?destination=GRU&source=instagram",
        "creative_asset_url": "",
    }


class TravelMonetizationPolicyTests(unittest.TestCase):
    def setUp(self):
        self.original_state = bridge.lumen_app.STATE
        self.original_save_state = bridge.lumen_app.save_state
        bridge.lumen_app.STATE = {
            "instagram_publish_approvals": {},
            "instagram_publish_audit": [],
            "distribution_receipts": [],
        }
        bridge.lumen_app.save_state = lambda: True

    def tearDown(self):
        bridge.lumen_app.STATE = self.original_state
        bridge.lumen_app.save_state = self.original_save_state

    def test_safe_owned_travel_affiliate_can_be_policy_approved(self):
        job = safe_job()
        result = bridge.authorize_safe_travel_affiliate_job(job)
        self.assertTrue(result["approved"])
        self.assertEqual(result["status"], "APPROVED")
        approval = bridge.lumen_app.STATE["instagram_publish_approvals"][job["id"]]
        self.assertEqual(approval["monetary_budget_usd"], 0)
        self.assertFalse(approval["binding_authority_changed"])
        self.assertEqual(approval["authority"], bridge.SAFE_TRAVEL_AUTHORITY)

    def test_paid_or_booking_authority_is_blocked(self):
        paid = safe_job("IGTRAVEL-PAID")
        paid["autonomous_spend_usd"] = 1
        self.assertFalse(bridge.authorize_safe_travel_affiliate_job(paid)["approved"])

        booking = safe_job("IGTRAVEL-BOOKING")
        booking["booking_authority"] = True
        self.assertFalse(bridge.authorize_safe_travel_affiliate_job(booking)["approved"])

    def test_explicit_human_rejection_wins(self):
        job = safe_job("IGTRAVEL-REJECTED")
        bridge.lumen_app.STATE["instagram_publish_approvals"][job["id"]] = {
            "job_id": job["id"],
            "status": "REJECTED",
            "content_fingerprint": bridge._fingerprint(job),
        }
        result = bridge.authorize_safe_travel_affiliate_job(job)
        self.assertFalse(result["approved"])
        self.assertEqual(result["reason"], "explicit_human_rejection_preserved")

    def test_daily_policy_limit_is_one(self):
        first = safe_job("IGTRAVEL-FIRST")
        second = safe_job("IGTRAVEL-SECOND")
        self.assertTrue(bridge.authorize_safe_travel_affiliate_job(first)["approved"])
        result = bridge.authorize_safe_travel_affiliate_job(second)
        self.assertFalse(result["approved"])
        self.assertEqual(result["reason"], "daily_policy_cap_reached")


    def test_duplicate_block_releases_daily_slot_for_recovery(self):
        first = safe_job("IGTRAVEL-DUPLICATE")
        second = safe_job("IGTRAVEL-RECOVERY")
        self.assertTrue(bridge.authorize_safe_travel_affiliate_job(first)["approved"])
        bridge.lumen_app.STATE["instagram_publish_approvals"][first["id"]]["status"] = "DUPLICATE_BLOCKED_REMOTE"
        self.assertTrue(bridge.authorize_safe_travel_affiliate_job(second)["approved"])

    def test_creative_recovery_variants_are_materially_distinct(self):
        destination = {"name": "São Paulo", "code": "GRU"}
        jobs = [acquisition.build_job(destination, "test", creative_variant=i) for i in range(3)]
        for left in range(len(jobs)):
            for right in range(left + 1, len(jobs)):
                similarity = dedupe.text_similarity(jobs[left]["caption"], jobs[right]["caption"])
                self.assertLess(similarity, dedupe.CAPTION_SIMILARITY_LIMIT)
        self.assertEqual(len({job["id"] for job in jobs}), 3)


if __name__ == "__main__":
    unittest.main()
