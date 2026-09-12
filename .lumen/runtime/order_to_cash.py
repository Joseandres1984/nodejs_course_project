from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from autonomy_governor import record_decision

REAL_STATUSES = {"closed", "invoiced", "delivered", "paid", "settled", "completed"}
FINAL_STATUSES = {"paid", "settled", "completed"}
MAX_CASES = 120
MAX_NEW_MESSAGES_PER_CYCLE = 1
PAYMENT_GRACE_DAYS = 3
CUSTOMER_SUCCESS_DELAY_DAYS = 7


def utcnow_dt() -> datetime:
    return datetime.now(timezone.utc)


def utcnow() -> str:
    return utcnow_dt().strftime("%Y-%m-%d %H:%M:%S UTC")


def _parse(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    formats = (
        "%Y-%m-%d %H:%M:%S UTC",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%d",
    )
    for fmt in formats:
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().strip().split())


def _deal_index(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(x.get("id")): x for x in state.get("deals", []) if x.get("id")}


def _account_index(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(x.get("id")): x for x in state.get("candidate_accounts", []) if x.get("id")}


def _buyer_for(state: Dict[str, Any], deal: Dict[str, Any]) -> Dict[str, Any]:
    accounts = _account_index(state)
    buyer = accounts.get(str(deal.get("buyer_account_id") or ""), {})
    if buyer:
        return buyer
    target = _norm(deal.get("buyer"))
    for account in accounts.values():
        if account.get("type") != "buyer":
            continue
        names = {_norm(account.get("company_name")), _norm(account.get("name_hint")), _norm(account.get("site_title"))}
        if target and any(name and (name == target or name in target or target in name) for name in names):
            return account
    return {}


def _buyer_contact(account: Dict[str, Any]) -> tuple[str | None, bool]:
    email = str(account.get("commercial_email") or "").strip().lower()
    return (email, bool(email and account.get("verified_contact")))


def _incident_open(state: Dict[str, Any], deal_id: str) -> bool:
    return any(
        str(x.get("deal_id") or "") == deal_id and str(x.get("status") or "") not in {"resolved", "closed"}
        for x in state.get("commercial_incidents", []) or []
    )


def _existing_key(state: Dict[str, Any], key: str) -> bool:
    return any(str(x.get("execution_key") or "") == key for x in state.get("outbox", []) or [])


def _make_message(
    state: Dict[str, Any], *, key: str, kind: str, purpose: str, deal: Dict[str, Any], txn: Dict[str, Any],
    buyer: Dict[str, Any], subject: str, body: str,
) -> bool:
    if _existing_key(state, key):
        return False
    contact, verified = _buyer_contact(buyer)
    if not contact or not verified:
        return False
    state.setdefault("outbox", []).append({
        "id": f"MSG-{len(state.get('outbox', []))+1:04d}",
        "deal_id": deal.get("id"),
        "transaction_id": txn.get("id"),
        "counterparty_account_id": buyer.get("id"),
        "kind": kind,
        "purpose": purpose,
        "counterparty": buyer.get("company_name") or buyer.get("name_hint") or buyer.get("domain") or deal.get("buyer"),
        "channel": "email",
        "contact": contact,
        "contact_verified": True,
        "subject": subject[:180],
        "body": body[:5600],
        "status": "ready",
        "execution_key": key,
        "created_at": utcnow(),
        "nonbinding": True,
        "post_sale_controlled": True,
    })
    return True


def _evidence(txn: Dict[str, Any], deal: Dict[str, Any]) -> Dict[str, Any]:
    def first(*keys: str) -> Any:
        for key in keys:
            value = txn.get(key)
            if value not in (None, ""):
                return value
            value = deal.get(key)
            if value not in (None, ""):
                return value
        return None

    return {
        "delivered_at": first("delivered_at", "delivery_at", "delivery_date"),
        "accepted_at": first("accepted_at", "acceptance_at", "acceptance_date"),
        "invoiced_at": first("invoiced_at", "invoice_date"),
        "payment_due_at": first("payment_due_at", "due_at", "due_date", "invoice_due_at"),
        "paid_at": first("paid_at", "settled_at", "completed_at"),
        "invoice_number": first("invoice_number", "invoice_id"),
        "delivery_reference": first("delivery_reference", "tracking_number", "delivery_note"),
    }


