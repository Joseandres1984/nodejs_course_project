from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from autonomy_governor import record_decision
from deal_safeguards import deal_safeguards_tick
from red_team_audit import red_team_tick
from revenue_factory import revenue_factory_tick
from master_orchestrator import master_orchestrator_tick
from strategy_simulator import strategy_simulator_tick


MAX_QUEUE = 80
MAX_TOP_ACTIONS = 12
RESOURCE_KEYS = ("core_research_pct", "deep_dive_pct", "expansion_pct", "exploration_pct")


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _financial_task(item: Dict[str, Any]) -> Dict[str, Any]:
    constraint = str(item.get("constraint") or "advance_pipeline")
    human_constraints = {"preclose_controls", "contract", "payment", "financial_commitment"}
    autonomous = constraint not in human_constraints
    risk = "high" if not autonomous else "low"
    money_score = max(0.0, min(100.0, _f(item.get("money_score"))))
    risk_profit = max(0.0, _f(item.get("risk_adjusted_expected_profit_usd")))
    impact = min(100.0, 55.0 + money_score * 0.45)
    urgency = min(100.0, 62.0 + money_score * 0.34)
    confidence = max(0.45, min(0.98, _f(item.get("close_probability"), 0.72)))
    priority = impact * 0.46 + urgency * 0.29 + confidence * 25.0
    if risk == "high":
        priority -= 18.0
    return {
        "key": f"warroom|{item.get('rank_key') or item.get('deal_id') or item.get('deep_dive_case_id')}",
        "kind": "money_priority",
        "title": f"Prioridad económica #{item.get('rank')}: {item.get('category') or item.get('buyer') or 'oportunidad'}",
        "reason": f"Money score {money_score:.1f}; beneficio esperado ajustado por riesgo USD {risk_profit:,.2f}; restricción: {constraint}.",
        "impact": round(impact, 2), "urgency": round(urgency, 2), "confidence": round(confidence, 2),
        "effort": 1.5, "risk": risk, "autonomous": autonomous,
        "object_type": "deal" if item.get("deal_id") else "deep_dive_case",
        "object_id": str(item.get("deal_id") or item.get("deep_dive_case_id") or ""),
        "payload": {"money_score": money_score, "risk_adjusted_expected_profit_usd": risk_profit, "constraint": constraint, "recommended_action": item.get("next_action"), "scenario_count": len(item.get("scenarios") or [])},
        "priority_score": round(max(0.0, priority / 1.12), 2), "created_at": utcnow(),
    }


def _revenue_task(factory: Dict[str, Any]) -> Dict[str, Any] | None:
    directive = factory.get("directive", {}) or {}
    if not directive:
        return None
    autonomous = bool(directive.get("autonomous", True))
    raw_priority = max(0.0, min(100.0, _f(directive.get("priority"), 75.0)))
    plan = factory.get("reverse_plan", {}) or {}
    target = factory.get("target", {}) or {}
    gap = plan.get("profit_gap_usd"); target_value = target.get("monthly_profit_target_usd"); coverage = factory.get("target_coverage_pct")
    reason_parts = [str(directive.get("title") or "Cerrar brecha del Revenue Factory")]
    if gap is not None: reason_parts.append(f"brecha económica USD {_f(gap):,.2f}")
    if target_value is not None: reason_parts.append(f"objetivo mensual USD {_f(target_value):,.2f}")
    if coverage is not None: reason_parts.append(f"cobertura {coverage}%")
    reason_parts.append(f"modelo {plan.get('status') or 'sin reverse plan completo'}")
    return {
        "key": f"revenue_factory|{directive.get('code') or 'maintain'}|{directive.get('stage') or 'company'}",
        "kind": "revenue_factory", "title": f"Revenue Factory: {directive.get('title') or directive.get('code')}", "reason": "; ".join(reason_parts),
        "impact": min(100.0, 72.0 + raw_priority * 0.28), "urgency": min(100.0, 65.0 + raw_priority * 0.30),
        "confidence": 0.9 if plan.get("status") == "reverse_plan_ready" else 0.68, "effort": 1.0,
        "risk": "high" if not autonomous else "low", "autonomous": autonomous, "object_type": "company", "object_id": "LUMEN",
        "payload": {"factory_code": directive.get("code"), "stage": directive.get("stage"), "gap": directive.get("gap"), "profit_gap_usd": gap, "target_usd": target_value, "coverage_pct": coverage, "target_source": target.get("source")},
        "priority_score": round(raw_priority * (0.92 if autonomous else 0.74), 2), "created_at": utcnow(),
    }


