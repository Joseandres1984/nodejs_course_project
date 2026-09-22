from __future__ import annotations

import unittest

import autonomous_director_runtime as director
import experiment_engine_runtime as engine


def variant(vid: str, clicks: int = 0, leads: int = 0, verified: int = 0, status: str = "testing") -> dict:
    rate = leads / max(1, clicks)
    return {
        "id": vid,
        "token": vid.replace("-", "")[-12:],
        "angle": vid.lower(),
        "headline": f"Headline {vid}",
        "body": f"Body {vid} with enough information for a governed B2B experiment.",
        "cta": "CTA",
        "tracking_path": f"/c/{vid}",
        "status": status,
        "performance": {
            "clicks": clicks,
            "landing_views": clicks,
            "submissions": leads,
            "verified_companies": verified,
            "click_to_lead_rate": rate,
            "score": verified * 100 + leads * 35 + rate * 100,
        },
    }


def campaign(cid: str = "ACQ-BUYER", audience: str = "buyer") -> dict:
    return {
        "id": cid,
        "audience": audience,
        "status": "active",
        "headline": "Campaign",
        "body": "Campaign body",
        "cta": "CTA",
        "landing_path": "/join/buyer",
        "champion_variant_id": f"{cid}-V1",
        "variants": [
            variant(f"{cid}-V1", clicks=12, leads=3, verified=1),
            variant(f"{cid}-V2", clicks=0, leads=0, verified=0),
            variant(f"{cid}-V3", clicks=4, leads=0, verified=0),
        ],
    }


def state_with_campaigns(ticks: int = 10) -> dict:
    return {
        "ticks": ticks,
        "acquisition_campaigns": [campaign()],
        "acquisition_distribution_queue": [],
        "autonomous_director": {"bottleneck": "demand_discovery", "target_metric": "buyers_with_verified_demand"},
        "cognitive_director_learning": {
            "status": "active",
            "top_product": {
                "product_slug": "export-pulse",
                "samples": 12,
                "settled_count": 3,
                "settlement_rate": 0.25,
                "realized_revenue_usd": 75,
                "evidence_class": "revenue_proven",
            },
            "top_channel": {
                "source": "instagram",
                "campaign": "organic-export",
                "samples": 10,
                "settled_count": 2,
                "realized_revenue_usd": 50,
                "evidence_class": "revenue_proven",
            },
        },
    }


class ExperimentEngineRuntimeTests(unittest.TestCase):
    def test_policy_is_exactly_four_exploit_then_one_explore(self) -> None:
        self.assertEqual([engine._mode_for_sequence(i) for i in range(1, 11)], [
            "exploit", "exploit", "exploit", "exploit", "explore",
            "exploit", "exploit", "exploit", "exploit", "explore",
        ])

    def test_exploit_uses_commercial_champion_not_raw_click_volume(self) -> None:
        state = state_with_campaigns()
        state["acquisition_campaigns"][0]["variants"].append(
            variant("ACQ-BUYER-V4", clicks=100, leads=0, verified=0)
        )
        chosen = engine._select_candidate(state, "exploit", "demand_discovery")
        self.assertEqual(chosen["variant_id"], "ACQ-BUYER-V1")
        self.assertEqual(chosen["leads"], 3)

    def test_explore_uses_least_exposed_non_champion(self) -> None:
        state = state_with_campaigns()
        chosen = engine._select_candidate(state, "explore", "demand_discovery")
        self.assertEqual(chosen["variant_id"], "ACQ-BUYER-V2")
        self.assertFalse(chosen["is_champion"])

    def test_tick_enqueues_only_governed_zero_cost_email_canary(self) -> None:
        state = state_with_campaigns()
        report = engine.experiment_engine_tick(state)
        exp = report["current_experiment"]
        self.assertEqual(exp["mode"], "exploit")
        self.assertEqual(exp["product_winner"], "export-pulse")
        self.assertEqual(exp["channel_winner"], "instagram")
        self.assertEqual(exp["verified_settlements"], 3)
        self.assertEqual(exp["verified_revenue_usd"], 75)
        self.assertTrue(exp["dispatch"]["queued"])
        self.assertEqual(exp["dispatch"]["channel"], "email_b2b")
        queued = [x for x in state["acquisition_distribution_queue"] if str(x.get("key") or "").startswith("EXPERIMENT|")]
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0]["channel"], "email_b2b")
        self.assertFalse(queued[0]["payload"].get("requires_human_budget_approval", False))
        self.assertEqual(report["guardrails"]["monetary_budget_usd"], 0)
        self.assertFalse(report["guardrails"]["paid_media_authority_changed"])

    def test_fifth_tick_explores_without_overwriting_champion(self) -> None:
        state = state_with_campaigns()
        state["experiment_engine"] = {
            "decision_sequence": 4,
            "exploit_decisions": 4,
            "explore_decisions": 0,
            "history": [],
        }
        original_champion = state["acquisition_campaigns"][0]["champion_variant_id"]
        report = engine.experiment_engine_tick(state)
        exp = report["current_experiment"]
        self.assertEqual(exp["mode"], "explore")
        self.assertEqual(exp["variant_id"], "ACQ-BUYER-V2")
        self.assertEqual(state["acquisition_campaigns"][0]["champion_variant_id"], original_champion)
        self.assertEqual(report["explore_decisions"], 1)

    def test_director_preserves_hard_bottleneck_and_zero_authority_expansion(self) -> None:
        state = state_with_campaigns()
        engine.experiment_engine_tick(state)
        state["canonical_revenue_truth"] = {"counts": {"verified_buyers": 4, "buyers_with_verified_demand": 0}}
        state["business_funnel"] = {"verified_buyers": 4, "buyers_with_public_demand": 0}
        report = engine.director_tick_with_experiments(state, {"no_progress_cycles": 0, "search": {"remaining": 3}})
        self.assertEqual(report["plan"][0]["priority"], 100)
        exp_task = next(x for x in report["plan"] if x.get("id") == "DIR-EXPERIMENT-ENGINE")
        self.assertLess(exp_task["priority"], 100)
        self.assertEqual(exp_task["spend_usd"], 0)
        self.assertFalse(exp_task["binding"])
        self.assertEqual(report["authority"]["experiment_engine_monetary_budget_usd"], 0)
        self.assertFalse(report["authority"]["experiment_engine_search_budget_increased"])
        self.assertFalse(report["authority"]["experiment_engine_hard_bottleneck_override"])
        self.assertTrue(all(float(v) <= director.ROLE_BOOST_CAP for v in report["role_boosts"].values()))

    def test_acquisition_wrapper_runs_experiment_after_performance_refresh(self) -> None:
        state = {"ticks": 1}
        report = engine.acquisition_tick_with_experiments(state)
        self.assertGreaterEqual(report.get("campaigns_active", 0), 1)
        self.assertEqual((report.get("experiment_engine") or {}).get("status"), "active")
        self.assertIsNotNone((state.get("experiment_engine") or {}).get("current_experiment"))


if __name__ == "__main__":
    unittest.main()
