from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

import agent_fleet
import elastic_agent_fleet
from canonical_revenue_truth_runtime import canonical_revenue_truth_tick

VERSION = "1.2-revenue-allocator-canonical"
_ORIGINAL_RUN = elastic_agent_fleet.run_elastic_agent_fleet_cycle

LANE_WEIGHTS = {
    "closing": {
        "buyer_hunter": 0.10, "supplier_hunter": 0.10, "market_scout": 0.04,
        "research_analyst": 0.14, "revops": 0.25, "negotiator": 0.16,
        "market_manager": 0.04, "risk_quality": 0.10, "finance": 0.07,
    },
    "quote_creation": {
        "buyer_hunter": 0.09, "supplier_hunter": 0.22, "market_scout": 0.05,
        "research_analyst": 0.12, "revops": 0.20, "negotiator": 0.17,
        "market_manager": 0.04, "risk_quality": 0.06, "finance": 0.05,
    },
    "opportunity_building": {
        "buyer_hunter": 0.20, "supplier_hunter": 0.17, "market_scout": 0.10,
        "research_analyst": 0.19, "revops": 0.16, "negotiator": 0.06,
        "market_manager": 0.04, "risk_quality": 0.05, "finance": 0.03,
    },
    "verification_contact": {
        "buyer_hunter": 0.21, "supplier_hunter": 0.10, "market_scout": 0.08,
        "research_analyst": 0.28, "revops": 0.14, "negotiator": 0.04,
        "market_manager": 0.05, "risk_quality": 0.07, "finance": 0.03,
    },
    "demand_discovery": {
        "buyer_hunter": 0.31, "supplier_hunter": 0.12, "market_scout": 0.20,
        "research_analyst": 0.14, "revops": 0.09, "negotiator": 0.03,
        "market_manager": 0.04, "risk_quality": 0.04, "finance": 0.03,
    },
}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _metrics(state: Dict[str, Any], truth: Dict[str, Any]) -> Dict[str, int]:
    accounts = list(state.get("candidate_accounts", []) or [])
    buyers = [x for x in accounts if x.get("type") == "buyer" and x.get("verified_company")]
    suppliers = [x for x in accounts if x.get("type") == "supplier" and x.get("verified_company")]
    external = state.get("external_market_readiness", {}) or {}
    reasons = external.get("ineligibility_reasons", {}) or {}
    counts = truth.get("counts", {}) or {}
    return {
        "verified_buyers": len(buyers),
        "buyers_with_demand": int(counts.get("buyers_with_verified_demand") or 0),
        "verified_suppliers": len(suppliers),
        "market_opportunities": int(counts.get("canonical_opportunities") or 0),
        "raw_market_opportunities": int(counts.get("raw_market_opportunities") or 0),
        "real_offers": int(counts.get("real_offers") or 0),
        "proposals": int(counts.get("proposals") or 0),
        "active_deals": int(counts.get("canonical_active_deals") or 0),
        "raw_deals": int(counts.get("raw_deals") or 0),
        "closing_eligible_deals": int(counts.get("closing_eligible_deals") or 0),
        "close_ready": int(counts.get("canonical_close_ready") or 0),
        "quarantined_deals": int(counts.get("quarantined_deals") or 0),
        "eligible_external_prospects": int(external.get("eligible_external_prospects") or 0),
        "company_not_verified": int(reasons.get("company_not_verified") or 0),
        "contact_not_verified": int(reasons.get("contact_not_verified") or 0),
    }


def _two_brain_weights(state: Dict[str, Any], lane: str) -> tuple[Dict[str, float], int]:
    weights = dict(LANE_WEIGHTS[lane])
    learning = state.get("commercial_learning_v2", {}) or {}
    two = learning.get("two_brain", {}) or {}
    explore_pct = int((two.get("exploration_brain", {}) or {}).get("attention_pct") or 25)
    explore_pct = max(15, min(35, explore_pct))
    target = explore_pct / 100.0
    exploration_roles = {"buyer_hunter", "market_scout"}
    current_explore = sum(weights.get(k, 0.0) for k in exploration_roles)
    current_execute = max(1e-9, 1.0 - current_explore)
    if current_explore > 0:
        for role in exploration_roles:
            weights[role] = weights[role] / current_explore * target
    for role in weights:
        if role not in exploration_roles:
            weights[role] = weights[role] / current_execute * (1.0 - target)
    total = sum(weights.values()) or 1.0
    return {k: v / total for k, v in weights.items()}, explore_pct


