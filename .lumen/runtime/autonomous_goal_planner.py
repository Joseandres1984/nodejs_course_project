from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from autonomy_governor import record_decision

MAX_HISTORY = 192
GOAL_HOLD_CYCLES = 4


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


def _memory(state: Dict[str, Any]) -> Dict[str, Any]:
    memory = state.setdefault("goal_planner_memory", {})
    memory["cycle"] = _i(memory.get("cycle")) + 1
    memory.setdefault("history", [])
    memory.setdefault("active_goal", None)
    return memory


def _cash_realized(state: Dict[str, Any]) -> float:
    settlement = state.get("commission_settlement", {}) or {}
    received = _f(settlement.get("received_commissions_usd"))
    if received > 0:
        return round(received, 2)
    ledger = state.get("revenue_ledger", []) or []
    return round(sum(
        max(0.0, _f(x.get("amount")))
        for x in ledger
        if str(x.get("kind") or "") == "commission_settlement" and str(x.get("status") or "").startswith("realized")
    ), 2)


def _target(state: Dict[str, Any]) -> Dict[str, Any]:
    factory = state.get("revenue_factory", {}) or {}
    target = factory.get("target", {}) or {}
    amount = _f(target.get("monthly_profit_target_usd"))
    if amount > 0:
        return {
            "amount_usd": round(amount, 2),
            "source": target.get("source") or "revenue_factory",
            "confidence": target.get("confidence") or "unknown",
            "adaptive": bool(target.get("adaptive")),
        }
    capital = state.get("capital_margin_intelligence", {}) or {}
    risk_profit = _f((capital.get("summary", {}) or {}).get("risk_adjusted_expected_profit_usd"))
    if risk_profit > 0:
        return {
            "amount_usd": round(risk_profit * 1.15, 2),
            "source": "adaptive_from_current_risk_adjusted_portfolio",
            "confidence": "low",
            "adaptive": True,
            "note": "Objetivo provisional de planificación; no es pronóstico ni promesa de resultado.",
        }
    return {"amount_usd": None, "source": "insufficient_evidence", "confidence": "unknown", "adaptive": True}


def _signals(state: Dict[str, Any], realized: float, target: Dict[str, Any]) -> Dict[str, Any]:
    settlement_cases = state.get("commission_settlement_cases", []) or []
    overdue = sum(_f(x.get("outstanding_amount_usd")) for x in settlement_cases if x.get("status") in {"OVERDUE", "PARTIAL_RECEIVED"})
    closing = state.get("closing_orchestrator", {}) or {}
    capital = state.get("capital_margin_intelligence", {}) or {}
    cap_summary = capital.get("summary", {}) or {}
    safeguards = state.get("deal_safeguards_report", {}) or {}
    target_amount = _f(target.get("amount_usd"))
    gap = max(0.0, target_amount - realized) if target_amount > 0 else None
    return {
        "realized_cash_profit_usd": round(realized, 2),
        "target_usd": target_amount if target_amount > 0 else None,
        "profit_gap_usd": round(gap, 2) if gap is not None else None,
        "overdue_or_partial_commissions_usd": round(overdue, 2),
        "close_packs_ready": _i(closing.get("ready_for_human_approval")),
        "close_packs_blocked": _i(closing.get("blocked_risk")),
        "capital_accelerate": _i(cap_summary.get("accelerate")),
        "capital_improve_margin": _i(cap_summary.get("improve_margin")),
        "capital_hold_risk": _i(cap_summary.get("hold_risk")),
        "open_incidents": _i(safeguards.get("open_incidents")),
        "company_mode": str((state.get("master_governance", {}) or {}).get("company_mode") or "BALANCED"),
    }


def _choose_goal(state: Dict[str, Any], signals: Dict[str, Any]) -> Dict[str, Any]:
    mode = signals["company_mode"]
    if mode == "RECOVERY":
        return {"code": "RECOVER_OPERATIONS", "priority": 100, "reason": "La integridad operativa domina cualquier objetivo de beneficio hasta recuperar el sistema.", "autonomous": True}
    if signals["open_incidents"] > 0 or signals["close_packs_blocked"] > 0:
        return {"code": "PROTECT_EXISTING_VALUE", "priority": 99, "reason": "Hay exposición/incidentes en valor ya creado; repararlo evita destruir beneficio antes de crecer.", "autonomous": True}
    if signals["overdue_or_partial_commissions_usd"] > 0:
        return {"code": "COLLECT_REALIZED_VALUE", "priority": 98, "reason": "Existe dinero devengado con saldo pendiente; convertir cuentas por cobrar en caja tiene prioridad sobre crear riesgo nuevo.", "autonomous": True}
    if signals["close_packs_ready"] > 0:
        return {"code": "CLOSE_READY_VALUE", "priority": 97, "reason": "Hay negocios económicamente preparados y protegidos que solo necesitan la decisión vinculante correspondiente.", "autonomous": False}
    if signals["capital_accelerate"] > 0:
        return {"code": "ACCELERATE_BEST_DEALS", "priority": 94, "reason": "Existen deals con retorno ajustado por riesgo suficiente; concentrar capacidad en convertirlos.", "autonomous": True}
    if signals["capital_improve_margin"] > 0:
        return {"code": "DEFEND_MARGIN", "priority": 92, "reason": "La principal fuga visible es margen; mejorar economía antes de sumar volumen.", "autonomous": True}

    factory = state.get("revenue_factory", {}) or {}
    directive = factory.get("directive", {}) or {}
    if directive and str(directive.get("code") or "") != "maintain_factory":
        return {
            "code": "BUILD_REVENUE_ENGINE",
            "priority": max(75, _i(directive.get("priority"), 82)),
            "reason": str(directive.get("title") or "Cerrar el cuello de botella del funnel económico."),
            "autonomous": bool(directive.get("autonomous", True)),
            "factory_code": directive.get("code"),
            "factory_stage": directive.get("stage"),
        }
    return {"code": "BUILD_EVIDENCE_AND_PIPELINE", "priority": 76, "reason": "No existe valor maduro suficiente; aumentar evidencia y pipeline verificable sin inventar conversiones.", "autonomous": True}


