from __future__ import annotations

import hashlib
import hmac
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse

from app import STATE, auth, load_state, log, save_state
from outbound_web import app

INSTAGRAM_ACCESS_TOKEN = os.getenv("LUMEN_INSTAGRAM_ACCESS_TOKEN", "").strip()
INSTAGRAM_USER_ID = os.getenv("LUMEN_INSTAGRAM_USER_ID", "").strip()
INSTAGRAM_USERNAME = os.getenv("LUMEN_INSTAGRAM_USERNAME", "").strip()
INSTAGRAM_GRAPH_BASE = os.getenv("LUMEN_INSTAGRAM_GRAPH_BASE", "https://graph.instagram.com").rstrip("/")
INSTAGRAM_VERIFY_TOKEN = os.getenv("LUMEN_INSTAGRAM_WEBHOOK_VERIFY_TOKEN", "").strip()
INSTAGRAM_APP_SECRET = os.getenv("LUMEN_INSTAGRAM_APP_SECRET", "").strip()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _graph_get(path: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if not INSTAGRAM_ACCESS_TOKEN:
        raise RuntimeError("Instagram access token is not configured")

    query = urllib.parse.urlencode(params or {})
    url = f"{INSTAGRAM_GRAPH_BASE}/{path.lstrip('/')}"
    if query:
        url = f"{url}?{query}"

    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {INSTAGRAM_ACCESS_TOKEN}",
            "Accept": "application/json",
            "User-Agent": "LUMEN-B2B/1.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = response.read().decode("utf-8")
            return json.loads(payload or "{}")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")[:500]
        except Exception:
            detail = ""
        raise RuntimeError(f"Instagram Graph HTTP {exc.code}: {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Instagram Graph connection error: {exc.reason}") from exc


def get_instagram_profile() -> Dict[str, Any]:
    target = INSTAGRAM_USER_ID or "me"
    data = _graph_get(target, {"fields": "user_id,username,id"})
    username = str(data.get("username") or INSTAGRAM_USERNAME or "")
    user_id = str(data.get("user_id") or data.get("id") or INSTAGRAM_USER_ID or "")
    return {
        "user_id": user_id,
        "username": username,
        "connected": bool(user_id or username),
    }


def instagram_status() -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "configured": bool(INSTAGRAM_ACCESS_TOKEN),
        "connected": False,
        "username": INSTAGRAM_USERNAME or None,
        "user_id": INSTAGRAM_USER_ID or None,
        "webhook_verify_configured": bool(INSTAGRAM_VERIFY_TOKEN),
        "webhook_signature_configured": bool(INSTAGRAM_APP_SECRET),
        "checked_at": _now_iso(),
    }
    if not INSTAGRAM_ACCESS_TOKEN:
        base["status"] = "not_configured"
        return base

    try:
        profile = get_instagram_profile()
        base.update(profile)
        base["status"] = "connected" if profile.get("connected") else "unexpected_response"
    except Exception as exc:
        base["status"] = "error"
        base["error"] = f"{type(exc).__name__}: {str(exc)[:350]}"
    return base


@app.get("/health/instagram", include_in_schema=False)
def instagram_health():
    """Safe health endpoint. Never returns access tokens or app secrets."""
    return instagram_status()


@app.get("/api/integrations/instagram/status", include_in_schema=False)
def instagram_private_status(_=Depends(auth)):
    """Authenticated integration status for the LUMEN command center."""
    return instagram_status()


@app.get("/webhooks/instagram", include_in_schema=False, response_class=PlainTextResponse)
def instagram_webhook_verify(request: Request):
    """Meta webhook verification handshake."""
    if not INSTAGRAM_VERIFY_TOKEN:
        raise HTTPException(status_code=503, detail="Instagram webhook verification is not configured")

    mode = request.query_params.get("hub.mode")
    verify_token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and verify_token == INSTAGRAM_VERIFY_TOKEN and challenge:
        return PlainTextResponse(challenge, status_code=200)
    raise HTTPException(status_code=403, detail="Webhook verification failed")


@app.post("/webhooks/instagram", include_in_schema=False)
async def instagram_webhook_receive(request: Request):
    """Receive signed Instagram webhook events and persist audit + Operator state atomically."""
    if not INSTAGRAM_APP_SECRET:
        raise HTTPException(status_code=503, detail="Instagram webhook signature verification is not configured")

    body = await request.body()
    supplied_signature = request.headers.get("x-hub-signature-256", "")
    expected_signature = "sha256=" + hmac.new(
        INSTAGRAM_APP_SECRET.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    if not supplied_signature or not hmac.compare_digest(supplied_signature, expected_signature):
        raise HTTPException(status_code=403, detail="Invalid webhook signature")

    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    load_state()
    events = list(STATE.get("instagram_webhook_events", []) or [])
    events.insert(
        0,
        {
            "received_at": _now_iso(),
            "object": payload.get("object"),
            "payload": payload,
        },
    )
    STATE["instagram_webhook_events"] = events[:100]

    operator_created = 0
    operator_error = None
    try:
        # The module is imported lazily to avoid circular imports during startup.
        # At request time public_entry has already registered Instagram Operator.
        from instagram_operator import process_instagram_webhook

        operator_result = process_instagram_webhook(payload, persist=False)
        operator_created = int(operator_result.get("created") or 0)
    except Exception as exc:
        operator_error = f"{type(exc).__name__}: {str(exc)[:300]}"
        print({"instagram_operator_direct_bridge": {"status": "error", "error": operator_error}}, flush=True)

    log(f"Instagram webhook recibido ({payload.get('object') or 'evento'}).")
    persisted = bool(save_state())
    print(
        {
            "instagram_webhook_receive": {
                "status": "ok",
                "persisted": persisted,
                "operator_created": operator_created,
                "operator_error": operator_error,
                "raw_events": len(STATE.get("instagram_webhook_events", []) or []),
                "operator_inbox": len(STATE.get("instagram_inbox", []) or []),
            }
        },
        flush=True,
    )
    return {"ok": True}
