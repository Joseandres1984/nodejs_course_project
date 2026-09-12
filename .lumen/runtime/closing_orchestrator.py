from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from autonomy_governor import record_decision
from payment_rails import payment_rails_tick
from preclose_gate import preclose_tick

MAX_CLOSE_PACKS = 120
MAX_CLARIFICATIONS_PER_CYCLE = 1


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _account_index(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(x.get("id")): x for x in state.get("candidate_accounts", []) or [] if x.get("id")}


def _risk(state: Dict[str, Any], account_id: Any) -> Dict[str, Any]:
    return dict((state.get("counterparty_risk_index", {}) or {}).get(str(account_id or ""), {}) or {})


def _route(state: Dict[str, Any], deal_id: Any) -> Dict[str, Any]:
    return dict((state.get("payment_route_index", {}) or {}).get(str(deal_id or ""), {}) or {})


def _has_execution_key(state: Dict[str, Any], key: str) -> bool:
    return any(str(x.get("execution_key") or "") == key for x in state.get("outbox", []) or [])


def _revenue_model(deal: Dict[str, Any]) -> Dict[str, Any]:
    explicit = str(deal.get("revenue_model") or "").strip().lower()
    confirmed = bool(deal.get("revenue_model_confirmed"))
    cash_gap = bool(deal.get("cash_gap_risk")) or "cash_gap_risk" in set((deal.get("deal_safeguards") or {}).get("critical_gaps") or [])
    cross_border = bool(deal.get("cross_border")) or bool((deal.get("trade") or {}).get("destination_country"))
    sale = _f((deal.get("economics") or {}).get("sale_price"), _f(deal.get("sale_price")))
    supplier = _f((deal.get("economics") or {}).get("supplier_cost"), _f(deal.get("supplier_cost")))

    if explicit in {"commission_intermediation", "sourcing_fee", "resale_margin"}:
        recommended = explicit
        reason = "Modelo de ingresos explícito en el deal."
    elif cash_gap or cross_border:
        recommended = "commission_intermediation"
        reason = "La intermediación por comisión reduce exposición de caja/operación frente a reventa cuando no existe evidencia de capacidad para asumir el rol de vendedor."
    elif sale > 0 and supplier > 0:
        recommended = "resale_margin"
        reason = "La economía actual está modelada como precio de venta menos costo proveedor; aun así el rol jurídico/fiscal debe confirmarse antes del cierre."
    else:
        recommended = "commission_intermediation"
        reason = "Sin evidencia suficiente para asumir reventa, LUMEN prioriza una estructura de intermediación más liviana como recomendación, no como compromiso."

    return {
        "selected": explicit or None,
        "confirmed": confirmed and explicit in {"commission_intermediation", "sourcing_fee", "resale_margin"},
        "recommended": recommended,
        "reason": reason,
        "binding_choice_requires_human": True,
    }


def _fee_terms(deal: Dict[str, Any], model: Dict[str, Any]) -> Dict[str, Any]:
    selected = str(model.get("selected") or "")
    payer = deal.get("commission_payer_account_id") or deal.get("fee_payer_account_id")
    amount = deal.get("commission_amount") if deal.get("commission_amount") not in (None, "") else deal.get("fee_amount")
    pct = deal.get("commission_pct") if deal.get("commission_pct") not in (None, "") else deal.get("fee_pct")
    currency = str(deal.get("commission_currency") or deal.get("fee_currency") or "").strip().upper()
    trigger = str(deal.get("commission_trigger") or deal.get("fee_trigger") or "").strip()
    due_terms = str(deal.get("commission_due_terms") or deal.get("fee_due_terms") or "").strip()
    evidence_ref = str(deal.get("commission_terms_evidence_ref") or deal.get("fee_terms_evidence_ref") or "").strip()

    if selected == "resale_margin":
        econ = deal.get("economics", {}) or {}
        margin = _f(econ.get("company_profit"), _f(deal.get("company_profit")))
        return {
            "applicable": False,
            "secured": bool(model.get("confirmed") and margin > 0),
            "payer_account_id": None,
            "amount": round(margin, 2) if margin > 0 else None,
            "pct": _f(econ.get("company_share_pct"), _f(deal.get("company_share_pct"))) or None,
            "currency": str(deal.get("currency") or "USD").upper(),
            "trigger": "resale_margin_realized_after_customer_payment_and_supplier_costs",
            "due_terms": None,
            "evidence_ref": evidence_ref or None,
            "missing": [] if model.get("confirmed") and margin > 0 else ["revenue_model_confirmation_or_margin"],
        }

    missing: List[str] = []
    if not payer:
        missing.append("commission_payer")
    if amount in (None, "") and pct in (None, ""):
        missing.append("commission_amount_or_pct")
    if not currency:
        missing.append("commission_currency")
    if not trigger:
        missing.append("commission_trigger")
    if not due_terms:
        missing.append("commission_due_terms")
    if not evidence_ref:
        missing.append("commission_terms_evidence")
    return {
        "applicable": True,
        "secured": bool(model.get("confirmed") and not missing),
        "payer_account_id": str(payer) if payer else None,
        "amount": round(_f(amount), 2) if amount not in (None, "") else None,
        "pct": round(_f(pct), 3) if pct not in (None, "") else None,
        "currency": currency or None,
        "trigger": trigger or None,
        "due_terms": due_terms or None,
        "evidence_ref": evidence_ref or None,
        "missing": missing,
    }


