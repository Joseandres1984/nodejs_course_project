from __future__ import annotations

import imaplib
import os
import re
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from typing import Any, Dict


VERSION = "1.0-gmail-sent-archiver"
IMAP_HOST = os.getenv("LUMEN_IMAP_HOST", "").strip()
IMAP_PORT = int(os.getenv("LUMEN_IMAP_PORT", "993"))
IMAP_USER = os.getenv("LUMEN_IMAP_USER", "").strip()
IMAP_PASSWORD = os.getenv("LUMEN_IMAP_PASSWORD", "").strip()
IMAP_SSL = os.getenv("LUMEN_IMAP_SSL", "true").lower() == "true"
BREVO_FROM_EMAIL = os.getenv("LUMEN_BREVO_FROM_EMAIL", "").strip()
BREVO_FROM_NAME = os.getenv("LUMEN_BREVO_FROM_NAME", "LUMEN B2B").strip() or "LUMEN B2B"
DISCLOSE_AUTOMATION = os.getenv("LUMEN_DISCLOSE_AUTOMATION", "true").lower() == "true"


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _log(state: Dict[str, Any], message: str) -> None:
    state.setdefault("activity", []).insert(0, {"ts": utcnow(), "msg": message})
    state["activity"] = state["activity"][:100]


def configured() -> bool:
    return bool(IMAP_HOST and IMAP_USER and IMAP_PASSWORD and BREVO_FROM_EMAIL)


def _client():
    client = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT) if IMAP_SSL else imaplib.IMAP4(IMAP_HOST, IMAP_PORT)
    client.login(IMAP_USER, IMAP_PASSWORD)
    return client


def _decode_mailbox_token(token: bytes | str) -> str:
    text = token.decode("utf-8", errors="replace") if isinstance(token, bytes) else str(token)
    text = text.strip()
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1].replace('\\"', '"').replace('\\\\', '\\')
    return text


def _sent_mailbox(client) -> str:
    typ, rows = client.list()
    if typ == "OK":
        for row in rows or []:
            text = row.decode("utf-8", errors="replace") if isinstance(row, bytes) else str(row)
            if "\\Sent" not in text:
                continue
            match = re.search(r'("(?:[^"\\]|\\.)*"|[^ ]+)$', text)
            if match:
                return _decode_mailbox_token(match.group(1))
    for candidate in ("[Gmail]/Sent Mail", "[Gmail]/Enviados", "Sent", "Sent Mail", "Enviados"):
        try:
            typ, _ = client.select(f'"{candidate}"', readonly=True)
            if typ == "OK":
                return candidate
        except Exception:
            pass
    raise RuntimeError("gmail_sent_mailbox_not_found")


def _body_for(item: Dict[str, Any]) -> str:
    body = str(item.get("body") or "")
    if DISCLOSE_AUTOMATION and "Mensaje comercial gestionado con asistencia automatizada." not in body:
        body += "\n\n—\nLUMEN B2B\nMensaje comercial gestionado con asistencia automatizada."
    return body


def _message_for(item: Dict[str, Any]) -> EmailMessage:
    target = str(item.get("contact") or "").strip()
    subject = str(item.get("subject") or "Consulta comercial")
    outbox_id = str(item.get("id") or "").strip()
    provider_id = str(item.get("email_provider_message_id") or "").strip()
    msg = EmailMessage()
    msg["From"] = f"{BREVO_FROM_NAME} <{BREVO_FROM_EMAIL}>"
    msg["To"] = target
    msg["Subject"] = subject
    msg["Date"] = format_datetime(datetime.now(timezone.utc))
    msg["Message-ID"] = make_msgid(domain=(BREVO_FROM_EMAIL.split("@", 1)[-1] if "@" in BREVO_FROM_EMAIL else None))
    msg["X-LUMEN-Outbox-ID"] = outbox_id
    if provider_id:
        msg["X-LUMEN-Brevo-Message-ID"] = provider_id
    msg.set_content(_body_for(item))
    return msg


