from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List

from autonomy_governor import record_decision


REAL_TRANSACTION_STATUSES = {"closed", "settled", "paid", "completed", "delivered", "invoiced"}
REALIZED_STATUSES = {"settled", "paid", "completed"}
STAGE_PROBABILITY = {
    "descubrimiento": 0.10,
    "contacto preparado": 0.14,
    "calificado": 0.24,
    "esperando oferta": 0.30,
    "propuesta": 0.40,
    "propuesta preparada": 0.48,
    "negociación": 0.62,
    "renegociación": 0.48,
    "preclose_validation": 0.72,
    "listo para cerrar": 0.78,
    "autorizado para cierre": 0.88,
    "listo para cierre aprobado": 0.94,
}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _probability(deal: Dict[str, Any]) -> float:
    explicit = deal.get("close_prob")
    if explicit not in (None, ""):
        return max(0.0, min(1.0, _f(explicit)))
    return STAGE_PROBABILITY.get(str(deal.get("stage") or ""), 0.18)


def _is_real_deal(deal: Dict[str, Any]) -> bool:
    if deal.get("source") == "demo":
        return False
    if str(deal.get("stage") or "") in {"cerrado (simulación)", "closed_simulated"}:
        return False
    return True


def _risk_profile(deal: Dict[str, Any]) -> Dict[str, Any]:
    flags: List[str] = []
    if not deal.get("economics"):
        flags.append("economics_incomplete")
    if deal.get("economics") and not deal.get("economics", {}).get("viable"):
        flags.append("margin_below_policy")
    if not deal.get("requirement_confirmed") and str(deal.get("stage") or "") not in {"descubrimiento", "contacto preparado"}:
        flags.append("requirement_not_confirmed")
    if str(deal.get("stage") or "") in {"preclose_validation", "listo para cerrar", "autorizado para cierre", "listo para cierre aprobado"}:
        if not deal.get("commercial_terms_confirmed"):
            flags.append("commercial_terms_unconfirmed")
        if not deal.get("delivery_terms_confirmed"):
            flags.append("delivery_terms_unconfirmed")
        if not deal.get("invoice_tax_treatment_confirmed"):
            flags.append("tax_treatment_unconfirmed")
        if not deal.get("payment_instructions_verified"):
            flags.append("payment_instructions_unverified")

    safeguards = deal.get("deal_safeguards", {}) or {}
    safe_close_score = max(0.0, min(100.0, _f(safeguards.get("safe_close_score"), 100.0)))
    if safeguards and not safeguards.get("cleared"):
        flags.append("deal_safeguards_incomplete")
    if deal.get("legal_review_required") or safeguards.get("mandatory_legal_review"):
        flags.append("legal_review_required")
    if deal.get("incident_hold") or deal.get("commercial_incident_open"):
        flags.append("commercial_incident_open")
    for gap in safeguards.get("critical_gaps", []) or []:
        if gap in {"returns_mismatch", "cancellation_mismatch", "warranty_mismatch", "cash_gap_risk", "cross_border_terms_incomplete"}:
            flags.append(str(gap))

    flags.extend(str(x) for x in (deal.get("risk_flags") or []))
    flags = list(dict.fromkeys(flags))

    severe = {
        "payment_instructions_unverified", "buyer_identity_unverified", "supplier_identity_unverified",
        "legal_review_required", "commercial_incident_open", "deal_safeguards_incomplete",
        "returns_mismatch", "cancellation_mismatch", "warranty_mismatch",
    }
    base_penalty = len(flags) * 0.05 + sum(0.07 for x in flags if x in severe)
    safeguard_penalty = max(0.0, (100.0 - safe_close_score) / 100.0 * 0.35) if safeguards else 0.0
    penalty = min(0.72, base_penalty + safeguard_penalty)
    return {
        "flags": flags,
        "safe_close_score": round(safe_close_score, 1) if safeguards else None,
        "risk_penalty_pct": round(penalty * 100.0, 1),
        "risk_factor": round(max(0.28, 1.0 - penalty), 3),
    }


