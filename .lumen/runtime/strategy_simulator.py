from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from autonomy_governor import record_decision


MIN_SAMPLE = 5
EXPERIMENT_HOLD_CYCLES = 8
MAX_HISTORY = 160
MAX_SCENARIOS = 8


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bounded(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _funnel_map(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    factory = state.get("revenue_factory", {}) or {}
    return {str(x.get("name")): x for x in factory.get("funnel_model", []) or [] if isinstance(x, dict) and x.get("name")}


def _metric_snapshot(state: Dict[str, Any]) -> Dict[str, Any]:
    factory = state.get("revenue_factory", {}) or {}
    counts = factory.get("funnel_counts", {}) or {}
    finance = (state.get("cfo", {}) or {}).get("financial_snapshot", {}) or {}
    return {
        "verified_buyers": _i(counts.get("verified_buyers")),
        "buyers_with_demand": _i(counts.get("buyers_with_demand")),
        "opportunities": _i(counts.get("opportunities")),
        "requirements_ready": _i(counts.get("requirements_ready")),
        "real_offers": _i(counts.get("real_offers")),
        "comparable_quote_sets": _i(counts.get("comparable_quote_sets")),
        "proposals": _i(counts.get("proposals")),
        "real_transactions": _i(counts.get("real_transactions")),
        "risk_adjusted_expected_profit_usd": round(_f(finance.get("risk_adjusted_expected_profit_usd")), 2),
        "realized_profit_usd": round(_f(finance.get("realized_profit_usd")), 2),
    }


def _downstream_value(state: Dict[str, Any], stage: str) -> Dict[str, Any]:
    funnel = _funnel_map(state)
    chain = {
        "verified_buyers": ["verified_buyer_to_demand", "demand_to_opportunity", "opportunity_to_requirement", "requirement_to_offer", "offer_to_comparable_set", "comparable_to_proposal", "proposal_to_transaction"],
        "buyers_with_demand": ["demand_to_opportunity", "opportunity_to_requirement", "requirement_to_offer", "offer_to_comparable_set", "comparable_to_proposal", "proposal_to_transaction"],
        "opportunities": ["opportunity_to_requirement", "requirement_to_offer", "offer_to_comparable_set", "comparable_to_proposal", "proposal_to_transaction"],
        "requirements_ready": ["requirement_to_offer", "offer_to_comparable_set", "comparable_to_proposal", "proposal_to_transaction"],
        "real_offers": ["offer_to_comparable_set", "comparable_to_proposal", "proposal_to_transaction"],
        "comparable_quote_sets": ["comparable_to_proposal", "proposal_to_transaction"],
        "proposals": ["proposal_to_transaction"],
        "real_transactions": [],
    }
    rates: List[float] = []
    evidence: List[Dict[str, Any]] = []
    complete = True
    for name in chain.get(stage, []):
        row = funnel.get(name, {})
        rate = row.get("observed_rate")
        sufficient = bool(row.get("sample_sufficient")) and rate is not None and _f(rate) > 0
        evidence.append({"conversion": name, "rate": rate, "sample_sufficient": sufficient, "denominator": row.get("denominator")})
        if not sufficient:
            complete = False
            break
        rates.append(_f(rate))

    probability = 1.0
    for rate in rates:
        probability *= rate

    economics = (state.get("revenue_factory", {}) or {}).get("economics", {}) or {}
    profit_per_deal = economics.get("planning_profit_per_deal_usd")
    dollar_value = None
    if complete and profit_per_deal is not None and _f(profit_per_deal) > 0:
        dollar_value = round(probability * _f(profit_per_deal), 2)
    return {
        "stage": stage,
        "downstream_probability": round(probability, 4) if complete else None,
        "marginal_expected_profit_per_successful_stage_unit_usd": dollar_value,
        "quantified": dollar_value is not None,
        "evidence": evidence,
        "note": "Valor por una unidad ya lograda en la etapa; no supone que asignar más recursos garantice crear esa unidad.",
    }


def _scenario_templates(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    governance = state.get("master_governance", {}) or {}
    mode = str(governance.get("company_mode") or "BALANCED")
    switches = governance.get("kill_switches", {}) or {}
    growth_ready = bool(((state.get("growth_expansion", {}) or {}).get("readiness", {}) or {}).get("ready"))
    bottleneck_stage = str(((state.get("revenue_factory", {}) or {}).get("directive", {}) or {}).get("stage") or "")
    rows = [
        {"id": "baseline", "title": "Mantener asignación actual", "target_stage": None, "adjustments": {}, "risk": "low", "reversible": True, "auto_eligible": False},
        {"id": "deepen_supplier_competition", "title": "Más foco en cotizaciones comparables", "target_stage": "comparable_quote_sets", "adjustments": {"deep_dive_pct": 10, "expansion_pct": -5, "exploration_pct": -5}, "risk": "low", "reversible": True, "auto_eligible": True},
        {"id": "accelerate_requirements", "title": "Más foco en requerimientos listos para RFQ", "target_stage": "requirements_ready", "adjustments": {"core_research_pct": 5, "deep_dive_pct": 5, "expansion_pct": -5, "exploration_pct": -5}, "risk": "low", "reversible": True, "auto_eligible": True},
        {"id": "core_market_density", "title": "Aumentar densidad del mercado base", "target_stage": "verified_buyers", "adjustments": {"core_research_pct": 10, "expansion_pct": -5, "exploration_pct": -5}, "risk": "low", "reversible": True, "auto_eligible": True},
        {"id": "controlled_expansion", "title": "Aumentar expansión internacional controlada", "target_stage": "verified_buyers", "adjustments": {"expansion_pct": 10, "core_research_pct": -5, "deep_dive_pct": -5}, "risk": "medium", "reversible": True, "auto_eligible": growth_ready and not bool(switches.get("expansion_pause"))},
        {"id": "close_pipeline_focus", "title": "Concentrar esfuerzo en propuestas/cierre", "target_stage": "proposals", "adjustments": {"deep_dive_pct": 10, "core_research_pct": -5, "exploration_pct": -5}, "risk": "low", "reversible": True, "auto_eligible": True},
    ]
    if mode in {"RECOVERY", "PROTECT_CASH", "BUILD_FOUNDATION"} or switches.get("expansion_pause"):
        for row in rows:
            if row["id"] == "controlled_expansion":
                row["auto_eligible"] = False
                row["constitutional_block"] = True
    for row in rows:
        row["bottleneck_stage"] = bottleneck_stage
    return rows[:MAX_SCENARIOS]


def _evidence_strength(value: Dict[str, Any]) -> float:
    evidence = value.get("evidence", []) or []
    if not evidence:
        return 0.35 if value.get("stage") == "real_transactions" else 0.20
    sufficient = [x for x in evidence if x.get("sample_sufficient")]
    if len(sufficient) != len(evidence):
        return min(0.55, len(sufficient) / max(1, len(evidence)))
    denominators = [_i(x.get("denominator")) for x in evidence]
    min_den = min(denominators) if denominators else 0
    return round(min(0.98, 0.60 + min(30, min_den) / 75.0), 2)


def _last_outcome_adjustment(state: Dict[str, Any], scenario_id: str) -> float:
    history = (state.get("strategy_simulator_memory", {}) or {}).get("experiment_history", []) or []
    rows = [x for x in history if x.get("scenario_id") == scenario_id and x.get("outcome")]
    if not rows:
        return 0.0
    outcome = str(rows[-1].get("outcome") or "")
    return {"supported": 6.0, "inconclusive": -4.0, "negative": -18.0}.get(outcome, 0.0)


def _scenario_score(state: Dict[str, Any], raw: Dict[str, Any]) -> Dict[str, Any]:
    scenario = dict(raw)
    stage = scenario.get("target_stage")
    value = _downstream_value(state, str(stage)) if stage else {"stage": None, "quantified": False, "marginal_expected_profit_per_successful_stage_unit_usd": None, "evidence": []}
    evidence = _evidence_strength(value)
    factory = state.get("revenue_factory", {}) or {}
    bottleneck = str((factory.get("directive", {}) or {}).get("stage") or "")
    fit = 100.0 if stage and stage == bottleneck else 72.0 if stage else 50.0
    adjacency = {
        "requirements_ready": {"real_offers", "opportunities"},
        "real_offers": {"requirements_ready", "comparable_quote_sets"},
        "comparable_quote_sets": {"real_offers", "proposals"},
        "proposals": {"comparable_quote_sets", "real_transactions"},
    }
    if stage in adjacency.get(bottleneck, set()) or bottleneck in adjacency.get(stage, set()):
        fit = max(fit, 86.0)

    marginal = value.get("marginal_expected_profit_per_successful_stage_unit_usd")
    money_signal = 50.0
    planning_profit = _f((factory.get("economics", {}) or {}).get("planning_profit_per_deal_usd"))
    if marginal is not None and planning_profit > 0:
        money_signal = _bounded(_f(marginal) / planning_profit * 100.0)
    risk_penalty = {"low": 0.0, "medium": 10.0, "high": 24.0}.get(str(scenario.get("risk")), 8.0)
    constitutional_penalty = 35.0 if scenario.get("constitutional_block") else 0.0
    learned_adjustment = _last_outcome_adjustment(state, str(scenario.get("id") or ""))
    score = fit * 0.44 + evidence * 100.0 * 0.30 + money_signal * 0.16 + (10.0 if scenario.get("reversible") else 0.0) - risk_penalty - constitutional_penalty + learned_adjustment
    if scenario.get("id") == "baseline":
        score = 55.0
    scenario.update({
        "evidence_strength": evidence,
        "bottleneck_fit": round(fit, 1),
        "marginal_value": value,
        "learned_adjustment": learned_adjustment,
        "simulation_score": round(_bounded(score), 2),
        "interpretation": "Ranking de experimento, no pronóstico de ventas. Combina cuello de botella, evidencia observada, valor marginal downstream, reversibilidad, riesgo y resultados previos del experimento.",
    })
    return scenario


def _experiment_state(state: Dict[str, Any]) -> Dict[str, Any]:
    memory = state.setdefault("strategy_simulator_memory", {})
    memory.setdefault("cycle", 0)
    memory.setdefault("active_experiment", None)
    memory.setdefault("experiment_history", [])
    return memory


def _finish_experiment(state: Dict[str, Any], active: Dict[str, Any], memory: Dict[str, Any]) -> None:
    current = _metric_snapshot(state)
    baseline = active.get("baseline_metrics", {}) or {}
    stage = str(active.get("target_stage") or "")
    stage_delta = _i(current.get(stage)) - _i(baseline.get(stage)) if stage else 0
    realized_delta = _f(current.get("realized_profit_usd")) - _f(baseline.get("realized_profit_usd"))
    risk_profit_delta = _f(current.get("risk_adjusted_expected_profit_usd")) - _f(baseline.get("risk_adjusted_expected_profit_usd"))
    if stage_delta > 0 or realized_delta > 0:
        outcome = "supported"
    elif stage_delta < 0 and realized_delta <= 0 and risk_profit_delta <= 0:
        outcome = "negative"
    else:
        outcome = "inconclusive"
    active.update({
        "status": "completed",
        "completed_at": utcnow(),
        "outcome": outcome,
        "outcome_metrics": current,
        "stage_delta": stage_delta,
        "realized_profit_delta_usd": round(realized_delta, 2),
        "risk_adjusted_profit_delta_usd": round(risk_profit_delta, 2),
        "evaluation_note": "Asociación operacional, no causalidad garantizada; el resultado ajusta futuras prioridades pero no prueba causalidad por sí solo.",
    })
    memory.setdefault("experiment_history", []).append(dict(active))
    memory["experiment_history"] = memory["experiment_history"][-MAX_HISTORY:]
    memory["active_experiment"] = None


def _select_experiment(state: Dict[str, Any], scenarios: List[Dict[str, Any]], memory: Dict[str, Any]) -> Dict[str, Any] | None:
    active = memory.get("active_experiment")
    cycle = _i(memory.get("cycle"))
    if isinstance(active, dict) and active.get("status") == "running":
        if cycle < _i(active.get("hold_until_cycle")):
            return active
        _finish_experiment(state, active, memory)

    eligible = [x for x in scenarios if x.get("auto_eligible") and x.get("reversible") and not x.get("constitutional_block") and _f(x.get("evidence_strength")) >= 0.55]
    if not eligible:
        return None
    winner = max(eligible, key=lambda x: _f(x.get("simulation_score")))
    if _f(winner.get("simulation_score")) < 68:
        return None
    experiment = {
        "id": f"SIMEXP-{cycle:05d}-{winner.get('id')}",
        "scenario_id": winner.get("id"),
        "title": winner.get("title"),
        "status": "running",
        "started_cycle": cycle,
        "hold_until_cycle": cycle + EXPERIMENT_HOLD_CYCLES,
        "started_at": utcnow(),
        "adjustments": dict(winner.get("adjustments") or {}),
        "baseline_resource_plan": dict(state.get("master_resource_plan", {}) or {}),
        "baseline_metrics": _metric_snapshot(state),
        "simulation_score": winner.get("simulation_score"),
        "evidence_strength": winner.get("evidence_strength"),
        "target_stage": winner.get("target_stage"),
        "binding": False,
        "reversible": True,
        "rule": "Solo reasigna atención/investigación dentro de límites constitucionales; no cambia precios, firma contratos ni autoriza gasto.",
    }
    memory["active_experiment"] = experiment
    return experiment


def strategy_simulator_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    memory = _experiment_state(state)
    memory["cycle"] = _i(memory.get("cycle")) + 1
    scenarios = [_scenario_score(state, x) for x in _scenario_templates(state)]
    scenarios.sort(key=lambda x: _f(x.get("simulation_score")), reverse=True)
    experiment = _select_experiment(state, scenarios, memory)
    report = {
        "updated_at": utcnow(),
        "cycle": memory["cycle"],
        "mode": "evidence_grounded_digital_twin",
        "scenarios": scenarios,
        "recommended_scenario": scenarios[0] if scenarios else None,
        "active_experiment": experiment,
        "completed_experiments": list(memory.get("experiment_history", []) or [])[-8:],
        "confidence_rule": "No auto-experimentar con evidencia < 0.55; las tasas del funnel requieren muestra suficiente; no inferir elasticidad precio-demanda sin historia específica.",
        "financial_rule": "Los valores en USD son sensibilidad downstream por unidad exitosa de etapa, no garantía de que una reasignación produzca esa unidad.",
        "authority_rule": "Solo experimentos reversibles sobre atención/investigación; contratos, pagos, precios vinculantes y compromisos financieros quedan fuera del simulador.",
    }
    state["strategy_simulator"] = report
    state.setdefault("strategy_simulator_history", []).append({"ts": report["updated_at"], "recommended": (report.get("recommended_scenario") or {}).get("id"), "score": (report.get("recommended_scenario") or {}).get("simulation_score"), "active_experiment": (experiment or {}).get("id")})
    state["strategy_simulator_history"] = state["strategy_simulator_history"][-MAX_HISTORY:]
    top = report.get("recommended_scenario") or {}
    if top:
        record_decision(state, engine="Strategy Simulator / Digital Twin", object_type="company_strategy", object_id="LUMEN", decision=f"simulate:{top.get('id')}", reason=f"Scenario score {top.get('simulation_score')}; evidence {top.get('evidence_strength')}; bottleneck fit {top.get('bottleneck_fit')}.", action="score_opportunity", confidence=max(0.5, min(0.98, _f(top.get("evidence_strength"), 0.5))), evidence_refs=[], allowed=True, requires_approval=False)
    return report
