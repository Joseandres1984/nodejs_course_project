from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, Iterable

from fastapi import Depends

from app import STATE, auth, load_state, save_state
from outbound_web import app
from instagram_operator import process_instagram_webhook

VERSION = "1.0-instagram-conversation-poller"
INSTAGRAM_ACCESS_TOKEN = os.getenv("LUMEN_INSTAGRAM_ACCESS_TOKEN", "").strip()
INSTAGRAM_USER_ID = os.getenv("LUMEN_INSTAGRAM_USER_ID", "").strip()
INSTAGRAM_GRAPH_BASE = os.getenv("LUMEN_INSTAGRAM_GRAPH_BASE", "https://graph.instagram.com").rstrip("/")
INSTAGRAM_GRAPH_VERSION = os.getenv("LUMEN_INSTAGRAM_GRAPH_VERSION", "v26.0").strip() or "v26.0"
POLL_SECONDS = max(30, min(600, int(os.getenv("LUMEN_INSTAGRAM_POLL_SECONDS", "60"))))
MAX_CONVERSATIONS = max(1, min(25, int(os.getenv("LUMEN_INSTAGRAM_POLL_CONVERSATIONS", "10"))))
MAX_MESSAGES = max(1, min(50, int(os.getenv("LUMEN_INSTAGRAM_POLL_MESSAGES", "20"))))

