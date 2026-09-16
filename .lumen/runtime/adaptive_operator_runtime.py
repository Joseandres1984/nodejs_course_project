from __future__ import annotations

"""Adaptive Operator for LUMEN.

Adds a bounded decision/learning loop above the existing continuous-learning and Mission Team
runtimes. It measures verified commercial progress, runs small reversible strategy experiments,
learns strategy yield, rotates repeatedly stagnant opportunities, and switches to offline evidence
reuse when the public-search budget is exhausted.

This runtime never creates binding authority, fabricated evidence, paid spend, orders, contracts,
new connectors, publication permission, or production self-modification/deployment authority.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List

import autonomy_core_runtime
import continuous_learning_runtime
import mission_team_runtime
import search_budget_governor

VERSION = "1.0-adaptive-operator"
MAX_HISTORY = 36
MAX_EXPERIMENTS = 36
MAX_ROTATIONS = 40
EXPERIMENT_MIN_SAMPLES = 2
EXPERIMENT_MAX_SAMPLES = 4
TEAM_ROTATE_AFTER_CYCLES = 6
TEAM_COOLDOWN_CYCLES = 3

_ORIGINAL_CONTINUOUS_LEARNING = continuous_learning_runtime.continuous_learning_tick
_ORIGINAL_CANONICAL_OPPORTUNITIES = mission_team_runtime._canonical_opportunities


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _metrics(state: Dict[str, Any]) -> Dict[str, float]:
    truth = _safe_dict(state.get("canonical_revenue_truth"))
    counts = _safe_dict(truth.get("counts"))
    funnel = _safe_dict(state.get("business_funnel"))
    cfo = _safe_dict(state.get("cfo_war_room"))
    finance = _safe_dict(_safe_dict(state.get("business_kpis")).get("finance"))
    return {
        "canonical_opportunities": _f(counts.get("canonical_opportunities") or funnel.get("evidence_backed_opportunities")),
        "requirements_ready_for_rfq": _f(funnel.get("requirements_ready_for_rfq")),
        "canonical_real_offers": _f(counts.get("canonical_real_offers")),
        "canonical_proposals": _f(counts.get("canonical_proposals") or funnel.get("proposals")),
        "canonical_close_ready": _f(counts.get("canonical_close_ready") or funnel.get("close_ready")),
        "realized_profit_usd": _f(cfo.get("realized_profit_usd") or finance.get("realized_profit_usd")),
    }


def _bottleneck(metrics: Dict[str, float]) -> tuple[str, str]:
    if metrics["canonical_opportunities"] <= 0:
        return "opportunity_creation", "canonical_opportunities"
    if metrics["requirements_ready_for_rfq"] <= 0:
        return "requirement_completion", "requirements_ready_for_rfq"
    if metrics["canonical_real_offers"] <= 0:
        return "quote_capture", "canonical_real_offers"
    if metrics["canonical_proposals"] <= 0:
        return "proposal_creation", "canonical_proposals"
    if metrics["canonical_close_ready"] <= 0:
        return "close_path", "canonical_close_ready"
    if metrics["realized_profit_usd"] <= 0:
        return "realized_revenue", "realized_profit_usd"
    return "scale_verified_revenue", "realized_profit_usd"


def _search_status(state: Dict[str, Any]) -> Dict[str, int]:
    try:
        row = dict(search_budget_governor.summary(state) or {})
        return {
            "daily_cap": _i(row.get("total_daily_cap")),
            "used": _i(row.get("effective_total_used")),
            "remaining": _i(row.get("effective_total_remaining")),
        }
    except Exception:
        general = _safe_dict(state.get("scout_budget"))
        demand = _safe_dict(state.get("demand_search_budget"))
        used = _i(general.get("queries_used")) + _i(demand.get("queries_used"))
        cap = _i(general.get("total_daily_cap"), _i(getattr(search_budget_governor, "TOTAL_DAILY_CAP", 0)))
        return {"daily_cap": cap, "used": used, "remaining": max(0, cap - used)}


_STRATEGIES: Dict[str, List[Dict[str, Any]]] = {
    "opportunity_creation": [
        {"id": "high_intent_demand_research", "needs_search": True, "roles": ["buyer_hunter", "research_analyst"], "directive": "Prioritize current, traceable high-intent buyer demand and official procurement evidence; verify identity before promoting an opportunity."},
        {"id": "reuse_verified_demand_inventory", "needs_search": False, "roles": ["research_analyst", "revops"], "directive": "Mine existing verified demand and procurement evidence for overlooked canonical opportunity candidates; do not invent missing facts."},
    ],
    "requirement_completion": [
        {"id": "targeted_requirement_research", "needs_search": True, "roles": ["research_analyst", "revops"], "directive": "Search specifically for traceable specification, quantity and delivery-location evidence for the strongest current buyer requirement."},
        {"id": "official_procurement_requirement_review", "needs_search": True, "roles": ["research_analyst", "risk_quality"], "directive": "Prioritize current official procurement documents that explicitly state specification, quantity and delivery location; reject expired or ambiguous demand."},
        {"id": "offline_requirement_evidence_mining", "needs_search": False, "roles": ["research_analyst", "revops"], "directive": "Re-read existing evidence, documents, messages and procurement signals to complete only explicitly supported requirement fields; never infer absent quantity or location."},
        {"id": "rotate_stalled_requirement_case", "needs_search": False, "roles": ["revops", "research_analyst"], "directive": "Temporarily rotate away from a repeatedly stagnant requirement case and test another canonical opportunity with stronger traceable evidence."},
    ],
    "quote_capture": [
        {"id": "verified_supplier_rfq_preparation", "needs_search": False, "roles": ["supplier_hunter", "revops", "negotiator"], "directive": "Use RFQ-ready requirements to prepare comparable non-binding RFQs for verified suppliers and capture traceable quote evidence."},
        {"id": "supplier_discovery_for_rfq", "needs_search": True, "roles": ["supplier_hunter", "research_analyst"], "directive": "Find and verify suppliers that match the exact RFQ-ready category, then prepare comparable RFQ outreach without fabricating prices."},
    ],
    "proposal_creation": [
        {"id": "quote_normalization_and_proposal", "needs_search": False, "roles": ["negotiator", "revops", "finance", "risk_quality"], "directive": "Normalize real supplier quotes, compare scope and economics, and prepare a non-binding buyer proposal backed by traceable evidence."},
    ],
    "close_path": [
        {"id": "objection_and_close_path_analysis", "needs_search": False, "roles": ["revops", "negotiator", "risk_quality"], "directive": "Analyze evidence-backed objections and missing close conditions, then surface only the exact binding decision that requires a human."},
    ],
    "realized_revenue": [
        {"id": "settlement_readiness", "needs_search": False, "roles": ["revops", "finance", "risk_quality"], "directive": "Verify fulfillment, settlement and collection prerequisites without creating financial or contractual commitments."},
    ],
    "scale_verified_revenue": [
        {"id": "replicate_verified_winner", "needs_search": False, "roles": ["revops", "research_analyst"], "directive": "Replicate only strategies with measured commercial progress into similar evidence-backed cases while preserving all authority gates."},
    ],
}


def _operator(state: Dict[str, Any]) -> Dict[str, Any]:
    op = state.setdefault("adaptive_operator", {})
    op.setdefault("version", VERSION)
    op.setdefault("status", "active")
    op.setdefault("metric_history", [])
    op.setdefault("strategy_memory", {})
    op.setdefault("experiments", [])
    op.setdefault("opportunity_cooldowns", {})
    op.setdefault("rotations", [])
    op.setdefault("no_progress_cycles", 0)
    return op


def _score_entry(op: Dict[str, Any], strategy_id: str) -> Dict[str, Any]:
    memory = op.setdefault("strategy_memory", {})
    row = memory.setdefault(strategy_id, {"score": 1.0, "attempts": 0, "wins": 0, "losses": 0})
    row["score"] = max(0.25, min(1.75, _f(row.get("score"), 1.0)))
    return row


def _select_strategy(op: Dict[str, Any], bottleneck: str, search_remaining: int) -> Dict[str, Any]:
    choices = list(_STRATEGIES.get(bottleneck) or _STRATEGIES["opportunity_creation"])
    eligible = [x for x in choices if not x.get("needs_search") or search_remaining > 0]
    if not eligible:
        eligible = [x for x in choices if not x.get("needs_search")] or choices
    recent_demoted = {
        str(x.get("strategy_id")) for x in list(op.get("experiments", []) or [])[-3:]
        if x.get("status") == "DEMOTED"
    }
    def rank(row: Dict[str, Any]) -> tuple[float, int, str]:
        mem = _score_entry(op, str(row.get("id")))
        novelty = 1 if str(row.get("id")) not in recent_demoted else 0
        return (_f(mem.get("score")), novelty, str(row.get("id")))
    return max(eligible, key=rank)


def _close_or_update_experiment(op: Dict[str, Any], metrics: Dict[str, float], bottleneck: str, target_metric: str, cycle: int) -> None:
    active = op.get("active_experiment")
    if not isinstance(active, dict):
        return
    if active.get("status") != "TESTING":
        op["active_experiment"] = None
        return
    metric = str(active.get("target_metric") or target_metric)
    current = _f(metrics.get(metric))
    active["current"] = current
    active["samples"] = _i(active.get("samples"), 1) + 1
    active["last_cycle"] = cycle
    active["updated_at"] = _now()
    baseline = _f(active.get("baseline"))
    mem = _score_entry(op, str(active.get("strategy_id")))

    if bottleneck != str(active.get("bottleneck")) and current >= baseline:
        active["status"] = "SUPPORTED"
        active["result"] = "bottleneck_advanced"
    elif current > baseline and active["samples"] >= EXPERIMENT_MIN_SAMPLES:
        active["status"] = "SUPPORTED"
        active["result"] = "associated_verified_progress"
    elif active["samples"] >= EXPERIMENT_MAX_SAMPLES:
        active["status"] = "DEMOTED"
        active["result"] = "no_verified_progress_in_evaluation_window"

    if active.get("status") == "SUPPORTED":
        mem["wins"] = _i(mem.get("wins")) + 1
        mem["score"] = min(1.75, _f(mem.get("score"), 1.0) + 0.16)
        mem["last_result"] = "supported"
        mem["last_delta"] = round(current - baseline, 4)
        mem["updated_at"] = _now()
        op["active_experiment"] = None
    elif active.get("status") == "DEMOTED":
        mem["losses"] = _i(mem.get("losses")) + 1
        mem["score"] = max(0.25, _f(mem.get("score"), 1.0) - 0.14)
        mem["last_result"] = "demoted"
        mem["last_delta"] = round(current - baseline, 4)
        mem["updated_at"] = _now()
        op["active_experiment"] = None


def _start_experiment(op: Dict[str, Any], bottleneck: str, target_metric: str, metrics: Dict[str, float], search_remaining: int, cycle: int) -> Dict[str, Any]:
    strategy = _select_strategy(op, bottleneck, search_remaining)
    sid = str(strategy.get("id"))
    mem = _score_entry(op, sid)
    mem["attempts"] = _i(mem.get("attempts")) + 1
    row = {
        "id": f"AOP-{cycle}-{sid}",
        "strategy_id": sid,
        "bottleneck": bottleneck,
        "target_metric": target_metric,
        "hypothesis": f"Applying {sid} will improve verified {target_metric} without widening authority.",
        "directive": strategy.get("directive"),
        "roles": list(strategy.get("roles") or []),
        "needs_search": bool(strategy.get("needs_search")),
        "baseline": _f(metrics.get(target_metric)),
        "current": _f(metrics.get(target_metric)),
        "start_cycle": cycle,
        "last_cycle": cycle,
        "samples": 1,
        "status": "TESTING",
        "created_at": _now(),
        "updated_at": _now(),
        "authority_change": False,
        "spend_cap_change": False,
        "code_change": False,
    }
    experiments = list(op.get("experiments", []) or [])
    experiments.append(row)
    op["experiments"] = experiments[-MAX_EXPERIMENTS:]
    op["active_experiment"] = row
    return row


def _record_progress(op: Dict[str, Any], metrics: Dict[str, float], cycle: int) -> bool:
    history = list(op.get("metric_history", []) or [])
    previous = history[-1].get("metrics", {}) if history else {}
    meaningful_keys = (
        "canonical_opportunities", "requirements_ready_for_rfq", "canonical_real_offers",
        "canonical_proposals", "canonical_close_ready", "realized_profit_usd",
    )
    progressed = any(_f(metrics.get(k)) > _f(previous.get(k)) for k in meaningful_keys) if previous else False
    op["no_progress_cycles"] = 0 if progressed else (_i(op.get("no_progress_cycles")) + (1 if previous else 0))
    history.append({"cycle": cycle, "at": _now(), "metrics": dict(metrics), "verified_progress": progressed})
    op["metric_history"] = history[-MAX_HISTORY:]
    return progressed


def _rotate_stalled_team(state: Dict[str, Any], op: Dict[str, Any], cycle: int, metrics: Dict[str, float]) -> Dict[str, Any] | None:
    if metrics.get("requirements_ready_for_rfq", 0) > 0:
        return None
    teams = [x for x in state.get("mission_teams", []) or [] if isinstance(x, dict)]
    active = [x for x in teams if x.get("status") == "active" and str(x.get("stage") or "") == "REQUIREMENT"]
    reserve = [x for x in teams if x.get("status") == "reserve" and str(x.get("stage") or "") == "REQUIREMENT"]
    if not reserve:
        return None
    stalled = sorted(active, key=lambda x: _i(x.get("stagnant_cycles")), reverse=True)
    victim = next((x for x in stalled if _i(x.get("stagnant_cycles")) >= TEAM_ROTATE_AFTER_CYCLES), None)
    if not victim:
        return None
    oid = str(victim.get("opportunity_id") or "")
    cooldowns = op.setdefault("opportunity_cooldowns", {})
    current = _safe_dict(cooldowns.get(oid))
    if oid and _i(current.get("until_cycle")) > cycle:
        return None
    if not oid:
        return None
    cooldowns[oid] = {
        "until_cycle": cycle + TEAM_COOLDOWN_CYCLES,
        "reason": "requirement_stage_stagnation",
        "stagnant_cycles": _i(victim.get("stagnant_cycles")),
        "created_at": _now(),
    }
    victim["adaptive_rotation_pending"] = True
    victim["adaptive_rotation_reason"] = "repeated_requirement_stagnation_test_alternate_canonical_opportunity"
    event = {
        "at": _now(), "cycle": cycle, "opportunity_id": oid,
        "stagnant_cycles": _i(victim.get("stagnant_cycles")),
        "cooldown_cycles": TEAM_COOLDOWN_CYCLES,
        "action": "temporary_attention_rotation_only",
    }
    rotations = list(op.get("rotations", []) or [])
    rotations.append(event)
    op["rotations"] = rotations[-MAX_ROTATIONS:]
    return event


def _adaptive_canonical_opportunities(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = list(_ORIGINAL_CANONICAL_OPPORTUNITIES(state) or [])
    op = _safe_dict(state.get("adaptive_operator"))
    cooldowns = _safe_dict(op.get("opportunity_cooldowns"))
    cycle = _i(state.get("ticks"))
    active_cooldowns = {
        oid: row for oid, row in cooldowns.items()
        if isinstance(row, dict) and _i(row.get("until_cycle")) > cycle
    }
    if not active_cooldowns or len(rows) <= mission_team_runtime.MAX_ACTIVE_TEAMS:
        return rows
    return sorted(rows, key=lambda x: (1 if str(x.get("id") or "") in active_cooldowns else 0, -_f(x.get("score") or x.get("portfolio_priority_score")), str(x.get("id") or "")))


def _publish_directive(state: Dict[str, Any], op: Dict[str, Any], experiment: Dict[str, Any], search: Dict[str, int], metrics: Dict[str, float]) -> None:
    core = autonomy_core_runtime._core(state)
    cards = [x for x in list(core.get("blackboard", []) or []) if x.get("kind") != "adaptive_operator"]
    offline = search.get("remaining", 0) <= 0
    card = {
        "kind": "adaptive_operator",
        "id": "AOP-CURRENT",
        "priority": 100,
        "created_at": _now(),
        "text": experiment.get("directive"),
        "strategy_id": experiment.get("strategy_id"),
        "target_metric": experiment.get("target_metric"),
        "bottleneck": experiment.get("bottleneck"),
        "operating_mode": "offline_existing_evidence" if offline else "bounded_market_plus_internal",
        "truth_rule": "Only traceable evidence changes commercial stage; never invent demand, requirements, quotes, delivery, or outcomes.",
        "production_first": metrics.get("realized_profit_usd", 0) <= 0,
        "binding": False,
    }
    core["blackboard"] = ([card] + cards)[:60]
    op["current_directive"] = card


def adaptive_operator_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    op = _operator(state)
    cycle = _i(state.get("ticks"))
    metrics = _metrics(state)
    bottleneck, target_metric = _bottleneck(metrics)
    search = _search_status(state)
    progressed = _record_progress(op, metrics, cycle)
    _close_or_update_experiment(op, metrics, bottleneck, target_metric, cycle)
    active = op.get("active_experiment")
    if not isinstance(active, dict) or active.get("status") != "TESTING" or str(active.get("bottleneck")) != bottleneck:
        active = _start_experiment(op, bottleneck, target_metric, metrics, search.get("remaining", 0), cycle)
    rotation = _rotate_stalled_team(state, op, cycle, metrics)
    _publish_directive(state, op, active, search, metrics)

    op.update({
        "version": VERSION,
        "status": "active",
        "updated_at": _now(),
        "cycle": cycle,
        "bottleneck": bottleneck,
        "target_metric": target_metric,
        "verified_progress_this_cycle": progressed,
        "no_progress_cycles": _i(op.get("no_progress_cycles")),
        "search": search,
        "operating_mode": "offline_existing_evidence" if search.get("remaining", 0) <= 0 else "bounded_market_plus_internal",
        "active_strategy": active.get("strategy_id"),
        "active_experiment_id": active.get("id"),
        "rotation_this_cycle": rotation,
        "production_first": metrics.get("realized_profit_usd", 0) <= 0,
        "authority": {
            "binding_authority_changed": False,
            "paid_spend_authorized": False,
            "self_modify_or_deploy_authorized": False,
            "evidence_gates_preserved": True,
        },
    })
    state["adaptive_operator"] = op
    return op


def _continuous_learning_with_adaptive_operator(state: Dict[str, Any]) -> Dict[str, Any]:
    report = dict(_ORIGINAL_CONTINUOUS_LEARNING(state) or {})
    try:
        op = adaptive_operator_tick(state)
        report["adaptive_operator"] = {
            "version": op.get("version"),
            "status": op.get("status"),
            "bottleneck": op.get("bottleneck"),
            "target_metric": op.get("target_metric"),
            "active_strategy": op.get("active_strategy"),
            "operating_mode": op.get("operating_mode"),
            "no_progress_cycles": op.get("no_progress_cycles"),
            "rotation_this_cycle": op.get("rotation_this_cycle"),
            "search": op.get("search"),
            "binding_authority_changed": False,
        }
        print({"adaptive_operator": report["adaptive_operator"]}, flush=True)
    except Exception as exc:
        report["adaptive_operator"] = {"version": VERSION, "status": "degraded_fail_open", "error": f"{type(exc).__name__}: {str(exc)[:240]}"}
        print({"adaptive_operator": report["adaptive_operator"]}, flush=True)
    state["continuous_learning"] = report
    return report


mission_team_runtime._canonical_opportunities = _adaptive_canonical_opportunities
continuous_learning_runtime.continuous_learning_tick = _continuous_learning_with_adaptive_operator

print({
    "adaptive_operator_runtime": {
        "version": VERSION,
        "status": "active",
        "strategy_experiments": True,
        "strategy_yield_memory": True,
        "mission_team_rotation": True,
        "offline_when_search_exhausted": True,
        "production_first": True,
        "binding_authority_changed": False,
        "self_modify_or_deploy_authorized": False,
    }
}, flush=True)
