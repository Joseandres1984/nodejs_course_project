from __future__ import annotations

import unittest

import zero_instagram_thematic_prepare as thematic


class ZeroInstagramThematicPrepareTests(unittest.TestCase):
    def test_travel_job_passes_quality_and_remains_human_gated(self):
        job = thematic.build_job("travel", "travel-20260924-chat")
        self.assertEqual(job["channel"], "instagram")
        self.assertEqual(job["theme"], "travel")
        self.assertEqual(job["content_mode"], "thematic_on_demand")
        self.assertGreaterEqual(job["editorial_qa_score"], 90)
        self.assertTrue(job["approval_required"])
        self.assertFalse(job["paid_media"])
        self.assertEqual(job["status"], "awaiting_human_approval")
        self.assertIn("explicit_human_approval", job["authority"])

    def test_prepare_is_idempotent_for_same_request(self):
        state = {}
        first = thematic.prepare_job(state, "travel", "travel-20260924-chat")
        second = thematic.prepare_job(state, "travel", "travel-20260924-chat")
        self.assertEqual(first["status"], "prepared")
        self.assertEqual(second["status"], "already_prepared")
        jobs = state.get("distribution_operator_jobs", [])
        self.assertEqual(len(jobs), 1)
        self.assertEqual(first["job_id"], second["job_id"])

    def test_alias_turismo_maps_to_travel(self):
        job = thematic.build_job("turismo", "travel-alias-test")
        self.assertEqual(job["theme"], "travel")
        self.assertEqual(job["creative_label"], "VIAJES / TURISMO")


if __name__ == "__main__":
    unittest.main()