def _safeguard_task(safeguards: Dict[str, Any]) -> Dict[str, Any] | None:
    directive = safeguards.get("primary_directive", {}) or {}
    deal_id = directive.get("deal_id")
    if not deal_id:
        return None
    structure = directive.get("recommended_structure", {}) or {}
    gaps = list(directive.get("critical_gaps") or [])
    human = bool(directive.get("mandatory_legal_review")) or not bool(structure.get("autonomous", True))
    exposure = max(0.0, min(100.0, _f(directive.get("exposure_score"))))
    safe = max(0.0, min(100.0, _f(directive.get("safe_close_score"))))
    return {
        "key": f"deal_safeguards|{deal_id}|{structure.get('code') or 'review'}",
        "kind": "deal_safeguards",
        "title": f"Safe Close {deal_id}: {structure.get('title') or 'revisar exposición'}",
        "reason": f"Safe-close score {safe:.0f}/100; exposición {exposure:.0f}/100; gaps: {', '.join(gaps[:6]) or 'ninguno'}.",
        "impact": 100.0 if human else min(98.0, 84.0 + exposure * 0.14),
        "urgency": 100.0 if human else min(98.0, 78.0 + exposure * 0.18),
        "confidence": 0.96, "effort": 1.0, "risk": "high" if human else "medium",
        "autonomous": not human, "object_type": "deal", "object_id": str(deal_id),
        "payload": {"safe_close_score": safe, "exposure_score": exposure, "gaps": gaps, "recommended_structure": structure, "open_incidents": safeguards.get("open_incidents")},
        "priority_score": 99.0 if human else round(min(97.0, 82.0 + exposure * 0.12), 2),
        "created_at": utcnow(),
    }


def _red_team_task(red_team: Dict[str, Any]) -> Dict[str, Any] | None:
    primary = red_team.get("primary_finding") or {}
    if not primary:
        return None
    blocking = bool(primary.get("blocking"))
    severity = str(primary.get("severity") or "medium")
    priority = 99.0 if blocking else 93.0 if severity in {"critical", "high"} else 76.0
    return {
        "key": f"red_team|{primary.get('kind') or 'audit'}|{primary.get('object_type') or 'system'}|{primary.get('object_id') or 'LUMEN'}",
        "kind": "internal_red_team",
        "title": f"Auditor Interno: {primary.get('title') or 'revisar contradicción'}",
        "reason": str(primary.get("reason") or "La auditoría detectó una inconsistencia que merece revisión."),
        "impact": 100.0 if blocking else 86.0,
        "urgency": 100.0 if blocking else 82.0,
        "confidence": 0.97 if blocking else 0.78,
        "effort": 1.0,
        "risk": "high" if blocking else "medium",
        "autonomous": True,
        "object_type": str(primary.get("object_type") or "system"),
        "object_id": str(primary.get("object_id") or "LUMEN"),
        "payload": {"verdict": red_team.get("verdict"), "audit_score": red_team.get("audit_score"), "blocking": blocking, "recommendation": primary.get("recommendation")},
        "priority_score": priority,
        "created_at": utcnow(),
    }


def _governance_task(governance: Dict[str, Any]) -> Dict[str, Any] | None:
    mode = str(governance.get("company_mode") or "")
    if mode != "RECOVERY":
        return None
    return {
        "key": "master_orchestrator|recovery", "kind": "constitutional_recovery",
        "title": "Master Orchestrator: recuperar salud antes de operar", "reason": str(governance.get("reason") or "Prioridad constitucional de recuperación"),
        "impact": 100.0, "urgency": 100.0, "confidence": 0.99, "effort": 1.0, "risk": "high", "autonomous": True,
        "object_type": "company", "object_id": "LUMEN", "payload": {"company_mode": mode, "kill_switches": governance.get("kill_switches", {})},
        "priority_score": 100.0, "created_at": utcnow(),
    }


