from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from collections import deque
from typing import Any, Dict

from fastapi import HTTPException, Request

from app import STATE, load_state, save_state
from outbound_web import app
from instagram_operator import process_instagram_webhook

VERSION = "1.0-manychat-instagram-bridge"
INGRESS_KEY = os.getenv("LUMEN_MANYCHAT_INGRESS_KEY", "").strip()
INSTAGRAM_USER_ID = os.getenv("LUMEN_INSTAGRAM_USER_ID", "").strip()
INSTAGRAM_USERNAME = os.getenv("LUMEN_INSTAGRAM_USERNAME", "").strip()
MAX_BODY_BYTES = 16_384
MAX_REQUESTS_PER_MINUTE = 120
_RECENT: deque[float] = deque()

STATUS: Dict[str, Any] = {
    "version": VERSION,
    "configured": bool(INGRESS_KEY and INSTAGRAM_USER_ID),
    "status": "ready" if INGRESS_KEY and INSTAGRAM_USER_ID else "not_configured",
    "received_total": 0,
    "created_total": 0,
    "last_received_at": None,
    "last_error": None,
}


def _rate_limit() -> None:
    now = time.time()
    while _RECENT and _RECENT[0] < now - 60:
        _RECENT.popleft()
    if len(_RECENT) >= MAX_REQUESTS_PER_MINUTE:
        raise HTTPException(status_code=429, detail="Too many requests")
    _RECENT.append(now)


def _first(payload: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _external_id(contact_id: str, text: str, event_time: str, explicit: str) -> str:
    if explicit:
        return f"manychat:{explicit}"
    raw = f"{contact_id}|{event_time}|{text}".encode("utf-8")
    return "manychat:" + hashlib.sha256(raw).hexdigest()[:32]


def _annotate(external_id: str, payload: Dict[str, Any]) -> None:
    for row in STATE.get("instagram_inbox", []) or []:
        if str(row.get("external_id") or "") != external_id:
            continue
        row["source"] = "manychat_bridge"
        row["manychat_contact_id"] = _first(payload, "contact_id", "user_id", "id") or None
        row["manychat_live_chat_url"] = _first(payload, "live_chat_url", "chat_url") or None
        username = _first(payload, "instagram_username", "username", "profile_name")
        if username:
            row["sender_username"] = username
        row["manychat_name"] = _first(payload, "full_name", "name") or None
        # Replies for bridged contacts must stay human-reviewed. The native Meta sender id is not
        # assumed to equal Manychat's contact id, so do not silently route sends through Meta.
        row["send_route"] = "manychat_manual_or_api_required"
        break


@app.post("/integrations/instagram/manychat", include_in_schema=False)
async def manychat_instagram_ingress(request: Request):
    _rate_limit()
    if not INGRESS_KEY or not INSTAGRAM_USER_ID:
        raise HTTPException(status_code=503, detail="Bridge is not configured")

    supplied = request.headers.get("x-lumen-bridge-key", "")
    if not supplied or not hmac.compare_digest(supplied, INGRESS_KEY):
        raise HTTPException(status_code=403, detail="Invalid bridge key")

    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large")
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON object required")

    text = _first(payload, "last_input_text", "message", "text").strip()
    contact_id = _first(payload, "contact_id", "user_id", "id").strip()
    event_time = _first(payload, "last_interaction", "timestamp", "event_time").strip()
    explicit_event_id = _first(payload, "event_id", "message_id").strip()
    account_username = _first(payload, "account_username", "instagram_account").strip().lstrip("@")

    if account_username and INSTAGRAM_USERNAME and account_username.lower() != INSTAGRAM_USERNAME.lower():
        raise HTTPException(status_code=400, detail="Unexpected Instagram account")
    if not text or not contact_id:
        raise HTTPException(status_code=400, detail="contact_id and last_input_text are required")

    external_id = _external_id(contact_id, text, event_time, explicit_event_id)
    synthetic = {
        "object": "instagram",
        "entry": [
            {
                "id": INSTAGRAM_USER_ID,
                "time": event_time or None,
                "messaging": [
                    {
                        "sender": {"id": f"manychat:{contact_id}"},
                        "recipient": {"id": INSTAGRAM_USER_ID},
                        "timestamp": event_time or None,
                        "message": {"mid": external_id, "text": text[:4000]},
                    }
                ],
            }
        ],
    }

    try:
        load_state()
        result = process_instagram_webhook(synthetic, persist=False)
        _annotate(external_id, payload)
        persisted = bool(save_state())
        created = int(result.get("created") or 0)
        STATUS["received_total"] = int(STATUS.get("received_total") or 0) + 1
        STATUS["created_total"] = int(STATUS.get("created_total") or 0) + created
        STATUS["last_received_at"] = event_time or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        STATUS["last_error"] = None
        print({
            "instagram_manychat_bridge": {
                "status": "ok",
                "created": created,
                "persisted": persisted,
                "text_length": len(text),
                "contact_present": True,
            }
        }, flush=True)
        return {"ok": True, "created": created}
    except HTTPException:
        raise
    except Exception as exc:
        STATUS["last_error"] = f"{type(exc).__name__}: {str(exc)[:400]}"
        print({"instagram_manychat_bridge": {"status": "error", "error": STATUS["last_error"]}}, flush=True)
        raise HTTPException(status_code=500, detail="Bridge ingestion failed") from exc


@app.get("/health/instagram/manychat", include_in_schema=False)
def manychat_bridge_health():
    # Never expose the bridge key or message contents.
    return dict(STATUS)
