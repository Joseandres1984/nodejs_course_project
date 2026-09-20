from __future__ import annotations

"""Owner notification fallback for LUMEN Zero.

WhatsApp remains optional because Meta business verification is unavailable. IMPORTANT/CRITICAL
internal owner events therefore get a bounded Gmail SMTP fallback. These messages go only to the
configured LUMEN mailbox, never to prospects, and do not alter commercial outbound authority.
"""

import smtplib
from email.message import EmailMessage
from typing import Any, Dict

import mail_connector
import notification_router

VERSION = "1.0-zero-owner-email-fallback"
MAX_EMAILS_PER_TICK = 3
_original_tick = notification_router.notification_router_tick


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
    report = dict(_original_tick(state) or {})
    wa_ready = bool(((report.get("status") or {}).get("delivery_ready")))
    email_sent = email_failed = 0
    # Use email as the active internal notification route only while WhatsApp is unavailable.
    # Keep events queued, so a future authorized WhatsApp connector can still deliver them once.
    if not wa_ready:
        for event in state.get("notification_events", []) or []:
            if email_sent >= MAX_EMAILS_PER_TICK:
                break
            if str(event.get("severity") or "").upper() not in {"IMPORTANT", "CRITICAL"}:
                continue
            if event.get("owner_email_sent_at"):
                continue
            if event.get("delivery_status") not in {"queued", "retry"}:
                continue
            result = _send_owner(event)
            event["owner_email_attempts"] = int(event.get("owner_email_attempts") or 0) + 1
            event["owner_email_last_attempt_at"] = notification_router.utcnow()
            if result.get("ok"):
                event["owner_email_sent_at"] = notification_router.utcnow()
                event.pop("owner_email_last_error", None)
                email_sent += 1
            else:
                event["owner_email_last_error"] = result.get("error")
                email_failed += 1
    report["channel"] = "whatsapp" if wa_ready else "email_fallback"
    report["owner_email_fallback"] = {
        "version": VERSION,
        "active": not wa_ready,
        "configured": bool(mail_connector.SMTP_HOST and mail_connector.SMTP_USER and mail_connector.SMTP_PASSWORD),
        "sent_this_tick": email_sent,
        "failed_this_tick": email_failed,
        "max_per_tick": MAX_EMAILS_PER_TICK,
        "recipient_exposed": False,
        "commercial_outbound_authority_changed": False,
    }
    policy = dict(report.get("policy") or {})
    policy["IMPORTANT"] = "email interno mientras WhatsApp no esté disponible"
    policy["CRITICAL"] = "email interno prioritario + Command Center mientras WhatsApp no esté disponible"
    report["policy"] = policy
    state["notification_router"] = report
    return report


notification_router.notification_router_tick = zero_notification_router_tick
print({"zero_notification_runtime": {"status": "installed", "version": VERSION, "recipient_exposed": False}}, flush=True)
