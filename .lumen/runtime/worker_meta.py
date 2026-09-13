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
    """Keep genuine LUMEN Market demand attached to the buyer as it moves from lead to account.

    This only copies evidence already created by the public Market ingestion path. It does not mark a
    company as verified and it does not bypass Company Verification, contact checks or outbound gates.
    """
    leads = {
        str(x.get("id") or ""): x
        for x in state.get("research_leads", []) or []
        if x.get("id")
    }
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
        for key in ("market_inquiry_id", "market_inquiry_key"):
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


# Worker imports qualify_tick after this wrapper is loaded, so every normal production cycle preserves
# direct Market demand metadata without changing the underlying Lead Intelligence authority boundary.
lead_intelligence.qualify_tick = _qualify_with_market_inbound


def _safe_meta(name: str, fn: Callable[[], Dict[str, Any]], errors: list[Dict[str, str]]) -> Dict[str, Any]:
    try:
        return dict(fn() or {})
    except Exception as exc:
        errors.append({"engine": name, "error": f"{type(exc).__name__}: {str(exc)[:260]}"})
        return {}


def meta_lumen_cycle() -> Dict[str, Any]:
    """Run one bounded executive/meta-control pass over the previous completed business cycle.

    Meta-LUMEN may reprioritize reversible attention, research and experiments. Constitution, safety,
    financial, contractual and production-code authority remain unchanged and human-gated.
    """
    if not load_state():
        report = {
            "updated_at": utcnow(),
            "mode": "meta_lumen_bounded_autonomous_management",
            "status": "skipped",
            "reason": "state_unavailable",
            "production_code_self_modify": False,
        }
        print({"meta_autonomy": report}, flush=True)
        return report

    errors: list[Dict[str, str]] = []

    # Economic target/funnel diagnosis first, because the Orchestrator reads this directive.
    revenue = _safe_meta("Revenue Factory", lambda: revenue_factory_tick(STATE), errors)

    # Digital twin proposes only reversible experiments with evidence thresholds.
    simulator = _safe_meta("Strategy Simulator", lambda: strategy_simulator_tick(STATE), errors)

    # Constitutionally arbitrate the single company mode and kill-switch/resource baseline.
    master = _safe_meta(
        "Master Orchestrator",
        lambda: master_orchestrator_tick(
            STATE,
            DB_STATUS,
            preflight=(STATE.get("operations_control", {}) or {}),
        ),
        errors,
    )

    # CEO-like management can reallocate bounded attention and manage portfolios/programs.
    management = _safe_meta("Autonomous Executive Management", lambda: executive_management_cycle(STATE), errors)

    # Controller closes the feedback loop and may apply a second bounded reversible overlay.
    controller = _safe_meta("Business Controller", lambda: business_controller_tick(STATE), errors)

    # Meta-learning diagnoses systematic weaknesses; code changes remain proposals, never self-deploys.
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
                "attention allocation",
                "research prioritization",
                "portfolio pursue/repair/park",
                "reversible strategy experiments",
                "evidence-based improvement programs",
                "commercial preparation and nonbinding execution within existing gates",
            ],
            "human_required_only_for": [
                "binding contracts or acceptance of binding terms",
                "payments/orders/financial commitments",
                "material legal or liability decisions",
                "production code changes and deployments",
            ],
            "production_code_self_modify": False,
        },
    }
    STATE["meta_autonomy"] = report
    persisted = save_state()
    report["persisted"] = bool(persisted)
    print({"meta_autonomy": report}, flush=True)
    return report


def agent_workforce_cycle() -> Dict[str, Any]:
    """Give Meta-LUMEN a 50-person parallel workforce before the normal production worker runs.

    The fleet performs evidence gathering and nonbinding analysis only. Search calls remain under the
    same shared daily budget and protected retail reserve. Results become research leads/signals and
    must still pass the existing verification, opportunity, risk and closing gates.
    """
    try:
        from agent_fleet import run_agent_fleet_cycle

        if not load_state():
            report = {"status": "skipped", "reason": "state_unavailable", "fleet_size": 0}
            print({"agent_workforce": report}, flush=True)
            return report
        report = dict(run_agent_fleet_cycle(STATE) or {})
        report["persisted"] = bool(save_state())
        print({"agent_workforce": report}, flush=True)
        return report
    except Exception as exc:
        report = {
            "status": "degraded_fail_open",
            "reason": f"{type(exc).__name__}: {str(exc)[:260]}",
            "fleet_size": 0,
        }
        print({"agent_workforce": report}, flush=True)
        return report


# One meta-control pass per cron execution. Meta-LUMEN decides the business focus first.
meta_lumen_cycle()

# Then the digital organization executes up to 50 parallel assignments under the same evidence,
# budget and authority boundaries. Its findings are available to the normal worker immediately.
agent_workforce_cycle()

# Existing production worker remains the execution engine. Importing this wrapper runs it unchanged after
# installing the Market-demand metadata bridge and all previously deployed demand/retail/distribution hooks.
import worker_with_demand  # noqa: E402,F401
