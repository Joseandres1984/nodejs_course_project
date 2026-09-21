from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

import agent_fleet
import elastic_agent_fleet
from canonical_revenue_truth_runtime import canonical_revenue_truth_tick

VERSION = "1.5-revenue-allocator-upstream-demand-guard"
_ORIGINAL_RUN = elastic_agent_fleet.run_elastic_agent_fleet_cycle

LANE_WEIGHTS = {
    "closing": {"buyer_hunter":0.10,"supplier_hunter":0.10,"market_scout":0.04,"research_analyst":0.14,"revops":0.25,"negotiator":0.16,"market_manager":0.04,"risk_quality":0.10,"finance":0.07},
    "quote_creation": {"buyer_hunter":0.09,"supplier_hunter":0.22,"market_scout":0.05,"research_analyst":0.12,"revops":0.20,"negotiator":0.17,"market_manager":0.04,"risk_quality":0.06,"finance":0.05},
    "opportunity_building": {"buyer_hunter":0.20,"supplier_hunter":0.17,"market_scout":0.10,"research_analyst":0.19,"revops":0.16,"negotiator":0.06,"market_manager":0.04,"risk_quality":0.05,"finance":0.03},
    "verification_contact": {"buyer_hunter":0.21,"supplier_hunter":0.10,"market_scout":0.08,"research_analyst":0.28,"revops":0.14,"negotiator":0.04,"market_manager":0.05,"risk_quality":0.07,"finance":0.03},
    "demand_discovery": {"buyer_hunter":0.31,"supplier_hunter":0.12,"market_scout":0.20,"research_analyst":0.14,"revops":0.09,"negotiator":0.03,"market_manager":0.04,"risk_quality":0.04,"finance":0.03},
}

LANE_SUCCESS_METRICS = {
    "closing": "canonical_close_ready",
    "quote_creation": "canonical_real_offers",
    "opportunity_building": "canonical_opportunities",
    "verification_contact": "eligible_external_prospects",
    "demand_discovery": "buyers_with_verified_demand",
}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _metrics(state: Dict[str, Any], truth: Dict[str, Any]) -> Dict[str, int]:
    accounts = list(state.get("candidate_accounts", []) or [])
    buyers = [x for x in accounts if x.get("type") == "buyer" and x.get("verified_company")]
    suppliers = [x for x in accounts if x.get("type") == "supplier" and x.get("verified_company")]
    ext = state.get("external_market_readiness", {}) or {}
    reasons = ext.get("ineligibility_reasons", {}) or {}
    counts = truth.get("counts", {}) or {}
    return {
        "verified_buyers": len(buyers),
        "buyers_with_demand": int(counts.get("buyers_with_verified_demand") or 0),
        "verified_suppliers": len(suppliers),
        "market_opportunities": int(counts.get("canonical_opportunities") or 0),
        "raw_market_opportunities": int(counts.get("raw_market_opportunities") or 0),
        "real_offers": int(counts.get("canonical_real_offers") or 0),
        "proposals": int(counts.get("canonical_proposals") or 0),
        "active_deals": int(counts.get("canonical_active_deals") or 0),
        "raw_deals": int(counts.get("raw_deals") or 0),
        "closing_eligible_deals": int(counts.get("closing_eligible_deals") or 0),
        "close_ready": int(counts.get("canonical_close_ready") or 0),
        "quarantined_deals": int(counts.get("quarantined_deals") or 0),
        "eligible_external_prospects": int(ext.get("eligible_external_prospects") or 0),
        "company_not_verified": int(reasons.get("company_not_verified") or 0),
        "contact_not_verified": int(reasons.get("contact_not_verified") or 0),
    }


def _two_brain_weights(state: Dict[str, Any], lane: str) -> tuple[Dict[str, float], int]:
    weights = dict(LANE_WEIGHTS[lane])
    two = (state.get("commercial_learning_v2", {}) or {}).get("two_brain", {}) or {}
    explore = int((two.get("exploration_brain", {}) or {}).get("attention_pct") or 25)
    explore = max(15, min(35, explore))
    target = explore / 100.0
    exploration_roles = {"buyer_hunter", "market_scout"}
    current_exploration = sum(weights.get(k, 0.0) for k in exploration_roles)
    current_execution = max(1e-9, 1.0 - current_exploration)
    if current_exploration > 0:
        for role in exploration_roles:
            weights[role] = weights[role] / current_exploration * target
    for role in weights:
        if role not in exploration_roles:
            weights[role] = weights[role] / current_execution * (1.0 - target)
    total = sum(weights.values()) or 1.0
    return {k: v / total for k, v in weights.items()}, explore


