from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from canonical_revenue_truth_runtime import canonical_revenue_truth_tick

VERSION = "1.1-first-cash-canonical"


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _realized_profit(state: Dict[str, Any]) -> float:
    finance = (state.get("business_kpis", {}) or {}).get("finance", {}) or {}
    cfo = state.get("cfo_war_room", {}) or {}
    snapshot = cfo.get("financial_snapshot", {}) or {}
    candidates = (
        finance.get("realized_profit_ars"), finance.get("realized_company_profit_ars"),
        finance.get("realized_profit_usd"), finance.get("realized_company_profit_usd"),
        snapshot.get("realized_profit_ars"), snapshot.get("realized_profit_usd"),
    )
    return max([_f(x) for x in candidates if x not in (None, "")] or [0.0])


def _cash_score(case: Dict[str, Any]) -> float:
    stage_rank = int(case.get("stage_rank") or 0)
    priority = _f(case.get("priority"), 50.0)
    score = priority * 0.55 + stage_rank * 6.0
    if case.get("human_required"):
        score -= 8.0
    if case.get("owner") == "LUMEN":
        score += 5.0
    economics = case.get("economics", {}) or {}
    if _f(economics.get("expected_profit")) > 0:
        score += 15.0
    if _f(economics.get("amount")) > 0:
        score += 6.0
    if case.get("deadline"):
        score += 4.0
    return round(max(0.0, min(100.0, score)), 1)


def first_cash_tick(state: Dict[str, Any], autonomy: Dict[str, Any] | None = None) -> Dict[str, Any]:
    autonomy = autonomy or (state.get("autonomy_operating_system", {}) or {})
    truth = canonical_revenue_truth_tick(state)
    realized = _realized_profit(state)
    active = realized <= 0.0
    allowed_opps = set(str(x) for x in truth.get("canonical_opportunity_ids", []) or [])
    allowed_deals = set(str(x) for x in truth.get("canonical_deal_ids", []) or [])
    cases: List[Dict[str, Any]] = list(autonomy.get("cases", []) or state.get("autonomy_cases", []) or [])

    ranked = []
    for case in cases:
        source_type = str(case.get("source_type") or "")
        source_id = str(case.get("source_id") or "")
        if source_type == "opportunity" and source_id not in allowed_opps:
            continue
        if source_type == "deal" and source_id not in allowed_deals:
            continue
        row = dict(case)
        row["first_cash_score"] = _cash_score(row)
        ranked.append(row)
    ranked.sort(key=lambda x: (x.get("first_cash_score", 0), x.get("stage_rank", 0)), reverse=True)

    top = ranked[:5]
    injected = 0
    if active:
        queue = state.setdefault("operating_action_queue", [])
        existing = {str(x.get("key") or "") for x in queue}
        for case in top:
            if case.get("owner") != "LUMEN" or case.get("human_required"):
                continue
            key = f"first_cash|{case.get('id')}|{case.get('stage')}"
            if key in existing:
                continue
            queue.insert(0, {
                "key": key, "kind": "first_cash_priority",
                "title": f"FIRST CASH: {case.get('title') or case.get('category') or case.get('id')}",
                "reason": f"Priorizar la primera ganancia realizada dentro del embudo canónico. Etapa {case.get('stage')}; cash score {case.get('first_cash_score')}; siguiente acción: {case.get('next_action')}",
                "impact": 100.0, "urgency": 96.0,
                "confidence": min(0.95, 0.55 + float(case.get("stage_rank") or 0) * 0.05),
                "effort": 1.0, "risk": "low", "autonomous": True,
                "object_type": "autonomy_case", "object_id": case.get("id"),
                "payload": {"stage": case.get("stage"), "next_action": case.get("next_action"), "cash_score": case.get("first_cash_score"), "source_type": case.get("source_type"), "source_id": case.get("source_id")},
                "priority_score": 100.0 - injected, "created_at": utcnow(),
            })
            existing.add(key); injected += 1
            if injected >= 3:
                break
        state["operating_action_queue"] = queue[:120]

    report = {
        "version": VERSION, "updated_at": utcnow(),
        "status": "ACTIVE" if active else "FIRST_PROFIT_ACHIEVED",
        "objective": "Obtener la primera ganancia realizada verificable" if active else "Escalar beneficio realizado preservando margen y riesgo",
        "realized_profit_detected": realized, "top_cash_cases": top, "actions_injected": injected,
        "canonical_truth_version": truth.get("version"), "canonical_lane": truth.get("recommended_lane"),
        "policy": {"contracts_payments_orders_remain_human_gated": True, "nonbinding_research_rfq_followup_negotiation_can_be_autonomous": True, "no_fake_revenue": True, "legacy_uncanonical_deals_excluded": True},
    }
    state["first_cash_mode"] = report
    return report
