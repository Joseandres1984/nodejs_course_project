from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict

from app import DB_STATUS, STATE, load_state, save_state
import lead_intelligence
from autonomous_management_runtime import executive_management_cycle
from business_controller import business_controller_tick
from master_orchestrator import master_orchestrator_tick
from revenue_factory import revenue_factory_tick
from self_improvement_lab import self_improvement_tick
from strategy_simulator import strategy_simulator_tick


_ORIGINAL_QUALIFY_TICK = lead_intelligence.qualify_tick


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _propagate_market_inbound_metadata(state: Dict[str, Any]) -> int:
    leads = {str(x.get("id") or ""): x for x in state.get("research_leads", []) or [] if x.get("id")}
    updated = 0
    for account in state.get("candidate_accounts", []) or []:
        lead = leads.get(str(account.get("source_lead_id") or ""))
        if not lead:
            continue
        touched = False
        if lead.get("direct_inbound_demand") and not account.get("direct_inbound_demand"):
            account["direct_inbound_demand"] = True
            account["market_source"] = "lumen_market_inbound"
            touched = True
        if lead.get("demand_signal") and not account.get("demand_signal"):
            account["demand_signal"] = True
            touched = True
        for key in ("market_inquiry_id", "market_inquiry_key", "acquisition_campaign_id", "acquisition_variant_id", "acquisition_lead_id"):
            value = lead.get(key)
            if value and account.get(key) != value:
                account[key] = value
                touched = True
        if touched:
            account["inbound_metadata_propagated_at"] = utcnow()
            updated += 1
    return updated


