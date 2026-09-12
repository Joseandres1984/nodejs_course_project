from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from statistics import median
from typing import Any, Dict, List

from autonomy_governor import record_decision

MAX_DEALS = 40
MAX_CATEGORY_ROWS = 30


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _pct(value: float, total: float) -> float:
    return 0.0 if total <= 0 else max(0.0, min(100.0, value / total * 100.0))


def _policy(state: Dict[str, Any]) -> Dict[str, float]:
    policies = state.get("policies", {}) or {}
    return {
        "minimum_margin_pct": max(0.0, _f(policies.get("min_company_share_pct"), 8.0)),
        "target_margin_pct": max(0.0, _f(policies.get("target_company_share_pct"), 12.0)),
        "risk_reserve_pct": max(0.0, _f(policies.get("risk_reserve_pct"), 2.0)),
    }


def _safe_score(row: Dict[str, Any]) -> float:
    value = row.get("safe_close_score")
    return 72.0 if value in (None, "") else max(0.0, min(100.0, _f(value)))


def _risk_margin_premium(row: Dict[str, Any]) -> float:
    safe = _safe_score(row)
    penalty = _f(row.get("risk_penalty_pct"))
    flags = set(str(x) for x in row.get("risk_flags", []) or [])
    premium = max(0.0, (80.0 - safe) / 10.0) + penalty / 25.0
    if "cash_gap_risk" in flags:
        premium += 1.5
    if "cross_border_terms_incomplete" in flags:
        premium += 1.0
    if "legal_review_required" in flags or "commercial_incident_open" in flags:
        premium += 3.0
    return round(min(8.0, premium), 2)


