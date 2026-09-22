from __future__ import annotations

import unittest
from unittest.mock import patch

import autonomous_director_runtime as director


class AutonomousDirectorRuntimeTests(unittest.TestCase):
    def test_upstream_demand_gap_becomes_real_bottleneck(self) -> None:
        metrics = {
            "verified_buyers": 23,
            "buyers_with_verified_demand": 0,
            "eligible_external_prospects": 0,
            "canonical_opportunities": 0,
            "requirements_ready_for_rfq": 0,
            "canonical_real_offers": 0,
            "canonical_proposals": 0,
            "canonical_close_ready": 0,
            "realized_profit_usd": 0,
        }
        self.assertEqual(
            director._expanded_bottleneck(metrics),
            ("demand_discovery", "buyers_with_verified_demand"),
        )

    def test_escalation_has_three_anti_stall_levels(self) -> None:
        self.assertEqual(director._escalation(2)["mode"], "observe")
        self.assertEqual(director._escalation(3)["mode"], "rebalance")
        self.assertEqual(director._escalation(6)["mode"], "rotate_tactic")
        self.assertEqual(director._escalation(12)["mode"], "challenge_plan")

    def test_verified_progress_resets_stall_counter(self) -> None:
        op = {"metric_history": [], "no_progress_cycles": 0}
        base = {key: 0.0 for key in director.PROGRESS_KEYS}
        self.assertFalse(director._record_progress_v2(op, base, 1))
        self.assertFalse(director._record_progress_v2(op, dict(base), 2))
        self.assertEqual(op["no_progress_cycles"], 1)
        advanced = dict(base)
        advanced["buyers_with_verified_demand"] = 1
        self.assertTrue(director._record_progress_v2(op, advanced, 3))
        self.assertEqual(op["no_progress_cycles"], 0)

    def test_offline_prolonged_stall_opens_parallel_first_cash_lane(self) -> None:
        state = {
            "ticks": 88,
            "canonical_revenue_truth": {"counts": {"verified_buyers": 23, "buyers_with_verified_demand": 0}},
            "business_funnel": {"verified_buyers": 23, "buyers_with_public_demand": 0},
            "external_market_readiness": {"eligible_external_prospects": 0},
            "service_growth_pipeline": {"pipeline_total": 40, "replies": 0, "won": 0},
            "intelligence_revenue_engine": {"verified_candidates": 24, "replies": 0},
        }
        report = director.director_tick(state, {"no_progress_cycles": 12, "search": {"remaining": 0}})
        ids = {row["id"] for row in report["plan"]}
        self.assertIn("DIR-DEMAND-EVIDENCE", ids)
        self.assertIn("DIR-TACTIC-ROTATION", ids)
        self.assertIn("DIR-FIRST-CASH-PARALLEL", ids)
        self.assertIn("DIR-ZERO-QUOTA-MODE", ids)
        self.assertEqual(report["escalation"]["mode"], "challenge_plan")
        self.assertEqual(report["operating_mode"], "offline_existing_evidence")

    def test_persisted_service_truth_and_pacing_drive_real_first_cash_plan(self) -> None:
        state = {
            "ticks": 89,
            "canonical_revenue_truth": {"counts": {"verified_buyers": 23, "buyers_with_verified_demand": 0}},
            "business_funnel": {"verified_buyers": 23, "buyers_with_public_demand": 0},
            "external_market_readiness": {"eligible_external_prospects": 0},
            "service_revenue_runtime": {
                "pipeline_total": 40,
                "replies": 0,
                "inbound_service_leads": 0,
                "won": 0,
                "realized_service_revenue_usd": 0,
            },
            "service_revenue_opportunities": [{"id": f"SVC-{i}"} for i in range(40)],
            "continuous_revenue_drive": {
                "intelligence_revenue": {
                    "verified_product_fit_candidates": 24,
                    "replies": 0,
                    "realized_intelligence_revenue_usd": 0,
                }
            },
        }
        with patch("search_budget_governor.summary", return_value={"pacing": {"enabled": True, "available_now": 0}}):
            report = director.director_tick(state, {"no_progress_cycles": 78, "search": {"remaining": 39}})
        ids = {row["id"] for row in report["plan"]}
        self.assertIn("DIR-FIRST-CASH-PARALLEL", ids)
        self.assertIn("DIR-ZERO-QUOTA-MODE", ids)
        self.assertEqual(report["search_reported_remaining"], 39)
        self.assertEqual(report["search_available_now"], 0)
        self.assertEqual(report["operating_mode"], "offline_existing_evidence")
        metrics = director._expanded_metrics(state)
        self.assertEqual(metrics["service_replies"], 0)
        self.assertEqual(director._service_snapshot(state)["pipeline_total"], 40)
        self.assertEqual(director._intelligence_snapshot(state)["verified_candidates"], 24)

    def test_director_never_widens_money_or_binding_authority(self) -> None:
        state = {
            "canonical_revenue_truth": {"counts": {"verified_buyers": 2, "buyers_with_verified_demand": 0}},
            "business_funnel": {"verified_buyers": 2, "buyers_with_public_demand": 0},
        }
        report = director.director_tick(state, {"no_progress_cycles": 20, "search": {"remaining": 0}})
        authority = report["authority"]
        self.assertEqual(authority["monetary_budget_usd"], 0)
        self.assertFalse(authority["binding_authority_changed"])
        self.assertFalse(authority["production_self_modify"])
        self.assertTrue(authority["evidence_gates_preserved"])
        self.assertTrue(all(row["spend_usd"] == 0 and not row["binding"] for row in report["plan"]))

    def test_director_role_boost_is_bounded(self) -> None:
        core = {
            "peer_help": [],
            "research_missions": [],
            "director_context": {"role_boosts": {"revops": 9.0, "research_analyst": 0.08}},
        }
        attention = director._role_attention_with_director(core)
        self.assertLessEqual(attention["revops"], director.ROLE_BOOST_CAP)
        self.assertEqual(attention["research_analyst"], 0.08)


if __name__ == "__main__":
    unittest.main()
