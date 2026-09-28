from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from PIL import Image

os.environ.setdefault("LUMEN_ZERO_COST_MODE", "true")
os.environ.setdefault("LIVE_OUTBOUND", "false")
os.environ.setdefault("LUMEN_INSTAGRAM_SEND_ENABLED", "false")

import zero_instagram_assets as assets


class ZeroInstagramAssetsPixelSafeTests(unittest.TestCase):
    def test_problem_headline_fits_without_cutting_words(self):
        headline = "UNA NECESIDAD CONCRETA MERECE PROVEEDORES COMPARABLES."
        job = {
            "id": "TEST-PIXEL-SAFE",
            "channel": "instagram",
            "headline": headline,
            "copy": (
                "¿Necesitás encontrar proveedores para una compra B2B concreta? "
                "LUMEN Sourcing Express transforma ese requerimiento en una búsqueda comercial ordenada: "
                "investiga alternativas, reúne información disponible y prepara una shortlist para evaluar próximos pasos."
            ),
        }

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "asset.jpg"
            report = assets._render(job, path)

            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["version"], assets.RENDERER_VERSION)
            self.assertLessEqual(report["headline_max_width"], assets.SAFE_WIDTH)
            self.assertEqual(report["overflow_blocks"], [])
            self.assertEqual(" ".join(report["headline_lines"]), headline.upper())
            self.assertLessEqual(len(report["headline_lines"]), 4)
            self.assertTrue(path.exists())

            with Image.open(path) as image:
                self.assertEqual(image.size, (1080, 1350))

    def test_renderer_rejects_an_unbreakable_word_instead_of_clipping_it(self):
        job = {
            "id": "TEST-UNBREAKABLE",
            "channel": "instagram",
            "headline": "X" * 90,
            "copy": "Texto breve de prueba.",
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "asset.jpg"
            with self.assertRaisesRegex(ValueError, "pixel_safe_text_does_not_fit"):
                assets._render(job, path)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