def _deal_rows(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    policy = _policy(state)
    source = list((state.get("cfo", {}) or {}).get("deal_financial_rankings", []) or [])
    deals = {str(x.get("id")): x for x in state.get("deals", []) if x.get("id")}
    rows: List[Dict[str, Any]] = []

    for raw in source[:MAX_DEALS]:
        row = dict(raw)
        deal_id = str(row.get("deal_id") or "")
        deal = deals.get(deal_id, {})
        profit = max(0.0, _f(row.get("company_profit_usd")))
        risk_profit = max(0.0, _f(row.get("risk_adjusted_expected_profit_usd")))
        exposure = max(0.0, _f(row.get("modeled_supplier_cost_if_won_usd")))
        margin = max(0.0, _f(row.get("margin_pct")))
        probability = max(0.0, min(1.0, _f(row.get("close_probability"))))
        safe = _safe_score(row)
        risk_premium = _risk_margin_premium(row)
        defended_target = round(max(policy["target_margin_pct"], policy["minimum_margin_pct"] + risk_premium), 2)
        margin_gap = round(margin - defended_target, 2)
        capital_efficiency = risk_profit / exposure if exposure > 0 else None
        expected_return_pct = (capital_efficiency * 100.0) if capital_efficiency is not None else None
        supplier_cost = max(0.0, _f(row.get("supplier_cost_usd")))
        sale = max(0.0, _f(row.get("sale_price_usd")))

        # Arithmetic sensitivity only. It does not claim the supplier will grant a discount.
        supplier_3pct_saving = supplier_cost * 0.03
        profit_if_supplier_minus_3 = profit + supplier_3pct_saving
        margin_if_supplier_minus_3 = (profit_if_supplier_minus_3 / sale * 100.0) if sale > 0 else None

        flags = set(str(x) for x in row.get("risk_flags", []) or [])
        hard_risk = bool(flags & {"legal_review_required", "commercial_incident_open"}) or bool(deal.get("incident_hold"))
        economics_known = sale > 0 and supplier_cost > 0 and profit >= 0

        if hard_risk:
            action = "HOLD_RISK"
            reason = "La exposición legal/incidente domina el retorno; no asignar atención premium hasta resolverla."
        elif not economics_known:
            action = "COMPLETE_ECONOMICS"
            reason = "No existe base económica completa para decidir capital/atención con rigor."
        elif risk_profit <= 0:
            action = "DEPRIORITIZE"
            reason = "No hay beneficio esperado ajustado por riesgo positivo que justifique atención premium."
        elif margin_gap < -2.0:
            action = "IMPROVE_MARGIN"
            reason = "El margen actual queda por debajo del objetivo interno defendido por riesgo."
        elif safe < 75:
            action = "REPAIR_TERMS"
            reason = "La economía puede ser atractiva, pero Safe Close todavía es demasiado bajo para acelerar."
        elif _f(row.get("money_score")) >= 72 and margin_gap >= 0 and probability >= 0.45:
            action = "ACCELERATE"
            reason = "Buen retorno ajustado por riesgo, margen defendido y probabilidad suficiente: merece atención prioritaria."
        else:
            action = "IMPROVE_CONVERSION"
            reason = "Economía utilizable, pero conviene aumentar probabilidad de cierre o calidad de términos antes de escalar."

        row.update({
            "capital_action": action,
            "capital_reason": reason,
            "defended_target_margin_pct": defended_target,
            "margin_gap_to_defended_target_pct": margin_gap,
            "risk_margin_premium_pct": risk_premium,
            "modeled_capital_efficiency": round(capital_efficiency, 4) if capital_efficiency is not None else None,
            "modeled_expected_return_on_supplier_exposure_pct": round(expected_return_pct, 2) if expected_return_pct is not None else None,
            "supplier_minus_3pct_sensitivity": {
                "supplier_cost_saving_usd": round(supplier_3pct_saving, 2),
                "company_profit_usd": round(profit_if_supplier_minus_3, 2),
                "margin_pct": round(margin_if_supplier_minus_3, 2) if margin_if_supplier_minus_3 is not None else None,
                "note": "Sensibilidad aritmética; no supone que el proveedor concederá 3%.",
            },
        })
        rows.append(row)

    # Opportunity-cost rank: reward actual risk-adjusted return and closability, not raw sale price.
    efficiencies = [x["modeled_capital_efficiency"] for x in rows if x.get("modeled_capital_efficiency") is not None]
    median_eff = median(efficiencies) if efficiencies else 0.0
    max_profit = max([_f(x.get("risk_adjusted_expected_profit_usd")) for x in rows] + [1.0])
    for row in rows:
        eff = _f(row.get("modeled_capital_efficiency"))
        profit_signal = _pct(_f(row.get("risk_adjusted_expected_profit_usd")), max_profit)
        efficiency_signal = 50.0 if not efficiencies else max(0.0, min(100.0, 50.0 + (eff - median_eff) * 450.0))
        safe = _safe_score(row)
        probability = _f(row.get("close_probability")) * 100.0
        margin_fit = max(0.0, min(100.0, 60.0 + _f(row.get("margin_gap_to_defended_target_pct")) * 8.0))
        score = profit_signal * 0.36 + efficiency_signal * 0.22 + safe * 0.16 + probability * 0.16 + margin_fit * 0.10
        if row.get("capital_action") == "HOLD_RISK":
            score *= 0.35
        elif row.get("capital_action") == "DEPRIORITIZE":
            score *= 0.55
        row["capital_priority_score"] = round(max(0.0, min(100.0, score)), 2)

    rows.sort(key=lambda x: (_f(x.get("capital_priority_score")), _f(x.get("risk_adjusted_expected_profit_usd"))), reverse=True)
    return rows


def _category_rows(deals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "deals": 0, "known_margin_deals": 0, "margin_sum": 0.0, "risk_profit": 0.0,
        "supplier_exposure": 0.0, "accelerate": 0, "hold": 0,
    })
    labels: Dict[str, str] = {}
    for row in deals:
        label = str(row.get("category") or "Sin categoría")
        key = " ".join(label.lower().split())
        labels[key] = label
        g = groups[key]
        g["deals"] += 1
        margin = row.get("margin_pct")
        if margin not in (None, "") and _f(row.get("sale_price_usd")) > 0:
            g["known_margin_deals"] += 1
            g["margin_sum"] += _f(margin)
        g["risk_profit"] += _f(row.get("risk_adjusted_expected_profit_usd"))
        g["supplier_exposure"] += _f(row.get("modeled_supplier_cost_if_won_usd"))
        if row.get("capital_action") == "ACCELERATE":
            g["accelerate"] += 1
        if row.get("capital_action") == "HOLD_RISK":
            g["hold"] += 1

    out: List[Dict[str, Any]] = []
    for key, g in groups.items():
        avg_margin = g["margin_sum"] / max(1, g["known_margin_deals"])
        efficiency = g["risk_profit"] / g["supplier_exposure"] if g["supplier_exposure"] > 0 else None
        out.append({
            "category": labels[key],
            "deals": g["deals"],
            "known_margin_deals": g["known_margin_deals"],
            "observed_avg_margin_pct": round(avg_margin, 2) if g["known_margin_deals"] else None,
            "risk_adjusted_expected_profit_usd": round(g["risk_profit"], 2),
            "modeled_supplier_exposure_usd": round(g["supplier_exposure"], 2),
            "modeled_capital_efficiency": round(efficiency, 4) if efficiency is not None else None,
            "accelerate_deals": g["accelerate"],
            "hold_risk_deals": g["hold"],
        })
    out.sort(key=lambda x: (_f(x.get("risk_adjusted_expected_profit_usd")), _f(x.get("modeled_capital_efficiency"))), reverse=True)
    return out[:MAX_CATEGORY_ROWS]


