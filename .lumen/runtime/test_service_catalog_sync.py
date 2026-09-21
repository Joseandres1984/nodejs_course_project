from __future__ import annotations

import re
import unittest
from pathlib import Path


ENTRY_RE = re.compile(
    r'\{\s*id:\s*"(?P<id>SRV-[^"]+)"\s*,\s*name:\s*"(?P<name>[^"]+)"\s*,\s*from_usd:\s*(?P<price>\d+)\s*,'
)


class ServiceCatalogSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[2]
        self.public_worker = (root / ".lumen" / "public-worker" / "worker.js").read_text(encoding="utf-8")
        self.dashboard_worker = (root / ".lumen" / "dashboard" / "worker.js").read_text(encoding="utf-8")

    @staticmethod
    def catalog(source: str) -> dict[str, tuple[str, int]]:
        return {
            match.group("id"): (match.group("name"), int(match.group("price")))
            for match in ENTRY_RE.finditer(source)
        }

    def test_dashboard_catalog_matches_public_commercial_catalog(self) -> None:
        public = self.catalog(self.public_worker)
        dashboard = self.catalog(self.dashboard_worker)
        self.assertEqual(6, len(public), "The public commercial catalog should expose six canonical services")
        self.assertEqual(public, dashboard, "Dashboard service names/prices drifted from the public commercial catalog")

    def test_catalog_price_floor_and_average_are_expected(self) -> None:
        public = self.catalog(self.public_worker)
        prices = [price for _, price in public.values()]
        self.assertEqual(59, min(prices))
        self.assertEqual(139, sum(prices) / len(prices))


if __name__ == "__main__":
    unittest.main()
