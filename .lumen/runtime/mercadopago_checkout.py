from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List

API_BASE = "https://api.mercadopago.com"
REAL_TRANSACTION_STATUSES = {"closed", "invoiced", "delivered", "paid", "settled", "completed"}
MAX_LINKS = 160
MAX_NEW_PREFERENCES_PER_CYCLE = 1
MAX_NEW_MESSAGES_PER_CYCLE = 1
BRAND_NAME = "LUMEN"


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _token() -> str:
    return str(os.getenv("LUMEN_MP_ACCESS_TOKEN", "") or "").strip()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _deal_index(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(x.get("id")): x for x in state.get("deals", []) or [] if x.get("id")}


def _account_index(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(x.get("id")): x for x in state.get("candidate_accounts", []) or [] if x.get("id")}


def _commission_amount(txn: Dict[str, Any], deal: Dict[str, Any]) -> float:
    for value in (
        txn.get("commission_amount"),
        deal.get("commission_amount"),
        txn.get("company_profit"),
        deal.get("company_profit"),
        (deal.get("economics") or {}).get("company_profit"),
    ):
        amount = _f(value)
        if amount > 0:
            return round(amount, 2)
    return 0.0


def _commission_currency(txn: Dict[str, Any], deal: Dict[str, Any]) -> str:
    for value in (
        txn.get("commission_currency"),
        deal.get("commission_currency"),
        deal.get("fee_currency"),
        txn.get("currency"),
        deal.get("currency"),
        (deal.get("economics") or {}).get("currency"),
    ):
        text = str(value or "").strip().upper()
        if text in {"ARS", "USD", "EUR"}:
            return text
    return ""


def _invoice_ref(txn: Dict[str, Any], deal: Dict[str, Any]) -> str:
    return str(
        txn.get("commission_invoice_number")
        or deal.get("commission_invoice_number")
        or txn.get("commission_invoice_id")
        or deal.get("commission_invoice_id")
        or ""
    ).strip()


def _existing_message(state: Dict[str, Any], key: str) -> bool:
    return any(str(x.get("execution_key") or "") == key for x in state.get("outbox", []) or [])


def _risk_allows_outreach(state: Dict[str, Any], account_id: Any) -> bool:
    risk = (state.get("counterparty_risk_index", {}) or {}).get(str(account_id or ""), {}) or {}
    return risk.get("risk_tier") != "BLOCKED" and risk.get("can_outreach") is not False


