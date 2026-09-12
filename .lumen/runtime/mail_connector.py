from __future__ import annotations

import email
import imaplib
import os
import re
import smtplib
from datetime import datetime, timezone
from email.header import decode_header
from email.message import EmailMessage
from typing import Any, Dict, List


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


SMTP_HOST = os.getenv("LUMEN_SMTP_HOST", "")
SMTP_PORT = int(os.getenv("LUMEN_SMTP_PORT", "587"))
SMTP_USER = os.getenv("LUMEN_SMTP_USER", "")
SMTP_PASSWORD = os.getenv("LUMEN_SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("LUMEN_SMTP_FROM", SMTP_USER)
SMTP_SSL = os.getenv("LUMEN_SMTP_SSL", "false").lower() == "true"

IMAP_HOST = os.getenv("LUMEN_IMAP_HOST", "")
IMAP_PORT = int(os.getenv("LUMEN_IMAP_PORT", "993"))
IMAP_USER = os.getenv("LUMEN_IMAP_USER", SMTP_USER)
IMAP_PASSWORD = os.getenv("LUMEN_IMAP_PASSWORD", SMTP_PASSWORD)
IMAP_SSL = os.getenv("LUMEN_IMAP_SSL", "true").lower() == "true"

DISCLOSE_AUTOMATION = os.getenv("LUMEN_DISCLOSE_AUTOMATION", "true").lower() == "true"


def connector_status() -> Dict[str, Any]:
    return {
        "smtp_configured": bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD and SMTP_FROM),
        "imap_configured": bool(IMAP_HOST and IMAP_USER and IMAP_PASSWORD),
        "from": SMTP_FROM or None,
        "disclose_automation": DISCLOSE_AUTOMATION,
    }


def _log(state: Dict[str, Any], msg: str) -> None:
    state.setdefault("activity", []).insert(0, {"ts": utcnow(), "msg": msg})
    state["activity"] = state["activity"][:100]


def _decode_header(value: str | None) -> str:
    if not value:
        return ""
    parts = []
    for chunk, enc in decode_header(value):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(enc or "utf-8", errors="replace"))
        else:
            parts.append(chunk)
    return "".join(parts)


def _plain_body(msg) -> str:
    if msg.is_multipart():
        chunks = []
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition", "")).lower():
                raw = part.get_payload(decode=True) or b""
                chunks.append(raw.decode(part.get_content_charset() or "utf-8", errors="replace"))
        return "\n".join(chunks)[:12000]
    raw = msg.get_payload(decode=True) or b""
    return raw.decode(msg.get_content_charset() or "utf-8", errors="replace")[:12000]


def classify_reply(subject: str, body: str) -> Dict[str, Any]:
    text = f"{subject}\n{body}".lower()
    kind = "general"
    if any(k in text for k in ["cotiz", "oferta", "precio", "usd", "u$s", "dólar", "dolar"]):
        kind = "commercial_offer"
    elif any(k in text for k in ["interesa", "interesado", "avancemos", "enviame", "envíame", "propuesta"]):
        kind = "buyer_interest"
    elif any(k in text for k in ["caro", "precio alto", "descuento", "mejorar precio", "fuera de presupuesto"]):
        kind = "price_objection"
    elif any(k in text for k in ["no me interesa", "no contactar", "baja", "unsubscribe", "remover"]):
        kind = "opt_out"
    elif any(k in text for k in ["plazo", "entrega", "lead time"]):
        kind = "delivery_question"
    amount = None
    currency = None
    patterns = [
        (r"(?:usd|u\$s|us\$|dolares|dólares)\s*[:$]?\s*([0-9][0-9.,]*)", "USD"),
        (r"\$\s*([0-9][0-9.,]*)", "ARS"),
    ]
    for pattern, curr in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            raw = match.group(1).replace(".", "").replace(",", ".")
            try:
                amount = float(raw); currency = curr; break
            except ValueError:
                pass
    return {"kind": kind, "amount": amount, "currency": currency}


def send_pending(state: Dict[str, Any], live_outbound: bool) -> Dict[str, int]:
    state.setdefault("outbox", []); state.setdefault("opt_out", [])
    stats = {"sent": 0, "blocked": 0, "failed": 0}
    if not live_outbound:
        return stats
    status = connector_status()
    if not status["smtp_configured"]:
        _log(state, "Mail Connector: salida real habilitada pero SMTP todavía no está configurado.")
        return stats
    limit = max(1, int(state.get("policies", {}).get("max_outbound_per_tick", 3)))
    for item in state["outbox"]:
        if stats["sent"] >= limit:
            break
        if item.get("status") != "ready":
            continue
        if item.get("quality_gate") != "passed" or not item.get("communication_reviewed"):
            item["status"] = "blocked_quality"
            item["last_error"] = "Mail Connector exige Communication Director + Quality Gate antes de enviar"
            stats["blocked"] += 1
            continue
        target = (item.get("contact") or "").strip().lower()
        if not target or not item.get("contact_verified") or target in {x.lower() for x in state["opt_out"]}:
            item["status"] = "blocked"
            stats["blocked"] += 1
            continue
        body = item.get("body", "")
        if DISCLOSE_AUTOMATION:
            body += "\n\n—\nLUMEN B2B\nMensaje comercial gestionado con asistencia automatizada."
        msg = EmailMessage()
        msg["From"] = SMTP_FROM
        msg["To"] = target
        msg["Subject"] = item.get("subject", "Consulta comercial")
        msg.set_content(body)
        try:
            if SMTP_SSL:
                with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=25) as client:
                    client.login(SMTP_USER, SMTP_PASSWORD); client.send_message(msg)
            else:
                with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=25) as client:
                    client.starttls(); client.login(SMTP_USER, SMTP_PASSWORD); client.send_message(msg)
            item["status"] = "sent"
            item["sent_at"] = utcnow()
            stats["sent"] += 1
            _log(state, f"Mail Connector envió {item['id']} a {item['counterparty']}.")
        except Exception as exc:
            item["status"] = "send_failed"
            item["last_error"] = str(exc)[:180]
            stats["failed"] += 1
            _log(state, f"Mail Connector no pudo enviar {item['id']}: {str(exc)[:120]}")
    return stats