def _annotate(state: Dict[str, Any], rows: List[Dict[str, Any]]) -> None:
    index = {str(x.get("deal_id")): x for x in rows if x.get("deal_id")}
    for deal in state.get("deals", []) or []:
        row = index.get(str(deal.get("id") or ""))
        if not row:
            continue
        deal["capital_priority_score"] = row.get("capital_priority_score")
        deal["capital_action"] = row.get("capital_action")
        deal["defended_target_margin_pct"] = row.get("defended_target_margin_pct")
        deal["capital_reviewed_at"] = utcnow()


def capital_margin_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    rows = _deal_rows(state)
    categories = _category_rows(rows)
    _annotate(state, rows)

    accelerate = [x for x in rows if x.get("capital_action") == "ACCELERATE"]
    improve_margin = [x for x in rows if x.get("capital_action") == "IMPROVE_MARGIN"]
    held = [x for x in rows if x.get("capital_action") == "HOLD_RISK"]
    total_risk_profit = sum(_f(x.get("risk_adjusted_expected_profit_usd")) for x in rows)
    top3 = sum(_f(x.get("risk_adjusted_expected_profit_usd")) for x in rows[:3])

    primary = rows[0] if rows else None
    directive = {
        "deal_id": (primary or {}).get("deal_id"),
        "action": (primary or {}).get("capital_action"),
        "capital_priority_score": (primary or {}).get("capital_priority_score"),
        "risk_adjusted_expected_profit_usd": (primary or {}).get("risk_adjusted_expected_profit_usd"),
        "defended_target_margin_pct": (primary or {}).get("defended_target_margin_pct"),
        "reason": (primary or {}).get("capital_reason"),
    } if primary else {}

    report = {
        "updated_at": utcnow(),
        "mode": "autonomous_capital_and_margin_intelligence",
        "deal_capital_rankings": rows,
        "category_capital_rankings": categories,
        "primary_directive": directive,
        "summary": {
            "deals_reviewed": len(rows),
            "accelerate": len(accelerate),
            "improve_margin": len(improve_margin),
            "hold_risk": len(held),
            "risk_adjusted_expected_profit_usd": round(total_risk_profit, 2),
            "top3_risk_profit_concentration_pct": round(_pct(top3, total_risk_profit), 1),
        },
        "governance": {
            "capital_definition": "Supplier exposure is modeled opportunity exposure, not confirmed cash usage unless a real financial source says so.",
            "margin_target_rule": "Defended margin is an internal negotiation/selection target, not a binding quote or automatic repricing instruction.",
            "sensitivity_rule": "Supplier discount scenarios are arithmetic sensitivities only and are never represented as achievable facts.",
            "cash_rule": "No cash balance, runway or financing capacity is invented.",
            "authority_rule": "May prioritize attention and request better terms; may not commit capital, place orders, accept binding pricing, make payments or sign contracts.",
        },
    }
    state["capital_margin_intelligence"] = report
    state["capital_priority_index"] = {str(x.get("deal_id")): x for x in rows if x.get("deal_id")}

    if primary:
        record_decision(
            state,
            engine="Capital & Margin Intelligence",
            object_type="deal",
            object_id=str(primary.get("deal_id") or ""),
            decision=f"capital_action:{str(primary.get('capital_action') or '').lower()}",
            reason=(
                f"Capital score {primary.get('capital_priority_score')}; beneficio ajustado USD "
                f"{_f(primary.get('risk_adjusted_expected_profit_usd')):,.2f}; margen {primary.get('margin_pct')}%; "
                f"objetivo defendido {primary.get('defended_target_margin_pct')}%. {primary.get('capital_reason')}"
            ),
            action="score_opportunity",
            confidence=max(0.45, min(0.98, _f(primary.get("close_probability"), 0.5))),
            evidence_refs=[],
            allowed=True,
            requires_approval=False,
        )
    return report
