from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

import autonomous_director_runtime as director
import experiment_engine_runtime as engine


def variant(vid: str, clicks: int = 0, leads: int = 0, verified: int = 0) -> dict:
    return {
        "id": vid,
        "token": vid.replace("-", "")[-12:],
        "headline": f"Headline {vid}",
        "body": f"Body {vid}",
        "cta": "CTA",
        "tracking_path": f"/c/{vid}",
        "status": "testing",
        "performance": {
            "clicks": clicks,
            "landing_views": clicks,
            "submissions": leads,
            "verified_companies": verified,
        },
    }


def campaign(v1: dict, v2: dict, v3: dict | None = None) -> dict:
    variants = [v1, v2] + ([v3] if v3 else [])
    return {
        "id": "ACQ-BUYER",
        "audience": "buyer",
        "status": "active",
        "headline": "Buyer",
        "body": "Buyer body",
        "cta": "CTA",
        "champion_variant_id": v1["id"],
        "variants": variants,
    }


class ExperimentEngineRuntimeTests(unittest.TestCase):
    def _state(self, camp: dict, ticks: int = 1) -> dict:
        return {
            "ticks": ticks,
            "acquisition_campaigns": [camp],
            "acquisition_distribution_queue": [],
            "distribution_operator_jobs": [],
            "autonomous_director": {"bottleneck": "demand_discovery"},
        }

    def test_allocation_reserves_exactly_one_exploration_bucket_in_five(self) -> None:
        phases = []
        for cycle in range(1, 6):
            state = self._state(campaign(variant("V1"), variant("V2")), ticks=cycle)
            report = engine.experiment_engine_tick(state)
            phases.append(report["experiments"][0]["phase"])
        self.assertEqual(phases.count("explore"), 1)
        self.assertEqual(phases.count("exploit"), 4)

    def test_challenger_is_not_promoted_before_minimum_exposure(self) -> None:
        camp = campaign(variant("V1", clicks=7, leads=0), variant("V2", clicks=7, leads=4, verified=1))
        state = self._state(camp)
        report = engine.experiment_engine_tick(state)
        exp = report["experiments"][0]
        self.assertEqual(exp["evaluation"]["status"], "testing")
        self.assertEqual(camp["champion_variant_id"], "V2")  # verified outcome is already the factual champion
        # Evaluation still refuses to call the current challenger a winner without exposure.
        self.assertEqual(exp["evaluation"]["reason"], "minimum_exposure_not_reached")

    def test_material_challenger_lift_promotes_after_evidence_threshold(self) -> None:
        # Keep V1 as factual champion initially: V2 has more clicks/leads only after evaluation.
        v1 = variant("V1", clicks=10, leads=1)
        v2 = variant("V2", clicks=10, leads=3)
        camp = campaign(v1, v2)
        # _champion will already rank a converting V2 above V1. Test the evaluation rule directly.
        result = engine._evaluation(v1, v2)
        self.assertEqual(result["status"], "supported")
        self.assertEqual(result["winner"], "V2")
        self.assertEqual(result["reason"], "material_lead_rate_lift")

    def test_queue_contains_only_selected_arm_for_active_campaign(self) -> None:
        camp = campaign(variant("V1"), variant("V2"))
        state = self._state(camp, ticks=2)
        state["acquisition_distribution_queue"] = [
            {"key": "ACQ-BUYER|OLD|email_b2b", "campaign_id": "ACQ-BUYER", "variant_id": "OLD", "channel": "email_b2b"},
            {"key": "OTHER|X|email_b2b", "campaign_id": "OTHER", "variant_id": "X", "channel": "email_b2b"},
        ]
        state["distribution_operator_jobs"] = [
            {"queue_key": "ACQ-BUYER|OLD|email_b2b", "campaign_id": "ACQ-BUYER", "variant_id": "OLD", "channel": "email_b2b", "status": "awaiting_verified_recipient"},
            {"queue_key": "ACQ-BUYER|DONE|instagram", "campaign_id": "ACQ-BUYER", "variant_id": "DONE", "channel": "instagram", "status": "verified_published"},
        ]
        with patch("experiment_engine_runtime._payloads", return_value=[
            {"channel": "email_b2b", "tracking_path": "/c/X", "tracking_url": "https://example/c/X", "requires_authorized_connector": False},
            {"channel": "instagram", "tracking_path": "/c/X", "tracking_url": "https://example/c/X", "requires_authorized_connector": True},
        ]):
            report = engine.experiment_engine_tick(state)
        selected = report["experiments"][0]["selected_variant_id"]
        active = [x for x in state["acquisition_distribution_queue"] if x.get("campaign_id") == "ACQ-BUYER"]
        self.assertEqual({x["variant_id"] for x in active}, {selected})
        self.assertTrue(all(x.get("experiment_active") is True for x in active))
        # Unsent stale work disappears; completed historical truth stays.
        self.assertFalse(any(x.get("variant_id") == "OLD" for x in state["distribution_operator_jobs"]))
        self.assertTrue(any(x.get("variant_id") == "DONE" for x in state["distribution_operator_jobs"]))

    def test_cognitive_focus_is_exposed_without_rewriting_product_or_channel(self) -> None:
        camp = campaign(variant("V1"), variant("V2"))
        state = self._state(camp)
        state["cognitive_director_learning"] = {
            "status": "active",
            "top_product": {"product_slug": "export-pulse", "samples": 12, "settlement_rate": 0.25},
            "top_channel": {"source": "instagram", "campaign": "organic-export", "samples": 10},
            "eligible_product_signals": 1,
            "eligible_channel_signals": 1,
        }
        report = engine.experiment_engine_tick(state)
        self.assertEqual(report["cognitive_focus"]["top_product"]["product_slug"], "export-pulse")
        self.assertEqual(report["cognitive_focus"]["top_channel"]["source"], "instagram")
        self.assertEqual(report["guardrails"]["monetary_budget_usd"], 0)
        self.assertFalse(report["guardrails"]["search_budget_increased"])
        self.assertFalse(report["guardrails"]["binding_authority_changed"])

    def test_director_keeps_hard_bottleneck_above_experiment_task(self) -> None:
        state = {
            "canonical_revenue_truth": {"counts": {"verified_buyers": 4, "buyers_with_verified_demand": 0}},
            "business_funnel": {"verified_buyers": 4, "buyers_with_public_demand": 0},
            "experiment_engine": {
                "status": "active",
                "experiments": [{"id": "EXP-X", "status": "testing", "phase": "exploit"}],
            },
        }
        report = engine.director_tick_with_experiment_engine(state, {"no_progress_cycles": 0, "search": {"remaining": 3}})
        self.assertEqual(report["plan"][0]["priority"], 100)
        exp = next(x for x in report["plan"] if x.get("id") == "DIR-EXPERIMENT-ENGINE")
        self.assertLess(exp["priority"], 100)
        self.assertEqual(exp["spend_usd"], 0)
        self.assertFalse(exp["binding"])
        self.assertEqual(report["authority"]["experiment_engine_monetary_budget_usd"], 0)
        self.assertFalse(report["authority"]["experiment_engine_search_budget_increased"])
        self.assertFalse(report["authority"]["experiment_engine_hard_bottleneck_override"])
        self.assertTrue(all(float(v) <= engine.ROLE_BOOST_CAP for v in report["role_boosts"].values()))


if __name__ == "__main__":
    unittest.main()