def _qualify_with_market_inbound(state: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(_ORIGINAL_QUALIFY_TICK(state) or {})
    result["inbound_metadata_propagated"] = _propagate_market_inbound_metadata(state)
    return result


lead_intelligence.qualify_tick = _qualify_with_market_inbound


def _safe_meta(name: str, fn: Callable[[], Dict[str, Any]], errors: list[Dict[str, str]]) -> Dict[str, Any]:
    try:
        return dict(fn() or {})
    except Exception as exc:
        errors.append({"engine": name, "error": f"{type(exc).__name__}: {str(exc)[:260]}"})
        return {}


def meta_lumen_cycle() -> Dict[str, Any]:
    if not load_state():
        report = {"updated_at": utcnow(), "mode": "meta_lumen_bounded_autonomous_management", "status": "skipped", "reason": "state_unavailable", "production_code_self_modify": False}
        print({"meta_autonomy": report}, flush=True)
        return report
    errors: list[Dict[str, str]] = []
    revenue = _safe_meta("Revenue Factory", lambda: revenue_factory_tick(STATE), errors)
    simulator = _safe_meta("Strategy Simulator", lambda: strategy_simulator_tick(STATE), errors)
    master = _safe_meta("Master Orchestrator", lambda: master_orchestrator_tick(STATE, DB_STATUS, preflight=(STATE.get("operations_control", {}) or {})), errors)
    management = _safe_meta("Autonomous Executive Management", lambda: executive_management_cycle(STATE), errors)
    controller = _safe_meta("Business Controller", lambda: business_controller_tick(STATE), errors)
    improvement = _safe_meta("Self-Improvement Lab", lambda: self_improvement_tick(STATE), errors)
    report = {
        "updated_at": utcnow(),
        "mode": "meta_lumen_bounded_autonomous_management",
        "status": "healthy" if not errors else "degraded_but_fail_open_to_normal_worker",
        "revenue_directive": (revenue.get("directive") or {}).get("code"),
        "recommended_scenario": (simulator.get("recommended_scenario") or {}).get("id"),
        "company_mode": master.get("company_mode"),
        "management_priority": (management.get("primary_management_priority") or {}).get("code"),
        "management_department": (management.get("primary_management_priority") or {}).get("department"),
        "controller_mode": controller.get("control_mode"),
        "self_improvement_primary": (improvement.get("primary_proposal") or {}).get("code"),
        "engine_errors": errors,
        "autonomy_boundary": {
            "autonomous": [
                "attention allocation", "research prioritization", "portfolio pursue/repair/park",
                "reversible strategy experiments", "evidence-based improvement programs",
                "commercial preparation and nonbinding execution within existing gates",
                "elastic digital workforce sizing and role allocation",
                "persistent professional case ownership and multistage research",
                "store/catalog discovery and commission-attribution preparation",
                "robots-respecting same-domain public catalog inspection",
                "organic acquisition copy generation, owned-channel publication and conversion learning",
            ],
            "human_required_only_for": [
                "binding contracts or acceptance of binding terms", "payments/orders/financial commitments",
                "material legal or liability decisions", "production code changes and deployments",
                "activation of a new partner agreement when binding terms must be accepted",
                "paid advertising budget, spend or binding ad-platform commitment",
            ],
            "production_code_self_modify": False,
        },
    }
    STATE["meta_autonomy"] = report
    report["persisted"] = bool(save_state())
    print({"meta_autonomy": report}, flush=True)
    return report


def professional_casework_cycle() -> Dict[str, Any]:
    try:
        from professional_casework import professional_casework_tick
        if not load_state():
            report = {"status": "skipped", "reason": "state_unavailable", "cases_worked": 0}
            print({"professional_casework": report}, flush=True)
            return report
        report = dict(professional_casework_tick(STATE) or {})
        report["persisted"] = bool(save_state())
        print({"professional_casework": report}, flush=True)
        return report
    except Exception as exc:
        report = {"status": "degraded_fail_open", "reason": f"{type(exc).__name__}: {str(exc)[:260]}", "cases_worked": 0}
        print({"professional_casework": report}, flush=True)
        return report


def partner_network_cycle() -> Dict[str, Any]:
    try:
        from partner_network_ext import partner_network_tick
        if not load_state():
            report = {"status": "skipped", "reason": "state_unavailable", "stores_total": 0}
            print({"partner_network": report}, flush=True)
            return report
        report = dict(partner_network_tick(STATE) or {})
        report["persisted"] = bool(save_state())
        print({"partner_network": report}, flush=True)
        return report
    except Exception as exc:
        report = {"status": "degraded_fail_open", "reason": f"{type(exc).__name__}: {str(exc)[:260]}", "stores_total": 0}
        print({"partner_network": report}, flush=True)
        return report


def acquisition_campaign_cycle() -> Dict[str, Any]:
    try:
        from acquisition_campaigns import acquisition_campaign_tick
        if not load_state():
            report = {"status": "skipped", "reason": "state_unavailable", "campaigns_active": 0}
            print({"acquisition_campaigns": report}, flush=True)
            return report
        report = dict(acquisition_campaign_tick(STATE) or {})
        report["persisted"] = bool(save_state())
        print({"acquisition_campaigns": report}, flush=True)
        return report
    except Exception as exc:
        report = {"status": "degraded_fail_open", "reason": f"{type(exc).__name__}: {str(exc)[:260]}", "campaigns_active": 0}
        print({"acquisition_campaigns": report}, flush=True)
        return report


def agent_workforce_cycle() -> Dict[str, Any]:
    try:
        from elastic_agent_fleet import run_elastic_agent_fleet_cycle
        if not load_state():
            report = {"status": "skipped", "reason": "state_unavailable", "fleet_size": 0}
            print({"agent_workforce": report}, flush=True)
            return report
        report = dict(run_elastic_agent_fleet_cycle(STATE) or {})
        report["persisted"] = bool(save_state())
        print({"agent_workforce": report}, flush=True)
        return report
    except Exception as exc:
        report = {"status": "degraded_fail_open", "reason": f"{type(exc).__name__}: {str(exc)[:260]}", "fleet_size": 0}
        print({"agent_workforce": report}, flush=True)
        return report


meta_lumen_cycle()
professional_casework_cycle()
partner_network_cycle()
acquisition_campaign_cycle()
agent_workforce_cycle()
import worker_with_demand  # noqa: E402,F401
