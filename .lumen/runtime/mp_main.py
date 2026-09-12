from __future__ import annotations

import html

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from app import auth
from main import app, STATE, load_state, save_state
from mercadopago_gateway import (
    create_checkout_probe,
    fetch_payment,
    public_status,
    reconcile_payment,
    validate_webhook_signature,
    verify_access_token,
)


@app.get("/health/mercadopago")
def mercadopago_health():
    status = public_status()
    auth_status = verify_access_token()
    return {
        "ok": bool(status.get("access_token_configured") and status.get("webhook_secret_configured") and auth_status.get("authenticated")),
        "provider": "mercadopago",
        "access_token_configured": bool(status.get("access_token_configured")),
        "access_token_authenticated": bool(auth_status.get("authenticated")),
        "site_id": auth_status.get("site_id"),
        "test_user": auth_status.get("test_user"),
        "webhook_secret_configured": bool(status.get("webhook_secret_configured")),
        "webhook_ready": bool(status.get("webhook_ready")),
        "webhook_path": status.get("webhook_path"),
        "secrets_exposed": False,
    }


def _probe_page(probe=None, error: str = "") -> HTMLResponse:
    probe = probe or {}
    if probe.get("preference_id") and str(probe.get("init_point") or "").startswith("https://"):
        body = f"""
        <div class='ok'>Preferencia creada correctamente.</div>
        <p><b>Importe:</b> ARS {html.escape(str(probe.get('amount_ars') or '100.00'))}</p>
        <p><b>Referencia:</b> {html.escape(str(probe.get('external_reference') or ''))}</p>
        <p><b>Preference ID:</b> {html.escape(str(probe.get('preference_id') or ''))}</p>
        <p><a class='btn secondary' href='{html.escape(str(probe.get('init_point') or ''))}' target='_blank' rel='noopener'>Abrir Checkout Pro (NO PAGAR)</a></p>
        <p class='warn'><b>No pagues este link.</b> Esta preferencia existe sólo para validar que LUMEN puede crear Checkout Pro con la cuenta productiva. No representa una venta ni una comisión.</p>
        """
    else:
        error_html = f"<div class='err'>{html.escape(error)}</div>" if error else ""
        body = f"""
        {error_html}
        <p>Esta prueba crea una única preferencia productiva de <b>ARS 100</b> para verificar la conexión saliente de LUMEN con Mercado Pago.</p>
        <p>No envía correos, no toca deals, no registra ingresos y no realiza ningún pago.</p>
        <form method='post' action='/mercadopago/probe'>
          <button class='btn' type='submit'>Crear link de prueba</button>
        </form>
        <p class='warn'>Después de crearla, sólo vamos a comprobar que Mercado Pago devuelve un Checkout válido. <b>No hay que pagarlo.</b></p>
        """
    return HTMLResponse(f"""<!doctype html>
<html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>LUMEN · Prueba Mercado Pago</title>
<style>
body{{font-family:Arial,sans-serif;max-width:760px;margin:48px auto;padding:0 20px;background:#f5f7fb;color:#172033}}
.card{{background:white;padding:28px;border-radius:16px;box-shadow:0 8px 28px #00000012}}
.btn{{display:inline-block;background:#172033;color:white;border:0;border-radius:10px;padding:13px 18px;text-decoration:none;font-weight:700;cursor:pointer}}
.secondary{{background:#009ee3}} .ok{{padding:12px;background:#eaf8ef;border-radius:10px;font-weight:700;color:#176b39}}
.warn{{padding:12px;background:#fff7df;border-radius:10px}} .err{{padding:12px;background:#ffe9e9;border-radius:10px;color:#9b1c1c}}
small{{color:#667085}}
</style></head><body><div class='card'>
<h1>Mercado Pago · prueba controlada</h1>
{body}
<hr><small>LUMEN no expone credenciales ni reconoce esta preferencia como ingreso.</small>
</div></body></html>""")


@app.get("/mercadopago/probe", response_class=HTMLResponse)
def mercadopago_probe_view(_=Depends(auth)):
    load_state()
    return _probe_page(STATE.get("mercadopago_probe") or {})


@app.post("/mercadopago/probe", response_class=HTMLResponse)
def mercadopago_probe_create(_=Depends(auth)):
    load_state()
    existing = STATE.get("mercadopago_probe") or {}
    if existing.get("preference_id") and str(existing.get("init_point") or "").startswith("https://"):
        return _probe_page(existing)
    try:
        probe = create_checkout_probe(100.0)
    except Exception as exc:
        return _probe_page(error=f"No se pudo crear la preferencia: {type(exc).__name__}")
    STATE["mercadopago_probe"] = {
        **probe,
        "status": "CREATED_NOT_PAID",
        "human_payment_not_requested": True,
        "excluded_from_revenue": True,
    }
    if not save_state():
        raise HTTPException(status_code=503, detail="probe_created_but_persistence_unavailable")
    return _probe_page(STATE["mercadopago_probe"])


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
