from __future__ import annotations

from fastapi import HTTPException, Request

from main import app, STATE, load_state, save_state
from mercadopago_gateway import fetch_payment, public_status, reconcile_payment, validate_webhook_signature


@app.post("/webhooks/mercadopago")
async def mercadopago_webhook(request: Request):
    config = public_status()
    if not config.get("webhook_secret_configured"):
        raise HTTPException(status_code=503, detail="mercadopago_webhook_secret_not_configured")

    try:
        payload = await request.json()
    except Exception:
        payload = {}

    data_id = str(request.query_params.get("data.id") or ((payload.get("data") or {}).get("id")) or "").strip()
    x_signature = str(request.headers.get("x-signature") or "")
    x_request_id = str(request.headers.get("x-request-id") or "")

    if not data_id or not validate_webhook_signature(x_signature, x_request_id, data_id):
        raise HTTPException(status_code=401, detail="invalid_mercadopago_webhook_signature")

    load_state()
    STATE.setdefault("mercadopago_webhook_events", [])
    event_key = f"{payload.get('id')}|{payload.get('action')}|{data_id}"
    if any(str(x.get("event_key") or "") == event_key for x in STATE["mercadopago_webhook_events"]):
        return {"ok": True, "duplicate": True}

    # Mercado Pago's webhook simulator sends a signed non-live event with an arbitrary Data ID.
    # Validate and acknowledge it without inventing a payment or querying a non-existent resource.
    if payload.get("live_mode") is False:
        STATE["mercadopago_webhook_events"].append({
            "event_key": event_key,
            "notification_id": payload.get("id"),
            "data_id": data_id,
            "action": payload.get("action"),
            "type": payload.get("type"),
            "live_mode": False,
            "status": "signature_validated_test",
        })
        STATE["mercadopago_webhook_events"] = STATE["mercadopago_webhook_events"][-300:]
        if not save_state():
            raise HTTPException(status_code=503, detail="persistence_unavailable")
        return {"ok": True, "test": True, "signature_valid": True}

    if str(payload.get("type") or request.query_params.get("type") or "") != "payment":
        return {"ok": True, "ignored": True, "reason": "unsupported_topic"}

    try:
        payment = fetch_payment(data_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"mercadopago_payment_lookup_failed:{str(exc)[:120]}")

    if str(payment.get("id") or "") != data_id:
        raise HTTPException(status_code=409, detail="mercadopago_payment_id_mismatch")

    reconciliation = reconcile_payment(STATE, payment)
    STATE["mercadopago_webhook_events"].append({
        "event_key": event_key,
        "notification_id": payload.get("id"),
        "data_id": data_id,
        "action": payload.get("action"),
        "type": "payment",
        "live_mode": True,
        "status": "verified_and_reconciled",
        "payment_status": payment.get("status"),
        "matched_transaction_id": reconciliation.get("matched_transaction_id"),
    })
    STATE["mercadopago_webhook_events"] = STATE["mercadopago_webhook_events"][-300:]
    if not save_state():
        raise HTTPException(status_code=503, detail="persistence_unavailable")
    return {"ok": True, "verified": True, "payment_status": payment.get("status")}
