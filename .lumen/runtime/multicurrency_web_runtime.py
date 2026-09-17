from __future__ import annotations

from fastapi import Depends, Request
from fastapi.responses import Response

from app import STATE, auth, load_state
from outbound_web import app
from payment_rails_panel import inject_payment_rails


@app.get("/health/currencies", include_in_schema=False)
def multicurrency_health(_=Depends(auth)):
    loaded = load_state()
    report = STATE.get("multicurrency_runtime", {}) or {}
    matrix = report.get("currency_matrix", {}) or {}
    return {
        "ok": bool(loaded and report.get("status") == "active"),
        "version": report.get("version"),
        "supported_currencies": report.get("supported_currencies", []),
        "ready_currencies": report.get("ready_currencies", []),
        "setup_required_currencies": report.get("setup_required_currencies", []),
        "currencies": {
            code: {
                "supported": bool((matrix.get(code) or {}).get("supported")),
                "commercial_processing_active": bool((matrix.get(code) or {}).get("commercial_processing_active")),
                "rail_enabled": bool((matrix.get(code) or {}).get("rail_enabled")),
                "rail_verified": bool((matrix.get(code) or {}).get("rail_verified")),
                "ready_to_collect": bool((matrix.get(code) or {}).get("ready_to_collect")),
                "status": (matrix.get(code) or {}).get("status"),
                "primary_rail_code": (matrix.get(code) or {}).get("primary_rail_code"),
            }
            for code in ("ARS", "USD", "EUR")
        },
        "automatic_fx_conversion": False,
        "autonomous_payment": False,
        "updated_at": report.get("updated_at"),
    }


@app.middleware("http")
async def multicurrency_command_center(request: Request, call_next):
    response = await call_next(request)
    if request.url.path != "/command-center" or "text/html" not in str(response.headers.get("content-type") or ""):
        return response

    body = b""
    async for chunk in response.body_iterator:
        body += chunk
    text = body.decode("utf-8", errors="replace")
    if "MULTIMONEDA · TESORERÍA" not in text:
        text = inject_payment_rails(text, STATE)
    headers = dict(response.headers)
    headers.pop("content-length", None)
    return Response(content=text, status_code=response.status_code, headers=headers, media_type="text/html")


try:
    loaded = load_state()
    report = STATE.get("multicurrency_runtime", {}) or {}
    matrix = report.get("currency_matrix", {}) or {}
    print({
        "multicurrency_web_runtime": {
            "status": "active" if loaded else "state_unavailable",
            "ars_ready": bool((matrix.get("ARS") or {}).get("ready_to_collect")),
            "usd_ready": bool((matrix.get("USD") or {}).get("ready_to_collect")),
            "eur_ready": bool((matrix.get("EUR") or {}).get("ready_to_collect")),
            "automatic_fx_conversion": False,
        }
    }, flush=True)
except Exception as exc:
    print({"multicurrency_web_runtime": {"status": "degraded_fail_open", "error": f"{type(exc).__name__}: {str(exc)[:220]}"}}, flush=True)