STATUS: Dict[str, Any] = {
    "version": VERSION,
    "configured": bool(INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_USER_ID),
    "status": "starting",
    "conversations_seen": 0,
    "messages_seen": 0,
    "operator_created": 0,
    "last_error": None,
    "last_sync_at": None,
    "poll_seconds": POLL_SECONDS,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _graph_get(path: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if not INSTAGRAM_ACCESS_TOKEN:
        raise RuntimeError("instagram_access_token_missing")
    query = urllib.parse.urlencode(params or {})
    url = f"{INSTAGRAM_GRAPH_BASE}/{INSTAGRAM_GRAPH_VERSION}/{path.lstrip('/')}"
    if query:
        url += "?" + query
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {INSTAGRAM_ACCESS_TOKEN}",
            "Accept": "application/json",
            "User-Agent": "LUMEN-B2B/1.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")[:700]
        except Exception:
            pass
        raise RuntimeError(f"Instagram conversations HTTP {exc.code}: {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Instagram conversations connection error: {exc.reason}") from exc


def _own_ids() -> set[str]:
    ids = {str(INSTAGRAM_USER_ID)} if INSTAGRAM_USER_ID else set()
    try:
        profile = _graph_get("me", {"fields": "id,user_id,username"})
        for key in ("id", "user_id"):
            if profile.get(key):
                ids.add(str(profile.get(key)))
    except Exception:
        # The professional user id already configured in Railway remains the authoritative fallback.
        pass
    return ids


def _iter_messages(conversation: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    messages = conversation.get("messages") or {}
    if isinstance(messages, dict):
        rows = messages.get("data") or []
    elif isinstance(messages, list):
        rows = messages
    else:
        rows = []
    for row in rows:
        if isinstance(row, dict):
            yield row


def _conversation_list() -> list[Dict[str, Any]]:
    # Instagram Login supports the professional-account conversations edge without a Facebook Page.
    # Ask for messages inline first so a normal poll is a single Graph request.
    fields = f"id,updated_time,participants,messages.limit({MAX_MESSAGES}){{id,created_time,from,to,message}}"
    params = {"platform": "instagram", "fields": fields, "limit": MAX_CONVERSATIONS}
    try:
        data = _graph_get(f"{INSTAGRAM_USER_ID}/conversations", params)
    except Exception:
        # Some Instagram Login deployments accept /me/conversations instead of the professional id.
        data = _graph_get("me/conversations", params)
    rows = data.get("data") if isinstance(data, dict) else []
    return [x for x in (rows or []) if isinstance(x, dict)]


def _message_sender_id(message: Dict[str, Any]) -> str:
    sender = message.get("from") or {}
    if isinstance(sender, dict):
        return str(sender.get("id") or "")
    return ""


def _message_recipient_id(message: Dict[str, Any], own_ids: set[str]) -> str:
    target = message.get("to") or {}
    rows = target.get("data") if isinstance(target, dict) else target
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and str(row.get("id") or "") in own_ids:
                return str(row.get("id"))
        for row in rows:
            if isinstance(row, dict) and row.get("id"):
                return str(row.get("id"))
    return INSTAGRAM_USER_ID


def _synthetic_webhook(message: Dict[str, Any], own_ids: set[str]) -> Dict[str, Any] | None:
    sender_id = _message_sender_id(message)
    if not sender_id or sender_id in own_ids:
        return None
    message_id = str(message.get("id") or "")
    text = str(message.get("message") or "")
    created = message.get("created_time")
    return {
        "object": "instagram",
        "entry": [
            {
                "id": INSTAGRAM_USER_ID,
                "time": created,
                "messaging": [
                    {
                        "sender": {"id": sender_id},
                        "recipient": {"id": _message_recipient_id(message, own_ids)},
                        "timestamp": created,
                        "message": {"mid": message_id, "text": text},
                    }
                ],
            }
        ],
    }


def poll_once() -> Dict[str, Any]:
    report = {
        "version": VERSION,
        "configured": bool(INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_USER_ID),
        "status": "ok",
        "conversations_seen": 0,
        "messages_seen": 0,
        "operator_created": 0,
        "last_error": None,
        "last_sync_at": _now_iso(),
        "poll_seconds": POLL_SECONDS,
    }
    if not report["configured"]:
        report["status"] = "not_configured"
        STATUS.clear(); STATUS.update(report)
        return report

    try:
        conversations = _conversation_list()
        own_ids = _own_ids()
        report["conversations_seen"] = len(conversations)
        created = 0
        message_count = 0

        load_state()
        sync_index = dict(STATE.get("instagram_conversation_sync_index", {}) or {})

        for conversation in conversations:
            conversation_id = str(conversation.get("id") or "")
            updated_time = str(conversation.get("updated_time") or "")
            # If inline messages are absent, fetch the thread only when it is new or changed.
            messages = list(_iter_messages(conversation))
            if not messages and conversation_id and sync_index.get(conversation_id) != updated_time:
                detail = _graph_get(
                    conversation_id,
                    {"fields": f"messages.limit({MAX_MESSAGES}){{id,created_time,from,to,message}}"},
                )
                messages = list(_iter_messages(detail))

            for message in messages:
                message_count += 1
                payload = _synthetic_webhook(message, own_ids)
                if not payload:
                    continue
                result = process_instagram_webhook(payload, persist=False)
                created += int(result.get("created") or 0)

            if conversation_id:
                sync_index[conversation_id] = updated_time

        STATE["instagram_conversation_sync_index"] = sync_index
        STATE["instagram_conversation_poller"] = {
            **report,
            "messages_seen": message_count,
            "operator_created": created,
            "own_ids_count": len(own_ids),
        }
        if conversations or created:
            save_state()
        report["messages_seen"] = message_count
        report["operator_created"] = created
    except Exception as exc:
        report["status"] = "error"
        report["last_error"] = f"{type(exc).__name__}: {str(exc)[:700]}"

    STATUS.clear(); STATUS.update(report)
    print({"instagram_conversation_poller": report}, flush=True)
    return report


async def _poll_loop() -> None:
    # Give Uvicorn a moment to finish startup, then keep the inbox synchronized independently of webhooks.
    await asyncio.sleep(3)
    while True:
        try:
            await asyncio.to_thread(poll_once)
        except Exception as exc:
            print({"instagram_conversation_poller_loop": {"status": "error", "error": f"{type(exc).__name__}: {str(exc)[:500]}"}}, flush=True)
        await asyncio.sleep(POLL_SECONDS)


@app.on_event("startup")
async def start_instagram_conversation_poller() -> None:
    asyncio.create_task(_poll_loop())


@app.get("/health/instagram/conversations", include_in_schema=False)
def instagram_conversation_health():
    # Safe operational status: no token, usernames, message ids or message contents are returned.
    return dict(STATUS)


@app.post("/api/integrations/instagram/poll", include_in_schema=False)
def instagram_poll_now(_=Depends(auth)):
    return poll_once()
