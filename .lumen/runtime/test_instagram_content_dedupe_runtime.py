from __future__ import annotations

import unittest
from types import SimpleNamespace

import instagram_content_dedupe_runtime as dedupe


class InstagramContentDedupeTests(unittest.TestCase):
    def _state(self):
        old = {
            "id": "IGPRO-OLD",
            "channel": "instagram",
            "status": "verified_published",
            "headline": "Decisiones B2B con evidencia, no con ruido.",
            "caption": "En B2B, encontrar información es fácil. Separar una señal útil del ruido es lo difícil.",
        }
        return {
            "distribution_operator_jobs": [old],
            "distribution_receipts": [{"distribution_job_id": "IGPRO-OLD", "external_post_id": "1789"}],
            "instagram_publish_approvals": {},
            "instagram_editorial_history": [{"job_id": "IGPRO-OLD", "headline": old["headline"]}],
        }

    def test_exact_published_headline_is_duplicate(self):
        state = self._state()
        job = {
            "id": "IGPRO-NEW",
            "channel": "instagram",
            "headline": "Decisiones B2B con evidencia, no con ruido.",
            "caption": "Texto completamente distinto para aislar el chequeo de título.",
        }
        self.assertIn("duplicate_headline_exact", dedupe.duplicate_reasons(state, job))

    def test_near_duplicate_headline_is_duplicate(self):
        state = self._state()
        job = {
            "id": "IGPRO-NEW",
            "channel": "instagram",
            "headline": "Decisiones B2B con evidencia y no con ruido",
            "caption": "Texto completamente distinto para aislar el chequeo de título.",
        }
        self.assertIn("duplicate_headline_near", dedupe.duplicate_reasons(state, job))

    def test_diverse_headline_avoids_recent_title(self):
        state = self._state()
        title, similarity = dedupe.choose_diverse_headline(
            state,
            [
                "Decisiones B2B con evidencia, no con ruido.",
                "La información vale más cuando ayuda a decidir.",
            ],
        )
        self.assertEqual(title, "La información vale más cuando ayuda a decidir.")
        self.assertLess(similarity, 0.82)

    def test_remote_exact_caption_is_detected(self):
        caption = "Una publicación de LUMEN con el mismo texto."
        rows = [{"id": "1", "caption": caption}]
        self.assertEqual(
            dedupe.remote_caption_duplicate_reasons(caption, rows),
            ["remote_duplicate_caption_exact"],
        )

    def test_publish_wrapper_blocks_before_provider_call(self):
        state = self._state()
        new = {
            "id": "IGPRO-NEW",
            "channel": "instagram",
            "status": "approved_safe_autonomous",
            "headline": "Decisiones B2B con evidencia, no con ruido.",
            "caption": "Texto nuevo.",
        }
        state["distribution_operator_jobs"].append(new)
        state["instagram_publish_approvals"]["IGPRO-NEW"] = {"job_id": "IGPRO-NEW", "status": "APPROVED"}
        called = {"provider": 0}

        def original_attempt(_state, _job_id):
            called["provider"] += 1
            return {"ok": True, "status": "PUBLISHED"}

        def store(s):
            return s["instagram_publish_approvals"]

        def by_id(s, jid):
            return next((x for x in s["distribution_operator_jobs"] if x["id"] == jid), None)

        module = SimpleNamespace(
            attempt_publish_approved=original_attempt,
            _job_by_id=by_id,
            _approval_store=store,
            _append_audit=lambda s, row: s.setdefault("instagram_publish_audit", []).append(row),
            utcnow=lambda: "2026-09-25T00:00:00+00:00",
        )
        dedupe.patch_publish_control(module)
        result = module.attempt_publish_approved(state, "IGPRO-NEW")
        self.assertEqual(result["status"], "DUPLICATE_BLOCKED")
        self.assertEqual(called["provider"], 0)
        self.assertEqual(state["instagram_publish_approvals"]["IGPRO-NEW"]["status"], "DUPLICATE_BLOCKED")


if __name__ == "__main__":
    unittest.main()
