from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

import demand_hunter
import demand_hunter_runtime
import demand_intelligence
import search_budget_governor as governor
import scout_connector
from app import STATE, load_state

VERSION = "1.1-adaptive-search-budget"
_ORIGINAL_SUMMARY = governor.summary


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _signals(state: Dict[str, Any]) -> Dict[str, Any]:
    accounts = list(state.get("candidate_accounts", []) or [])
    buyers = [x for x in accounts if x.get("type") == "buyer" and x.get("verified_company")]
    external = state.get("external_market_readiness", {}) or {}
    reasons = external.get("ineligibility_reasons", {}) or {}
    crd = state.get("continuous_revenue_drive", {}) or {}
    return {
        "verified_buyers": len(buyers),
        "buyers_with_demand": sum(1 for x in buyers if x.get("demand_signal")),
        "market_opportunities": len(state.get("market_opportunities", []) or []),
        "active_deals": sum(1 for x in state.get("deals", []) or [] if str(x.get("stage") or "").lower() not in {"closed", "lost", "cancelled", "canceled", "cerrado"}),
        "close_ready": sum(1 for x in state.get("deals", []) or [] if str(x.get("stage") or "").lower() in {"listo para cerrar", "close_ready", "autorizado para cierre"}),
        "eligible_external_prospects": _i(external.get("eligible_external_prospects")),
        "verification_backlog": _i(reasons.get("company_not_verified")) + _i(reasons.get("contact_not_verified")),
        "crd_lane": str(crd.get("primary_lane") or "").lower(),
        "unlinked_demand": len(state.get("unlinked_demand_signals", []) or []),
    }


def build_budget_plan(state: Dict[str, Any]) -> Dict[str, Any]:
    total = int(governor.TOTAL_DAILY_CAP)
    s = _signals(state)

    # Reallocate the existing envelope only. Never increase the provider/cost cap here.
    if s["verified_buyers"] == 0 or s["buyers_with_demand"] == 0:
        demand_ratio = 0.65
        reason = "Falta demanda/comprador verificado; proteger más capacidad para demanda de alta intención."
    elif s["eligible_external_prospects"] == 0 and s["verification_backlog"] >= 8:
        demand_ratio = 0.35
        reason = "Hay demanda pero la salida está trabada por verificación/contacto; liberar más capacidad general para resolver identidad y canales."
    elif s["market_opportunities"] == 0 and s["buyers_with_demand"] > 0:
        demand_ratio = 0.45
        reason = "Hay compradores con demanda pero faltan oportunidades materializadas; balancear confirmación de demanda y matching."
    elif s["active_deals"] > 0 and s["close_ready"] == 0 and s["crd_lane"] == "closing":
        demand_ratio = 0.30
        reason = "CRD está en closing; mantener reserva de demanda pero evitar que descubrimiento consuma la mayoría del presupuesto."
    else:
        demand_ratio = 0.50
        reason = "Embudo sin desequilibrio dominante; reparto equilibrado entre demanda y búsqueda general."

    min_lane = max(2, int(round(total * 0.15)))
    demand = max(min_lane, min(total - min_lane, int(round(total * demand_ratio))))
    general = total - demand
    return {
        "version": VERSION,
        "status": "active",
        "updated_at": utcnow(),
        "total_daily_cap": total,
        "general_pool_daily": general,
        "demand_reserved_daily": demand,
        "demand_ratio": round(demand / max(1, total), 3),
        "reason": reason,
        "signals": s,
        "safety": {
            "increases_total_cap": False,
            "intraday_reallocation_respects_actual_usage": True,
            "provider_rate_and_cost_envelope_preserved": True,
            "dependent_runtime_caps_synchronized": True,
            "legacy_overage_reconciliation_reopens_budget": False,
        },
    }


def apply_adaptive_search_budget(state: Dict[str, Any]) -> Dict[str, Any]:
    plan = build_budget_plan(state)
    demand_cap = int(plan["demand_reserved_daily"])
    general_cap = int(plan["general_pool_daily"])

    governor.DEMAND_RESERVED = demand_cap
    governor.GENERAL_POOL_CAP = general_cap
    scout_connector.DAILY_QUERY_BUDGET = general_cap

    # These modules import/copy the lane cap during startup. Keep their runtime values synchronized
    # whenever the adaptive split changes, otherwise an old 6/18 split can survive beside a new 11/13
    # split and make the counters drift even though the provider-level hard cap is correct.
    demand_hunter.DAILY_QUERY_BUDGET = demand_cap
    demand_intelligence.DAILY_QUERY_BUDGET = demand_cap
    demand_hunter_runtime.DAILY_CAP = demand_cap

    # Repair only same-day legacy counters that were already above the provider envelope. The repair
    # keeps the day exhausted and records the original values for audit, so it never creates new spend.
    reconciliation = governor.reconcile_legacy_counters(state)
    plan["reconciliation"] = reconciliation

    state["adaptive_search_budget"] = plan
    return plan


def adaptive_summary(state: Dict[str, Any]) -> Dict[str, Any]:
    base = dict(_ORIGINAL_SUMMARY(state) or {})
    plan = state.get("adaptive_search_budget", {}) or build_budget_plan(state)
    reconciliation = plan.get("reconciliation", {}) or state.get("search_budget_reconciliation", {}) or {}
    base["adaptive"] = {
        "version": VERSION,
        "general_pool_daily": plan.get("general_pool_daily"),
        "demand_reserved_daily": plan.get("demand_reserved_daily"),
        "reason": plan.get("reason"),
        "total_cap_unchanged": True,
        "dependent_runtime_caps_synchronized": True,
        "accounting_reconciled": bool(reconciliation.get("reconciled")),
        "legacy_overage_absorbed": int(reconciliation.get("legacy_overage_absorbed") or 0),
    }
    return base


governor.summary = adaptive_summary

try:
    load_state()
    _PLAN = apply_adaptive_search_budget(STATE)
    _RECON = _PLAN.get("reconciliation", {}) or {}
    print({
        "adaptive_search_budget_runtime": {
            **{k: _PLAN.get(k) for k in ("version", "status", "total_daily_cap", "general_pool_daily", "demand_reserved_daily", "reason")},
            "accounting_reconciled": bool(_RECON.get("reconciled")),
            "legacy_overage_absorbed": int(_RECON.get("legacy_overage_absorbed") or 0),
        }
    }, flush=True)
except Exception as exc:
    print({"adaptive_search_budget_runtime": {"version": VERSION, "status": "degraded_fail_open", "error": f"{type(exc).__name__}: {str(exc)[:220]}"}}, flush=True)
