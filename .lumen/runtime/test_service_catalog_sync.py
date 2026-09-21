from __future__ import annotations

import re
import unittest
from pathlib import Path


CANONICAL_RE = re.compile(
    r'\{\s*id:\s*"(?P<id>SRV-[^"]+)"\s*,\s*name:\s*"(?P<name>[^"]+)"\s*,\s*from_usd:\s*(?P<price>\d+)\s*,'
)
DEPLOYED_RE = re.compile(
    r'\{\s*id:\s*"(?P<id>SRV-[^"]+)"\s*,\s*name:\s*"(?P<name>[^"]+)"\s*,\s*price:\s*(?P<price>\d+)\s*,'
)


class ServiceCatalogSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[2]
        self.public_worker = (root / ".lumen" / "public-worker" / "worker.js").read_text(encoding="utf-8")
        self.dashboard_worker = (root / ".lumen" / "dashboard" / "worker.js").read_text(encoding="utf-8")
        self.deployed_dashboard = (root / ".lumen" / "dashboard" / "refresh_worker.js").read_text(encoding="utf-8")
        self.a2a_worker = (root / ".lumen" / "a2a-worker" / "worker.js").read_text(encoding="utf-8")

    @staticmethod
    def canonical_catalog(source: str) -> dict[str, tuple[str, int]]:
        return {
            match.group("id"): (match.group("name"), int(match.group("price")))
            for match in CANONICAL_RE.finditer(source)
        }

    @staticmethod
    def deployed_prices(source: str) -> dict[str, int]:
        return {
            match.group("id"): int(match.group("price"))
            for match in DEPLOYED_RE.finditer(source)
        }

    def test_dashboard_catalog_matches_public_commercial_catalog(self) -> None:
        public = self.canonical_catalog(self.public_worker)
        dashboard = self.canonical_catalog(self.dashboard_worker)
        self.assertEqual(6, len(public), "The public commercial catalog should expose six canonical services")
        self.assertEqual(public, dashboard, "Dashboard service names/prices drifted from the public commercial catalog")

    def test_a2a_seller_catalog_prices_match_public_catalog(self) -> None:
        public = self.canonical_catalog(self.public_worker)
        a2a = self.canonical_catalog(self.a2a_worker)
        self.assertEqual(set(public), set(a2a), "A2A Seller Mode must expose exactly the six public paid services")
        self.assertEqual(
            {service_id: price for service_id, (_, price) in public.items()},
            {service_id: price for service_id, (_, price) in a2a.items()},
            "A2A Seller Mode prices drifted from the canonical public catalog",
        )

    def test_deployed_dashboard_prices_match_public_catalog(self) -> None:
        public = self.canonical_catalog(self.public_worker)
        deployed = self.deployed_prices(self.deployed_dashboard)
        expected = {service_id: price for service_id, (_, price) in public.items()}
        self.assertEqual(expected, deployed, "The Cloudflare dashboard entrypoint drifted from public service prices")

    def test_catalog_price_floor_and_average_are_expected(self) -> None:
        public = self.canonical_catalog(self.public_worker)
        prices = [price for _, price in public.values()]
        self.assertEqual(59, min(prices))
        self.assertEqual(139, sum(prices) / len(prices))


if __name__ == "__main__":
    unittest.main()