def build_revenue_allocation(state: Dict[str, Any]) -> Dict[str, Any]:
    truth = canonical_revenue_truth_tick(state)
    m = _metrics(state, truth)
    lane = str(truth.get("recommended_lane") or "demand_discovery")
    if lane not in LANE_WEIGHTS:
        lane = "demand_discovery"
    reason = str(truth.get("reason") or "Seguir el embudo canónico.")
    metric = str(truth.get("target_metric") or "buyers_with_verified_demand")

    # Anti-drift may challenge tactics inside the current canonical stage, but it cannot leapfrog
    # the evidence-backed revenue sequence (for example, force closing with zero canonical opportunities).
    learning = state.get("commercial_learning_v2", {}) or {}
    anti = learning.get("anti_drift", {}) or {}
    anti_note = None
    if anti.get("status") == "triggered":
        anti_note = str(anti.get("recommended_lane") or "")

    target_weights, explore_pct = _two_brain_weights(state, lane)
    return {
        "version": VERSION,
        "status": "active",
        "updated_at": utcnow(),
        "lane": lane,
        "reason": reason,
        "success_metric": metric,
        "target_weights": target_weights,
        "execution_attention_pct": 100 - explore_pct,
        "exploration_attention_pct": explore_pct,
        "anti_drift_applied": False,
        "anti_drift_suggestion": anti_note,
        "canonical_truth_version": truth.get("version"),
        "metrics": m,
        "authority": "attention_and_reversible_workforce_allocation_only",
    }


def _run_with_revenue_allocation(state: Dict[str, Any]) -> Dict[str, Any]:
    plan = build_revenue_allocation(state)
    original_weights = dict(elastic_agent_fleet.BASE_WEIGHTS)
    original_bottleneck = agent_fleet._bottleneck
    try:
        elastic_agent_fleet.BASE_WEIGHTS.clear()
        elastic_agent_fleet.BASE_WEIGHTS.update(plan["target_weights"])
        agent_fleet._bottleneck = lambda _state: str(plan["lane"])
        report = dict(_ORIGINAL_RUN(state) or {})
    finally:
        elastic_agent_fleet.BASE_WEIGHTS.clear()
        elastic_agent_fleet.BASE_WEIGHTS.update(original_weights)
        agent_fleet._bottleneck = original_bottleneck

    plan["actual_role_plan"] = dict(report.get("role_plan", {}) or {})
    plan["fleet_size"] = int(report.get("selected_fleet_size") or report.get("fleet_size") or 0)
    plan["assignments_completed"] = int(report.get("assignments_completed") or 0)
    state["revenue_allocator"] = plan
    report["revenue_allocator"] = {
        "version": VERSION,
        "lane": plan["lane"],
        "success_metric": plan["success_metric"],
        "reason": plan["reason"],
        "execution_attention_pct": plan["execution_attention_pct"],
        "exploration_attention_pct": plan["exploration_attention_pct"],
        "anti_drift_applied": plan["anti_drift_applied"],
        "anti_drift_suggestion": plan["anti_drift_suggestion"],
        "canonical_truth_version": plan["canonical_truth_version"],
        "metrics": plan["metrics"],
        "target_weights": plan["target_weights"],
        "actual_role_plan": plan["actual_role_plan"],
    }
    return report


elastic_agent_fleet.run_elastic_agent_fleet_cycle = _run_with_revenue_allocation
print({"revenue_allocator_runtime": {"version": VERSION, "status": "active", "canonical_truth": True}}, flush=True)
