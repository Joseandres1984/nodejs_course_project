from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from autonomy_governor import record_decision
from payment_rails import choose_payment_route, runtime_instruction_for

REAL_TRANSACTION_STATUSES = {"closed", "invoiced", "delivered", "paid", "settled", "completed"}
RECEIVED_COMMISSION_STATUSES = {"received", "paid", "settled", "completed"}
MAX_CASES = 160
PAYMENT_GRACE_DAYS = max(0, min(30, int(os.getenv("LUMEN_COMMISSION_GRACE_DAYS", "3"))))


def utcnow_dt() -> datetime:
    return datetime.now(timezone.utc)


def utcnow() -> str:
    return utcnow_dt().strftime("%Y-%m-%d %H:%M:%S UTC")


def _parse(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%d"):
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


def _deal_index(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(x.get("id")): x for x in state.get("deals", []) or [] if x.get("id")}


def _account_index(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(x.get("id")): x for x in state.get("candidate_accounts", []) or [] if x.get("id")}


def _settlement_config(state: Dict[str, Any], deal: Dict[str, Any]) -> Dict[str, Any]:
    route = (state.get("payment_route_index", {}) or {}).get(str(deal.get("id") or "")) or choose_payment_route(state, deal)
    rail = route.get("selected_rail") or {}
    code = str(rail.get("code") or "")
    instructions = runtime_instruction_for(code)
    return {
        "route": route,
        "rail_code": code or None,
        "mode": code or None,
        "destination_label": rail.get("destination_label") or rail.get("label"),
        "instructions_present": bool(instructions),
        "instructions_verified": bool(rail.get("verified") and instructions),
        "auto_prepare_enabled": bool(rail.get("auto_prepare")),
        "currency": rail.get("currency") or "USD",
        "_instructions": instructions,
    }


def _buyer_account(deal: Dict[str, Any], accounts: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    return accounts.get(str(deal.get("buyer_account_id") or ""), {})


def _incident_open(state: Dict[str, Any], deal_id: str) -> bool:
    return any(str(x.get("deal_id") or "") == deal_id and str(x.get("status") or "") not in {"resolved", "closed"} for x in state.get("commercial_incidents", []) or [])


def _commission_basis(txn: Dict[str, Any], deal: Dict[str, Any]) -> float:
    for value in (txn.get("commission_amount"), txn.get("company_profit"), deal.get("company_profit"), (deal.get("economics") or {}).get("company_profit")):
        amount = _f(value)
        if amount > 0:
            return round(amount, 2)
    return 0.0


def _explicit_received_amount(txn: Dict[str, Any], deal: Dict[str, Any]) -> float | None:
    for key in ("commission_amount_received", "commission_received_amount", "settlement_amount_received"):
        for source in (txn, deal):
            if source.get(key) not in (None, ""):
                amount = _f(source.get(key), -1.0)
                return round(amount, 2) if amount >= 0 else None
    return None


def _commission_status(txn: Dict[str, Any], deal: Dict[str, Any]) -> str:
    return str(txn.get("commission_status") or deal.get("commission_status") or "").strip().lower()


def _commission_received_at(txn: Dict[str, Any], deal: Dict[str, Any]) -> Any:
    return txn.get("commission_received_at") or deal.get("commission_received_at") or txn.get("settlement_received_at") or deal.get("settlement_received_at")


def _commission_due_at(txn: Dict[str, Any], deal: Dict[str, Any]) -> Any:
    return txn.get("commission_due_at") or deal.get("commission_due_at") or txn.get("settlement_due_at") or deal.get("settlement_due_at")


def _invoice_ref(txn: Dict[str, Any], deal: Dict[str, Any]) -> Any:
    return txn.get("commission_invoice_number") or deal.get("commission_invoice_number") or txn.get("commission_invoice_id") or deal.get("commission_invoice_id")


def _existing_message(state: Dict[str, Any], execution_key: str) -> bool:
    return any(str(x.get("execution_key") or "") == execution_key for x in state.get("outbox", []) or [])


def _prepare_payment_instruction_message(state: Dict[str, Any], *, case: Dict[str, Any], deal: Dict[str, Any], buyer: Dict[str, Any], config: Dict[str, Any]) -> bool:
    if not config.get("instructions_verified") or not config.get("auto_prepare_enabled"):
        return False
    if case.get("status") not in {"AWAITING_PAYMENT", "OVERDUE", "PARTIAL_RECEIVED"}:
        return False
    if case.get("incident_hold") or deal.get("red_team_hold") or deal.get("legal_review_required"):
        return False
    email = str(buyer.get("commercial_email") or "").strip().lower()
    if not email or not buyer.get("verified_contact"):
        return False
    key = f"commission_settlement|{case.get('transaction_id')}|{case.get('status')}|{config.get('rail_code')}|v2"
    if _existing_message(state, key):
        return False
    instructions = str(config.get("_instructions") or "").strip()
    if not instructions:
        return False

    invoice_ref = case.get("invoice_ref")
    invoice_text = f" correspondiente a {invoice_ref}" if invoice_ref else ""
    amount_due = _f(case.get("outstanding_amount_usd")) or _f(case.get("expected_amount_usd"))
    rail_label = config.get("destination_label") or config.get("rail_code") or "medio verificado"
    state.setdefault("outbox", []).append({
        "id": f"MSG-{len(state.get('outbox', []))+1:04d}",
        "deal_id": deal.get("id"), "transaction_id": case.get("transaction_id"),
        "counterparty_account_id": buyer.get("id"), "kind": "commission_payment_request",
        "purpose": "collect_verified_commission_receivable", "counterparty": buyer.get("company_name") or buyer.get("name_hint") or buyer.get("domain") or deal.get("buyer"),
        "channel": "email", "contact": email, "contact_verified": True,
        "subject": "Datos para liquidación de comisión",
        "body": (f"Para la liquidación de nuestra participación comercial{invoice_text}, el saldo registrado es USD {amount_due:,.2f}. "
                 f"El medio seleccionado es {rail_label}. Los datos de cobro previamente verificados por LUMEN son: {instructions}. "
                 "Agradecemos utilizar únicamente estos datos y confirmar la referencia del pago. Si existe cualquier discrepancia, por favor no efectuar la transferencia hasta aclararla por el canal comercial habitual.")[:5600],
        "status": "ready", "execution_key": key, "created_at": utcnow(), "nonbinding": True,
        "settlement_controlled": True, "payment_rail_code": config.get("rail_code"),
        "financial_instruction_source": "verified_runtime_payment_rail",
    })
    return True


def _upsert_realized_revenue(state: Dict[str, Any], case: Dict[str, Any]) -> bool:
    if case.get("status") not in {"RECEIVED", "PARTIAL_RECEIVED"} or case.get("received_amount_usd") is None:
        return False
    amount = max(0.0, _f(case.get("received_amount_usd")))
    if amount <= 0:
        return False
    txn_id = str(case.get("transaction_id") or "")
    ledger = state.setdefault("revenue_ledger", [])
    row = next((x for x in ledger if str(x.get("transaction_id") or "") == txn_id and x.get("kind") == "commission_settlement"), None)
    payload = {"transaction_id": txn_id, "deal_id": case.get("deal_id"), "kind": "commission_settlement", "amount": round(amount, 2),
               "currency": "USD", "status": "realized_partial" if case.get("status") == "PARTIAL_RECEIVED" else "realized",
               "source": "explicit_commission_receipt_evidence", "received_at": case.get("received_at"), "payment_rail": case.get("payment_rail"), "updated_at": utcnow()}
    if row:
        row.update(payload)
        return False
    payload["id"] = f"REV-{len(ledger)+1:04d}"; payload["created_at"] = utcnow(); ledger.append(payload)
    return True


def _materialize_task(state: Dict[str, Any], case: Dict[str, Any]) -> None:
    status = str(case.get("status") or "")
    if status not in {"SETUP_REQUIRED", "INVOICE_REQUIRED", "OVERDUE", "PARTIAL_RECEIVED", "RECEIVED_AMOUNT_MISSING", "DISPUTED_HOLD"}:
        return
    human = status in {"SETUP_REQUIRED", "INVOICE_REQUIRED", "RECEIVED_AMOUNT_MISSING", "DISPUTED_HOLD"}
    priority = {"DISPUTED_HOLD": 98, "OVERDUE": 94, "PARTIAL_RECEIVED": 92, "RECEIVED_AMOUNT_MISSING": 92, "SETUP_REQUIRED": 88, "INVOICE_REQUIRED": 84}.get(status, 80)
    task = {"key": f"commission_settlement|{case.get('transaction_id')}|{status}", "kind": "commission_settlement", "title": f"Comisión: {case.get('next_action')}",
            "reason": str(case.get("next_action") or "Revisar liquidación"), "impact": 96 if status in {"OVERDUE", "DISPUTED_HOLD"} else 88,
            "urgency": priority, "confidence": 0.98, "effort": 1.0, "risk": "high" if status == "DISPUTED_HOLD" else "medium" if human else "low",
            "autonomous": not human, "object_type": "transaction", "object_id": str(case.get("transaction_id") or ""), "priority_score": priority, "created_at": utcnow()}
    queue = list(state.get("operating_action_queue", []) or []); by_key = {str(x.get("key")): x for x in queue if x.get("key")}; by_key[task["key"]] = task
    state["operating_action_queue"] = sorted(by_key.values(), key=lambda x: _f(x.get("priority_score")), reverse=True)[:120]


def _case(state: Dict[str, Any], txn: Dict[str, Any], deal: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    expected = _commission_basis(txn, deal); received_amount = _explicit_received_amount(txn, deal); received_at = _commission_received_at(txn, deal)
    explicit_status = _commission_status(txn, deal); due_raw = _commission_due_at(txn, deal); due = _parse(due_raw); invoice_ref = _invoice_ref(txn, deal)
    deal_id = str(deal.get("id") or txn.get("deal_id") or ""); incident = _incident_open(state, deal_id) or bool(deal.get("incident_hold")); now = utcnow_dt()
    route_status = str((config.get("route") or {}).get("status") or "")

    if expected <= 0:
        status, next_action = "NO_COMMISSION_BASIS", "Definir la base económica de nuestra comisión antes de liquidar"
    elif incident:
        status, next_action = "DISPUTED_HOLD", "Resolver el incidente antes de reclamar o liquidar la comisión"
    elif explicit_status in RECEIVED_COMMISSION_STATUSES or received_at:
        if received_amount is None:
            status, next_action = "RECEIVED_AMOUNT_MISSING", "Registrar el importe efectivamente recibido antes de reconocer ganancia"
        elif received_amount + 0.01 < expected:
            status, next_action = "PARTIAL_RECEIVED", "Reconocer el cobro parcial y gestionar únicamente el saldo pendiente"
        else:
            status, next_action = "RECEIVED", "Comisión cobrada y disponible para reconocimiento económico"
    elif route_status in {"COUNTRY_REQUIRED", "NO_RAIL_AVAILABLE", "RAIL_SETUP_REQUIRED"} or not config.get("instructions_verified"):
        status, next_action = "SETUP_REQUIRED", (config.get("route") or {}).get("reason") or "Configurar y verificar el destino de cobro de LUMEN"
    elif not invoice_ref:
        status, next_action = "INVOICE_REQUIRED", "Emitir/registrar documento de liquidación o factura correspondiente"
    elif due is not None and now > due + timedelta(days=PAYMENT_GRACE_DAYS):
        status, next_action = "OVERDUE", "Gestionar el cobro profesionalmente sobre el vencimiento documentado"
    else:
        status, next_action = "AWAITING_PAYMENT", "Monitorear la liquidación y conciliar el ingreso cuando exista evidencia"

    outstanding = max(0.0, expected - (received_amount or 0.0)) if status != "NO_COMMISSION_BASIS" else 0.0
    return {"transaction_id": str(txn.get("id") or ""), "deal_id": deal_id, "buyer": txn.get("buyer") or deal.get("buyer"), "supplier": txn.get("supplier") or deal.get("supplier"),
            "expected_amount_usd": round(expected, 2), "received_amount_usd": received_amount, "outstanding_amount_usd": round(outstanding, 2),
            "status": status, "next_action": next_action, "invoice_ref": invoice_ref, "due_at": due_raw, "received_at": received_at, "incident_hold": incident,
            "settlement_destination_verified": bool(config.get("instructions_verified")), "payment_rail": config.get("rail_code"), "payment_route": config.get("route"), "updated_at": utcnow()}


def commission_settlement_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    deals = _deal_index(state); accounts = _account_index(state); cases: List[Dict[str, Any]] = []; messages_prepared = 0; ledger_realizations = 0
    for txn in state.get("transactions", []) or []:
        status = str(txn.get("status") or "").strip().lower()
        if status not in REAL_TRANSACTION_STATUSES or status in {"closed_simulated", "simulated"}:
            continue
        deal = deals.get(str(txn.get("deal_id") or ""), {})
        if not deal or deal.get("source") == "demo":
            continue
        config = _settlement_config(state, deal); case = _case(state, txn, deal, config); buyer = _buyer_account(deal, accounts); case["buyer_account_id"] = buyer.get("id")
        _materialize_task(state, case)
        if _upsert_realized_revenue(state, case): ledger_realizations += 1
        if messages_prepared < 1 and _prepare_payment_instruction_message(state, case=case, deal=deal, buyer=buyer, config=config):
            case["payment_message_prepared"] = True; messages_prepared += 1
        else: case["payment_message_prepared"] = False
        cases.append(case)

    priority = {"DISPUTED_HOLD": 100, "OVERDUE": 96, "PARTIAL_RECEIVED": 94, "RECEIVED_AMOUNT_MISSING": 94, "SETUP_REQUIRED": 90, "NO_COMMISSION_BASIS": 88, "INVOICE_REQUIRED": 86, "AWAITING_PAYMENT": 70, "RECEIVED": 40}
    cases.sort(key=lambda x: priority.get(str(x.get("status")), 50), reverse=True); cases = cases[:MAX_CASES]
    expected = round(sum(_f(x.get("expected_amount_usd")) for x in cases), 2); received = round(sum(_f(x.get("received_amount_usd")) for x in cases if x.get("status") in {"RECEIVED", "PARTIAL_RECEIVED"}), 2)
    outstanding = round(sum(_f(x.get("outstanding_amount_usd")) for x in cases), 2); primary = cases[0] if cases else None
    payment_report = state.get("payment_rails", {}) or {}
    report = {"updated_at": utcnow(), "mode": "autonomous_commission_settlement", "cases": cases, "case_count": len(cases), "primary_case": primary,
              "expected_commissions_usd": expected, "received_commissions_usd": received, "outstanding_commissions_usd": outstanding, "messages_prepared": messages_prepared,
              "ledger_realizations": ledger_realizations, "payment_rails_ready": payment_report.get("ready_routes", 0), "payment_rails_setup_required": payment_report.get("setup_required", 0),
              "stage_counts": {stage: sum(1 for x in cases if x.get("status") == stage) for stage in sorted({str(x.get("status")) for x in cases})},
              "governance": {"cash_truth_rule": "Una comisión solo es ganancia realizada por el importe explícitamente recibido.",
                             "partial_payment_rule": "Los cobros parciales se reconocen solo por el importe recibido y mantienen el saldo pendiente.",
                             "payment_data_rule": "Los datos bancarios/PSP nunca se persisten en estado/Git/API; provienen de runtime verificado por rail.",
                             "routing_rule": "Argentina prioriza banco local; exterior prioriza Payoneer USD; fallback solo si está configurado y verificado.",
                             "authority_rule": "LUMEN puede preparar seguimiento de cobro; no puede mover fondos ni cambiar un destino de cobro por sí solo."}}
    state["commission_settlement"] = report; state["commission_settlement_cases"] = cases
    if primary:
        record_decision(state, engine="Commission Settlement", object_type="transaction", object_id=str(primary.get("transaction_id") or ""), decision=f"settlement:{str(primary.get('status') or '').lower()}",
                        reason=f"Comisión esperada USD {_f(primary.get('expected_amount_usd')):,.2f}; cobrada USD {_f(primary.get('received_amount_usd')):,.2f}; rail {primary.get('payment_rail')}; estado {primary.get('status')}.",
                        action="score_opportunity", confidence=0.98, evidence_refs=[], allowed=primary.get("status") not in {"DISPUTED_HOLD"},
                        requires_approval=primary.get("status") in {"SETUP_REQUIRED", "INVOICE_REQUIRED", "RECEIVED_AMOUNT_MISSING", "DISPUTED_HOLD"})
    return report
