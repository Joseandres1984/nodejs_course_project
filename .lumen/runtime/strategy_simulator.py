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
    return {
        str(x.get("name")): x
        for x in factory.get("funnel_model", []) or []
        if isinstance(x, dict) and x.get("name")
    }


def _downstream_value(state: Dict[str, Any], stage: str) -> Dict[str, Any]:
    """Value of one *successful unit already present at a stage*.

    This deliberately does NOT estimate how many stage units a resource shift will create.
    It only propagates an existing unit through observed downstream conversion rates.
    """
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
        evidence.append({
            "conversion": name,
            "rate": rate,
            "sample_sufficient": sufficient,
            "denominator": row.get("denominator"),
        })
        if not sufficient:
            complete = False
            break
        rates.append(_f(rate))

    probability = 1.0
    for rate in rates:
        probability *= rate

    factory = state.get("revenue_factory", {}) or {}
    economics = factory.get("economics", {}) or {}
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
        "note": "Este valor parte de una unidad ya lograda en la etapa; no supone que asignar más recursos garantice crear esa unidad.",
    }


def _scenario_templates(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    governance = state.get("master_governance", {}) or {}
    mode = str(governance.get("company_mode") or "BALANCED")
    switches = governance.get("kill_switches", {}) or {}
    growth = state.get("growth_expansion", {}) or {}
    growth_ready = bool((growth.get("readiness", {}) or {}).get("ready"))
    factory = state.get("revenue_factory", {}) or {}
    directive = factory.get("directive", {}) or {}
    bottleneck_stage = str(directive.get("stage") or "")

    rows = [
        {
            "id": "baseline",
            "title": "Mantener asignación actual",
            "target_stage": None,
            "adjustments": {},
            "risk": "low",
            "reversible": True,
            "auto_eligible": False,
        },
        {
            "id": "deepen_supplier_competition",
            "title": "Más foco en cotizaciones comparables",
            "target_stage": "comparable_quote_sets",
            "adjustments": {"deep_dive_pct": 10, "expansion_pct": -5, "exploration_pct": -5},
            "risk": "low",
            "reversible": True,
            "auto_eligible": True,
        },
        {
            "id": "accelerate_requirements",
            "title": "Más foco en requerimientos listos para RFQ",
            "target_stage": "requirements_ready",
            "adjustments": {"core_research_pct": 5, "deep_dive_pct": 5, "expansion_pct": -5, "exploration_pct": -5},
            "risk": "low",
            "reversible": True,
            "auto_eligible": True,
        },
        {
            "id": "core_market_density",
            "title": "Aumentar densidad del mercado base",
            "target_stage": "verified_buyers",
            "adjustments": {"core_research_pct": 10, "expansion_pct": -5, "exploration_pct": -5},
            "risk": "low",
            "reversible": True,
            "auto_eligible": True,
        },
        {
            "id": "controlled_expansion",
            "title": "Aumentar expansión internacional controlada",
            "target_stage": "verified_buyers",
            "adjustments": {"expansion_pct": 10, "core_research_pct": -5, "deep_dive_pct": -5},
            "risk": "medium",
            "reversible": True,
            "auto_eligible": growth_ready and not bool(switches.get("expansion_pause")),
        },
        {
            "id": "close_pipeline_focus",
            "title": "Concentrar esfuerzo en propuestas/cierre",
            "target_stage": "proposals",
            "adjustments": {"deep_dive_pct": 10, "core_research_pct": -5, "exploration_pct": -5},
            "risk": "low",
            "reversible": True,
            "auto_eligible": True,
        },
    ]

    # Constitutional hard exclusions.
    if mode in {"RECOVERY", "PROTECT_CASH", "BUILD_FOUNDATION"} or switches.get("expansion_pause"):
        for row in rows:
            if row["id"] == "controlled_expansion":
                row["auto_eligible"] = False
                row["constitutional_block"] = True

    # The current Revenue Factory bottleneck gets a fit bonus later.
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


def _scenario_score(state: Dict[str, Any], raw: Dict[str, Any]) -> Dict[str, Any]:
    scenario = dict(raw)
    stage = scenario.get("target_stage")
    value = _downstream_value(state, str(stage)) if stage else {
        "stage": None,
        "quantified": False,
        "marginal_expected_profit_per_successful_stage_unit_usd": None,
        "evidence": [],
    }
    evidence = _evidence_strength(value)
    factory = state.get("revenue_factory", {}) or {}
    directive = factory.get("directive", {}) or {}
    bottleneck = str(directive.get("stage") or "")
    fit = 100.0 if stage and stage == bottleneck else 72.0 if stage else 50.0

    # If the scenario is one step adjacent to a known bottleneck, still give it useful fit.
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
    score = fit * 0.44 + evidence * 100.0 * 0.30 + money_signal * 0.16 + (10.0 if scenario.get("reversible") else 0.0) - risk_penalty - constitutional_penalty
    if scenario.get("id") == "baseline":
        score = 55.0

    scenario.update({
        "evidence_strength": evidence,
        "bottleneck_fit": round(fit, 1),
        "marginal_value": value,
        "simulation_score": round(_bounded(score), 2),
        "interpretation": "Ranking de experimento, no pronóstico de ventas. El score combina cuello de botella, evidencia observada, valor marginal downstream, reversibilidad y riesgo.",
    })
    return scenario


def _experiment_state(state: Dict[str, Any]) -> Dict[str, Any]:
    memory = state.setdefault("strategy_simulator_memory", {})
    memory.setdefault("cycle", 0)
    memory.setdefault("active_experiment", None)
    memory.setdefault("experiment_history", [])
    return memory


def _select_experiment(state: Dict[str, Any], scenarios: List[Dict[str, Any]], memory: Dict[str, Any]) -> Dict[str, Any] | None:
    active = memory.get("active_experiment")
    cycle = _i(memory.get("cycle"))
    if isinstance(active, dict) and active.get("status") == "running":
        if cycle < _i(active.get("hold_until_cycle")):
            return active
        active["status"] = "completed_hold_period"
        active["completed_at"] = utcnow()
        memory.setdefault("experiment_history", []).append(active)
        memory["experiment_history"] = memory["experiment_history"][-MAX_HISTORY:]
        memory["active_experiment"] = None

    eligible = [
        x for x in scenarios
        if x.get("auto_eligible") and x.get("reversible") and not x.get("constitutional_block")
        and _f(x.get("evidence_strength")) >= 0.55
    ]
    if not eligible:
        return None
    winner = max(eligible, key=lambda x: _f(x.get("simulation_score")))
    if _f(winner.get("simulation_score")) < 68:
        return None

    baseline = dict(state.get("master_resource_plan", {}) or {})
    experiment = {
        "id": f"SIMEXP-{cycle:05d}-{winner.get('id')}",
        "scenario_id": winner.get("id"),
        "title": winner.get("title"),
        "status": "running",
        "started_cycle": cycle,
        "hold_until_cycle": cycle + EXPERIMENT_HOLD_CYCLES,
        "started_at": utcnow(),
        "adjustments": dict(winner.get("adjustments") or {}),
        "baseline_resource_plan": baseline,
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
    raw = _scenario_templates(state)
    scenarios = [_scenario_score(state, x) for x in raw]
    scenarios.sort(key=lambda x: _f(x.get("simulation_score")), reverse=True)
    experiment = _select_experiment(state, scenarios, memory)

    report = {
        "updated_at": utcnow(),
        "cycle": memory["cycle"],
        "mode": "evidence_grounded_digital_twin",
        "scenarios": scenarios,
        "recommended_scenario": scenarios[0] if scenarios else None,
        "active_experiment": experiment,
        "confidence_rule": "No auto-experimentar con evidencia < 0.55; las tasas del funnel requieren muestra suficiente; no inferir elasticidad precio-demanda sin historia específica.",
        "financial_rule": "Los valores en USD son sensibilidad downstream por unidad exitosa de etapa, no garantía de que una reasignación produzca esa unidad.",
        "authority_rule": "Solo experimentos reversibles sobre atención/investigación; contratos, pagos, precios vinculantes y compromisos financieros quedan fuera del simulador.",
    }
    state["strategy_simulator"] = report
    state.setdefault("strategy_simulator_history", []).append({
        "ts": report["updated_at"],
        "recommended": (report.get("recommended_scenario") or {}).get("id"),
        "score": (report.get("recommended_scenario") or {}).get("simulation_score"),
        "active_experiment": (experiment or {}).get("id"),
    })
    state["strategy_simulator_history"] = state["strategy_simulator_history"][-MAX_HISTORY:]

    top = report.get("recommended_scenario") or {}
    if top:
        record_decision(
            state,
            engine="Strategy Simulator / Digital Twin",
            object_type="company_strategy",
            object_id="LUMEN",
            decision=f"simulate:{top.get('id')}",
            reason=f"Scenario score {top.get('simulation_score')}; evidence {top.get('evidence_strength')}; bottleneck fit {top.get('bottleneck_fit')}.",
            action="score_opportunity",
            confidence=max(0.5, min(0.98, _f(top.get("evidence_strength"), 0.5))),
            evidence_refs=[],
            allowed=True,
            requires_approval=False,
        )
    return report
