from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import notification_router as nr


VERSION = "1.1"


def _safe_meta_error(raw: str) -> Dict[str, Any]:
    """Return only non-secret Meta error fields safe for state/logging."""
    try:
        data = json.loads(raw or "{}")
        error = data.get("error") or {}
        return {
            "meta_error_code": error.get("code"),
            "meta_error_subcode": error.get("error_subcode"),
            "meta_error_type": " ".join(str(error.get("type") or "").split())[:120] or None,
            "meta_error_message": " ".join(str(error.get("message") or "").split())[:600] or None,
            "meta_fbtrace_id": " ".join(str(error.get("fbtrace_id") or "").split())[:160] or None,
        }
    except Exception:
        return {"meta_error_message": "unparseable_meta_error"}


def _send_whatsapp(event: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    url = f"https://graph.facebook.com/{cfg['graph_version']}/{cfg['phone_number_id']}/messages"
    data = json.dumps(nr._payload(event, cfg), ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {cfg['access_token']}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            body = json.loads(response.read().decode("utf-8") or "{}")
            message_id = ((body.get("messages") or [{}])[0] or {}).get("id")
            return {
                "ok": True,
                "message_id": message_id,
                "http_status": int(response.status),
            }
    except urllib.error.HTTPError as exc:
        raw = exc.read(8000).decode("utf-8", errors="replace") if exc.fp else ""
        return {
            "ok": False,
            "error": f"HTTPError:{exc.code}",
            "http_status": int(exc.code),
            **_safe_meta_error(raw),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": type(exc).__name__,
            "exception_message": " ".join(str(exc).split())[:300] or None,
        }


def _parse_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _retry_delay(attempts: int, result: Dict[str, Any]) -> timedelta:
    # Auth/configuration failures should not hammer Meta while still remaining recoverable
    # automatically after an operator updates the credential/template configuration.
    code = result.get("meta_error_code")
    http_status = int(result.get("http_status") or 0)
    if http_status in {401, 403} or code in {10, 190}:
        return timedelta(hours=1)
    schedule = (1, 5, 15, 30, 60, 180)
    minutes = schedule[min(max(attempts - 1, 0), len(schedule) - 1)]
    return timedelta(minutes=minutes)


def _due(event: Dict[str, Any], now: datetime) -> bool:
    next_at = _parse_utc(event.get("next_whatsapp_attempt_at"))
    return next_at is None or now >= next_at


def notification_router_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    discovered = nr._discover(state)
    cfg = nr._config()
    status = nr.public_status()
    sent = 0
    failed = 0
    attempts_this_tick = 0
    now = datetime.now(timezone.utc)

    for event in state.get("notification_events", []) or []:
        if event.get("severity") == "INFO" or event.get("delivery_status") == "sent":
            continue
        if event.get("delivery_status") not in {"queued", "retry"}:
            continue
        if not status["delivery_ready"] or attempts_this_tick >= nr.MAX_WHATSAPP_PER_TICK:
            continue
        if not _due(event, now):
            continue

        result = _send_whatsapp(event, cfg)
        attempts_this_tick += 1
        attempts = int(event.get("whatsapp_attempts") or 0) + 1
        event["whatsapp_attempts"] = attempts
        event["last_whatsapp_attempt_at"] = nr.utcnow()
        event["last_http_status"] = result.get("http_status")

        if result.get("ok"):
            event["delivery_status"] = "sent"
            event["whatsapp_sent_at"] = nr.utcnow()
            event["whatsapp_message_id"] = result.get("message_id")
            for key in (
                "last_error", "next_whatsapp_attempt_at", "meta_error_code",
                "meta_error_subcode", "meta_error_type", "meta_error_message",
                "meta_fbtrace_id", "exception_message",
            ):
                event.pop(key, None)
            sent += 1
            continue

        event["delivery_status"] = "retry"
        event["last_error"] = result.get("error")
        for key in (
            "meta_error_code", "meta_error_subcode", "meta_error_type",
            "meta_error_message", "meta_fbtrace_id", "exception_message",
        ):
            if result.get(key) is not None:
                event[key] = result.get(key)
        event["next_whatsapp_attempt_at"] = (
            now + _retry_delay(attempts, result)
        ).strftime("%Y-%m-%d %H:%M:%S UTC")
        failed += 1

    events = state.get("notification_events", []) or []
    failures = [x for x in reversed(events) if x.get("delivery_status") == "retry"][:5]
    diagnostics = [
        {
            "id": x.get("id"),
            "kind": x.get("kind"),
            "attempts": x.get("whatsapp_attempts"),
            "http_status": x.get("last_http_status"),
            "meta_error_code": x.get("meta_error_code"),
            "meta_error_subcode": x.get("meta_error_subcode"),
            "meta_error_type": x.get("meta_error_type"),
            "meta_error_message": x.get("meta_error_message"),
            "next_attempt_at": x.get("next_whatsapp_attempt_at"),
        }
        for x in failures
    ]

    report = {
        "version": VERSION,
        "updated_at": nr.utcnow(),
        "channel": "whatsapp",
        "status": status,
        "discovered": discovered,
        "events_total": len(events),
        "queued_for_whatsapp": sum(
            1 for x in events if x.get("delivery_status") in {"queued", "retry"}
        ),
        "sent_total": sum(1 for x in events if x.get("delivery_status") == "sent"),
        "sent_this_tick": sent,
        "failed_this_tick": failed,
        "attempts_this_tick": attempts_this_tick,
        "recent": list(reversed(events[-12:])),
        "delivery_diagnostics": diagnostics,
        "policy": {
            "INFO": "solo Command Center",
            "IMPORTANT": "WhatsApp cuando el canal está configurado",
            "CRITICAL": "WhatsApp prioritario + Command Center",
            "max_whatsapp_attempts_per_tick": nr.MAX_WHATSAPP_PER_TICK,
            "bounded_backoff": True,
            "deduplication": "un evento estable se notifica una sola vez",
            "template_recommended": True,
        },
    }
    state["notification_router"] = report

    if diagnostics:
        print({
            "whatsapp_delivery_diagnostics": diagnostics,
            "secrets_exposed": False,
        }, flush=True)
    return report


# Install the hardened sender/router before worker_journal imports the callable.
nr._send_whatsapp = _send_whatsapp
nr.notification_router_tick = notification_router_tick