def _resolve_lane_with_anti_drift(state: Dict[str, Any], truth: Dict[str, Any], metrics: Dict[str, int]) -> Dict[str, Any]:
    base_lane = str(truth.get("recommended_lane") or "demand_discovery")
    if base_lane not in LANE_WEIGHTS:
        base_lane = "demand_discovery"
    lane = base_lane
    metric = str(truth.get("target_metric") or LANE_SUCCESS_METRICS[base_lane])
    reason = str(truth.get("reason") or "Seguir el embudo canónico.")
    anti = (state.get("commercial_learning_v2", {}) or {}).get("anti_drift", {}) or {}
    triggered = anti.get("status") == "triggered"
    suggestion = str(anti.get("recommended_lane") or "").strip()
    applied = False
    guard_reason = None

    if triggered and suggestion in LANE_WEIGHTS and suggestion != base_lane:
        if base_lane == "closing" and metrics.get("closing_eligible_deals", 0) > 0:
            guard_reason = "canonical_closing_path_protected"
        elif base_lane == "demand_discovery" and metrics.get("verified_buyers", 0) > 0 and metrics.get("buyers_with_demand", 0) == 0:
            # Demand is an upstream truth gate: without one verified need there can be no canonical
            # opportunity/deal. Anti-drift may vary tactics inside the lane, but cannot rotate away
            # from the missing prerequisite itself.
            guard_reason = "upstream_verified_demand_gap_protected"
        else:
            lane = suggestion
            metric = LANE_SUCCESS_METRICS[lane]
            applied = True
            reason = f"{reason} Anti-drift aplicado: no hubo movimiento comercial verificado; rotar temporalmente a {lane} para desafiar la estrategia de forma reversible."
    elif triggered:
        guard_reason = "anti_drift_suggestion_invalid_or_same_lane"

    return {"base_lane":base_lane,"lane":lane,"success_metric":metric,"reason":reason,"anti_drift_applied":applied,"anti_drift_suggestion":suggestion or None,"anti_drift_guard_reason":guard_reason}


def build_revenue_allocation(state: Dict[str, Any]) -> Dict[str, Any]:
    truth = canonical_revenue_truth_tick(state)
    metrics = _metrics(state, truth)
    resolved = _resolve_lane_with_anti_drift(state, truth, metrics)
    lane = str(resolved["lane"])
    target_weights, explore = _two_brain_weights(state, lane)
    return {"version":VERSION,"status":"active","updated_at":utcnow(),"lane":lane,"base_lane":resolved["base_lane"],"reason":resolved["reason"],"success_metric":resolved["success_metric"],"target_weights":target_weights,"execution_attention_pct":100-explore,"exploration_attention_pct":explore,"anti_drift_applied":resolved["anti_drift_applied"],"anti_drift_suggestion":resolved["anti_drift_suggestion"],"anti_drift_guard_reason":resolved["anti_drift_guard_reason"],"canonical_truth_version":truth.get("version"),"metrics":metrics,"authority":"attention_and_reversible_workforce_allocation_only"}


def _run_with_revenue_allocation(state: Dict[str, Any]) -> Dict[str, Any]:
    plan = build_revenue_allocation(state)
    original_weights = dict(elastic_agent_fleet.BASE_WEIGHTS)
    original_bottleneck = agent_fleet._bottleneck
    try:
        elastic_agent_fleet.BASE_WEIGHTS.clear(); elastic_agent_fleet.BASE_WEIGHTS.update(plan["target_weights"])
        agent_fleet._bottleneck = lambda _state: str(plan["lane"])
        report = dict(_ORIGINAL_RUN(state) or {})
    finally:
        elastic_agent_fleet.BASE_WEIGHTS.clear(); elastic_agent_fleet.BASE_WEIGHTS.update(original_weights)
        agent_fleet._bottleneck = original_bottleneck
    plan["actual_role_plan"] = dict(report.get("role_plan", {}) or {})
    plan["fleet_size"] = int(report.get("selected_fleet_size") or report.get("fleet_size") or 0)
    plan["assignments_completed"] = int(report.get("assignments_completed") or 0)
    state["revenue_allocator"] = plan
    report["revenue_allocator"] = {key:plan.get(key) for key in ("version","lane","base_lane","success_metric","reason","execution_attention_pct","exploration_attention_pct","anti_drift_applied","anti_drift_suggestion","anti_drift_guard_reason","canonical_truth_version","metrics","target_weights","actual_role_plan")}
    return report

elastic_agent_fleet.run_elastic_agent_fleet_cycle = _run_with_revenue_allocation
print({"revenue_allocator_runtime":{"version":VERSION,"status":"active","canonical_truth":True,"guarded_anti_drift":True,"upstream_demand_gap_protected":True}}, flush=True)