from __future__ import annotations

"""LUMEN Superautonomy v1.

Superautonomy is a bounded orchestration layer above Autonomy Core, Adaptive Operator,
Autonomous Director, Cognitive learning and the Experiment Engine.

It makes LUMEN more self-directed by:
- continuously observing verified commercial progress,
- selecting the current bottleneck and next reversible action,
- routing role attention without widening authority,
- learning from measured outcomes,
- recovering from stalls by rotating tactics or opening a parallel zero-cost lane,
- surfacing a human only when an existing binding/financial/legal gate truly requires one.

It never authorizes outgoing spend, purchases, contracts, legal commitments, new
connectors/accounts, paid-media spend, production deployments, or fabricated evidence.
Those existing gates remain authoritative.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List
import hashlib

import autonomy_core_runtime
import autonomous_director_runtime

VERSION = "1.0-superautonomy"
MAX_MEMORY = 96
MAX_DECISIONS = 72
MAX_OUTCOMES = 96
ROLE_BOOST_CAP = float(getattr(autonomy_core_runtime, "ROLE_BOOST_CAP", 0.12))

_ORIGINAL_PREPARE = autonomy_core_runtime.autonomy_core_prepare
_ORIGINAL_TICK = autonomy_core_runtime.autonomy_core_tick


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _clean(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


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


def _fingerprint(*parts: Any) -> str:
    raw = "|".join(_clean(x).lower() for x in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14]


def _super(state: Dict[str, Any]) -> Dict[str, Any]:
    sup = state.setdefault("superautonomy", {})
    sup.setdefault("version", VERSION)
    sup.setdefault("status", "active")
    sup.setdefault("mode", "observe_prioritize_act_measure_learn_recover")
    sup.setdefault("decision_memory", {})
    sup.setdefault("decisions", [])
    sup.setdefault("outcomes", [])
    sup.setdefault("no_progress_cycles", 0)
    sup.setdefault("stage", "OBSERVING")
    return sup


def _metrics(state: Dict[str, Any]) -> Dict[str, float]:
    try:
        return dict(autonomous_director_runtime._expanded_metrics(state) or {})
    except Exception:
        return dict(autonomy_core_runtime._metric_snapshot(state) or {})


def _bottleneck(metrics: Dict[str, float]) -> tuple[str, str]:
    try:
        return autonomous_director_runtime._expanded_bottleneck(metrics)
    except Exception:
        order = (
            ("opportunity_creation", "canonical_opportunities"),
            ("requirement_completion", "requirements_ready_for_rfq"),
            ("quote_capture", "canonical_real_offers"),
            ("proposal_creation", "canonical_proposals"),
            ("close_path", "canonical_close_ready"),
            ("realized_revenue", "realized_profit_usd"),
        )
        for lane, metric in order:
            if _f(metrics.get(metric)) <= 0:
                return lane, metric
        return "scale_verified_revenue", "realized_profit_usd"


def _search_remaining(state: Dict[str, Any]) -> int:
    summary = _safe_dict(state.get("search_budget_governor"))
    if not summary:
        try:
            import search_budget_governor
            summary = _safe_dict(search_budget_governor.summary(state))
        except Exception:
            summary = {}
    for key in ("effective_total_remaining", "total_remaining", "queries_remaining"):
        if key in summary:
            return max(0, _i(summary.get(key)))
    general = _safe_dict(state.get("scout_budget"))
    demand = _safe_dict(state.get("demand_search_budget"))
    return max(0, _i(general.get("queries_remaining")) + _i(demand.get("queries_remaining")))


def _pending_human_gate(state: Dict[str, Any]) -> Dict[str, Any] | None:
    """Return only explicit pending binding/financial/legal approvals.

    Mere absence of data or ordinary research work must never be escalated to the human.
    """
    sensitive_tokens = {
        "payment", "pay", "purchase", "order", "contract", "binding", "legal",
        "deploy", "production", "connector", "account", "paid_media", "spend",
        "financial", "settlement", "accept_terms",
    }
    for row in reversed(_safe_list(state.get("approvals"))[-80:]):
        if not isinstance(row, dict):
            continue
        status = _clean(row.get("status")).lower()
        if status not in {"pending", "awaiting_human", "human_required", "approval_required"}:
            continue
        text = " ".join(
            _clean(row.get(k)).lower()
            for k in ("type", "action", "reason", "category", "title", "description")
        )
        if any(token in text for token in sensitive_tokens):
            return {
                "id": row.get("id"),
                "type": _clean(row.get("type") or row.get("action") or "sensitive_action"),
                "reason": _clean(row.get("reason") or row.get("description") or "human approval required"),
            }
    return None


_ACTIONS: Dict[str, List[Dict[str, Any]]] = {
    "demand_discovery": [
        {"id": "mine_existing_demand_evidence", "roles": ["research_analyst", "buyer_hunter"], "needs_search": False,
         "directive": "Re-read stored buyer-bound evidence and official documents for exact demand signals before spending another search."},
        {"id": "precision_demand_search", "roles": ["buyer_hunter", "research_analyst"], "needs_search": True,
         "directive": "Search only for current traceable purchase, tender, procurement or requirement evidence for already verified buyers."},
    ],
    "verification_contact": [
        {"id": "repair_official_contact_evidence", "roles": ["research_analyst", "buyer_hunter", "revops"], "needs_search": False,
         "directive": "Reconcile stored official-domain and corporate contact evidence for demand-verified buyers, respecting cooldowns and opt-outs."},
        {"id": "precision_contact_verification", "roles": ["research_analyst", "buyer_hunter"], "needs_search": True,
         "directive": "Find only official corporate commercial channels for the strongest demand-verified buyer; never infer personal addresses."},
    ],
    "opportunity_creation": [
        {"id": "promote_verified_inventory", "roles": ["revops", "research_analyst"], "needs_search": False,
         "directive": "Mine existing verified demand and supplier evidence for overlooked canonical opportunity pairs before new discovery."},
        {"id": "high_intent_opportunity_search", "roles": ["buyer_hunter", "research_analyst"], "needs_search": True,
         "directive": "Search for current high-intent demand that can be paired with already verified supply and promoted only with traceable evidence."},
    ],
    "requirement_completion": [
        {"id": "offline_requirement_completion", "roles": ["research_analyst", "revops"], "needs_search": False,
         "directive": "Complete requirement fields only from existing explicit evidence; do not infer absent quantity, specification or delivery location."},
        {"id": "precision_requirement_search", "roles": ["research_analyst", "risk_quality"], "needs_search": True,
         "directive": "Search specifically for official requirement documents that can complete the strongest canonical RFQ pack."},
    ],
    "quote_capture": [
        {"id": "prepare_comparable_rfq", "roles": ["supplier_hunter", "revops", "negotiator"], "needs_search": False,
         "directive": "Use RFQ-ready requirements to prepare comparable non-binding supplier outreach and capture real quote evidence."},
        {"id": "supplier_match_for_rfq", "roles": ["supplier_hunter", "research_analyst"], "needs_search": True,
         "directive": "Find verified suppliers matching the exact RFQ-ready requirement and prepare comparable quote requests."},
    ],
    "proposal_creation": [
        {"id": "normalize_real_quotes", "roles": ["negotiator", "revops", "finance", "risk_quality"], "needs_search": False,
         "directive": "Normalize real quotes and prepare a traceable non-binding buyer proposal using only verified scope, price and condition evidence."},
    ],
    "close_path": [
        {"id": "remove_close_friction", "roles": ["revops", "negotiator", "risk_quality"], "needs_search": False,
         "directive": "Identify the exact unresolved close condition, automate every reversible preparatory step, and surface only a truly binding decision."},
    ],
    "realized_revenue": [
        {"id": "settlement_readiness", "roles": ["revops", "finance", "risk_quality"], "needs_search": False,
         "directive": "Verify fulfillment, invoice, payment-route and settlement prerequisites without moving funds or accepting terms."},
    ],
    "scale_verified_revenue": [
        {"id": "replicate_measured_winner", "roles": ["revops", "research_analyst", "market_manager"], "needs_search": False,
         "directive": "Replicate only tactics with measured commercial progress into similar evidence-backed cases while preserving all authority gates."},
    ],
}


def _decision_score(sup: Dict[str, Any], action: Dict[str, Any], search_remaining: int) -> float:
    if action.get("needs_search") and search_remaining <= 0:
        return -999.0
    mem = _safe_dict(_safe_dict(sup.get("decision_memory")).get(str(action.get("id"))))
    score = _f(mem.get("score"), 1.0)
    attempts = _i(mem.get("attempts"))
    novelty = 0.12 if attempts == 0 else 0.0
    return score + novelty


def _select_action(sup: Dict[str, Any], bottleneck: str, search_remaining: int) -> Dict[str, Any]:
    choices = list(_ACTIONS.get(bottleneck) or _ACTIONS["opportunity_creation"])
    ranked = sorted(
        choices,
        key=lambda row: (_decision_score(sup, row, search_remaining), str(row.get("id"))),
        reverse=True,
    )
    eligible = [row for row in ranked if _decision_score(sup, row, search_remaining) > -900]
    return dict((eligible or ranked)[0])


def _role_boosts(action: Dict[str, Any], stall_cycles: int) -> Dict[str, float]:
    base = 0.05
    if stall_cycles >= 3:
        base = 0.08
    if stall_cycles >= 6:
        base = 0.10
    if stall_cycles >= 12:
        base = ROLE_BOOST_CAP
    return {str(role): min(ROLE_BOOST_CAP, base) for role in action.get("roles", []) or []}


def _evaluate_previous(state: Dict[str, Any], sup: Dict[str, Any], metrics: Dict[str, float]) -> Dict[str, Any] | None:
    active = sup.get("active_decision")
    if not isinstance(active, dict):
        return None

    metric = _clean(active.get("target_metric"))
    current = _f(metrics.get(metric))
    baseline = _f(active.get("baseline"))
    samples = _i(active.get("samples"), 1) + 1
    active["samples"] = samples
    active["current"] = current
    active["updated_at"] = _now()

    progressed = current > baseline
    if progressed:
        result = "SUPPORTED"
    elif samples >= 4:
        result = "DEMOTED"
    else:
        result = "TESTING"

    active["status"] = result
    memory = sup.setdefault("decision_memory", {})
    mem = memory.setdefault(str(active.get("action_id")), {
        "score": 1.0, "attempts": 0, "wins": 0, "losses": 0,
    })

    if result == "SUPPORTED":
        mem["wins"] = _i(mem.get("wins")) + 1
        mem["score"] = min(1.8, _f(mem.get("score"), 1.0) + 0.18)
        mem["last_result"] = "supported"
        mem["last_delta"] = round(current - baseline, 4)
        sup["no_progress_cycles"] = 0
        sup["active_decision"] = None
    elif result == "DEMOTED":
        mem["losses"] = _i(mem.get("losses")) + 1
        mem["score"] = max(0.2, _f(mem.get("score"), 1.0) - 0.16)
        mem["last_result"] = "demoted"
        mem["last_delta"] = round(current - baseline, 4)
        sup["no_progress_cycles"] = _i(sup.get("no_progress_cycles")) + 1
        sup["active_decision"] = None
    else:
        sup["no_progress_cycles"] = _i(sup.get("no_progress_cycles")) + 1

    mem["updated_at"] = _now()
    outcome = {
        "decision_id": active.get("id"),
        "action_id": active.get("action_id"),
        "target_metric": metric,
        "baseline": baseline,
        "current": current,
        "status": result,
        "at": _now(),
    }
    outcomes = list(sup.get("outcomes", []) or [])
    outcomes.append(outcome)
    sup["outcomes"] = outcomes[-MAX_OUTCOMES:]
    return outcome


def _parallel_lane(state: Dict[str, Any], stall_cycles: int) -> Dict[str, Any] | None:
    """Choose a zero-cost parallel revenue lane only after repeated verified stagnation."""
    if stall_cycles < 6:
        return None

    services = _safe_dict(state.get("service_revenue_runtime"))
    intelligence = _safe_dict(state.get("intelligence_revenue_engine"))
    acquisition = _safe_dict(state.get("acquisition_campaigns"))

    if _i(services.get("pipeline_total")) > 0 and _i(services.get("replies")) <= 0:
        return {
            "id": "parallel_service_followup",
            "roles": ["revops", "market_manager"],
            "directive": "Keep the canonical bottleneck primary while using already-permitted zero-cost service follow-up on existing pipeline evidence.",
        }
    if _i(intelligence.get("verified_candidates")) > 0 and _i(intelligence.get("replies")) <= 0:
        return {
            "id": "parallel_intelligence_offer",
            "roles": ["market_manager", "revops"],
            "directive": "Open a bounded parallel intelligence-offer lane using existing verified candidates and existing no-spend channels.",
        }
    if _i(acquisition.get("clicks")) > 0 and _i(acquisition.get("leads")) <= 0:
        return {
            "id": "parallel_conversion_repair",
            "roles": ["market_manager", "research_analyst"],
            "directive": "Analyze observed click-to-lead friction and rotate only reversible organic conversion variants.",
        }
    return None


def _apply_attention(core: Dict[str, Any], action: Dict[str, Any], stall_cycles: int, parallel: Dict[str, Any] | None) -> Dict[str, float]:
    current = dict(core.get("role_attention", {}) or {})
    boosts = _role_boosts(action, stall_cycles)
    if parallel:
        for role, value in _role_boosts(parallel, stall_cycles).items():
            boosts[role] = max(boosts.get(role, 0.0), min(ROLE_BOOST_CAP, value * 0.75))
    for role, boost in boosts.items():
        current[role] = min(ROLE_BOOST_CAP, max(_f(current.get(role)), boost))
    core["role_attention"] = current
    return current


def superautonomy_prepare(state: Dict[str, Any]) -> Dict[str, Any]:
    sup = _super(state)
    metrics = _metrics(state)
    bottleneck, target_metric = _bottleneck(metrics)
    search_remaining = _search_remaining(state)
    cycle = _i(state.get("ticks"))

    _evaluate_previous(state, sup, metrics)

    human_gate = _pending_human_gate(state)
    action = _select_action(sup, bottleneck, search_remaining)
    memory = sup.setdefault("decision_memory", {})
    mem = memory.setdefault(str(action.get("id")), {
        "score": 1.0, "attempts": 0, "wins": 0, "losses": 0,
    })
    mem["attempts"] = _i(mem.get("attempts")) + 1

    stall_cycles = max(
        _i(sup.get("no_progress_cycles")),
        _i(_safe_dict(state.get("adaptive_operator")).get("no_progress_cycles")),
    )
    parallel = _parallel_lane(state, stall_cycles)

    decision = {
        "id": f"SUPER-{cycle}-{_fingerprint(bottleneck, action.get('id'), target_metric)}",
        "cycle": cycle,
        "created_at": _now(),
        "stage": "HUMAN_APPROVAL_REQUIRED" if human_gate else "NEXT_ACTION",
        "bottleneck": bottleneck,
        "target_metric": target_metric,
        "baseline": _f(metrics.get(target_metric)),
        "current": _f(metrics.get(target_metric)),
        "action_id": action.get("id"),
        "directive": action.get("directive"),
        "roles": list(action.get("roles") or []),
        "needs_search": bool(action.get("needs_search")),
        "search_remaining": search_remaining,
        "stall_cycles": stall_cycles,
        "parallel_lane": parallel,
        "human_gate": human_gate,
        "status": "TESTING",
        "samples": 1,
        "authority_change": False,
        "outgoing_spend_enabled": False,
        "autonomous_purchase": False,
        "binding_actions_human_gated": True,
        "production_deploy_human_gated": True,
    }

    core = _safe_dict(state.get("autonomy_core"))
    hints = core.setdefault("policy_hints", {})
    hints["superautonomy_current_plan"] = {
        "decision_id": decision["id"],
        "bottleneck": bottleneck,
        "target_metric": target_metric,
        "directive": action.get("directive"),
        "parallel_lane": parallel,
        "operating_rule": "Execute all reversible evidence-backed work autonomously; ask a human only for an existing binding/financial/legal/production gate.",
    }
    _apply_attention(core, action, stall_cycles, parallel)
    state["autonomy_core"] = core

    decisions = list(sup.get("decisions", []) or [])
    decisions.append(decision)
    sup["decisions"] = decisions[-MAX_DECISIONS:]
    sup["active_decision"] = decision
    sup.update({
        "version": VERSION,
        "status": "active",
        "stage": decision["stage"],
        "updated_at": _now(),
        "cycle": cycle,
        "bottleneck": bottleneck,
        "target_metric": target_metric,
        "current_action": action.get("id"),
        "current_directive": action.get("directive"),
        "parallel_lane": parallel,
        "search_remaining": search_remaining,
        "human_gate": human_gate,
        "learning_policy": "measured outcomes update action scores; stagnant tactics are demoted and reversible alternatives are rotated",
        "recovery_policy": "after repeated verified stagnation, rotate tactic and open one bounded zero-cost parallel lane when evidence supports it",
        "human_policy": "surface only explicit existing binding, payment, legal, connector, paid-spend or production approval gates",
        "guardrails": {
            "outgoing_spend_enabled": False,
            "autonomous_purchase": False,
            "binding_actions_human_gated": True,
            "production_deploy_human_gated": True,
            "new_connector_human_gated": True,
            "paid_media_human_gated": True,
            "fabricated_evidence_allowed": False,
            "authority_change": False,
        },
    })
    state["superautonomy"] = sup
    return sup


def _prepare_with_superautonomy(state: Dict[str, Any]) -> Dict[str, Any]:
    core = _ORIGINAL_PREPARE(state)
    superautonomy_prepare(state)
    return core


def _tick_with_superautonomy(state: Dict[str, Any]) -> Dict[str, Any]:
    core = _ORIGINAL_TICK(state)
    sup = superautonomy_prepare(state)
    core["superautonomy"] = {
        "version": sup.get("version"),
        "stage": sup.get("stage"),
        "bottleneck": sup.get("bottleneck"),
        "target_metric": sup.get("target_metric"),
        "current_action": sup.get("current_action"),
        "parallel_lane": sup.get("parallel_lane"),
        "human_gate": sup.get("human_gate"),
        "guardrails": sup.get("guardrails"),
    }
    state["autonomy_core"] = core
    return core


autonomy_core_runtime.autonomy_core_prepare = _prepare_with_superautonomy
autonomy_core_runtime.autonomy_core_tick = _tick_with_superautonomy

print({
    "superautonomy_runtime": {
        "version": VERSION,
        "status": "active",
        "loop": "observe -> prioritize -> act -> measure -> learn -> recover -> next action",
        "reversible_work_autonomous": True,
        "stagnation_recovery": True,
        "parallel_zero_cost_lane": True,
        "outgoing_spend_enabled": False,
        "autonomous_purchase": False,
        "binding_actions_human_gated": True,
        "production_deploy_human_gated": True,
        "authority_change": False,
    }
}, flush=True)