def _prepare_terms_clarification(state: Dict[str, Any], deal: Dict[str, Any], fee: Dict[str, Any]) -> bool:
    payer_id = str(fee.get("payer_account_id") or "")
    if not payer_id:
        return False
    accounts = _account_index(state)
    payer = accounts.get(payer_id, {})
    email = str(payer.get("commercial_email") or "").strip().lower()
    if not email or not payer.get("verified_contact"):
        return False
    risk = _risk(state, payer_id)
    if risk.get("risk_tier") == "BLOCKED" or risk.get("can_outreach") is False:
        return False
    deal_id = str(deal.get("id") or "")
    key = f"close_commission_terms|{deal_id}|{payer_id}|v1"
    if _has_execution_key(state, key):
        return False

    missing = set(fee.get("missing") or [])
    asks = []
    if "commission_amount_or_pct" in missing:
        asks.append("importe o porcentaje de la comisión/honorario")
    if "commission_currency" in missing:
        asks.append("moneda de liquidación")
    if "commission_trigger" in missing:
        asks.append("evento que genera el derecho al cobro")
    if "commission_due_terms" in missing:
        asks.append("plazo o condición de vencimiento")
    if "commission_terms_evidence" in missing:
        asks.append("confirmación escrita de estas condiciones")
    if not asks:
        return False

    state.setdefault("outbox", []).append({
        "id": f"MSG-{len(state.get('outbox', []))+1:04d}",
        "deal_id": deal.get("id"),
        "counterparty_account_id": payer_id,
        "kind": "terms_clarification",
        "purpose": "secure_commission_terms_before_close",
        "counterparty": payer.get("company_name") or payer.get("name_hint") or payer.get("domain"),
        "channel": "email",
        "contact": email,
        "contact_verified": True,
        "subject": "Confirmación de condiciones de intermediación",
        "body": (
            "Para completar el expediente comercial antes de cualquier compromiso vinculante, necesitamos dejar documentadas las condiciones de nuestra participación. "
            "Agradeceremos confirmar: " + "; ".join(asks) + ". "
            "Esta consulta es únicamente de validación y no constituye aceptación de contrato, orden de compra, obligación de pago ni modificación de términos existentes."
        )[:5600],
        "status": "ready",
        "execution_key": key,
        "created_at": utcnow(),
        "nonbinding": True,
        "close_orchestrator_controlled": True,
    })
    return True


def _close_pack(state: Dict[str, Any], deal: Dict[str, Any]) -> Dict[str, Any]:
    deal_id = str(deal.get("id") or "")
    model = _revenue_model(deal)
    fee = _fee_terms(deal, model)
    route = _route(state, deal_id)
    buyer_risk = _risk(state, deal.get("buyer_account_id"))
    supplier_risk = _risk(state, deal.get("supplier_account_id"))
    safeguards = deal.get("deal_safeguards", {}) or {}
    economics = deal.get("economics", {}) or {}

    missing: List[str] = []
    if not model.get("confirmed"):
        missing.append("revenue_model_confirmed")
    if not fee.get("secured"):
        missing.extend(list(fee.get("missing") or ["commission_terms_secured"]))
    if route.get("status") != "READY":
        missing.append("payment_route_ready")
    if not economics.get("viable"):
        missing.append("viable_economics")
    if not deal.get("deal_safeguards_cleared") or deal.get("legal_review_required") or deal.get("incident_hold"):
        missing.append("safe_close")
    if buyer_risk.get("risk_tier") == "BLOCKED" or supplier_risk.get("risk_tier") == "BLOCKED":
        missing.append("counterparty_risk")
    if deal.get("red_team_hold"):
        missing.append("red_team_hold")

    hard_risk = any(x in missing for x in {"safe_close", "counterparty_risk", "red_team_hold"})
    if hard_risk:
        status = "BLOCKED_RISK"
    elif missing:
        status = "BUILDING"
    else:
        status = "READY_FOR_HUMAN_APPROVAL"

    deal["revenue_model_recommendation"] = model
    deal["commission_terms_secured"] = bool(fee.get("secured"))
    deal["payment_route_ready"] = route.get("status") == "READY"
    deal["close_execution_ready_for_approval"] = status == "READY_FOR_HUMAN_APPROVAL"

    return {
        "deal_id": deal_id,
        "status": status,
        "buyer": deal.get("buyer"),
        "supplier": deal.get("supplier"),
        "revenue_model": model,
        "fee_terms": fee,
        "payment_route": route,
        "economics": {
            "viable": bool(economics.get("viable")),
            "sale_price": economics.get("sale_price") or deal.get("sale_price"),
            "company_profit": economics.get("company_profit") or deal.get("company_profit"),
            "company_share_pct": economics.get("company_share_pct") or deal.get("company_share_pct"),
        },
        "safe_close_score": safeguards.get("safe_close_score"),
        "buyer_risk_tier": buyer_risk.get("risk_tier"),
        "supplier_risk_tier": supplier_risk.get("risk_tier"),
        "red_team_hold": bool(deal.get("red_team_hold")),
        "missing": list(dict.fromkeys(missing)),
        "human_approval_required": True,
        "binding_execution_allowed": False,
        "updated_at": utcnow(),
    }


