from __future__ import annotations

import re
import unittest
from pathlib import Path


PRODUCT_RE = re.compile(
    r'\{\s*id:"(?P<id>MP-[^"]+)",\s*name:"(?P<name>[^"]+)",\s*price_usd:(?P<price>\d+),\s*service_id:"(?P<service>SRV-[^"]+)"'
)
PLAN_RE = re.compile(
    r'\{\s*id:"(?P<id>PLAN-[^"]+)",\s*name:"(?P<name>[^"]+)",\s*price_usd:(?P<price>\d+),\s*interval:"month",\s*service_id:"(?P<service>SRV-[^"]+)"'
)
SERVICE_RE = re.compile(r'\{\s*id:"(?P<id>SRV-[^"]+)",\s*name:"[^"]+",\s*from_usd:(?P<price>\d+)')


class A2AMachineStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[2]
        self.worker = (root / ".lumen" / "a2a-worker" / "worker.js").read_text(encoding="utf-8")
        self.bridge = (root / ".lumen" / "runtime" / "zero_a2a_inbound_bridge_runtime.py").read_text(encoding="utf-8")
        self.accelerator = (root / ".lumen" / "runtime" / "agent_network_accelerator_runtime.py").read_text(encoding="utf-8")

    def test_machine_store_has_six_low_cost_products(self) -> None:
        products = [m.groupdict() for m in PRODUCT_RE.finditer(self.worker)]
        self.assertEqual(6, len(products))
        prices = [int(x["price"]) for x in products]
        self.assertEqual(5, min(prices))
        self.assertEqual(25, max(prices))
        self.assertEqual(len(products), len({x["id"] for x in products}))

    def test_recurring_store_has_four_monthly_plans(self) -> None:
        plans = [m.groupdict() for m in PLAN_RE.finditer(self.worker)]
        self.assertEqual(4, len(plans))
        self.assertEqual([29, 39, 59, 79], sorted(int(x["price"]) for x in plans))

    def test_every_machine_offer_maps_to_a_sold_service(self) -> None:
        services = {m.group("id") for m in SERVICE_RE.finditer(self.worker)}
        mapped = {m.group("service") for m in PRODUCT_RE.finditer(self.worker)} | {m.group("service") for m in PLAN_RE.finditer(self.worker)}
        self.assertEqual(6, len(services))
        self.assertTrue(mapped <= services)
        for service_id in mapped:
            self.assertIn(f'"{service_id}"', self.bridge)

    def test_store_exposes_quote_order_and_payment_status_protocol(self) -> None:
        for token in (
            '"/machine/catalog"',
            '"/payments/status"',
            '"QuoteMachineProduct"',
            '"QuoteRecurringPlan"',
            '"lumen_machine_orders"',
            '"receive_revenue_only"',
        ):
            self.assertIn(token, self.worker)

    def test_a2a_is_seller_autonomous_but_cannot_spend(self) -> None:
        self.assertIn('_base._handshake = _seller_handshake', self.accelerator)
        self.assertIn('autonomous_nonbinding_offer', self.accelerator)
        self.assertIn('"autonomous_purchase": False', self.accelerator)
        self.assertIn('"autonomous_payment": False', self.accelerator)
        self.assertIn('MACHINE_CATALOG_URL', self.accelerator)

    def test_a2a_orders_enter_service_crm(self) -> None:
        self.assertIn('def _ensure_service_inquiry', self.bridge)
        self.assertIn('"source": "a2a_machine_store"', self.bridge)
        self.assertIn('"quoted_amount_usd"', self.bridge)
        self.assertIn('"charge_created": False', self.bridge)


if __name__ == "__main__":
    unittest.main()
