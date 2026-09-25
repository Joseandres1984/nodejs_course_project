from __future__ import annotations

import unittest

import zero_instagram_thematic_prepare_v2 as thematic


class ZeroInstagramThematicPrepareV2Tests(unittest.TestCase):
    def test_travel_copy_is_shorter_and_human_gated(self):
        job = thematic.build_job("travel", "travel-v2-test")
        self.assertEqual(job["theme"], "travel")
        self.assertEqual(job["headline"], "El sector viajes también genera oportunidades comerciales.")
        self.assertTrue(job["approval_required"])
        self.assertFalse(job["paid_media"])
        self.assertEqual(job["status"], "awaiting_human_approval")
        self.assertGreaterEqual(job["editorial_qa_score"], 92)

    def test_renderer_passes_strict_pixel_safe_qa(self):
        job = thematic.build_job("travel", "travel-v2-render-test")
        path, qa = thematic.render_asset(job)
        self.assertTrue(path.exists())
        self.assertEqual(qa["status"], "PASS")
        self.assertEqual(qa["score"], 100)
        self.assertLessEqual(qa["headline_lines"], 3)
        self.assertLessEqual(qa["subtitle_lines"], 3)
        self.assertEqual(qa["overflow_blocks"], [])
        self.assertEqual((qa["asset_width"], qa["asset_height"]), (1080, 1350))
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def test_regeneration_rejects_previous_unpublished_theme_variant(self):
        old = thematic.build_job("travel", "old-travel")
        state = {
            "distribution_operator_jobs": [old],
            "instagram_publish_approvals": {},
        }
        result = thematic.prepare_job(state, "travel", "new-travel")
        self.assertEqual(result["status"], "prepared")
        self.assertIn(old["id"], result["superseded"])
        self.assertEqual(old["status"], "superseded_by_regeneration")
        self.assertEqual(state["instagram_publish_approvals"][old["id"]]["status"], "REJECTED")


if __name__ == "__main__":
    unittest.main()
