from __future__ import annotations

import unittest
from unittest import mock

import microservice_factory_runtime as factory


class MicroserviceFactoryTests(unittest.TestCase):
    def test_report_qa_is_first_build_candidate_but_not_sellable(self) -> None:
        state = {
            "research_leads": [
                {
                    "title": "Necesitamos revisar informe comercial",
                    "details": "control de calidad y consistencia antes de enviar el reporte",
                }
            ]
        }
        report = factory.microservice_factory_tick(state)
        self.assertEqual(report["top_candidate_id"], "CAND-REPORT-QA")
        self.assertEqual(report["top_candidate_status"], "BUILD_READY")
        top = report["candidates"][0]
        self.assertFalse(top["publishable"])
        self.assertFalse(top["charge_enabled"])
        self.assertFalse(top["public_catalog_enabled"])
        self.assertIn("x402_checkout", top["missing_gates"])
        self.assertIn("fulfillment_adapter", top["missing_gates"])
        self.assertIn("e2e_tests", top["missing_gates"])

    def test_candidate_ids_cannot_be_confused_with_live_product_ids(self) -> None:
        self.assertTrue(all(row["id"].startswith("CAND-") for row in factory.CANDIDATE_LIBRARY))
        self.assertTrue(all(product.startswith("MP-") for product in factory.LIVE_MICROPRODUCTS))
        self.assertFalse(set(row["id"] for row in factory.CANDIDATE_LIBRARY) & set(factory.LIVE_MICROPRODUCTS))

    def test_publish_ready_requires_every_product_specific_gate(self) -> None:
        gates = {gate: True for gate in factory.RELEASE_GATES}
        self.assertEqual(factory._status(gates), "PUBLISH_READY")
        for gate in factory.RELEASE_GATES:
            partial = dict(gates)
            partial[gate] = False
            self.assertNotEqual(factory._status(partial), "PUBLISH_READY", gate)

    def test_factory_build_action_is_non_autonomous_code_work(self) -> None:
        state = {}
        report = factory.microservice_factory_tick(state)
        action = report["build_action"]
        self.assertTrue(action["queued"])
        queued = next(row for row in state["operating_action_queue"] if row["key"] == action["key"])
        self.assertFalse(queued["autonomous"])
        self.assertEqual(queued["payload"]["required_change_mode"], "pr_reviewed_code_change")
        self.assertEqual(queued["payload"]["release_rule"], "all_product_specific_gates_required_before_publication_or_charge")

    def test_factory_preserves_first_cash_acquisition_then_appends_learning(self) -> None:
        state = {}
        with mock.patch.object(
            factory,
            "_ORIGINAL_ACQUISITION_TICK",
            return_value={"status": "active", "acquisition_sprint": {"selected_product_slug": "quote-sanity"}},
        ) as original:
            report = factory.acquisition_tick_with_microservice_factory(state)
        original.assert_called_once_with(state)
        self.assertEqual(report["acquisition_sprint"]["selected_product_slug"], "quote-sanity")
        self.assertEqual(report["microservice_factory"]["top_candidate_id"], "CAND-REPORT-QA")
        self.assertEqual(report["microservice_factory"]["outgoing_spend_usd"], 0)

    def test_factory_never_changes_financial_or_binding_authority(self) -> None:
        report = factory.microservice_factory_tick({})
        governance = report["governance"]
        self.assertEqual(governance["outgoing_spend_usd"], 0)
        self.assertFalse(governance["autonomous_purchase"])
        self.assertFalse(governance["binding_authority_changed"])
        self.assertFalse(governance["production_code_self_modify"])
        self.assertFalse(governance["autonomous_deploy"])
        self.assertEqual(report["live_microproducts_count"], 6)
        self.assertEqual(report["publish_ready_count"], 0)


if __name__ == "__main__":
    unittest.main()