def _milestones(state: Dict[str, Any], goal: Dict[str, Any], signals: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if signals["overdue_or_partial_commissions_usd"] > 0:
        rows.append({"code": "collect_receivables", "metric": "outstanding_commissions_usd", "target_direction": "down", "current": signals["overdue_or_partial_commissions_usd"], "priority": 100})
    if signals["close_packs_ready"] > 0:
        rows.append({"code": "resolve_ready_closures", "metric": "close_packs_ready", "target_direction": "down_via_decision", "current": signals["close_packs_ready"], "priority": 98})

    reverse = (state.get("revenue_factory", {}) or {}).get("reverse_plan", {}) or {}
    for stage, gap in (reverse.get("stage_gaps", {}) or {}).items():
        if _i(gap) > 0:
            rows.append({"code": f"fill_{stage}", "metric": stage, "target_direction": "close_gap", "current_gap": _i(gap), "priority": 90})
    if signals["capital_improve_margin"] > 0:
        rows.append({"code": "improve_margin", "metric": "deals_below_defended_margin", "target_direction": "down", "current": signals["capital_improve_margin"], "priority": 94})
    if signals["capital_hold_risk"] > 0:
        rows.append({"code": "repair_or_park_risky_deals", "metric": "capital_hold_risk", "target_direction": "down", "current": signals["capital_hold_risk"], "priority": 96})
    rows.sort(key=lambda x: _i(x.get("priority")), reverse=True)
    return rows[:10]


def _manage_goal(memory: Dict[str, Any], choice: Dict[str, Any], signals: Dict[str, Any]) -> Dict[str, Any]:
    cycle = _i(memory.get("cycle"))
    active = memory.get("active_goal")
    force_change = choice.get("code") in {"RECOVER_OPERATIONS", "PROTECT_EXISTING_VALUE", "COLLECT_REALIZED_VALUE"}
    if isinstance(active, dict) and active.get("status") == "active" and cycle < _i(active.get("hold_until_cycle")) and not force_change:
        return active
    if isinstance(active, dict) and active.get("status") == "active":
        active["status"] = "superseded"
        active["completed_at"] = utcnow()
        active["ending_realized_cash_profit_usd"] = signals.get("realized_cash_profit_usd")
        memory.setdefault("history", []).append(dict(active))
        memory["history"] = memory["history"][-MAX_HISTORY:]

    active = {
        "id": f"GOAL-{cycle:05d}-{choice.get('code')}",
        "code": choice.get("code"),
        "status": "active",
        "priority": choice.get("priority"),
        "reason": choice.get("reason"),
        "autonomous": choice.get("autonomous", True),
        "started_cycle": cycle,
        "hold_until_cycle": cycle + GOAL_HOLD_CYCLES,
        "started_at": utcnow(),
        "baseline_realized_cash_profit_usd": signals.get("realized_cash_profit_usd"),
        "factory_code": choice.get("factory_code"),
        "factory_stage": choice.get("factory_stage"),
    }
    memory["active_goal"] = active
    return active


def autonomous_goal_planner_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    memory = _memory(state)
    realized = _cash_realized(state)
    target = _target(state)
    signals = _signals(state, realized, target)
    choice = _choose_goal(state, signals)
    active = _manage_goal(memory, choice, signals)
    milestones = _milestones(state, active, signals)

    report = {
        "updated_at": utcnow(),
        "mode": "autonomous_profit_goal_planning",
        "target": target,
        "signals": signals,
        "active_goal": active,
        "milestones": milestones,
        "history_count": len(memory.get("history", [])),
        "operating_rule": "Priorizar caja y valor maduro antes que actividad nueva; usar conversiones observadas cuando existen y no inventar tasas faltantes.",
        "governance": {
            "objective": "Maximizar beneficio sostenible efectivamente cobrable y realizado, ajustado por riesgo.",
            "cash_truth": "El beneficio realizado para el Goal Planner se basa primero en comisiones explícitamente recibidas.",
            "authority": "El planner puede decidir prioridades y acciones reversibles; cierres vinculantes, pagos e inversión de capital siguen requiriendo autoridad humana.",
        },
    }
    state["autonomous_goal_planner"] = report
    state["profit_goal"] = active

    record_decision(
        state,
        engine="Autonomous Goal Planner",
        object_type="company",
        object_id="LUMEN",
        decision=f"goal:{str(active.get('code') or '').lower()}",
        reason=str(active.get("reason") or "Objetivo económico activo"),
        action="score_opportunity" if active.get("autonomous") else "request_human_close_approval",
        confidence=0.95 if active.get("code") in {"COLLECT_REALIZED_VALUE", "CLOSE_READY_VALUE", "PROTECT_EXISTING_VALUE"} else 0.82,
        evidence_refs=[],
        allowed=True,
        requires_approval=not bool(active.get("autonomous", True)),
    )
    return report
