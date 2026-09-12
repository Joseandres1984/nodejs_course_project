from __future__ import annotations

import hashlib
import hmac
import json
import os
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict

API_BASE = "https://api.mercadopago.com"
ACCESS_TOKEN = os.getenv("LUMEN_MP_ACCESS_TOKEN", "").strip()
WEBHOOK_SECRET = os.getenv("LUMEN_MP_WEBHOOK_SECRET", "").strip()


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def public_status() -> Dict[str, Any]:
    return {
        "provider": "mercadopago",
        "access_token_configured": bool(ACCESS_TOKEN),
        "webhook_secret_configured": bool(WEBHOOK_SECRET),
        "webhook_ready": bool(ACCESS_TOKEN and WEBHOOK_SECRET),
        "webhook_path": "/webhooks/mercadopago",
        "secrets_persisted": False,
    }


def _signature_parts(value: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for part in str(value or "").split(","):
        if "=" not in part:
            continue
        key, val = part.split("=", 1)
        out[key.strip()] = val.strip()
    return out


def validate_webhook_signature(x_signature: str, x_request_id: str, data_id: str) -> bool:
    if not WEBHOOK_SECRET or not x_signature:
        return False
    parts = _signature_parts(x_signature)
    ts, v1 = parts.get("ts", ""), parts.get("v1", "")
    if not ts or not v1:
        return False
    manifest = ""
    if data_id:
        manifest += f"id:{str(data_id).lower()};"
    if x_request_id:
        manifest += f"request-id:{x_request_id};"
    manifest += f"ts:{ts};"
    expected = hmac.new(WEBHOOK_SECRET.encode("utf-8"), manifest.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, v1)


def fetch_payment(payment_id: str) -> Dict[str, Any]:
    if not ACCESS_TOKEN:
        raise RuntimeError("mercadopago_access_token_not_configured")
    req = urllib.request.Request(
        f"{API_BASE}/v1/payments/{payment_id}",
        headers={"Authorization": f"Bearer {ACCESS_TOKEN}", "Accept": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def reconcile_payment(state: Dict[str, Any], payment: Dict[str, Any]) -> Dict[str, Any]:
    payment_id = str(payment.get("id") or "")
    status = str(payment.get("status") or "")
    external_reference = str(payment.get("external_reference") or "")
    currency = str(payment.get("currency_id") or "")
    try:
        amount = float(payment.get("transaction_amount") or 0)
    except (TypeError, ValueError):
        amount = 0.0

    receipts = state.setdefault("payment_receipts", [])
    receipt = next((x for x in receipts if str(x.get("provider_payment_id") or "") == payment_id), None)
    payload = {
        "provider": "mercadopago",
        "provider_payment_id": payment_id,
        "status": status,
        "external_reference": external_reference or None,
        "amount": round(amount, 2),
        "currency": currency or None,
        "date_approved": payment.get("date_approved"),
        "updated_at": utcnow(),
        "source": "verified_mercadopago_api",
    }
    if receipt:
        receipt.update(payload)
    else:
        payload["id"] = f"RCPT-{len(receipts)+1:05d}"
        payload["created_at"] = utcnow()
        receipts.append(payload)
        receipt = payload

    matched_transaction = None
    if external_reference.startswith("LUMEN-COM-"):
        txn_id = external_reference[len("LUMEN-COM-"):]
        matched_transaction = next((x for x in state.get("transactions", []) or [] if str(x.get("id") or "") == txn_id), None)
        if matched_transaction:
            matched_transaction["mercadopago_payment_id"] = payment_id
            matched_transaction["commission_payment_status"] = status
            matched_transaction["commission_received_original_amount"] = round(amount, 2)
            matched_transaction["commission_received_currency"] = currency or None
            matched_transaction["commission_payment_verified_at"] = utcnow()
            if status == "approved":
                matched_transaction["commission_payment_approved_at"] = payment.get("date_approved") or utcnow()
                # Only feed the legacy USD settlement amount when Mercado Pago itself confirms USD.
                # ARS receipts remain fully reconciled in original currency until an explicit FX/accounting rule converts them.
                if currency == "USD":
                    matched_transaction["commission_received_amount"] = round(amount, 2)
                    matched_transaction["commission_received_at"] = payment.get("date_approved") or utcnow()
                    matched_transaction["commission_status"] = "received"

    state["mercadopago_gateway"] = {
        **public_status(),
        "last_payment_id": payment_id or None,
        "last_payment_status": status or None,
        "last_external_reference": external_reference or None,
        "last_reconciled_at": utcnow(),
        "matched_transaction": str((matched_transaction or {}).get("id") or "") or None,
    }
    return {"receipt": receipt, "matched_transaction_id": (matched_transaction or {}).get("id")}
