from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from autonomy_governor import record_decision

MAX_HISTORY = 192
INTERVENTION_HOLD_CYCLES = 8
RESOURCE_KEYS = ("core_research_pct", "deep_dive_pct", "expansion_pct", "exploration_pct")


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


def _ensure(state: Dict[str, Any]) -> Dict[str, Any]:
    memory = state.setdefault("business_controller_memory", {})
    memory.setdefault("cycle", 0)
    memory.setdefault("snapshots", [])
    memory.setdefault("active_intervention", None)
    memory.setdefault("intervention_history", [])
    return memory


def _real_transactions(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    valid = {"closed", "settled", "paid", "completed", "delivered", "invoiced"}
    return [x for x in state.get("transactions", []) or [] if str(x.get("status") or "") in valid]


def _snapshot(state: Dict[str, Any], cycle: int) -> Dict[str, Any]:
    cfo = state.get("cfo", {}) or {}
    finance = cfo.get("financial_snapshot", {}) or {}
    capital = state.get("capital_margin_intelligence", {}) or {}
    cap_summary = capital.get("summary", {}) or {}
    safeguards = state.get("deal_safeguards_report", {}) or {}
    operations = state.get("operations_control", {}) or (state.get("connector_telemetry", {}) or {}).get("autonomous_coo", {}) or {}
    management = state.get("autonomous_management", {}) or {}

    offers = [x for x in state.get("offers", []) or [] if x.get("source") != "demo/simulación"]
    comparable = [x for x in state.get("quote_comparisons", []) or [] if x.get("status") == "comparable"]
    sent = [x for x in state.get("outbox", []) or [] if x.get("status") == "sent"]
    inbox = state.get("inbox", []) or []
    proposals = state.get("proposals", []) or []
    transactions = _real_transactions(state)
    safeguard_cases = state.get("deal_safeguard_cases", []) or []
    safe_scores = [_f(x.get("safe_close_score")) for x in safeguard_cases if x.get("safe_close_score") not in (None, "")]
    avg_safe = sum(safe_scores) / len(safe_scores) if safe_scores else 100.0

    failed = len((operations.get("engine_health", {}) or {}).get("failed_now", []) or [])
    circuits = len((operations.get("engine_health", {}) or {}).get("circuits_open", []) or [])
    response_rate = len(inbox) / len(sent) if sent else 0.0
    comparable_rate = len(comparable) / len(offers) if offers else 0.0
    proposal_to_tx = len(transactions) / len(proposals) if proposals else 0.0

    return {
        "cycle": cycle,
        "ts": utcnow(),
        "research_leads": len(state.get("research_leads", []) or []),
        "verified_companies": sum(1 for x in state.get("candidate_accounts", []) or [] if x.get("verified_company")),
        "outbound_sent": len(sent),
        "inbound_received": len(inbox),
        "real_offers": len(offers),
        "comparable_quote_sets": len(comparable),
        "proposals": len(proposals),
        "real_transactions": len(transactions),
        "response_rate": round(response_rate, 4),
        "comparable_rate": round(comparable_rate, 4),
        "proposal_to_transaction_rate": round(proposal_to_tx, 4),
        "realized_profit_usd": round(_f(finance.get("realized_profit_usd")), 2),
        "risk_adjusted_expected_profit_usd": round(_f(finance.get("risk_adjusted_expected_profit_usd")), 2),
        "gross_unsettled_receivable_usd": round(_f(finance.get("gross_unsettled_receivable_usd")), 2),
        "avg_safe_close": round(avg_safe, 2),
        "open_incidents": _i(safeguards.get("open_incidents")),
        "legal_review_count": _i(safeguards.get("mandatory_legal_review")),
        "capital_accelerate": _i(cap_summary.get("accelerate")),
        "capital_improve_margin": _i(cap_summary.get("improve_margin")),
        "capital_hold_risk": _i(cap_summary.get("hold_risk")),
        "management_score": _f(management.get("company_management_score"), 50.0),
        "health_score": _f(operations.get("health_score"), 100.0),
        "failed_engines": failed,
        "open_circuits": circuits,
    }


def _delta(current: Dict[str, Any], previous: Dict[str, Any], key: str) -> float:
    return _f(current.get(key)) - _f(previous.get(key))


def _signals(current: Dict[str, Any], previous: Dict[str, Any] | None) -> Dict[str, Any]:
    if not previous:
        return {
            "history_ready": False,
            "profit_delta": 0.0,
            "risk_profit_delta": 0.0,
            "outbound_delta": 0,
            "lead_delta": 0,
            "safe_close_delta": 0.0,
            "activity_without_value": False,
            "risk_deterioration": False,
            "conversion_improving": False,
        }
    profit_delta = _delta(current, previous, "realized_profit_usd")
    risk_profit_delta = _delta(current, previous, "risk_adjusted_expected_profit_usd")
    outbound_delta = _i(current.get("outbound_sent")) - _i(previous.get("outbound_sent"))
    lead_delta = _i(current.get("research_leads")) - _i(previous.get("research_leads"))
    safe_delta = _delta(current, previous, "avg_safe_close")
    activity_without_value = (outbound_delta > 0 or lead_delta >= 3) and risk_profit_delta <= 0 and profit_delta <= 0
    risk_deterioration = safe_delta <= -8.0 or _i(current.get("open_incidents")) > _i(previous.get("open_incidents"))
    conversion_improving = (
        _delta(current, previous, "comparable_rate") > 0.05
        or _delta(current, previous, "proposal_to_transaction_rate") > 0.03
        or profit_delta > 0
    )
    return {
        "history_ready": True,
        "profit_delta": round(profit_delta, 2),
        "risk_profit_delta": round(risk_profit_delta, 2),
        "outbound_delta": outbound_delta,
        "lead_delta": lead_delta,
        "safe_close_delta": round(safe_delta, 2),
        "activity_without_value": activity_without_value,
        "risk_deterioration": risk_deterioration,
        "conversion_improving": conversion_improving,
    }


def _choose_mode(state: Dict[str, Any], current: Dict[str, Any], signals: Dict[str, Any]) -> Dict[str, Any]:
    governance = state.get("master_governance", {}) or {}
    company_mode = str(governance.get("company_mode") or "BALANCED")
    if company_mode == "RECOVERY" or current["failed_engines"] or current["open_circuits"]:
        return {"mode": "RECOVER", "priority": 100, "reason": "La confiabilidad domina cualquier objetivo económico hasta recuperar operación estable."}
    if company_mode == "PROTECT_CASH" or current["gross_unsettled_receivable_usd"] > max(1000.0, current["risk_adjusted_expected_profit_usd"] * 1.5):
        return {"mode": "PROTECT_CASH", "priority": 99, "reason": "La exposición de cobro/caja exige convertir y cobrar antes de ampliar riesgo."}
    if signals.get("risk_deterioration") or current["open_incidents"] or current["legal_review_count"]:
        return {"mode": "PROTECT_VALUE", "priority": 97, "reason": "El beneficio potencial está acompañado por deterioro de Safe Close/incidentes; reparar exposición antes de crecer."}
    if signals.get("activity_without_value"):
        return {"mode": "CONVERT_ACTIVITY", "priority": 94, "reason": "Aumentó actividad sin crecimiento de beneficio ajustado; reducir exploración y concentrar conversión."}
    if current["capital_improve_margin"] > current["capital_accelerate"] and current["capital_improve_margin"] >= 1:
        return {"mode": "DEFEND_MARGIN", "priority": 91, "reason": "La principal fuga económica está en margen; mejorar costo/términos antes de perseguir más volumen."}
    if current["capital_accelerate"] >= 1 and current["risk_adjusted_expected_profit_usd"] > 0:
        return {"mode": "ACCELERATE_WINNERS", "priority": 90, "reason": "Existen deals con retorno, margen y riesgo suficientemente buenos; concentrar ejecución en ganadores."}
    if current["real_offers"] > 0 and current["comparable_quote_sets"] == 0:
        return {"mode": "BUILD_COMPARABILITY", "priority": 88, "reason": "Hay ofertas pero falta competencia comparable; profundizar procurement antes de proponer."}
    if current["proposals"] > 0 and current["real_transactions"] == 0:
        return {"mode": "CLOSE_PIPELINE", "priority": 87, "reason": "Existe pipeline comercial avanzado sin conversión real; priorizar cierre seguro sobre descubrimiento."}
    return {"mode": "BUILD_VALUE", "priority": 78, "reason": "No hay una fuga dominante; aumentar evidencia, demanda y oportunidades manteniendo disciplina económica."}


def _adjustments(mode: str) -> Dict[str, float]:
    return {
        "RECOVER": {},
        "PROTECT_CASH": {"deep_dive_pct": 8, "core_research_pct": -4, "expansion_pct": -4},
        "PROTECT_VALUE": {"deep_dive_pct": 8, "exploration_pct": -4, "expansion_pct": -4},
        "CONVERT_ACTIVITY": {"deep_dive_pct": 10, "core_research_pct": -5, "exploration_pct": -5},
        "DEFEND_MARGIN": {"deep_dive_pct": 10, "expansion_pct": -5, "exploration_pct": -5},
        "ACCELERATE_WINNERS": {"deep_dive_pct": 10, "core_research_pct": -5, "exploration_pct": -5},
        "BUILD_COMPARABILITY": {"deep_dive_pct": 10, "core_research_pct": -5, "exploration_pct": -5},
        "CLOSE_PIPELINE": {"deep_dive_pct": 10, "core_research_pct": -5, "expansion_pct": -5},
        "BUILD_VALUE": {"core_research_pct": 5, "exploration_pct": 3, "deep_dive_pct": -5, "expansion_pct": -3},
    }.get(mode, {})


def _finish_intervention(memory: Dict[str, Any], active: Dict[str, Any], current: Dict[str, Any]) -> None:
    baseline = active.get("baseline", {}) or {}
    profit_delta = _f(current.get("realized_profit_usd")) - _f(baseline.get("realized_profit_usd"))
    risk_profit_delta = _f(current.get("risk_adjusted_expected_profit_usd")) - _f(baseline.get("risk_adjusted_expected_profit_usd"))
    safe_delta = _f(current.get("avg_safe_close")) - _f(baseline.get("avg_safe_close"))
    tx_delta = _i(current.get("real_transactions")) - _i(baseline.get("real_transactions"))
    if profit_delta > 0 or tx_delta > 0 or (risk_profit_delta > 0 and safe_delta >= -3):
        outcome = "supported"
    elif risk_profit_delta < 0 and safe_delta < -5:
        outcome = "negative"
    else:
        outcome = "inconclusive"
    active.update({
        "status": "completed",
        "completed_at": utcnow(),
        "outcome": outcome,
        "realized_profit_delta_usd": round(profit_delta, 2),
        "risk_adjusted_profit_delta_usd": round(risk_profit_delta, 2),
        "safe_close_delta": round(safe_delta, 2),
        "transaction_delta": tx_delta,
        "evaluation_note": "Operational association only; outcome influences future control decisions but does not prove causality.",
    })
    memory.setdefault("intervention_history", []).append(dict(active))
    memory["intervention_history"] = memory["intervention_history"][-MAX_HISTORY:]
    memory["active_intervention"] = None


def _manage_intervention(memory: Dict[str, Any], choice: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any] | None:
    cycle = _i(memory.get("cycle"))
    active = memory.get("active_intervention")
    if isinstance(active, dict) and active.get("status") == "running":
        if cycle < _i(active.get("hold_until_cycle")):
            return active
        _finish_intervention(memory, active, current)

    if choice.get("mode") in {"RECOVER"}:
        return None
    intervention = {
        "id": f"CTRL-{cycle:05d}-{choice.get('mode')}",
        "mode": choice.get("mode"),
        "status": "running",
        "started_at": utcnow(),
        "started_cycle": cycle,
        "hold_until_cycle": cycle + INTERVENTION_HOLD_CYCLES,
        "baseline": dict(current),
        "adjustments": _adjustments(str(choice.get("mode"))),
        "reason": choice.get("reason"),
        "binding": False,
        "reversible": True,
    }
    memory["active_intervention"] = intervention
    return intervention


def _apply_overlay(state: Dict[str, Any], intervention: Dict[str, Any] | None) -> Dict[str, Any]:
    governance = state.get("master_governance", {}) or {}
    switches = governance.get("kill_switches", {}) or {}
    mode = str(governance.get("company_mode") or "")
    base = dict(governance.get("resource_plan", {}) or state.get("master_resource_plan", {}) or {})
    result = {"applied": False, "reason": "no_controller_intervention", "base_resource_plan": base}
    if not intervention or not base:
        state["business_controller_overlay"] = result
        return result
    if mode in {"RECOVERY", "PROTECT_CASH"} or switches.get("global_pause"):
        result["reason"] = f"constitutional_mode_blocks_controller:{mode}"
        state["business_controller_overlay"] = result
        return result

    adjusted = dict(base)
    changes = intervention.get("adjustments", {}) or {}
    for key in RESOURCE_KEYS:
        adjusted[key] = max(0.0, min(100.0, _f(base.get(key)) + _f(changes.get(key))))
    if switches.get("expansion_pause"):
        adjusted["expansion_pct"] = 0.0
    total = sum(_f(adjusted.get(k)) for k in RESOURCE_KEYS)
    if total > 0:
        for key in RESOURCE_KEYS:
            adjusted[key] = round(_f(adjusted.get(key)) / total * 100.0, 1)

    # Never widen operational/financial authority or caps.
    for key in ("outbound_cap", "mission_queries_cap", "expansion_queries_cap", "daily_queries_remaining", "resource_type", "authorizes_spending"):
        if key in base:
            adjusted[key] = base[key]
    governance["resource_plan"] = adjusted
    governance["business_controller_overlay"] = {
        "intervention_id": intervention.get("id"),
        "mode": intervention.get("mode"),
        "adjustments": changes,
        "rule": "bounded reversible attention allocation below Constitution and safety gates",
    }
    state["master_governance"] = governance
    state["master_resource_plan"] = adjusted
    result.update({"applied": True, "reason": "bounded_controller_intervention", "adjusted_resource_plan": adjusted, "intervention_id": intervention.get("id")})
    state["business_controller_overlay"] = result
    return result


def _control_score(current: Dict[str, Any]) -> float:
    profit = min(100.0, max(0.0, current["risk_adjusted_expected_profit_usd"] / 30.0))
    realized = min(100.0, max(0.0, current["realized_profit_usd"] / 20.0))
    safe = max(0.0, min(100.0, current["avg_safe_close"]))
    conversion = min(100.0, current["comparable_rate"] * 100.0 * 0.45 + current["proposal_to_transaction_rate"] * 100.0 * 0.55)
    reliability = max(0.0, min(100.0, current["health_score"] - current["failed_engines"] * 15 - current["open_circuits"] * 15))
    return round(profit * 0.27 + realized * 0.18 + safe * 0.20 + conversion * 0.17 + reliability * 0.18, 1)


def _materialize_task(state: Dict[str, Any], choice: Dict[str, Any], score: float) -> Dict[str, Any]:
    task = {
        "key": f"business_controller|{choice.get('mode')}",
        "kind": "business_controller",
        "title": f"Business Controller: {choice.get('mode')}",
        "reason": choice.get("reason"),
        "impact": max(72.0, min(100.0, _f(choice.get("priority")))),
        "urgency": max(70.0, min(100.0, _f(choice.get("priority")))),
        "confidence": 0.90,
        "effort": 1.0,
        "risk": "low",
        "autonomous": True,
        "object_type": "company",
        "object_id": "LUMEN",
        "payload": {"control_score": score, "mode": choice.get("mode")},
        "priority_score": round(_f(choice.get("priority")), 2),
        "created_at": utcnow(),
    }
    queue = list(state.get("operating_action_queue", []) or [])
    by_key = {str(x.get("key")): x for x in queue if x.get("key")}
    by_key[task["key"]] = task
    state["operating_action_queue"] = sorted(by_key.values(), key=lambda x: _f(x.get("priority_score")), reverse=True)[:80]
    return task


def business_controller_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    memory = _ensure(state)
    memory["cycle"] = _i(memory.get("cycle")) + 1
    current = _snapshot(state, memory["cycle"])
    previous = (memory.get("snapshots") or [])[-1] if memory.get("snapshots") else None
    signals = _signals(current, previous)
    choice = _choose_mode(state, current, signals)
    intervention = _manage_intervention(memory, choice, current)
    overlay = _apply_overlay(state, intervention)
    score = _control_score(current)
    task = _materialize_task(state, choice, score)

    memory.setdefault("snapshots", []).append(current)
    memory["snapshots"] = memory["snapshots"][-MAX_HISTORY:]

    report = {
        "updated_at": utcnow(),
        "mode": "autonomous_business_controller",
        "cycle": memory["cycle"],
        "company_control_score": score,
        "control_mode": choice.get("mode"),
        "control_priority": choice.get("priority"),
        "reason": choice.get("reason"),
        "current_snapshot": current,
        "signals": signals,
        "active_intervention": intervention,
        "intervention_overlay": overlay,
        "recent_interventions": list(memory.get("intervention_history", []) or [])[-8:],
        "operating_task": task,
        "governance": {
            "objective": "maximize sustainable realized and risk-adjusted profit, not activity volume",
            "anti_thrash": f"interventions are held at least {INTERVENTION_HOLD_CYCLES} cycles before outcome evaluation",
            "authority": "may reprioritize reversible attention and park/deprioritize work; cannot expand caps, spend, order, pay, sign, accept liability or binding terms",
            "truth_rule": "controller treats missing cash/runway data as unknown and never invents financial capacity",
        },
    }
    state["business_controller"] = report

    record_decision(
        state,
        engine="Autonomous Business Controller",
        object_type="company",
        object_id="LUMEN",
        decision=f"control_mode:{str(choice.get('mode') or '').lower()}",
        reason=str(choice.get("reason") or "Continuous company control"),
        action="score_opportunity",
        confidence=0.92,
        evidence_refs=[],
        allowed=True,
        requires_approval=False,
    )
    return report