def _already_archived(client, mailbox: str, outbox_id: str) -> bool:
    typ, _ = client.select(f'"{mailbox}"', readonly=True)
    if typ != "OK":
        raise RuntimeError(f"gmail_sent_select_failed:{mailbox}")
    typ, data = client.search(None, "HEADER", "X-LUMEN-Outbox-ID", f'"{outbox_id}"')
    if typ != "OK":
        raise RuntimeError("gmail_sent_dedupe_search_failed")
    return bool(data and data[0] and data[0].strip())


def archive_item(state: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Any]:
    if not configured():
        return {"ok": False, "reason": "imap_not_configured"}
    if item.get("status") != "sent" or item.get("email_provider") != "brevo":
        return {"ok": False, "reason": "not_confirmed_brevo_send"}
    outbox_id = str(item.get("id") or "").strip()
    if not outbox_id:
        return {"ok": False, "reason": "missing_outbox_id"}
    if item.get("gmail_sent_archived_at"):
        return {"ok": True, "deduped": True, "mailbox": item.get("gmail_sent_mailbox")}

    client = None
    try:
        client = _client()
        mailbox = _sent_mailbox(client)
        if _already_archived(client, mailbox, outbox_id):
            item["gmail_sent_archived_at"] = utcnow()
            item["gmail_sent_mailbox"] = mailbox
            item["gmail_sent_archive_version"] = VERSION
            item["gmail_sent_deduped"] = True
            return {"ok": True, "deduped": True, "mailbox": mailbox}

        msg = _message_for(item)
        typ, _ = client.append(mailbox, "(\\Seen)", imaplib.Time2Internaldate(datetime.now().astimezone()), msg.as_bytes())
        if typ != "OK":
            raise RuntimeError("gmail_sent_append_failed")
        item["gmail_sent_archived_at"] = utcnow()
        item["gmail_sent_mailbox"] = mailbox
        item["gmail_sent_archive_version"] = VERSION
        item["gmail_sent_deduped"] = False
        return {"ok": True, "deduped": False, "mailbox": mailbox}
    except Exception as exc:
        item["gmail_sent_archive_last_error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        item["gmail_sent_archive_last_attempt"] = utcnow()
        return {"ok": False, "reason": item["gmail_sent_archive_last_error"]}
    finally:
        if client:
            try:
                client.logout()
            except Exception:
                pass


def backfill_confirmed_sends(state: Dict[str, Any], limit: int = 5) -> Dict[str, int]:
    stats = {"eligible": 0, "archived": 0, "deduped": 0, "failed": 0}
    if not configured():
        state["gmail_sent_archiver"] = {**stats, "version": VERSION, "configured": False, "updated_at": utcnow()}
        return stats

    eligible = [
        item for item in state.get("outbox", []) or []
        if item.get("status") == "sent"
        and item.get("email_provider") == "brevo"
        and not item.get("gmail_sent_archived_at")
    ]
    eligible.sort(key=lambda x: str(x.get("sent_at") or ""))
    stats["eligible"] = len(eligible)
    for item in eligible[:max(1, limit)]:
        result = archive_item(state, item)
        if result.get("ok"):
            if result.get("deduped"):
                stats["deduped"] += 1
            else:
                stats["archived"] += 1
            item.pop("gmail_sent_archive_last_error", None)
            _log(state, f"Gmail Sent archivó {item.get('id')} sin reenviar el correo.")
        else:
            stats["failed"] += 1
            _log(state, f"Gmail Sent no pudo archivar {item.get('id')}: {result.get('reason')}")

    state["gmail_sent_archiver"] = {
        **stats,
        "version": VERSION,
        "configured": True,
        "updated_at": utcnow(),
        "policy": "append_after_confirmed_brevo_send_no_resend_dedupe_by_outbox_id",
    }
    return stats