def _apply_simulator_overlay(state: Dict[str, Any], governance: Dict[str, Any], simulator: Dict[str, Any]) -> Dict[str, Any]:
    experiment = simulator.get("active_experiment") or {}
    switches = governance.get("kill_switches", {}) or {}
    mode = str(governance.get("company_mode") or "")
    result = {"applied": False, "experiment_id": experiment.get("id"), "scenario_id": experiment.get("scenario_id"), "reason": "no_active_experiment"}
    if not experiment or experiment.get("status") != "running":
        state["strategy_experiment_overlay"] = result
        return result
    if mode in {"RECOVERY", "PROTECT_CASH"} or switches.get("global_pause"):
        result["reason"] = f"constitutional_mode_blocks_experiment:{mode}"
        state["strategy_experiment_overlay"] = result
        return result
    if not experiment.get("reversible") or experiment.get("binding"):
        result["reason"] = "experiment_not_reversible_or_binding"
        state["strategy_experiment_overlay"] = result
        return result
    if _f(experiment.get("evidence_strength")) < 0.55:
        result["reason"] = "insufficient_experiment_evidence"
        state["strategy_experiment_overlay"] = result
        return result

    base = dict(governance.get("resource_plan", {}) or {})
    adjusted = dict(base)
    adjustments = experiment.get("adjustments", {}) or {}
    for key in RESOURCE_KEYS:
        adjusted[key] = max(0.0, min(100.0, _f(base.get(key)) + _f(adjustments.get(key))))
    if switches.get("expansion_pause"):
        adjusted["expansion_pct"] = 0.0
    total = sum(_f(adjusted.get(key)) for key in RESOURCE_KEYS)
    if total > 0:
        for key in RESOURCE_KEYS:
            adjusted[key] = round(_f(adjusted.get(key)) / total * 100.0, 1)
    for key in ("outbound_cap", "mission_queries_cap", "expansion_queries_cap", "daily_queries_remaining", "resource_type", "authorizes_spending"):
        if key in base:
            adjusted[key] = base[key]
    adjusted["digital_twin_experiment_id"] = experiment.get("id")
    adjusted["digital_twin_scenario_id"] = experiment.get("scenario_id")
    governance["resource_plan"] = adjusted
    governance["digital_twin_overlay"] = {
        "experiment_id": experiment.get("id"), "scenario_id": experiment.get("scenario_id"), "adjustments": adjustments,
        "evidence_strength": experiment.get("evidence_strength"), "hold_until_cycle": experiment.get("hold_until_cycle"),
        "rule": "Constitutional caps remain authoritative; only reversible attention allocation is adjusted.",
    }
    state["master_governance"] = governance
    state["master_resource_plan"] = adjusted
    result.update({"applied": True, "reason": "bounded_reversible_experiment", "adjusted_resource_plan": adjusted})
    state["strategy_experiment_overlay"] = result
    return result


def _apply_runtime_caps(state: Dict[str, Any], governance: Dict[str, Any]) -> Dict[str, Any]:
    policies = state.setdefault("policies", {})
    baseline = state.setdefault("master_policy_baseline", {})
    if "max_outbound_per_tick" not in baseline:
        baseline["max_outbound_per_tick"] = max(1, int(policies.get("max_outbound_per_tick", 3) or 3))
    configured_cap = max(1, int(baseline["max_outbound_per_tick"]))
    orchestrated_cap = max(0, int((governance.get("resource_plan", {}) or {}).get("outbound_cap", configured_cap) or 0))
    effective = min(configured_cap, orchestrated_cap) if orchestrated_cap > 0 else 1
    policies["max_outbound_per_tick"] = effective
    state["constitutional_runtime_caps"] = {
        "updated_at": utcnow(), "configured_outbound_cap": configured_cap,
        "orchestrated_outbound_cap": orchestrated_cap, "effective_outbound_cap": effective,
        "outbound_paused": bool((governance.get("kill_switches", {}) or {}).get("outbound_pause")),
    }
    return state["constitutional_runtime_caps"]