def _api_request(method: str, path: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    token = _token()
    if not token:
        raise RuntimeError("mercadopago_access_token_not_configured")
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(f"{API_BASE}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _search_preference(external_reference: str) -> Dict[str, Any] | None:
    query = urllib.parse.urlencode({"external_reference": external_reference})
    response = _api_request("GET", f"/checkout/preferences/search?{query}")
    rows = response.get("elements") or response.get("results") or []
    for row in rows:
        if str(row.get("external_reference") or "") == external_reference and row.get("id") and row.get("init_point"):
            return row
    return None


def _create_preference(*, txn_id: str, deal_id: str, amount_ars: float, invoice_ref: str) -> Dict[str, Any]:
    external_reference = f"LUMEN-COM-{txn_id}"
    payload = {
        "items": [
            {
                "id": f"COM-{txn_id}",
                "title": f"LUMEN · Liquidación de comisión comercial {invoice_ref}",
                "currency_id": "ARS",
                "quantity": 1,
                "unit_price": round(amount_ars, 2),
            }
        ],
        "statement_descriptor": BRAND_NAME,
        "external_reference": external_reference,
        "metadata": {"lumen_transaction_id": txn_id, "lumen_deal_id": deal_id, "brand": BRAND_NAME},
    }
    return _api_request("POST", "/checkout/preferences", payload)


def _recover_or_create_preference(*, txn_id: str, deal_id: str, amount_ars: float, invoice_ref: str) -> Dict[str, Any]:
    external_reference = f"LUMEN-COM-{txn_id}"
    existing = _search_preference(external_reference)
    if existing:
        return existing
    return _create_preference(txn_id=txn_id, deal_id=deal_id, amount_ars=amount_ars, invoice_ref=invoice_ref)


def _prepare_collection_message(
    state: Dict[str, Any], *, txn: Dict[str, Any], deal: Dict[str, Any], buyer: Dict[str, Any], link: Dict[str, Any]
) -> bool:
    email = str(buyer.get("commercial_email") or "").strip().lower()
    if not email or not buyer.get("verified_contact") or not _risk_allows_outreach(state, buyer.get("id")):
        return False
    if deal.get("incident_hold") or deal.get("red_team_hold") or deal.get("legal_review_required"):
        return False
    txn_id = str(txn.get("id") or "")
    preference_id = str(link.get("preference_id") or "")
    key = f"mercadopago_collection|{txn_id}|{preference_id}|v1"
    if not preference_id or _existing_message(state, key):
        return False
    amount = _f(link.get("amount_ars"))
    checkout_url = str(link.get("init_point") or "").strip()
    if amount <= 0 or not checkout_url.startswith("https://"):
        return False

    invoice_ref = str(link.get("invoice_ref") or "").strip()
    state.setdefault("outbox", []).append({
        "id": f"MSG-{len(state.get('outbox', []))+1:04d}",
        "deal_id": deal.get("id"),
        "transaction_id": txn_id,
        "counterparty_account_id": buyer.get("id"),
        "kind": "commission_payment_request",
        "purpose": "collect_verified_commission_receivable_via_mercadopago",
        "counterparty": buyer.get("company_name") or buyer.get("name_hint") or buyer.get("domain") or deal.get("buyer"),
        "channel": "email",
        "contact": email,
        "contact_verified": True,
        "subject": "LUMEN · Link de pago para liquidación de comisión",
        "body": (
            f"Para la liquidación de nuestra participación comercial correspondiente a {invoice_ref}, "
            f"el importe documentado es ARS {amount:,.2f}. Puede abonarse mediante el enlace seguro de Mercado Pago: {checkout_url}. "
            f"Referencia: LUMEN-COM-{txn_id}. Si existe cualquier discrepancia en importe, concepto o condiciones, por favor no realizar el pago hasta aclararla por el canal comercial habitual."
        )[:5600],
        "status": "ready",
        "execution_key": key,
        "created_at": utcnow(),
        "nonbinding": True,
        "settlement_controlled": True,
        "payment_rail_code": "mercadopago_ars",
        "financial_instruction_source": "mercadopago_checkout_pro_api",
        "mercadopago_preference_id": preference_id,
    })
    return True


def mercadopago_checkout_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    configured = bool(_token())
    deals = _deal_index(state)
    accounts = _account_index(state)
    links: List[Dict[str, Any]] = []
    created = 0
    recovered = 0
    messages = 0
    blocked_currency = 0
    errors = 0

    if not configured:
        report = {
            "updated_at": utcnow(), "configured": False, "status": "SETUP_REQUIRED", "links": [],
            "created_this_cycle": 0, "messages_prepared": 0,
            "rule": "Checkout Pro se habilita únicamente con Access Token presente en runtime; los secretos nunca se persisten.",
        }
        state["mercadopago_checkout"] = report
        return report

    for txn in state.get("transactions", []) or []:
        if created >= MAX_NEW_PREFERENCES_PER_CYCLE and messages >= MAX_NEW_MESSAGES_PER_CYCLE:
            break
        txn_status = str(txn.get("status") or "").strip().lower()
        if txn_status not in REAL_TRANSACTION_STATUSES or txn_status in {"closed_simulated", "simulated"}:
            continue
        deal = deals.get(str(txn.get("deal_id") or ""), {})
        if not deal or deal.get("source") == "demo":
            continue
        route = (state.get("payment_route_index", {}) or {}).get(str(deal.get("id") or ""), {}) or {}
        rail = route.get("selected_rail") or {}
        if route.get("status") != "READY" or str(rail.get("code") or "") != "mercadopago_ars":
            continue
        if deal.get("incident_hold") or deal.get("red_team_hold") or deal.get("legal_review_required"):
            continue
        invoice_ref = _invoice_ref(txn, deal)
        if not invoice_ref:
            continue
        currency = _commission_currency(txn, deal)
        if currency != "ARS":
            blocked_currency += 1
            continue
        expected = _commission_amount(txn, deal)
        if expected <= 0:
            continue

        received = 0.0
        if str(txn.get("commission_received_currency") or "").upper() == "ARS":
            received = max(0.0, _f(txn.get("commission_received_original_amount")))
        outstanding = round(max(0.0, expected - received), 2)
        if outstanding <= 0 or str(txn.get("commission_payment_status") or "").lower() == "approved":
            continue

        txn_id = str(txn.get("id") or "")
        deal_id = str(deal.get("id") or "")
        external_reference = f"LUMEN-COM-{txn_id}"
        existing_id = str(txn.get("mercadopago_preference_id") or "")
        existing_url = str(txn.get("mercadopago_init_point") or "")
        preference: Dict[str, Any] = {}
        source = "state"

        if existing_id and existing_url.startswith("https://"):
            preference = {"id": existing_id, "init_point": existing_url, "external_reference": external_reference}
        else:
            if created >= MAX_NEW_PREFERENCES_PER_CYCLE:
                continue
            try:
                preference = _recover_or_create_preference(
                    txn_id=txn_id, deal_id=deal_id, amount_ars=outstanding, invoice_ref=invoice_ref
                )
                source = "api"
                if str(preference.get("external_reference") or "") == external_reference:
                    recovered += 1
                created += 1
            except Exception as exc:
                errors += 1
                state.setdefault("activity", []).insert(0, {
                    "ts": utcnow(),
                    "msg": f"Mercado Pago Checkout: no se pudo preparar el link para {txn_id}; {type(exc).__name__}. No se envió solicitud de cobro.",
                })
                continue

        preference_id = str(preference.get("id") or "")
        init_point = str(preference.get("init_point") or "")
        if not preference_id or not init_point.startswith("https://"):
            errors += 1
            continue

        txn["mercadopago_preference_id"] = preference_id
        txn["mercadopago_init_point"] = init_point
        txn["mercadopago_external_reference"] = external_reference
        txn["mercadopago_amount_ars"] = outstanding
        txn["mercadopago_preference_updated_at"] = utcnow()

        link = {
            "transaction_id": txn_id,
            "deal_id": deal_id,
            "preference_id": preference_id,
            "external_reference": external_reference,
            "amount_ars": outstanding,
            "currency": "ARS",
            "invoice_ref": invoice_ref,
            "init_point": init_point,
            "source": source,
            "brand": BRAND_NAME,
            "updated_at": utcnow(),
        }
        links.append(link)

        buyer = accounts.get(str(deal.get("buyer_account_id") or ""), {})
        if messages < MAX_NEW_MESSAGES_PER_CYCLE and _prepare_collection_message(
            state, txn=txn, deal=deal, buyer=buyer, link=link
        ):
            messages += 1

    existing_links = [
        x for x in state.get("mercadopago_checkout_links", []) or []
        if str(x.get("transaction_id") or "") not in {str(y.get("transaction_id") or "") for y in links}
    ]
    state["mercadopago_checkout_links"] = (links + existing_links)[:MAX_LINKS]
    report = {
        "updated_at": utcnow(),
        "configured": True,
        "status": "READY",
        "brand": BRAND_NAME,
        "links": state.get("mercadopago_checkout_links", []),
        "active_links": len(state.get("mercadopago_checkout_links", [])),
        "created_or_recovered_this_cycle": created,
        "recovered_by_reference_this_cycle": recovered,
        "messages_prepared": messages,
        "currency_blocks": blocked_currency,
        "errors": errors,
        "governance": {
            "currency_rule": "Mercado Pago Argentina solo genera automáticamente cobros cuya comisión esté documentada en ARS; nunca convierte USD/EUR por su cuenta.",
            "evidence_rule": "Requiere transacción real, riel READY, importe positivo, moneda ARS y referencia de factura/liquidación.",
            "risk_rule": "No prepara ni envía cobro con incident_hold, red_team_hold, legal_review_required o contrapartida bloqueada.",
            "cash_truth_rule": "Crear un link no equivale a cobrar. El ingreso solo se reconoce tras Webhook firmado y verificación API del pago.",
        },
    }
    state["mercadopago_checkout"] = report
    return report
