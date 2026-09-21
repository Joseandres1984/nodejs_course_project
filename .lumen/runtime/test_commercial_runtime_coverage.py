from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path


PUBLIC_ID_RE = re.compile(r'id:\s*"(?P<id>SRV-[^"]+)"')


def python_catalog(path: Path, variable: str) -> list[dict]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == variable for t in node.targets):
            value = ast.literal_eval(node.value)
            if isinstance(value, list):
                return value
    raise AssertionError(f"{variable} not found in {path}")


class CommercialRuntimeCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[2]
        self.public_worker = root / ".lumen" / "public-worker" / "worker.js"
        self.service_runtime = root / ".lumen" / "runtime" / "service_revenue_runtime.py"
        self.intelligence_runtime = root / ".lumen" / "runtime" / "intelligence_revenue_runtime.py"

    def test_every_public_service_has_an_active_runtime_handler(self) -> None:
        public_ids = set(PUBLIC_ID_RE.findall(self.public_worker.read_text(encoding="utf-8")))
        service_catalog = python_catalog(self.service_runtime, "SERVICE_CATALOG")
        intelligence_catalog = python_catalog(self.intelligence_runtime, "INTELLIGENCE_CATALOG")

        active_service_ids = {
            str(item["id"])
            for item in service_catalog
            if isinstance(item, dict) and item.get("status") == "active"
        }
        active_intelligence_ids = {
            str(item["id"])
            for item in intelligence_catalog
            if isinstance(item, dict) and item.get("status") == "active"
        }
        handled = active_service_ids | active_intelligence_ids

        self.assertEqual(6, len(public_ids), "Public catalog service count changed unexpectedly")
        self.assertEqual(public_ids, handled, "A public paid service is missing an active runtime handler, or runtime exposes an unsold active service")

    def test_intelligence_catalog_is_installed_into_service_runtime(self) -> None:
        source = self.intelligence_runtime.read_text(encoding="utf-8")
        self.assertIn("service_revenue_runtime.SERVICE_CATALOG.append(dict(item))", source)
        self.assertIn("_install_catalog()", source)
        self.assertIn("service_revenue_runtime.service_revenue_tick = _service_tick_with_intelligence", source)


if __name__ == "__main__":
    unittest.main()
