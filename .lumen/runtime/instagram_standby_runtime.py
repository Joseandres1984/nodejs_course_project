from __future__ import annotations

from typing import Any, Dict, List

from app import STATE, load_state, save_state
import instagram_operator

VERSION = "1.0-instagram-standby-runtime"
_ORIGINAL_NORMALIZE = instagram_operator._normalize_webhook


def _normalize_standby_event(entry: Dict[str, Any], event: Dict[str, Any]) -> Dict[str, Any] | None:
    if not isinstance(event, dict):
        return None

    sender = event.get("sender") or {}
    recipient = event.get("recipient") or {}
    sender_id = str(sender.get("id") or "") if isinstance(sender, dict) else ""
    recipient_id = str(recipient.get("id") or "") if isinstance(recipient, dict) else ""

    if sender_id and sender_id == instagram_operator.INSTAGRAM_USER_ID:
        return None

    kind = ""
    text = ""
    external_id = ""

    if isinstance(event.get("message"), dict):
        message = event["message"]
        if message.get("is_echo"):
            return None
        kind = "message"
        text = instagram_operator._message_text(message)
        external_id = str(message.get("mid") or "")
    elif isinstance(event.get("postback"), dict):
        postback = event.get("postback") or {}
        kind = "postback"
        text = str(postback.get("title") or postback.get("payload") or "")
        external_id = str(postback.get("mid") or "")
    elif isinstance(event.get("reaction"), dict):
        reaction = event.get("reaction") or {}
        kind = "reaction"
        text = str(reaction.get("reaction") or "")
    elif isinstance(event.get("referral"), dict):
        referral = event.get("referral") or {}
        kind = "referral"
        text = str(referral.get("ref") or "")
    elif event.get("read") or event.get("seen"):
        kind = "seen"
    else:
        return None

    entry_id = str(entry.get("id") or "")
    timestamp = event.get("timestamp") or entry.get("time")
    external_id = external_id or instagram_operator._stable_id(
        "standby", entry_id, sender_id, recipient_id, timestamp, kind, text
    )

    return {
        "external_id": external_id,
        "kind": kind,
        "sender_id": sender_id,
        "recipient_id": recipient_id,
        "sender_username": None,
        "text": text,
        "event_at": timestamp,
        "entry_id": entry_id,
        "raw_field": "standby",
        "standby": True,
    }


def _normalize_with_standby(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    normalized = list(_ORIGINAL_NORMALIZE(payload) or [])
    for entry in payload.get("entry", []) or []:
        if not isinstance(entry, dict):
            continue
        for event in entry.get("standby", []) or []:
            row = _normalize_standby_event(entry, event)
            if row:
                normalized.append(row)
    return normalized


instagram_operator._normalize_webhook = _normalize_with_standby

# Reprocess a bounded slice of already-received events after installing the patch.
# Existing message IDs are deduplicated by Instagram Operator, so this cannot create duplicates.
backfilled = 0
try:
    if load_state():
        for audit_row in reversed(list(STATE.get("instagram_webhook_events", []) or [])[:25]):
            payload = audit_row.get("payload") if isinstance(audit_row, dict) else None
            if isinstance(payload, dict):
                result = instagram_operator.process_instagram_webhook(payload, persist=False)
                backfilled += int(result.get("created") or 0)
        if backfilled:
            save_state()
except Exception as exc:
    print({"instagram_standby_runtime": {"version": VERSION, "status": "backfill_error", "error": f"{type(exc).__name__}: {str(exc)[:400]}"}}, flush=True)

print({"instagram_standby_runtime": {"version": VERSION, "status": "active", "backfilled": backfilled}}, flush=True)