def _classify_case(state: Dict[str, Any], txn: Dict[str, Any], deal: Dict[str, Any]) -> Dict[str, Any]:
    status = str(txn.get("status") or "").lower()
    evidence = _evidence(txn, deal)
    deal_id = str(deal.get("id") or txn.get("deal_id") or "")
    incident = _incident_open(state, deal_id) or bool(deal.get("incident_hold"))
    now = utcnow_dt()
    due = _parse(evidence.get("payment_due_at"))
    delivered = _parse(evidence.get("delivered_at"))
    accepted = _parse(evidence.get("accepted_at"))
    paid = _parse(evidence.get("paid_at"))

    if incident:
        stage = "INCIDENT_HOLD"
        next_action = "Preservar evidencia y resolver el incidente antes de cobranza o expansión de cuenta"
        autonomous = False
    elif status in FINAL_STATUSES:
        if paid and now >= paid + timedelta(days=CUSTOMER_SUCCESS_DELAY_DAYS):
            stage = "CUSTOMER_SUCCESS"
            next_action = "Confirmar satisfacción y explorar una necesidad adicional sin presión"
        else:
            stage = "CUSTOMER_SUCCESS_PENDING"
            next_action = "Esperar evidencia/ventana adecuada antes del seguimiento postventa"
        autonomous = True
    elif status == "invoiced":
        if due is None:
            stage = "PAYMENT_EVIDENCE_GAP"
            next_action = "Obtener fecha de vencimiento trazable antes de reclamar pago"
        elif now > due + timedelta(days=PAYMENT_GRACE_DAYS):
            stage = "COLLECTION_DUE"
            next_action = "Enviar recordatorio profesional de pago sin amenazas ni cargos inventados"
        else:
            stage = "PAYMENT_MONITORING"
            next_action = "Monitorear vencimiento sin contactar anticipadamente"
        autonomous = True
    elif status == "delivered" or delivered:
        if accepted:
            stage = "ACCEPTED_PENDING_INVOICE"
            next_action = "Esperar/fijar evidencia de facturación y vencimiento"
        else:
            stage = "ACCEPTANCE_CONFIRMATION"
            next_action = "Solicitar confirmación de recepción/conformidad sin alterar garantías ni términos"
        autonomous = True
    else:
        stage = "DELIVERY_EVIDENCE_GAP"
        next_action = "Obtener evidencia de entrega/estado antes de activar postventa"
        autonomous = True

    return {
        "transaction_id": txn.get("id"),
        "deal_id": deal_id,
        "buyer": txn.get("buyer") or deal.get("buyer"),
        "supplier": txn.get("supplier") or deal.get("supplier"),
        "category": deal.get("category") or deal.get("need"),
        "transaction_status": status,
        "stage": stage,
        "next_action": next_action,
        "autonomous": autonomous,
        "incident_hold": incident,
        "sale_price_usd": round(_f(txn.get("sale_price")), 2),
        "company_profit_usd": round(_f(txn.get("company_profit")), 2),
        "evidence": evidence,
        "updated_at": utcnow(),
    }


def _prepare_case_message(state: Dict[str, Any], case: Dict[str, Any], txn: Dict[str, Any], deal: Dict[str, Any], buyer: Dict[str, Any]) -> bool:
    stage = str(case.get("stage") or "")
    if stage == "INCIDENT_HOLD":
        return False
    txn_id = str(txn.get("id") or "")
    deal_id = str(deal.get("id") or "")
    evidence = case.get("evidence", {}) or {}

    if stage == "ACCEPTANCE_CONFIRMATION":
        ref = evidence.get("delivery_reference")
        ref_text = f" (referencia {ref})" if ref else ""
        return _make_message(
            state,
            key=f"post_sale_acceptance|{txn_id}|v1",
            kind="delivery_acceptance_request",
            purpose="confirm_delivery_acceptance",
            deal=deal,
            txn=txn,
            buyer=buyer,
            subject="Confirmación de recepción",
            body=(
                f"Según la evidencia registrada, la operación {deal_id}{ref_text} figura entregada. "
                "Cuando tengan un momento, agradeceremos confirmar si la recepción fue conforme o indicarnos cualquier observación factual. "
                "Esta consulta no modifica condiciones contractuales, garantías ni responsabilidades acordadas."
            ),
        )

    if stage == "COLLECTION_DUE":
        due = evidence.get("payment_due_at")
        inv = evidence.get("invoice_number")
        inv_text = f" de la factura {inv}" if inv else ""
        return _make_message(
            state,
            key=f"post_sale_collection|{txn_id}|v1",
            kind="payment_status_reminder",
            purpose="professional_payment_follow_up",
            deal=deal,
            txn=txn,
            buyer=buyer,
            subject="Consulta sobre estado de pago",
            body=(
                f"Queríamos consultar el estado de pago{inv_text}. Según el registro disponible, el vencimiento informado es {due}. "
                "Si el pago ya fue procesado, pueden ignorar este mensaje; de lo contrario, agradeceremos confirmar el estado o si necesitan algún dato administrativo de nuestra parte. "
                "No se aplican ni se presumen penalidades, intereses o cargos que no estén expresamente documentados."
            ),
        )

    if stage == "CUSTOMER_SUCCESS":
        category = case.get("category") or "esta categoría"
        return _make_message(
            state,
            key=f"post_sale_success|{txn_id}|v1",
            kind="customer_success_checkin",
            purpose="post_sale_success_and_repeat_business",
            deal=deal,
            txn=txn,
            buyer=buyer,
            subject="Seguimiento de la operación",
            body=(
                "Queríamos confirmar que la operación haya quedado correctamente cerrada desde su lado. "
                f"Si están planificando nuevas necesidades relacionadas con {category}, podemos ayudarlos a comparar alternativas y condiciones sobre una base no vinculante. "
                "Si no tienen una necesidad activa, no hace falta responder."
            ),
        )
    return False