def financial_priority_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    # Safeguards runs after Trade + RevOps + Professional OS and before Communication/Quality.
    deal_safeguards = deal_safeguards_tick(state)
    revenue_factory = revenue_factory_tick(state)
    preflight = state.get("operational_guard", {}) or {}
    db_status = {"connected": bool(preflight.get("persistence_connected", True))}
    master_governance = master_orchestrator_tick(state, db_status, preflight=preflight)
    strategy_simulator = strategy_simulator_tick(state)
    simulator_overlay = _apply_simulator_overlay(state, master_governance, strategy_simulator)
    runtime_caps = _apply_runtime_caps(state, master_governance)

    # Internal Red Team is the final adversarial check before Communication Director + Quality Gate.
    # It may block reversible execution on strong contradictions, but never authorizes binding actions.
    red_team = red_team_tick(state)

    existing = list(state.get("operating_action_queue", []) or [])
    finance_tasks = [_financial_task(x) for x in list(state.get("war_room", {}).get("top_money_opportunities", []) or [])[:8]]
    revenue_task = _revenue_task(revenue_factory); revenue_tasks = [revenue_task] if revenue_task else []
    safeguard_task = _safeguard_task(deal_safeguards); safeguard_tasks = [safeguard_task] if safeguard_task else []
    red_team_task = _red_team_task(red_team); red_team_tasks = [red_team_task] if red_team_task else []
    governance_task = _governance_task(master_governance); governance_tasks = [governance_task] if governance_task else []

    by_key: Dict[str, Dict[str, Any]] = {}
    for task in [*existing, *finance_tasks, *revenue_tasks, *safeguard_tasks, *red_team_tasks, *governance_tasks]:
        key = str(task.get("key") or f"anon|{len(by_key)}")
        current = by_key.get(key)
        if current is None or _f(task.get("priority_score")) > _f(current.get("priority_score")):
            by_key[key] = task
    merged = sorted(by_key.values(), key=lambda x: _f(x.get("priority_score")), reverse=True)[:MAX_QUEUE]
    state["operating_action_queue"] = merged

    chief = state.setdefault("chief_of_staff", {})
    chief.update({
        "top_actions": merged[:MAX_TOP_ACTIONS], "financially_prioritized_at": utcnow(), "money_priority_actions": len(finance_tasks),
        "revenue_factory_actions": len(revenue_tasks), "revenue_factory_directive": (revenue_factory.get("directive") or {}).get("code"),
        "deal_safeguards_actions": len(safeguard_tasks), "deal_safeguards_blocked": deal_safeguards.get("blocked"),
        "deal_safeguards_open_incidents": deal_safeguards.get("open_incidents"),
        "red_team_verdict": red_team.get("verdict"), "red_team_audit_score": red_team.get("audit_score"),
        "red_team_blocking_findings": red_team.get("blocking"), "red_team_messages_blocked": red_team.get("messages_blocked"),
        "master_company_mode": master_governance.get("company_mode"), "master_conflicts_resolved": len(master_governance.get("conflicts_resolved", []) or []),
        "digital_twin_recommended": (strategy_simulator.get("recommended_scenario") or {}).get("id"),
        "digital_twin_active_experiment": (strategy_simulator.get("active_experiment") or {}).get("id"),
        "digital_twin_overlay_applied": bool(simulator_overlay.get("applied")),
        "autonomous_actions": sum(1 for x in merged if x.get("autonomous")), "human_decisions_required": sum(1 for x in merged if not x.get("autonomous")),
        "operating_rule": "Deal Safeguards + Counterparty Risk + Internal Red Team precede outbound quality; obey Constitution/Master; optimize safe risk-adjusted profit; binding commitments remain human-controlled",
    })

    top = merged[0] if merged else None
    if top:
        record_decision(state, engine="Financial Chief of Staff", object_type=str(top.get("object_type") or "company"), object_id=str(top.get("object_id") or "LUMEN"), decision="financially_prioritized_action", reason=str(top.get("reason") or top.get("title") or "Prioridad financiera-operativa"), action="score_opportunity" if top.get("autonomous") else "prepare_draft", confidence=max(0.5, min(0.99, _f(top.get("confidence"), 0.8))), evidence_refs=[], allowed=True, requires_approval=not bool(top.get("autonomous")))

    report = {
        "updated_at": utcnow(), "queue_size": len(merged), "money_priority_actions": len(finance_tasks),
        "revenue_factory_actions": len(revenue_tasks), "revenue_factory": revenue_factory,
        "deal_safeguards": deal_safeguards, "red_team": red_team,
        "master_governance": master_governance, "strategy_simulator": strategy_simulator,
        "strategy_experiment_overlay": simulator_overlay, "runtime_caps": runtime_caps,
        "top_action": top, "autonomous_actions": chief.get("autonomous_actions", 0), "human_decisions_required": chief.get("human_decisions_required", 0),
    }
    state["financial_chief_of_staff"] = report
    return report
