from __future__ import annotations

"""WhatsApp Cloud API webhook for LUMEN.

Public verification + inbound event capture. Verification token and Meta App Secret
live only in Railway environment variables. Unsigned events are never promoted to
trusted commercial input. Raw webhook payloads are stored in a dedicated PostgreSQL
table to avoid overwriting the shared LUMEN state during concurrent worker cycles.
"""

import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List

import psycopg
from psycopg.types.json import Jsonb
from fastapi import Request
from fastapi.responses import JSONResponse, PlainTextResponse

from outbound_web import app

VERSION = "1.0-whatsapp-production-webhook"
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _verify_token() -> str:
    return os.getenv("LUMEN_WHATSAPP_VERIFY_TOKEN", "").strip()


def _app_secret() -> str:
    return os.getenv("LUMEN_META_APP_SECRET", "").strip()


def _ensure_table() -> bool:
    if not DATABASE_URL:
        return False
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS lumen_whatsapp_webhooks (
                    event_key TEXT PRIMARY KEY,
                    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    signature_verified BOOLEAN NOT NULL DEFAULT FALSE,
                    object_type TEXT,
                    payload JSONB NOT NULL
                )
            """)
    return True


def _signature_ok(raw: bytes, header: str) -> bool:
    secret = _app_secret()
    if not secret:
        return False
    prefix = "sha256="
    if not header.startswith(prefix):
        return False
    expected = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    supplied = header[len(prefix):].strip()
    return bool(supplied) and hmac.compare_digest(expected, supplied)


def _event_key(payload: Dict[str, Any], raw: bytes) -> str:
    ids: List[str] = []
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value", {}) or {}
            for msg in value.get("messages", []) or []:
                if msg.get("id"):
                    ids.append(str(msg["id"]))
            for status in value.get("statuses", []) or []:
                if status.get("id"):
                    ids.append(str(status["id"]) + ":" + str(status.get("status") or ""))
    seed = "|".join(ids) if ids else hashlib.sha256(raw).hexdigest()
    return "WAW-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


def _store(payload: Dict[str, Any], raw: bytes, verified: bool) -> bool:
    if not _ensure_table():
        return False
    key = _event_key(payload, raw)
    safe_payload = payload if len(raw) <= 512_000 else {"object": payload.get("object"), "truncated": True}
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO lumen_whatsapp_webhooks(event_key,received_at,signature_verified,object_type,payload)
                   VALUES (%s,NOW(),%s,%s,%s)
                   ON CONFLICT (event_key) DO NOTHING""",
                (key, bool(verified), str(payload.get("object") or "")[:120], Jsonb(safe_payload)),
            )
    return True


@app.get("/webhooks/whatsapp", include_in_schema=False)
def whatsapp_webhook_verify(request: Request):
    mode = request.query_params.get("hub.mode", "")
    challenge = request.query_params.get("hub.challenge", "")
    supplied = request.query_params.get("hub.verify_token", "")
    expected = _verify_token()
    if mode == "subscribe" and challenge and expected and secrets.compare_digest(supplied, expected):
        return PlainTextResponse(challenge, status_code=200)
    return PlainTextResponse("verification failed", status_code=403)


@app.post("/webhooks/whatsapp", include_in_schema=False)
async def whatsapp_webhook_receive(request: Request):
    raw = await request.body()
    if len(raw) > 1_000_000:
        return JSONResponse({"ok": False, "reason": "payload_too_large"}, status_code=413)
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except Exception:
        return JSONResponse({"ok": False, "reason": "invalid_json"}, status_code=400)
    if not isinstance(payload, dict) or payload.get("object") != "whatsapp_business_account":
        return JSONResponse({"ok": False, "reason": "unsupported_object"}, status_code=400)

    signature = request.headers.get("x-hub-signature-256", "")
    verified = _signature_ok(raw, signature)
    # When an App Secret is configured, fail closed on a bad/missing signature.
    if _app_secret() and not verified:
        return JSONResponse({"ok": False, "reason": "invalid_signature"}, status_code=403)

    stored = False
    try:
        stored = _store(payload, raw, verified)
    except Exception as exc:
        print({"whatsapp_webhook": {"version": VERSION, "status": "store_error", "error": type(exc).__name__}}, flush=True)

    print({
        "whatsapp_webhook": {
            "version": VERSION,
            "status": "received",
            "signature_verified": verified,
            "trusted_for_commercial_ingest": bool(verified),
            "stored": stored,
            "app_secret_configured": bool(_app_secret()),
            "secrets_exposed": False,
            "received_at": _now(),
        }
    }, flush=True)
    return JSONResponse({"ok": True}, status_code=200)


@app.get("/health/whatsapp-webhook", include_in_schema=False)
def whatsapp_webhook_health():
    return {
        "ok": bool(_verify_token() and DATABASE_URL),
        "version": VERSION,
        "route": "/webhooks/whatsapp",
        "verify_token_configured": bool(_verify_token()),
        "app_secret_configured": bool(_app_secret()),
        "signature_required_for_trusted_ingest": True,
        "database_configured": bool(DATABASE_URL),
        "secrets_exposed": False,
    }


print({
    "whatsapp_webhook_runtime": {
        "version": VERSION,
        "status": "installed",
        "route": "/webhooks/whatsapp",
        "verify_token_configured": bool(_verify_token()),
        "app_secret_configured": bool(_app_secret()),
        "signature_required_for_trusted_ingest": True,
        "secrets_exposed": False,
    }
}, flush=True)