def _deal_financials(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    target_margin = _f(state.get("policies", {}).get("target_company_share_pct"), 12.0)
    rows: List[Dict[str, Any]] = []
    for deal in state.get("deals", []):
        if not _is_real_deal(deal):
            continue
        econ = deal.get("economics", {}) or {}
        sale = max(0.0, _f(econ.get("sale_price"), _f(deal.get("sale_price"), _f(deal.get("expected_value")))))
        supplier_cost = max(0.0, _f(econ.get("supplier_cost"), _f(deal.get("supplier_cost"))))
        logistics = max(0.0, _f(econ.get("logistics_cost"), _f(deal.get("logistics_cost"))))
        profit = max(0.0, _f(econ.get("company_profit"), _f(deal.get("company_profit"))))
        margin = max(0.0, _f(econ.get("company_share_pct"), _f(deal.get("company_share_pct"))))
        probability = _probability(deal)
        risk = _risk_profile(deal)
        expected_profit = profit * probability
        risk_adjusted_profit = expected_profit * _f(risk.get("risk_factor"), 1.0)
        modeled_supplier_exposure = supplier_cost * probability
        capital_efficiency = (profit / supplier_cost) if supplier_cost > 0 else 0.0
        margin_quality = min(1.5, margin / max(1.0, target_margin))
        deep_win = max(0.0, min(100.0, _f(deal.get("deep_dive_win_score"), 50.0)))

        profit_signal = min(100.0, risk_adjusted_profit / 25.0)
        score = (
            profit_signal * 0.40
            + probability * 100.0 * 0.22
            + min(100.0, margin_quality * 66.7) * 0.14
            + min(100.0, capital_efficiency * 250.0) * 0.10
            + deep_win * 0.14
        )
        rows.append({
            "deal_id": deal.get("id"), "buyer": deal.get("buyer"), "supplier": deal.get("supplier"),
            "category": deal.get("need") or deal.get("category"), "stage": deal.get("stage"),
            "sale_price_usd": round(sale, 2), "supplier_cost_usd": round(supplier_cost, 2),
            "logistics_cost_usd": round(logistics, 2), "company_profit_usd": round(profit, 2),
            "margin_pct": round(margin, 2), "close_probability": round(probability, 3),
            "expected_profit_usd": round(expected_profit, 2), "risk_adjusted_expected_profit_usd": round(risk_adjusted_profit, 2),
            "modeled_supplier_cost_if_won_usd": round(modeled_supplier_exposure, 2), "capital_efficiency": round(capital_efficiency, 3),
            "safe_close_score": risk.get("safe_close_score"), "risk_flags": risk["flags"],
            "risk_penalty_pct": risk["risk_penalty_pct"], "money_score": round(max(0.0, min(100.0, score)), 2),
        })
    rows.sort(key=lambda x: (x["money_score"], x["risk_adjusted_expected_profit_usd"]), reverse=True)
    return rows


def _concentration(rows: List[Dict[str, Any]], field: str) -> Dict[str, Any]:
    totals: Dict[str, float] = defaultdict(float)
    for row in rows:
        key = str(row.get(field) or "sin identificar")
        totals[key] += _f(row.get("risk_adjusted_expected_profit_usd"))
    total = sum(totals.values())
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    top = []
    for key, amount in ranked[:8]:
        share = amount / total * 100.0 if total > 0 else 0.0
        top.append({"name": key, "risk_adjusted_profit_usd": round(amount, 2), "share_pct": round(share, 1)})
    top_share = top[0]["share_pct"] if top else 0.0
    return {"top": top, "top_share_pct": top_share, "risk": "high" if top_share >= 55 else "medium" if top_share >= 35 else "low"}


def _transactions(state: Dict[str, Any]) -> Dict[str, Any]:
    committed_profit = 0.0
    realized_profit = 0.0
    committed_supplier_cost = 0.0
    gross_receivable = 0.0
    unsettled: List[Dict[str, Any]] = []
    for txn in state.get("transactions", []):
        status = str(txn.get("status") or "")
        if status in {"closed_simulated", "simulated"} or status not in REAL_TRANSACTION_STATUSES:
            continue
        profit = max(0.0, _f(txn.get("company_profit")))
        supplier_cost = max(0.0, _f(txn.get("supplier_cost")))
        sale = max(0.0, _f(txn.get("sale_price")))
        committed_profit += profit
        committed_supplier_cost += supplier_cost
        if status in REALIZED_STATUSES:
            realized_profit += profit
        else:
            gross_receivable += sale
            unsettled.append({"transaction_id": txn.get("id"), "deal_id": txn.get("deal_id"), "status": status, "gross_receivable_usd": round(sale, 2), "company_profit_usd": round(profit, 2)})
    return {
        "committed_profit_usd": round(committed_profit, 2), "realized_profit_usd": round(realized_profit, 2),
        "committed_supplier_cost_usd": round(committed_supplier_cost, 2), "gross_unsettled_receivable_usd": round(gross_receivable, 2),
        "unsettled_transactions": unsettled[:20],
    }


def cfo_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    rows = _deal_financials(state)
    tx = _transactions(state)
    pipeline_sale = sum(_f(x.get("sale_price_usd")) for x in rows)
    pipeline_profit = sum(_f(x.get("company_profit_usd")) for x in rows)
    expected_profit = sum(_f(x.get("expected_profit_usd")) for x in rows)
    risk_adjusted = sum(_f(x.get("risk_adjusted_expected_profit_usd")) for x in rows)
    modeled_supplier_exposure = sum(_f(x.get("modeled_supplier_cost_if_won_usd")) for x in rows)
    pending_ids = {str(x.get("deal_id")) for x in state.get("approvals", []) if x.get("status") == "pending"}
    pending_approval_profit = sum(_f(x.get("company_profit_usd")) for x in rows if str(x.get("deal_id")) in pending_ids)

    buyer_conc = _concentration(rows, "buyer")
    supplier_conc = _concentration(rows, "supplier")
    category_conc = _concentration(rows, "category")
    warnings: List[str] = []
    if buyer_conc["risk"] == "high": warnings.append("buyer_concentration_high")
    if supplier_conc["risk"] == "high": warnings.append("supplier_concentration_high")
    if category_conc["risk"] == "high": warnings.append("category_concentration_high")
    if _f(tx.get("gross_unsettled_receivable_usd")) > 0: warnings.append("collection_exposure_present")
    if any("payment_instructions_unverified" in x.get("risk_flags", []) for x in rows[:5]): warnings.append("payment_controls_incomplete_on_top_deals")
    if any("legal_review_required" in x.get("risk_flags", []) or "commercial_incident_open" in x.get("risk_flags", []) for x in rows[:5]): warnings.append("safe_close_exposure_on_top_deals")

    snapshot = {
        "pipeline_sale_price_usd": round(pipeline_sale, 2), "pipeline_company_profit_usd": round(pipeline_profit, 2),
        "probability_weighted_profit_usd": round(expected_profit, 2), "risk_adjusted_expected_profit_usd": round(risk_adjusted, 2),
        "modeled_supplier_cost_if_pipeline_won_usd": round(modeled_supplier_exposure, 2),
        "pending_human_approval_profit_usd": round(pending_approval_profit, 2), **tx,
        "cash_balance_usd": None, "cash_runway_days": None,
        "cash_data_note": "No se inventa saldo de caja ni runway: requieren una fuente financiera real conectada.",
    }

    report = {
        "updated_at": utcnow(), "mode": "autonomous_cfo", "financial_snapshot": snapshot,
        "deal_financial_rankings": rows[:30],
        "concentration": {"buyers": buyer_conc, "suppliers": supplier_conc, "categories": category_conc},
        "warnings": warnings,
        "capital_doctrine": [
            "priorizar beneficio esperado ajustado por riesgo y Safe Close, no facturación bruta",
            "separar pipeline, compromisos y resultados realizados",
            "penalizar deals con exposición de devoluciones, garantías, incidentes o revisión legal pendiente",
            "evitar concentración excesiva en un solo comprador, proveedor o categoría",
            "no comprometer capital ni aceptar condiciones vinculantes sin aprobación humana",
            "no tratar simulaciones como caja real",
        ],
    }
    state["cfo"] = report
    top = rows[0] if rows else None
    if top:
        record_decision(
            state, engine="LUMEN CFO", object_type="deal", object_id=str(top.get("deal_id") or ""),
            decision="capital_priority_ranked",
            reason=f"Mayor prioridad financiera actual: beneficio esperado ajustado por riesgo USD {top.get('risk_adjusted_expected_profit_usd', 0):,.2f}; money score {top.get('money_score', 0):.1f}; Safe Close {top.get('safe_close_score')}.",
            action="score_opportunity", confidence=max(0.5, min(0.98, _f(top.get("close_probability"), 0.5))), evidence_refs=[],
        )
    return report
