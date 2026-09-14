from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

import agent_fleet
import elastic_agent_fleet

VERSION = "1.1-revenue-allocator"
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


def _active_deals(state: Dict[str, Any]) -> list[Dict[str, Any]]:
    terminal = {"closed", "lost", "cancelled", "canceled", "cerrado", "perdido", "cancelado"}
    return [x for x in state.get("deals", []) or [] if str(x.get("stage") or "").strip().lower() not in terminal]


def _metrics(state: Dict[str, Any]) -> Dict[str, int]:
    accounts = list(state.get("candidate_accounts", []) or [])
    buyers = [x for x in accounts if x.get("type") == "buyer" and x.get("verified_company")]
    suppliers = [x for x in accounts if x.get("type") == "supplier" and x.get("verified_company")]
    external = state.get("external_market_readiness", {}) or {}
    reasons = external.get("ineligibility_reasons", {}) or {}
    opportunities = list(state.get("market_opportunities", []) or [])
    offers = [x for x in state.get("offers", []) or [] if str(x.get("source") or "") != "demo/simulación"]
    proposals = list(state.get("proposals", []) or [])
    close_ready = sum(1 for x in state.get("deals", []) or [] if str(x.get("stage") or "").lower() in {"listo para cerrar", "close_ready", "autorizado para cierre"})
    return {
        "verified_buyers": len(buyers),
        "buyers_with_demand": sum(1 for x in buyers if x.get("demand_signal")),
        "verified_suppliers": len(suppliers),
        "market_opportunities": len(opportunities),
        "real_offers": len(offers),
        "proposals": len(proposals),
        "active_deals": len(_active_deals(state)),
        "close_ready": close_ready,
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
    m = _metrics(state)
    crd = state.get("continuous_revenue_drive", {}) or {}
    crd_lane = str(crd.get("primary_lane") or "").lower()

    if m["active_deals"] > 0 and m["close_ready"] == 0 and crd_lane == "closing":
        lane = "closing"
        reason = "Hay operaciones activas pero ninguna close-ready; proteger trabajo cercano a ingreso."
        metric = "close_ready > 0"
    elif m["market_opportunities"] > 0 and m["real_offers"] == 0:
        lane = "quote_creation"
        reason = "Hay oportunidades pero no hay ofertas reales; mover capacidad hacia proveedores, RevOps y negociación."
        metric = "real_offers > 0"
    elif m["buyers_with_demand"] > 0 and m["market_opportunities"] == 0:
        lane = "opportunity_building"
        reason = "Existe demanda verificada sin oportunidades materializadas; completar matching y evidencia."
        metric = "market_opportunities > 0"
    elif m["eligible_external_prospects"] == 0 and (m["company_not_verified"] + m["contact_not_verified"]) > 0:
        lane = "verification_contact"
        reason = "La salida comercial está frenada por identidad/contacto; concentrar verificación antes de más volumen."
        metric = "eligible_external_prospects > 0"
    else:
        lane = "demand_discovery"
        reason = "No hay una ruta de conversión suficientemente madura; ampliar demanda de calidad sin abandonar validación."
        metric = "buyers_with_demand > 0"

    learning = state.get("commercial_learning_v2", {}) or {}
    anti = learning.get("anti_drift", {}) or {}
    board = learning.get("review_board", {}) or {}
    recommended = str(anti.get("recommended_lane") or "")
    if anti.get("status") == "triggered" and board.get("status") == "AUTO_APPROVED_REVERSIBLE" and recommended in LANE_WEIGHTS:
        old_lane = lane
        lane = recommended
        reason = f"Anti-drift rotó de {old_lane} a {lane}: {anti.get('reason') or 'sin progreso verificable suficiente'}."
        metric = {
            "closing": "close_ready > 0", "quote_creation": "real_offers > 0",
            "opportunity_building": "market_opportunities > 0",
            "verification_contact": "eligible_external_prospects > 0",
            "demand_discovery": "buyers_with_demand > 0",
        }[lane]

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
        "anti_drift_applied": bool(anti.get("status") == "triggered" and lane == recommended),
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
        "target_weights": plan["target_weights"],
        "actual_role_plan": plan["actual_role_plan"],
    }
    return report


elastic_agent_fleet.run_elastic_agent_fleet_cycle = _run_with_revenue_allocation
print({"revenue_allocator_runtime": {"version": VERSION, "status": "active"}}, flush=True)
