from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List

MAX_EVENTS = 240
MAX_WHATSAPP_PER_TICK = 3
COMMAND_CENTER_URL = os.getenv(
    "LUMEN_COMMAND_CENTER_URL",
    "https://lumen-web-production-5755.up.railway.app/command-center",
).strip()


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _config() -> Dict[str, Any]:
    return {
        "enabled": _truthy(os.getenv("LUMEN_WHATSAPP_ENABLED", "false")),
        "phone_number_id": os.getenv("LUMEN_WHATSAPP_PHONE_NUMBER_ID", "").strip(),
        "to": os.getenv("LUMEN_WHATSAPP_TO", "").strip(),
        "access_token": os.getenv("LUMEN_WHATSAPP_ACCESS_TOKEN", "").strip(),
        "graph_version": os.getenv("LUMEN_WHATSAPP_GRAPH_VERSION", "").strip(),
        "template_name": os.getenv("LUMEN_WHATSAPP_TEMPLATE_NAME", "").strip(),
        "template_language": os.getenv("LUMEN_WHATSAPP_TEMPLATE_LANGUAGE", "es_AR").strip() or "es_AR",
        "allow_text": _truthy(os.getenv("LUMEN_WHATSAPP_ALLOW_TEXT", "false")),
    }


def public_status() -> Dict[str, Any]:
    cfg = _config()
    template_ready = bool(cfg["template_name"])
    credentials_ready = bool(cfg["phone_number_id"] and cfg["to"] and cfg["access_token"] and cfg["graph_version"])
    return {
        "enabled": bool(cfg["enabled"]),
        "credentials_ready": credentials_ready,
        "template_ready": template_ready,
        "text_mode_allowed": bool(cfg["allow_text"]),
        "delivery_ready": bool(cfg["enabled"] and credentials_ready and (template_ready or cfg["allow_text"])),
        "recipient_configured": bool(cfg["to"]),
        "phone_number_id_configured": bool(cfg["phone_number_id"]),
        "access_token_configured": bool(cfg["access_token"]),
        "graph_version_configured": bool(cfg["graph_version"]),
        "template_name_configured": template_ready,
        "template_language": cfg["template_language"],
        "command_center_url": COMMAND_CENTER_URL,
        "secrets_exposed": False,
    }


def _stable(key: str) -> str:
    return "NTF-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def _clean(value: Any, max_len: int = 700) -> str:
    return " ".join(str(value or "").split())[:max_len]


def _event(state: Dict[str, Any], *, key: str, severity: str, kind: str, title: str,
           summary: str, object_type: str = "", object_id: str = "",
           action_required: bool = False) -> bool:
    events = state.setdefault("notification_events", [])
    if any(str(x.get("key") or "") == key for x in events):
        return False
    severity = severity.upper()
    events.append({
        "id": _stable(key),
        "key": key,
        "kind": kind,
        "severity": severity,
        "title": _clean(title, 180),
        "summary": _clean(summary, 900),
        "object_type": object_type,
        "object_id": object_id,
        "action_required": bool(action_required),
        "command_center_url": COMMAND_CENTER_URL,
        "created_at": utcnow(),
        "delivery_status": "dashboard_only" if severity == "INFO" else "queued",
        "whatsapp_attempts": 0,
    })
    state["notification_events"] = events[-MAX_EVENTS:]
    return True


