from __future__ import annotations

"""Internal owner notifications for LUMEN Zero.

WhatsApp is intentionally retired from the Zero runtime. IMPORTANT/CRITICAL owner events are sent
through the already-configured internal email route, while INFO events remain visible in the Command
Center. This module does not alter commercial outbound authority.
"""

import smtplib
from email.message import EmailMessage
from typing import Any, Dict

import mail_connector
import notification_router

VERSION = "2.0-owner-email-primary"
MAX_EMAILS_PER_TICK = 3


def _send_owner(event: Dict[str, Any]) -> Dict[str, Any]:
    recipient = str(mail_connector.SMTP_USER or "").strip()
    sender = str(mail_connector.SMTP_FROM or mail_connector.SMTP_USER or "").strip()
    if not (recipient and sender and mail_connector.SMTP_HOST and mail_connector.SMTP_PASSWORD):
        return {"ok": False, "error": "owner_email_not_configured"}
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = f"LUMEN · {str(event.get('severity') or 'IMPORTANTE')} · {str(event.get('title') or 'Evento')[:120]}"
    body = (
        f"{event.get('title') or 'Evento LUMEN'}\n\n"
        f"{event.get('summary') or ''}\n\n"
        f"Panel: {notification_router.COMMAND_CENTER_URL}\n\n"
        "—\nLUMEN · alerta interna del sistema"
    )
    msg.set_content(body[:6000])
    try:
        if mail_connector.SMTP_SSL:
            with smtplib.SMTP_SSL(mail_connector.SMTP_HOST, mail_connector.SMTP_PORT, timeout=25) as client:
                client.login(mail_connector.SMTP_USER, mail_connector.SMTP_PASSWORD)
                client.send_message(msg)
        else:
            with smtplib.SMTP(mail_connector.SMTP_HOST, mail_connector.SMTP_PORT, timeout=25) as client:
                client.starttls()
                client.login(mail_connector.SMTP_USER, mail_connector.SMTP_PASSWORD)
                client.send_message(msg)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:180]}"}


def zero_notification_router_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    # Reuse the existing evidence-backed event discovery, but bypass the WhatsApp transport entirely.
    discovered = notification_router._discover(state)
    email_sent = email_failed = 0
    configured = bool(mail_connector.SMTP_HOST and mail_connector.SMTP_USER and mail_connector.SMTP_PASSWORD)

    for event in state.get("notification_events", []) or []:
        if email_sent >= MAX_EMAILS_PER_TICK:
            break
        if str(event.get("severity") or "").upper() not in {"IMPORTANT", "CRITICAL"}:
            continue
        if event.get("owner_email_sent_at"):
            continue
        if event.get("delivery_status") not in {"queued", "retry", "email_pending"}:
            continue
        result = _send_owner(event)
        event["owner_email_attempts"] = int(event.get("owner_email_attempts") or 0) + 1
        event["owner_email_last_attempt_at"] = notification_router.utcnow()
        if result.get("ok"):
            event["owner_email_sent_at"] = notification_router.utcnow()
            event["delivery_status"] = "email_sent"
            event.pop("owner_email_last_error", None)
            event.pop("last_error", None)
            email_sent += 1
        else:
            event["owner_email_last_error"] = result.get("error")
            event["delivery_status"] = "email_pending"
            email_failed += 1

    events = state.get("notification_events", []) or []
    report = {
        "updated_at": notification_router.utcnow(),
        "channel": "email_internal",
        "status": {
            "delivery_ready": configured,
            "email_configured": configured,
            "whatsapp_retired": True,
            "command_center_url": notification_router.COMMAND_CENTER_URL,
            "secrets_exposed": False,
        },
        "discovered": discovered,
        "events_total": len(events),
        "queued_for_email": sum(
            1 for x in events
            if str(x.get("severity") or "").upper() in {"IMPORTANT", "CRITICAL"}
            and not x.get("owner_email_sent_at")
            and x.get("delivery_status") in {"queued", "retry", "email_pending"}
        ),
        "sent_total": sum(1 for x in events if x.get("owner_email_sent_at")),
        "sent_this_tick": email_sent,
        "failed_this_tick": email_failed,
        "recent": list(reversed(events[-12:])),
        "policy": {
            "INFO": "solo Command Center",
            "IMPORTANT": "email interno",
            "CRITICAL": "email interno prioritario + Command Center",
            "max_email_per_tick": MAX_EMAILS_PER_TICK,
            "deduplication": "un evento estable se notifica una sola vez",
            "whatsapp": "retired_by_owner_decision",
        },
        "owner_email_fallback": {
            "version": VERSION,
            "active": True,
            "configured": configured,
            "sent_this_tick": email_sent,
            "failed_this_tick": email_failed,
            "max_per_tick": MAX_EMAILS_PER_TICK,
            "recipient_exposed": False,
            "commercial_outbound_authority_changed": False,
        },
    }
    state["notification_router"] = report
    return report


notification_router.notification_router_tick = zero_notification_router_tick
print({
    "zero_notification_runtime": {
        "status": "installed",
        "version": VERSION,
        "primary_channel": "email_internal",
        "whatsapp_retired": True,
        "recipient_exposed": False,
    }
}, flush=True)
