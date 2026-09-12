from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from autonomy_governor import record_decision


TOP_OPPORTUNITIES = 10


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _deal_map(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(x.get("id")): x for x in state.get("deals", []) if x.get("id")}


def _scenario_pack(state: Dict[str, Any], row: Dict[str, Any], deal: Dict[str, Any]) -> List[Dict[str, Any]]:
    sale = _f(row.get("sale_price_usd"))
    supplier = _f(row.get("supplier_cost_usd"))
    logistics = _f(row.get("logistics_cost_usd"))
    current_profit = _f(row.get("company_profit_usd"))
    reserve_pct = _f(state.get("policies", {}).get("risk_reserve_pct"), 2.0) / 100.0
    max_discount = _f(state.get("policies", {}).get("max_auto_discount_pct"), 5.0) / 100.0

    def calc(name: str, sale_price: float, supplier_cost: float, note: str) -> Dict[str, Any]:
        reserve = sale_price * reserve_pct
        profit = sale_price - supplier_cost - logistics - reserve
        margin = profit / sale_price * 100.0 if sale_price > 0 else 0.0
        return {
            "scenario": name,
            "sale_price_usd": round(max(0.0, sale_price), 2),
            "supplier_cost_usd": round(max(0.0, supplier_cost), 2),
            "company_profit_usd": round(profit, 2),
            "margin_pct": round(margin, 2),
            "profit_delta_usd": round(profit - current_profit, 2),
            "note": note,
            "binding": False,
        }

    scenarios = [
        calc("protect_margin", sale, supplier, "Mantener precio y defender valor; no conceder descuento sin recibir algo a cambio."),
        calc("supplier_minus_3pct", sale, supplier * 0.97, "Mejorar costo proveedor 3% sin alterar precio al comprador."),
    ]
    if max_discount > 0 and sale > 0:
        scenarios.append(calc(
            "max_policy_discount",
            sale * (1.0 - max_discount),
            supplier,
            "Simulación del descuento máximo de política; no es una autorización para ofrecerlo.",
        ))
        scenarios.append(calc(
            "trade_discount_for_supplier_gain",
            sale * (1.0 - max_discount * 0.5),
            supplier * 0.97,
            "Ceder parcialmente al comprador solo si se obtiene mejora simultánea del proveedor.",
        ))
    return scenarios


def _constraint(row: Dict[str, Any], deal: Dict[str, Any]) -> str:
    flags = list(row.get("risk_flags") or [])
    stage = str(row.get("stage") or "")
    if flags:
        return str(flags[0])
    if stage in {"descubrimiento", "contacto preparado"}:
        return "buyer_validation"
    if stage in {"calificado", "esperando oferta"}:
        return "supplier_quote"
    if stage in {"propuesta", "propuesta preparada"}:
        return "buyer_decision"
    if stage in {"negociación", "renegociación"}:
        return "commercial_negotiation"
    if stage in {"preclose_validation", "listo para cerrar", "autorizado para cierre"}:
        return "preclose_controls"
    return "advance_pipeline"