def _materialize_task(state: Dict[str, Any], case: Dict[str, Any]) -> None:
    if case.get("stage") not in {"DELIVERY_EVIDENCE_GAP", "PAYMENT_EVIDENCE_GAP", "INCIDENT_HOLD"}:
        return
    task = {
        "key": f"order_to_cash|{case.get('transaction_id')}|{case.get('stage')}",
        "kind": "order_to_cash",
        "title": f"Postventa: {case.get('next_action')}",
        "reason": f"Transacción {case.get('transaction_id')} en etapa {case.get('stage')}.",
        "impact": 84 if case.get("stage") == "INCIDENT_HOLD" else 72,
        "urgency": 94 if case.get("stage") == "INCIDENT_HOLD" else 70,
        "confidence": 0.95,
        "effort": 1.0,
        "risk": "high" if case.get("stage") == "INCIDENT_HOLD" else "low",
        "autonomous": case.get("stage") != "INCIDENT_HOLD",
        "object_type": "transaction",
        "object_id": str(case.get("transaction_id") or ""),
        "priority_score": 96 if case.get("stage") == "INCIDENT_HOLD" else 78,
        "created_at": utcnow(),
    }
    queue = list(state.get("operating_action_queue", []) or [])
    by_key = {str(x.get("key")): x for x in queue if x.get("key")}
    by_key[task["key"]] = task
    state["operating_action_queue"] = sorted(by_key.values(), key=lambda x: _f(x.get("priority_score")), reverse=True)[:100]


def order_to_cash_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    deals = _deal_index(state)
    cases: List[Dict[str, Any]] = []
    created_messages = 0
    reviewed = 0

    for txn in state.get("transactions", []) or []:
        status = str(txn.get("status") or "").lower()
        if status not in REAL_STATUSES or status in {"closed_simulated", "simulated"}:
            continue
        deal = deals.get(str(txn.get("deal_id") or ""), {})
        if not deal:
            continue
        reviewed += 1
        case = _classify_case(state, txn, deal)
        buyer = _buyer_for(state, deal)
        case["buyer_account_id"] = buyer.get("id")
        case["verified_buyer_contact"] = bool(_buyer_contact(buyer)[1])
        _materialize_task(state, case)
        if created_messages < MAX_NEW_MESSAGES_PER_CYCLE and _prepare_case_message(state, case, txn, deal, buyer):
            created_messages += 1
            case["message_prepared"] = True
        else:
            case["message_prepared"] = False
        cases.append(case)

    priority = {
        "INCIDENT_HOLD": 100,
        "COLLECTION_DUE": 95,
        "ACCEPTANCE_CONFIRMATION": 88,
        "PAYMENT_EVIDENCE_GAP": 86,
        "DELIVERY_EVIDENCE_GAP": 82,
        "CUSTOMER_SUCCESS": 70,
        "PAYMENT_MONITORING": 55,
        "CUSTOMER_SUCCESS_PENDING": 45,
        "ACCEPTED_PENDING_INVOICE": 60,
    }
    cases.sort(key=lambda x: priority.get(str(x.get("stage")), 50), reverse=True)
    cases = cases[:MAX_CASES]
    primary = cases[0] if cases else None

    report = {
        "updated_at": utcnow(),
        "mode": "autonomous_order_to_cash_customer_success",
        "transactions_reviewed": reviewed,
        "cases": cases,
        "case_count": len(cases),
        "messages_prepared": created_messages,
        "primary_case": primary,
        "stage_counts": {stage: sum(1 for x in cases if x.get("stage") == stage) for stage in set(str(x.get("stage")) for x in cases)},
        "governance": {
            "real_only": "Solo se procesan estados de transacción reales; closed_simulated se excluye.",
            "evidence_rule": "No se inventan fechas de entrega, facturas, vencimientos, aceptación ni pagos.",
            "collections_rule": "Recordatorios profesionales sin amenazas, cargos, intereses o penalidades no documentadas.",
            "incident_rule": "Con incidente abierto se congela cobranza/expansión comercial y se preserva evidencia.",
            "customer_success_rule": "Seguimiento postventa no vinculante, sin presión y solo sobre operaciones reales.",
            "authority_rule": "No autoriza reembolsos, devoluciones, notas de crédito, compensaciones, pagos ni admisión de responsabilidad.",
        },
    }
    state["order_to_cash"] = report
    state["order_to_cash_cases"] = cases
    state["order_to_cash_index"] = {str(x.get("transaction_id")): x for x in cases if x.get("transaction_id")}

    if primary:
        record_decision(
            state,
            engine="Order-to-Cash & Customer Success",
            object_type="transaction",
            object_id=str(primary.get("transaction_id") or ""),
            decision=f"post_sale_stage:{str(primary.get('stage') or '').lower()}",
            reason=str(primary.get("next_action") or "Gestionar postventa sobre evidencia trazable."),
            action="prepare_outreach" if primary.get("autonomous") else "score_opportunity",
            confidence=0.95,
            evidence_refs=[],
            allowed=bool(primary.get("autonomous")),
            requires_approval=False,
        )
    return report