def closing_orchestrator_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    # Refresh payment routing here so closing decisions do not depend on the late KPI cycle.
    payment_rails_tick(state)
    packs: List[Dict[str, Any]] = []
    clarifications = 0

    for deal in state.get("deals", []) or []:
        if deal.get("source") == "demo" or str(deal.get("stage") or "") in {"closed_simulated", "cerrado (simulación)"}:
            continue
        if not deal.get("economics") and str(deal.get("stage") or "") not in {"propuesta preparada", "negociación", "listo para cerrar", "preclose_validation", "autorizado para cierre", "listo para cierre aprobado"}:
            continue
        pack = _close_pack(state, deal)
        if clarifications < MAX_CLARIFICATIONS_PER_CYCLE and pack.get("fee_terms", {}).get("applicable") and pack.get("fee_terms", {}).get("payer_account_id"):
            if _prepare_terms_clarification(state, deal, pack["fee_terms"]):
                clarifications += 1
                pack["clarification_prepared"] = True
        packs.append(pack)

    packs.sort(key=lambda x: ({"BLOCKED_RISK": 3, "BUILDING": 2, "READY_FOR_HUMAN_APPROVAL": 1}.get(str(x.get("status")), 0), len(x.get("missing") or [])), reverse=True)
    packs = packs[:MAX_CLOSE_PACKS]
    index = {str(x.get("deal_id")): x for x in packs if x.get("deal_id")}
    state["closing_packs"] = packs
    state["closing_pack_index"] = index

    # Re-run pre-close after revenue model, commission protection and payment route flags are refreshed.
    preclose_stats = preclose_tick(state)

    ready = [x for x in packs if x.get("status") == "READY_FOR_HUMAN_APPROVAL"]
    blocked = [x for x in packs if x.get("status") == "BLOCKED_RISK"]
    primary = (blocked or ready or packs[:1])[:1]
    report = {
        "updated_at": utcnow(),
        "mode": "autonomous_revenue_model_and_real_close_orchestration",
        "packs": packs,
        "pack_count": len(packs),
        "ready_for_human_approval": len(ready),
        "blocked_risk": len(blocked),
        "clarifications_prepared": clarifications,
        "primary_pack": primary[0] if primary else None,
        "preclose_refresh": preclose_stats,
        "governance": {
            "commission_protection_rule": "No deal is treated as closable until LUMEN's revenue model and economic entitlement are explicit and traceable.",
            "role_rule": "Commission, sourcing-fee and resale structures are recommendations until a human confirms the legal/tax role.",
            "payment_rule": "A close packet requires a verified payment route but never exposes raw account instructions in state/API.",
            "authority_rule": "LUMEN may build the packet and seek nonbinding clarification; final binding close remains human-authorized.",
        },
    }
    state["closing_orchestrator"] = report

    if report.get("primary_pack"):
        p = report["primary_pack"]
        record_decision(
            state,
            engine="Closing Orchestrator",
            object_type="deal",
            object_id=str(p.get("deal_id") or ""),
            decision=f"close_pack:{str(p.get('status') or '').lower()}",
            reason=f"Modelo recomendado {p.get('revenue_model', {}).get('recommended')}; faltantes: {', '.join(p.get('missing') or []) or 'ninguno'}.",
            action="block_contractual_commitment" if p.get("status") != "READY_FOR_HUMAN_APPROVAL" else "request_human_close_approval",
            confidence=0.97,
            evidence_refs=[str(p.get("fee_terms", {}).get("evidence_ref"))] if p.get("fee_terms", {}).get("evidence_ref") else [],
            allowed=p.get("status") == "READY_FOR_HUMAN_APPROVAL",
            requires_approval=True,
        )
    return report