def _discover(state: Dict[str, Any]) -> Dict[str, int]:
    created = {"info": 0, "important": 0, "critical": 0}

    # Evidence-backed opportunities are useful context in the app, but do not interrupt the executive.
    for opp in state.get("market_opportunities", []) or []:
        if str(opp.get("status") or "") not in {"evidence_backed", "ready", "active"}:
            continue
        if opp.get("collection_focus") == "mercadopago_ars" and opp.get("collection_focus_eligible") is False:
            continue
        key = f"opportunity|{opp.get('id')}"
        if _event(
            state, key=key, severity="INFO", kind="opportunity_detected",
            title="Nueva oportunidad respaldada por evidencia",
            summary=f"{opp.get('id')}: {_clean(opp.get('category') or 'oportunidad B2B', 180)}. Próxima acción: {_clean(opp.get('next_action') or 'validar el caso', 300)}",
            object_type="opportunity", object_id=str(opp.get("id") or ""),
        ):
            created["info"] += 1

    # A real email actually sent is an important commercial milestone.
    for msg in state.get("outbox", []) or []:
        if msg.get("status") != "sent" or msg.get("probe") or msg.get("simulation"):
            continue
        key = f"outbound_sent|{msg.get('id')}"
        if _event(
            state, key=key, severity="IMPORTANT", kind="outbound_sent",
            title="LUMEN envió un contacto comercial",
            summary=f"{_clean(msg.get('counterparty') or 'Contraparte', 180)} · {_clean(msg.get('subject') or msg.get('kind') or 'mensaje comercial', 240)}",
            object_type="message", object_id=str(msg.get("id") or ""),
        ):
            created["important"] += 1

    # Only linked inbound mail is considered a meaningful commercial event.
    for incoming in state.get("inbox", []) or []:
        if not (incoming.get("revops_case_id") or incoming.get("deal_id") or incoming.get("opportunity_id") or incoming.get("revops_source_message_id")):
            continue
        key = f"inbound|{incoming.get('id')}"
        classification = (incoming.get("classification") or {}).get("kind") or incoming.get("response_intent") or "respuesta"
        if _event(
            state, key=key, severity="IMPORTANT", kind="commercial_reply",
            title="Llegó una respuesta comercial",
            summary=f"De {_clean(incoming.get('from') or 'contraparte', 180)} · tipo {_clean(classification, 120)} · {_clean(incoming.get('subject') or incoming.get('body') or '', 420)}",
            object_type="inbox", object_id=str(incoming.get("id") or ""),
        ):
            created["important"] += 1

    # Real supplier offers/cotizaciones.
    for offer in state.get("offers", []) or []:
        if offer.get("source") == "demo/simulación" or offer.get("simulation"):
            continue
        if not (offer.get("amount") or offer.get("document_id") or offer.get("source_message_id")):
            continue
        key = f"real_offer|{offer.get('id')}"
        amount = f"{offer.get('currency') or ''} {offer.get('amount')}".strip() if offer.get("amount") else "importe pendiente de normalización"
        if _event(
            state, key=key, severity="IMPORTANT", kind="supplier_offer_received",
            title="LUMEN recibió una cotización real",
            summary=f"{_clean(offer.get('supplier') or 'Proveedor', 180)} · {amount} · estado {_clean(offer.get('normalization_status') or 'recibida', 120)}",
            object_type="offer", object_id=str(offer.get("id") or ""),
        ):
            created["important"] += 1

    # Human close approvals must interrupt immediately.
    for approval in state.get("approvals", []) or []:
        if approval.get("status") != "pending" or approval.get("kind") != "close_deal":
            continue
        key = f"human_approval|{approval.get('id')}"
        if _event(
            state, key=key, severity="CRITICAL", kind="human_approval_required",
            title="LUMEN necesita tu OK final",
            summary=f"Deal {_clean(approval.get('deal_id') or '', 120)} llegó al punto de decisión humana. Revisá el paquete de cierre antes de aprobar.",
            object_type="approval", object_id=str(approval.get("id") or ""), action_required=True,
        ):
            created["critical"] += 1

    # Explicit realized commission evidence.
    for case in state.get("commission_settlement_cases", []) or []:
        if str(case.get("status") or "") not in {"RECEIVED", "PARTIAL_RECEIVED"}:
            continue
        amount = case.get("received_amount_usd")
        key = f"commission_received|{case.get('transaction_id')}|{case.get('status')}|{amount}"
        if _event(
            state, key=key, severity="CRITICAL", kind="commission_received",
            title="Comisión recibida",
            summary=f"Transacción {_clean(case.get('transaction_id') or '', 120)} · recibido USD {amount} · estado {case.get('status')}",
            object_type="transaction", object_id=str(case.get("transaction_id") or ""),
        ):
            created["critical"] += 1

    # Verified Mercado Pago live events can confirm payment reconciliation in ARS.
    for mp in state.get("mercadopago_webhook_events", []) or []:
        if mp.get("live_mode") is not True or mp.get("status") != "verified_and_reconciled":
            continue
        key = f"mercadopago_reconciled|{mp.get('event_key') or mp.get('data_id')}"
        if _event(
            state, key=key, severity="CRITICAL", kind="mercadopago_payment_reconciled",
            title="Mercado Pago confirmó un pago",
            summary=f"Pago {mp.get('data_id')} verificado por API y conciliado. Estado: {_clean(mp.get('payment_status') or 'verificado', 100)}.",
            object_type="payment", object_id=str(mp.get("data_id") or ""),
        ):
            created["critical"] += 1

    # Operational blockers/failures should also notify the owner.
    coo = state.get("autonomous_coo", {}) or (state.get("connector_telemetry", {}) or {}).get("autonomous_coo", {}) or {}
    guard = coo.get("operational_guard", {}) or {}
    for blocker in list(guard.get("blockers", []) or [])[:8]:
        text = _clean(blocker, 500)
        key = "system_blocker|" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
        if _event(
            state, key=key, severity="CRITICAL", kind="operational_blocker",
            title="LUMEN detectó un bloqueo operativo",
            summary=text, object_type="system", object_id="autonomous_coo", action_required=True,
        ):
            created["critical"] += 1

    return created