def _top_money_opportunities(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    cfo_rows = state.get("cfo", {}).get("deal_financial_rankings", []) or []
    deals = _deal_map(state)
    deep_by_opp = {str(x.get("opportunity_id")): x for x in state.get("deep_dive_cases", []) if x.get("opportunity_id")}
    items: List[Dict[str, Any]] = []

    for row in cfo_rows:
        deal_id = str(row.get("deal_id") or "")
        deal = deals.get(deal_id, {})
        probability = _f(row.get("close_probability"))
        risk_profit = _f(row.get("risk_adjusted_expected_profit_usd"))
        money_score = _f(row.get("money_score"))
        margin = _f(row.get("margin_pct"))
        supplier_cost = _f(row.get("supplier_cost_usd"))
        roi_on_supplier_cost = (_f(row.get("company_profit_usd")) / supplier_cost * 100.0) if supplier_cost > 0 else 0.0
        items.append({
            "rank_key": deal_id,
            "deal_id": deal_id,
            "buyer": row.get("buyer"),
            "supplier": row.get("supplier"),
            "category": row.get("category"),
            "stage": row.get("stage"),
            "money_score": round(money_score, 2),
            "close_probability": round(probability, 3),
            "company_profit_usd": row.get("company_profit_usd"),
            "risk_adjusted_expected_profit_usd": round(risk_profit, 2),
            "margin_pct": round(margin, 2),
            "roi_on_supplier_cost_pct": round(roi_on_supplier_cost, 1),
            "constraint": _constraint(row, deal),
            "risk_flags": list(row.get("risk_flags") or []),
            "next_action": deal.get("next_action") or "Avanzar la oportunidad según su principal restricción",
            "scenarios": _scenario_pack(state, row, deal),
            "source": "real_deal_financial_model",
        })

    # Also surface evidence-backed deep-dive opportunities that have not yet become financial deals.
    known_deal_categories = {str(x.get("category") or "").lower() for x in items}
    for case in state.get("deep_dive_cases", []) or []:
        category = str(case.get("category") or "")
        if not category or category.lower() in known_deal_categories:
            continue
        win = _f(case.get("win_score"))
        priority = _f(case.get("portfolio_priority_score"))
        synthetic_score = min(89.0, win * 0.65 + priority * 0.35)
        items.append({
            "rank_key": str(case.get("id") or ""),
            "deal_id": None,
            "deep_dive_case_id": case.get("id"),
            "buyer": case.get("buyer_name"),
            "supplier": case.get("selected_supplier_name"),
            "category": category,
            "stage": "deep_dive",
            "money_score": round(synthetic_score, 2),
            "close_probability": None,
            "company_profit_usd": None,
            "risk_adjusted_expected_profit_usd": None,
            "margin_pct": None,
            "roi_on_supplier_cost_pct": None,
            "constraint": ((case.get("strategy", {}) or {}).get("primary_action", {}) or {}).get("code") or "complete_economics",
            "risk_flags": list(case.get("gaps") or []),
            "next_action": case.get("next_action"),
            "scenarios": [],
            "source": "evidence_backed_pre_financial_opportunity",
        })

    items.sort(
        key=lambda x: (
            1 if x.get("risk_adjusted_expected_profit_usd") is not None else 0,
            _f(x.get("money_score")),
            _f(x.get("risk_adjusted_expected_profit_usd")),
        ),
        reverse=True,
    )
    for idx, item in enumerate(items[:TOP_OPPORTUNITIES], start=1):
        item["rank"] = idx
    return items[:TOP_OPPORTUNITIES]


def _resource_allocation(top: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not top:
        return []
    scores = [max(1.0, _f(x.get("money_score"), 1.0)) for x in top[:5]]
    total = sum(scores)
    allocations = []
    for item, score in zip(top[:5], scores):
        allocations.append({
            "rank": item.get("rank"),
            "deal_id": item.get("deal_id"),
            "deep_dive_case_id": item.get("deep_dive_case_id"),
            "category": item.get("category"),
            "attention_pct": round(score / total * 100.0, 1) if total > 0 else 0.0,
            "constraint": item.get("constraint"),
            "recommended_action": item.get("next_action"),
        })
    return allocations


def _war_room_alerts(state: Dict[str, Any], top: List[Dict[str, Any]]) -> List[str]:
    alerts = list(state.get("cfo", {}).get("warnings", []) or [])
    if top and _f(top[0].get("money_score")) >= 80:
        alerts.append("high_value_opportunity_requires_focus")
    if top and top[0].get("risk_flags"):
        alerts.append("top_opportunity_has_unresolved_risk")
    if state.get("approval_briefs"):
        alerts.append("binding_decisions_waiting_human_approval")
    return list(dict.fromkeys(alerts))


def war_room_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    top = _top_money_opportunities(state)
    allocation = _resource_allocation(top)
    alerts = _war_room_alerts(state, top)
    top_item = top[0] if top else None

    report = {
        "updated_at": utcnow(),
        "mode": "executive_money_war_room",
        "top_money_opportunities": top,
        "resource_allocation": allocation,
        "alerts": alerts,
        "primary_money_move": ({
            "rank": top_item.get("rank"),
            "deal_id": top_item.get("deal_id"),
            "deep_dive_case_id": top_item.get("deep_dive_case_id"),
            "category": top_item.get("category"),
            "buyer": top_item.get("buyer"),
            "money_score": top_item.get("money_score"),
            "constraint": top_item.get("constraint"),
            "next_action": top_item.get("next_action"),
        } if top_item else None),
        "operating_rule": "poner atención incremental donde el beneficio esperado ajustado por riesgo y la probabilidad de avance sean mayores; no sacrificar controles de caja, margen, evidencia ni autoridad humana vinculante",
    }
    state["war_room"] = report

    if top_item:
        record_decision(
            state,
            engine="LUMEN War Room",
            object_type="deal" if top_item.get("deal_id") else "deep_dive_case",
            object_id=str(top_item.get("deal_id") or top_item.get("deep_dive_case_id") or ""),
            decision="primary_money_move",
            reason=(
                f"Ranking económico-operativo #1; money score {top_item.get('money_score', 0):.1f}; "
                f"restricción principal {top_item.get('constraint')}."
            ),
            action="score_opportunity",
            confidence=max(0.5, min(0.98, _f(top_item.get("close_probability"), 0.75) if top_item.get("close_probability") is not None else 0.75)),
            evidence_refs=[],
        )
    return report
