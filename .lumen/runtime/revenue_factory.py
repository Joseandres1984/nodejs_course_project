from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from autonomy_governor import record_decision

MIN_SAMPLE = 5
MAX_PLAN_ACTIONS = 10
MAX_HISTORY = 120


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


def _real_transactions(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    statuses = {"closed", "settled", "paid", "completed", "delivered", "invoiced"}
    return [x for x in state.get("transactions", []) if str(x.get("status") or "") in statuses]


def _counts(state: Dict[str, Any]) -> Dict[str, int]:
    accounts = state.get("candidate_accounts", []) or []
    verified = [x for x in accounts if x.get("verified_company")]
    buyers = [x for x in verified if x.get("type") == "buyer"]
    demand = [x for x in buyers if x.get("demand_signal")]
    opps = [x for x in state.get("market_opportunities", []) if x.get("source") == "public_evidence"]
    cases = state.get("interlocution_cases", []) or []
    req = [x for x in cases if x.get("supplier_rfq_ready")]
    offers = [x for x in state.get("offers", []) if x.get("source") != "demo/simulación"]
    comparisons = [x for x in state.get("quote_comparisons", []) if x.get("status") == "comparable"]
    proposals = [x for x in state.get("proposals", []) if x.get("source") != "demo/simulación"]
    tx = _real_transactions(state)
    return {
        "research_leads": len(state.get("research_leads", []) or []),
        "candidate_accounts": len(accounts),
        "verified_companies": len(verified),
        "verified_buyers": len(buyers),
        "buyers_with_demand": len(demand),
        "opportunities": len(opps),
        "requirements_ready": len(req),
        "real_offers": len(offers),
        "comparable_quote_sets": len(comparisons),
        "proposals": len(proposals),
        "real_transactions": len(tx),
    }


def _conversion(name: str, num: int, den: int) -> Dict[str, Any]:
    observed = den >= MIN_SAMPLE
    rate = round(num / den, 4) if den > 0 else None
    return {
        "name": name,
        "numerator": num,
        "denominator": den,
        "observed_rate": rate,
        "observed_rate_pct": round(rate * 100, 1) if rate is not None else None,
        "sample_sufficient": observed,
        "planning_status": "observed" if observed else "insufficient_history",
    }


def _funnel_model(counts: Dict[str, int]) -> List[Dict[str, Any]]:
    pairs = [
        ("lead_to_candidate", "candidate_accounts", "research_leads"),
        ("candidate_to_verified", "verified_companies", "candidate_accounts"),
        ("verified_buyer_to_demand", "buyers_with_demand", "verified_buyers"),
        ("demand_to_opportunity", "opportunities", "buyers_with_demand"),
        ("opportunity_to_requirement", "requirements_ready", "opportunities"),
        ("requirement_to_offer", "real_offers", "requirements_ready"),
        ("offer_to_comparable_set", "comparable_quote_sets", "real_offers"),
        ("comparable_to_proposal", "proposals", "comparable_quote_sets"),
        ("proposal_to_transaction", "real_transactions", "proposals"),
    ]
    return [_conversion(name, counts[num], counts[den]) for name, num, den in pairs]


def _profit_economics(state: Dict[str, Any]) -> Dict[str, Any]:
    tx = _real_transactions(state)
    realized_profits = [max(0.0, _f(x.get("company_profit"))) for x in tx if _f(x.get("company_profit")) > 0]
    real_deals = [x for x in state.get("deals", []) if x.get("source") != "demo"]
    known_deal_profits = [
        max(0.0, _f((x.get("economics") or {}).get("company_profit") or x.get("company_profit")))
        for x in real_deals
        if _f((x.get("economics") or {}).get("company_profit") or x.get("company_profit")) > 0
    ]
    avg_realized = round(sum(realized_profits) / len(realized_profits), 2) if realized_profits else None
    avg_known = round(sum(known_deal_profits) / len(known_deal_profits), 2) if known_deal_profits else None
    return {
        "real_transactions_with_profit": len(realized_profits),
        "economically_known_deals": len(known_deal_profits),
        "average_realized_profit_usd": avg_realized,
        "average_known_deal_profit_usd": avg_known,
        "planning_profit_per_deal_usd": avg_realized or avg_known,
        "planning_profit_confidence": "high" if len(realized_profits) >= MIN_SAMPLE else "medium" if realized_profits else "low" if known_deal_profits else "unknown",
    }


def _explicit_target() -> float | None:
    value = _f(os.getenv("LUMEN_MONTHLY_PROFIT_TARGET_USD", "0"))
    return value if value > 0 else None


def _corporate_target(state: Dict[str, Any]) -> Tuple[float | None, str | None]:
    brain = state.get("corporate_brain", {}) or {}
    objectives = (brain.get("objectives", {}) or {}).get("monthly", []) or []
    for obj in objectives:
        if not isinstance(obj, dict):
            continue
        metric = str(obj.get("metric") or "")
        target = _f(obj.get("target"))
        if metric in {"realized_profit_usd", "risk_adjusted_expected_profit_usd"} and target > 0:
            return target, f"corporate_brain:{metric}"
    return None, None


def _target(state: Dict[str, Any], economics: Dict[str, Any]) -> Dict[str, Any]:
    explicit = _explicit_target()
    if explicit:
        return {"monthly_profit_target_usd": round(explicit, 2), "source": "explicit_env", "confidence": "high", "adaptive": False}
    corporate, source = _corporate_target(state)
    if corporate:
        return {"monthly_profit_target_usd": round(corporate, 2), "source": source, "confidence": "medium", "adaptive": True}

    kpis = state.get("business_kpis", {}) or {}
    finance = kpis.get("finance", {}) or {}
    risk_profit = _f(finance.get("risk_adjusted_expected_profit_usd"))
    if risk_profit > 0:
        return {
            "monthly_profit_target_usd": round(risk_profit * 1.20, 2),
            "source": "adaptive_from_risk_adjusted_portfolio",
            "confidence": "low",
            "adaptive": True,
            "note": "Objetivo de planificación, no promesa de resultado; se recalibra con evidencia real.",
        }

    per_deal = _f(economics.get("planning_profit_per_deal_usd"))
    if per_deal > 0:
        return {
            "monthly_profit_target_usd": round(per_deal * 2.0, 2),
            "source": "adaptive_from_known_deal_economics",
            "confidence": "low",
            "adaptive": True,
            "note": "Bootstrap provisional hasta acumular suficiente historia de conversiones y operaciones reales.",
        }
    return {
        "monthly_profit_target_usd": None,
        "source": "not_established",
        "confidence": "unknown",
        "adaptive": True,
        "note": "Falta economía real suficiente para fijar una meta monetaria responsable.",
    }


def _current_realized_profit(state: Dict[str, Any]) -> float:
    kpis = state.get("business_kpis", {}) or {}
    finance = kpis.get("finance", {}) or {}
    value = _f(finance.get("realized_profit_usd"))
    if value > 0:
        return value
    return round(sum(max(0.0, _f(x.get("company_profit"))) for x in _real_transactions(state)), 2)


def _reverse_plan(target: Dict[str, Any], economics: Dict[str, Any], funnel: List[Dict[str, Any]], counts: Dict[str, int], realized: float) -> Dict[str, Any]:
    target_value = target.get("monthly_profit_target_usd")
    per_deal = economics.get("planning_profit_per_deal_usd")
    if not target_value:
        return {
            "status": "target_economics_missing",
            "profit_gap_usd": None,
            "required_transactions": None,
            "required_stage_counts": {},
            "confidence": "unknown",
        }
    gap = max(0.0, _f(target_value) - realized)
    if gap <= 0:
        return {"status": "target_covered", "profit_gap_usd": 0.0, "required_transactions": 0, "required_stage_counts": {}, "confidence": "high"}
    if not per_deal:
        return {
            "status": "unit_economics_missing",
            "profit_gap_usd": round(gap, 2),
            "required_transactions": None,
            "required_stage_counts": {},
            "confidence": "low",
        }

    required_tx = max(1, math.ceil(gap / _f(per_deal)))
    required: Dict[str, int] = {"real_transactions": required_tx}
    stage_chain = [
        ("proposal_to_transaction", "proposals"),
        ("comparable_to_proposal", "comparable_quote_sets"),
        ("offer_to_comparable_set", "real_offers"),
        ("requirement_to_offer", "requirements_ready"),
        ("opportunity_to_requirement", "opportunities"),
        ("demand_to_opportunity", "buyers_with_demand"),
        ("verified_buyer_to_demand", "verified_buyers"),
    ]
    by_name = {x["name"]: x for x in funnel}
    needed = required_tx
    complete = True
    for conv_name, stage in stage_chain:
        conv = by_name.get(conv_name, {})
        if not conv.get("sample_sufficient") or not conv.get("observed_rate"):
            complete = False
            break
        rate = _f(conv["observed_rate"])
        if rate <= 0:
            complete = False
            break
        needed = max(1, math.ceil(needed / rate))
        required[stage] = needed

    gaps = {stage: max(0, amount - counts.get(stage, 0)) for stage, amount in required.items()}
    return {
        "status": "reverse_plan_ready" if complete else "partial_reverse_plan",
        "profit_gap_usd": round(gap, 2),
        "required_transactions": required_tx,
        "required_stage_counts": required,
        "stage_gaps": gaps,
        "confidence": "high" if complete and economics.get("planning_profit_confidence") == "high" else "medium" if complete else "low",
        "note": "Las etapas sin muestra suficiente no se extrapolan con porcentajes inventados.",
    }


def _stage_pressure(counts: Dict[str, int], funnel: List[Dict[str, Any]], plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = []
    by_name = {x["name"]: x for x in funnel}
    stage_gaps = plan.get("stage_gaps", {}) or {}

    templates = [
        ("verified_buyers", "buyer_acquisition", "Encontrar y verificar más compradores con fit B2B", 84),
        ("buyers_with_demand", "demand_discovery", "Confirmar demanda pública real en compradores verificados", 90),
        ("opportunities", "opportunity_creation", "Convertir demanda verificada en oportunidades respaldadas por evidencia", 91),
        ("requirements_ready", "requirement_completion", "Completar requerimientos hasta dejarlos listos para RFQ", 94),
        ("real_offers", "rfq_execution", "Conseguir cotizaciones reales de proveedores verificados", 96),
        ("comparable_quote_sets", "supplier_competition", "Lograr al menos dos ofertas comparables por caso prioritario", 97),
        ("proposals", "proposal_conversion", "Convertir comparaciones completas en propuestas comerciales viables", 95),
        ("real_transactions", "close_conversion", "Mover casos viables hacia cierre sin saltar controles", 99),
    ]
    for stage, code, title, priority in templates:
        gap = _i(stage_gaps.get(stage))
        if gap > 0:
            actions.append({"code": code, "title": title, "stage": stage, "gap": gap, "priority": priority, "autonomous": code != "close_conversion"})

    if not actions:
        insufficient = [x for x in funnel if not x.get("sample_sufficient")]
        if insufficient:
            first = insufficient[0]
            actions.append({
                "code": "build_conversion_evidence",
                "title": f"Construir muestra para {first.get('name')}",
                "stage": first.get("name"),
                "gap": max(0, MIN_SAMPLE - _i(first.get("denominator"))),
                "priority": 82,
                "autonomous": True,
            })
    if counts.get("real_offers", 0) > 0 and counts.get("comparable_quote_sets", 0) == 0:
        actions.insert(0, {"code": "normalize_quotes", "title": "Completar términos de ofertas hasta hacerlas comparables", "stage": "real_offers", "gap": 1, "priority": 98, "autonomous": True})
    return sorted(actions, key=lambda x: x["priority"], reverse=True)[:MAX_PLAN_ACTIONS]


def _category_allocation(state: Dict[str, Any]) -> Dict[str, Any]:
    learning = state.get("profit_learning", {}) or {}
    memory = state.get("profit_learning_memory", {}) or {}
    rows = []
    for category, raw in (memory.get("category_scores", {}) or {}).items():
        if not isinstance(raw, dict):
            continue
        score = _f(raw.get("learned_score") or raw.get("score"), 50)
        conf = _f(raw.get("confidence"))
        obs = _i(raw.get("observations"))
        action = "explore"
        if conf >= 0.65 and obs >= 15 and score >= 70:
            action = "scale"
        elif conf >= 0.65 and obs >= 15 and score < 30:
            action = "pause"
        rows.append({"category": category, "score": round(score, 1), "confidence": round(conf, 2), "observations": obs, "action": action})
    rows.sort(key=lambda x: (x["action"] == "scale", x["score"], x["confidence"]), reverse=True)
    focus = [str(x.get("category")) for x in learning.get("focus_categories", []) if x.get("category")][:3]
    return {
        "focus_categories": focus,
        "scale": [x for x in rows if x["action"] == "scale"][:5],
        "pause": [x for x in rows if x["action"] == "pause"][:5],
        "rule": "escalar o pausar solo con confianza >= 0.65 y >= 15 observaciones; mantener exploración en el resto",
    }


def revenue_factory_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    counts = _counts(state)
    funnel = _funnel_model(counts)
    economics = _profit_economics(state)
    target = _target(state, economics)
    realized = _current_realized_profit(state)
    plan = _reverse_plan(target, economics, funnel, counts, realized)
    actions = _stage_pressure(counts, funnel, plan)
    allocation = _category_allocation(state)

    target_value = target.get("monthly_profit_target_usd")
    coverage = None
    if target_value and _f(target_value) > 0:
        coverage = round(min(100.0, realized / _f(target_value) * 100.0), 1)

    directive = actions[0] if actions else {
        "code": "maintain_factory",
        "title": "Mantener ejecución y recalibrar con nueva evidencia",
        "priority": 60,
        "autonomous": True,
    }
    report = {
        "updated_at": utcnow(),
        "mode": "autonomous_revenue_factory",
        "target": target,
        "realized_profit_usd": round(realized, 2),
        "target_coverage_pct": coverage,
        "economics": economics,
        "funnel_counts": counts,
        "funnel_model": funnel,
        "reverse_plan": plan,
        "factory_actions": actions,
        "category_allocation": allocation,
        "directive": directive,
        "operating_rule": "convertir objetivo económico en trabajo medible; no extrapolar conversiones sin muestra suficiente ni contar simulaciones como ingresos reales",
    }
    state["revenue_factory"] = report
    state.setdefault("revenue_factory_history", []).append({
        "ts": report["updated_at"], "target": target_value, "coverage_pct": coverage,
        "profit_gap_usd": plan.get("profit_gap_usd"), "directive": directive.get("code"),
    })
    state["revenue_factory_history"] = state["revenue_factory_history"][-MAX_HISTORY:]

    record_decision(
        state,
        engine="Autonomous Revenue Factory",
        object_type="company",
        object_id="LUMEN",
        decision=str(directive.get("code") or "maintain_factory"),
        reason=str(directive.get("title") or "Plan de producción de ingresos"),
        action="score_opportunity",
        confidence=0.9 if plan.get("status") == "reverse_plan_ready" else 0.65,
        evidence_refs=[],
        allowed=True,
        requires_approval=not bool(directive.get("autonomous", True)),
    )
    return report