def _payload(event: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    summary_with_link = f"{event.get('summary')} | Ver LUMEN: {COMMAND_CENTER_URL}"[:900]
    if cfg["template_name"]:
        return {
            "messaging_product": "whatsapp",
            "to": cfg["to"],
            "type": "template",
            "template": {
                "name": cfg["template_name"],
                "language": {"code": cfg["template_language"]},
                "components": [{
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": str(event.get("severity") or "IMPORTANTE")},
                        {"type": "text", "text": str(event.get("title") or "Evento LUMEN")[:180]},
                        {"type": "text", "text": summary_with_link},
                    ],
                }],
            },
        }
    return {
        "messaging_product": "whatsapp",
        "to": cfg["to"],
        "type": "text",
        "text": {"preview_url": True, "body": f"LUMEN · {event.get('severity')}\n{event.get('title')}\n{summary_with_link}"[:1800]},
    }


def _send_whatsapp(event: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    url = f"https://graph.facebook.com/{cfg['graph_version']}/{cfg['phone_number_id']}/messages"
    data = json.dumps(_payload(event, cfg), ensure_ascii=False).encode("utf-8")
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
            return {"ok": True, "message_id": message_id, "http_status": int(response.status)}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": f"HTTPError:{exc.code}", "http_status": int(exc.code)}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}


def notification_router_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    discovered = _discover(state)
    cfg = _config()
    status = public_status()
    sent = 0
    failed = 0
    queued = 0

    for event in state.get("notification_events", []) or []:
        if event.get("severity") == "INFO" or event.get("delivery_status") == "sent":
            continue
        if event.get("delivery_status") not in {"queued", "retry"}:
            continue
        queued += 1
        if not status["delivery_ready"] or sent >= MAX_WHATSAPP_PER_TICK:
            continue
        result = _send_whatsapp(event, cfg)
        event["whatsapp_attempts"] = int(event.get("whatsapp_attempts") or 0) + 1
        event["last_whatsapp_attempt_at"] = utcnow()
        if result.get("ok"):
            event["delivery_status"] = "sent"
            event["whatsapp_sent_at"] = utcnow()
            event["whatsapp_message_id"] = result.get("message_id")
            event.pop("last_error", None)
            sent += 1
        else:
            event["delivery_status"] = "retry"
            event["last_error"] = result.get("error")
            failed += 1

    events = state.get("notification_events", []) or []
    report = {
        "updated_at": utcnow(),
        "channel": "whatsapp",
        "status": status,
        "discovered": discovered,
        "events_total": len(events),
        "queued_for_whatsapp": sum(1 for x in events if x.get("delivery_status") in {"queued", "retry"}),
        "sent_total": sum(1 for x in events if x.get("delivery_status") == "sent"),
        "sent_this_tick": sent,
        "failed_this_tick": failed,
        "recent": list(reversed(events[-12:])),
        "policy": {
            "INFO": "solo Command Center",
            "IMPORTANT": "WhatsApp cuando el canal está configurado",
            "CRITICAL": "WhatsApp prioritario + Command Center",
            "max_whatsapp_per_tick": MAX_WHATSAPP_PER_TICK,
            "deduplication": "un evento estable se notifica una sola vez",
            "template_recommended": True,
        },
    }
    state["notification_router"] = report
    return report
