from __future__ import annotations

import revenue_expansion_runtime as revenue


def test_catalog_contains_three_new_monetization_lanes():
    catalog = revenue.build_catalog()
    assert catalog["sourcing_success"]["id"] == "REV-SOURCING-SUCCESS"
    assert len(catalog["subscriptions"]) >= 4
    assert len(catalog["agent_apis"]) >= 5


def test_sourcing_success_never_claims_transaction_ready_without_verified_demand():
    state = {"operational_truth_auditor": {"counts": {"verified_buyers": 24, "buyers_with_verified_demand": 0}}}
    report = revenue.run_once(state)
    sourcing = [row for row in report["lane_priority"] if row["lane"] == "sourcing_success"][0]
    assert "do_not_sell_as_transaction_ready" in sourcing["reason"] or "prepare_success_fee_lane" in sourcing["reason"]
    assert report["counts"]["buyers_with_verified_demand"] == 0


def test_sourcing_success_becomes_top_priority_when_verified_demand_exists():
    state = {"operational_truth_auditor": {"counts": {"verified_buyers": 24, "buyers_with_verified_demand": 2}}}
    report = revenue.run_once(state)
    assert report["lane_priority"][0]["lane"] == "sourcing_success"
    assert report["lane_priority"][0]["priority"] == 100


def test_guardrails_remain_unchanged():
    report = revenue.run_once({})
    assert report["monetary_budget_usd"] == 0
    assert report["search_cap_changed"] is False
    assert report["outbound_caps_changed"] is False
    assert report["evidence_thresholds_changed"] is False
    assert report["autonomous_discount"] is False
    assert report["autonomous_contract"] is False
    assert report["autonomous_payment"] is False
    assert report["binding_authority_changed"] is False


def test_prices_are_fixed_launch_prices_and_nonbinding():
    catalog = revenue.build_catalog()
    assert catalog["price_changes_require_human_review"] is True
    assert all(row["price_usd_month"] > 0 for row in catalog["subscriptions"])
    assert all(row["unit_price_usd"] > 0 for row in catalog["agent_apis"])