def fetch_unseen(state: Dict[str, Any], max_messages: int = 10) -> Dict[str, int]:
    state.setdefault("inbox", []); state.setdefault("opt_out", [])
    stats = {"received": 0, "classified": 0, "offers_detected": 0}
    status = connector_status()
    if not status["imap_configured"]:
        return stats
    client = None
    try:
        client = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT) if IMAP_SSL else imaplib.IMAP4(IMAP_HOST, IMAP_PORT)
        client.login(IMAP_USER, IMAP_PASSWORD)
        client.select("INBOX")
        typ, data = client.search(None, "UNSEEN")
        ids = (data[0].split() if data and data[0] else [])[-max_messages:]
        for msg_id in ids:
            typ, payload = client.fetch(msg_id, "(RFC822)")
            if typ != "OK" or not payload:
                continue
            raw = next((p[1] for p in payload if isinstance(p, tuple)), None)
            if not raw:
                continue
            msg = email.message_from_bytes(raw)
            sender = email.utils.parseaddr(msg.get("From", ""))[1].lower()
            subject = _decode_header(msg.get("Subject"))
            body = _plain_body(msg)
            classification = classify_reply(subject, body)
            record = {
                "id": f"IN-{len(state['inbox'])+1:04d}",
                "from": sender,
                "subject": subject,
                "body": body,
                "classification": classification,
                "received_at": utcnow(),
            }
            state["inbox"].append(record)
            stats["received"] += 1; stats["classified"] += 1
            if classification["kind"] == "opt_out" and sender:
                if sender not in state["opt_out"]: state["opt_out"].append(sender)
            if classification["kind"] == "commercial_offer" and classification.get("amount"):
                stats["offers_detected"] += 1
            _log(state, f"Inbox recibió respuesta de {sender or 'remitente desconocido'}: {classification['kind']}.")
        return stats
    except Exception as exc:
        _log(state, f"Mail Connector no pudo leer el inbox: {str(exc)[:140]}")
        return stats
    finally:
        if client:
            try: client.logout()
            except Exception: pass


def apply_inbox_to_deals(state: Dict[str, Any]) -> Dict[str, int]:
    state.setdefault("inbox", []); state.setdefault("offers", [])
    stats = {"linked": 0, "offers_created": 0, "objections": 0, "opt_outs": 0}
    for incoming in state["inbox"]:
        if incoming.get("processed"):
            continue
        sender = incoming.get("from", "").lower()
        related = None
        for item in reversed(state.get("outbox", [])):
            if (item.get("contact") or "").lower() == sender:
                related = item; break
        if not related:
            incoming["processed"] = True; incoming["processing_note"] = "sin deal vinculado"; continue
        deal = next((d for d in state.get("deals", []) if d.get("id") == related.get("deal_id")), None)
        if not deal:
            incoming["processed"] = True; continue
        stats["linked"] += 1
        cls = incoming.get("classification", {})
        kind = cls.get("kind")
        if kind == "commercial_offer" and cls.get("amount"):
            state["offers"].append({
                "id": f"OFFER-{len(state['offers'])+1:04d}", "deal_id":deal["id"], "supplier":deal.get("supplier"),
                "amount":cls["amount"], "currency":cls.get("currency") or "USD", "lead_days":None,
                "payment_terms":"por validar", "source":"email real", "verified":False, "created_at":utcnow(),
            })
            deal["stage"] = "propuesta"; deal["next_action"] = "Normalizar oferta real y recalcular economía"
            stats["offers_created"] += 1
        elif kind == "buyer_interest":
            deal["stage"] = "calificado"; deal["close_prob"] = min(.9, float(deal.get("close_prob",.3))+.12); deal["next_action"] = "Profundizar requerimiento y enviar propuesta"
        elif kind == "price_objection":
            deal["stage"] = "renegociación"; deal["next_action"] = "Mejorar costo proveedor o reformular propuesta"; stats["objections"] += 1
        elif kind == "opt_out":
            deal["next_action"] = "No volver a contactar esta dirección"; stats["opt_outs"] += 1
        incoming["processed"] = True; incoming["deal_id"] = deal["id"]
    return stats
