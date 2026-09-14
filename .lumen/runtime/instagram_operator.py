from __future__ import annotations

import hashlib
import html
import json
import os
import re
import unicodedata
import urllib.error
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import STATE, auth, load_state, log, save_state
from outbound_web import app

INSTAGRAM_ACCESS_TOKEN = os.getenv("LUMEN_INSTAGRAM_ACCESS_TOKEN", "").strip()
INSTAGRAM_USER_ID = os.getenv("LUMEN_INSTAGRAM_USER_ID", "").strip()
INSTAGRAM_USERNAME = os.getenv("LUMEN_INSTAGRAM_USERNAME", "").strip()
INSTAGRAM_GRAPH_BASE = os.getenv("LUMEN_INSTAGRAM_GRAPH_BASE", "https://graph.instagram.com").rstrip("/")
INSTAGRAM_GRAPH_VERSION = os.getenv("LUMEN_INSTAGRAM_GRAPH_VERSION", "v26.0").strip() or "v26.0"
INSTAGRAM_SEND_ENABLED = os.getenv("LUMEN_INSTAGRAM_SEND_ENABLED", "false").lower() == "true"

MAX_INBOX = 300
MAX_LEADS = 300
MAX_SENT_AUDIT = 300


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.lower().strip().split())


def _contains_any(text: str, needles: Iterable[str]) -> bool:
    return any(_norm(x) in text for x in needles)


def _stable_id(*parts: Any) -> str:
    raw = "|".join(str(x or "") for x in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:18]


def _message_text(message: Dict[str, Any]) -> str:
    if message.get("text"):
        return str(message.get("text"))
    quick = message.get("quick_reply") or {}
    if isinstance(quick, dict) and quick.get("payload"):
        return str(quick.get("payload"))
    attachments = message.get("attachments") or []
    if attachments:
        kinds = []
        for item in attachments if isinstance(attachments, list) else [attachments]:
            if isinstance(item, dict):
                kinds.append(str(item.get("type") or "adjunto"))
        return "[Adjunto" + (": " + ", ".join(kinds) if kinds else "") + "]"
    return ""


def _normalize_webhook(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for entry in payload.get("entry", []) or []:
        if not isinstance(entry, dict):
            continue
        entry_id = str(entry.get("id") or "")
        entry_time = entry.get("time")

        for event in entry.get("messaging", []) or []:
            if not isinstance(event, dict):
                continue
            sender = event.get("sender") or {}
            recipient = event.get("recipient") or {}
            sender_id = str(sender.get("id") or "")
            recipient_id = str(recipient.get("id") or "")
            if sender_id and sender_id == INSTAGRAM_USER_ID:
                continue

            kind = ""
            text = ""
            external_id = ""
            if isinstance(event.get("message"), dict):
                message = event["message"]
                if message.get("is_echo"):
                    continue
                kind = "message"
                text = _message_text(message)
                external_id = str(message.get("mid") or "")
            elif isinstance(event.get("postback"), dict):
                kind = "postback"
                text = str((event.get("postback") or {}).get("title") or (event.get("postback") or {}).get("payload") or "")
                external_id = str((event.get("postback") or {}).get("mid") or "")
            elif isinstance(event.get("reaction"), dict):
                kind = "reaction"
                text = str((event.get("reaction") or {}).get("reaction") or "")
            elif isinstance(event.get("referral"), dict):
                kind = "referral"
                text = str((event.get("referral") or {}).get("ref") or "")
            elif event.get("read") or event.get("seen"):
                kind = "seen"
            else:
                continue

            timestamp = event.get("timestamp") or entry_time
            external_id = external_id or _stable_id(entry_id, sender_id, recipient_id, timestamp, kind, text)
            normalized.append(
                {
                    "external_id": external_id,
                    "kind": kind,
                    "sender_id": sender_id,
                    "recipient_id": recipient_id,
                    "sender_username": None,
                    "text": text,
                    "event_at": timestamp,
                    "entry_id": entry_id,
                    "raw_field": kind,
                }
            )

        for change in entry.get("changes", []) or []:
            if not isinstance(change, dict):
                continue
            field = str(change.get("field") or "")
            value = change.get("value") or {}
            if not isinstance(value, dict):
                value = {}
            if field != "comments":
                continue
            author = value.get("from") or {}
            if not isinstance(author, dict):
                author = {}
            sender_id = str(author.get("id") or value.get("from_id") or "")
            username = author.get("username") or value.get("username")
            text = str(value.get("text") or value.get("message") or "")
            comment_id = str(value.get("id") or value.get("comment_id") or "")
            normalized.append(
                {
                    "external_id": comment_id or _stable_id(entry_id, sender_id, entry_time, field, text),
                    "kind": "comment",
                    "sender_id": sender_id,
                    "recipient_id": entry_id or INSTAGRAM_USER_ID,
                    "sender_username": username,
                    "text": text,
                    "event_at": entry_time,
                    "entry_id": entry_id,
                    "media_id": value.get("media", {}).get("id") if isinstance(value.get("media"), dict) else value.get("media_id"),
                    "raw_field": field,
                }
            )
    return normalized


def _classify(kind: str, text: str) -> Dict[str, Any]:
    t = _norm(text)
    score = 48 if kind == "message" else 40
    intent = "consulta_general"
    commercial = False

    if _contains_any(t, ("spam", "crypto", "forex", "casino", "apuesta", "followers", "seguidores gratis", "inversion garantizada")):
        return {"intent": "spam", "priority": 10, "commercial": False}

    if _contains_any(t, ("reclamo", "problema", "no funciona", "no llego", "demora", "devolucion", "reembolso", "mal servicio")):
        intent, score = "soporte_reclamo", 96
    elif _contains_any(t, ("precio", "cuanto", "cotizacion", "cotizar", "presupuesto", "comprar", "necesito", "busco", "me interesa", "quiero", "stock", "disponibilidad")):
        intent, score, commercial = "oportunidad_comercial", 92, True
    elif _contains_any(t, ("proveedor", "distribuidor", "mayorista", "fabricamos", "representamos", "somos fabricantes", "ofrecemos")):
        intent, score, commercial = "proveedor", 74, True
    elif _contains_any(t, ("alianza", "colaboracion", "partner", "socios", "trabajar juntos")):
        intent, score, commercial = "alianza", 68, True
    elif kind == "comment" and _contains_any(t, ("info", "informacion", "precio", "me interesa")):
        intent, score, commercial = "oportunidad_comercial", 86, True
    elif not t:
        intent, score = "evento_sin_texto", 25
    elif "?" in str(text or ""):
        intent, score = "consulta_general", 58

    if len(t) > 20:
        score = min(100, score + 3)
    return {"intent": intent, "priority": score, "commercial": commercial}


def _infer_need(text: str) -> str:
    t = _norm(text)
    if _contains_any(t, ("calibr", "metrolog", "instrument")):
        return "instrumentación / metrología"
    if _contains_any(t, ("sensor", "nivel", "presion", "temperatura")):
        return "instrumentación industrial"
    if _contains_any(t, ("electronic", "diodo", "resistencia", "conector", "cable")):
        return "componentes electrónicos"
    if _contains_any(t, ("mantenimiento", "repuesto", "reparacion")):
        return "MRO / repuestos industriales"
    return "consulta comercial recibida por Instagram"


def _draft_reply(kind: str, intent: str, text: str) -> str:
    if intent == "oportunidad_comercial":
        return (
            "¡Hola! Gracias por escribir a LUMEN B2B. Podemos ayudarte con la consulta. "
            "¿Podés indicarnos qué producto o servicio necesitás, cantidad aproximada y ciudad/país de entrega? "
            "Con esos datos avanzamos con una propuesta más precisa."
        )
    if intent == "proveedor":
        return (
            "Gracias por contactarnos. Nos interesa conocer alternativas de proveedores para nuestra red B2B. "
            "¿Podés enviarnos razón social, sitio web, líneas o marcas que trabajan, zona de cobertura y un contacto comercial?"
        )
    if intent == "alianza":
        return (
            "Gracias por escribirnos. Estamos abiertos a evaluar alianzas B2B cuando hay una propuesta concreta y trazable. "
            "Contanos brevemente qué ofrecen, a qué tipo de empresas apuntan y cómo imaginan la colaboración."
        )
    if intent == "soporte_reclamo":
        return (
            "Gracias por avisarnos. Queremos revisarlo correctamente. "
            "¿Podés contarnos qué ocurrió y, si corresponde, compartir número de operación, fecha y cualquier dato que nos ayude a identificar el caso?"
        )
    if intent == "spam":
        return ""
    if kind == "comment":
        return "¡Gracias por escribirnos! Si querés, contanos un poco más sobre lo que necesitás y lo revisamos."
    return "¡Hola! Gracias por escribir a LUMEN B2B. Contanos qué necesitás y te orientamos."


def _operator_stats(inbox: List[Dict[str, Any]], leads: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "version": "1.0-instagram-operator",
        "status": "active",
        "inbox_total": len(inbox),
        "pending_review": sum(1 for x in inbox if x.get("status") == "pending_review"),
        "commercial_signals": sum(1 for x in inbox if x.get("commercial_signal")),
        "leads_total": len(leads),
        "sent_total": sum(1 for x in inbox if x.get("status") == "sent"),
        "send_enabled": INSTAGRAM_SEND_ENABLED,
        "updated_at": _now_iso(),
    }


def process_instagram_webhook(payload: Dict[str, Any], *, persist: bool = False) -> Dict[str, Any]:
    inbox = list(STATE.get("instagram_inbox", []) or [])
    leads = list(STATE.get("instagram_leads", []) or [])
    existing = {str(x.get("external_id") or x.get("id") or "") for x in inbox}
    created = 0

    for event in _normalize_webhook(payload):
        if event["kind"] in {"seen", "reaction"}:
            continue
        external_id = str(event.get("external_id") or "")
        if external_id and external_id in existing:
            continue

        classification = _classify(str(event.get("kind") or ""), str(event.get("text") or ""))
        item = {
            "id": f"IG-{_stable_id(external_id, event.get('sender_id'), event.get('kind'))}",
            "external_id": external_id,
            "received_at": _now_iso(),
            **event,
            "intent": classification["intent"],
            "priority": classification["priority"],
            "commercial_signal": classification["commercial"],
            "status": "pending_review" if classification["intent"] != "spam" else "dismissed",
            "draft_reply": _draft_reply(str(event.get("kind") or ""), classification["intent"], str(event.get("text") or "")),
            "lead_id": None,
            "sent_message_id": None,
            "last_error": None,
        }
        inbox.insert(0, item)
        existing.add(external_id or item["id"])
        created += 1
        if item["commercial_signal"]:
            log(f"Instagram Operator detectó señal comercial ({item['intent']}) con prioridad {item['priority']}.")

    STATE["instagram_inbox"] = inbox[:MAX_INBOX]
    STATE["instagram_operator"] = _operator_stats(STATE["instagram_inbox"], leads)
    if persist and created:
        save_state()
    return {"created": created, "stats": dict(STATE["instagram_operator"])}


def _find_item(item_id: str) -> Dict[str, Any]:
    for row in STATE.get("instagram_inbox", []) or []:
        if str(row.get("id")) == str(item_id):
            return row
    raise HTTPException(status_code=404, detail="Evento de Instagram no encontrado")


def _send_message(recipient_id: str, text: str) -> Dict[str, Any]:
    if not INSTAGRAM_SEND_ENABLED:
        raise RuntimeError("instagram_send_disabled")
    if not INSTAGRAM_ACCESS_TOKEN or not INSTAGRAM_USER_ID:
        raise RuntimeError("instagram_credentials_missing")
    if not recipient_id:
        raise RuntimeError("recipient_missing")
    payload = json.dumps(
        {"recipient": {"id": recipient_id}, "message": {"text": text[:1000]}},
        ensure_ascii=False,
    ).encode("utf-8")
    url = f"{INSTAGRAM_GRAPH_BASE}/{INSTAGRAM_GRAPH_VERSION}/{INSTAGRAM_USER_ID}/messages"
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {INSTAGRAM_ACCESS_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "LUMEN-B2B/1.0",
        },
        method="POST",
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
        raise RuntimeError(f"Instagram send HTTP {exc.code}: {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Instagram send connection error: {exc.reason}") from exc


def _send_comment_reply(comment_id: str, text: str) -> Dict[str, Any]:
    if not INSTAGRAM_SEND_ENABLED:
        raise RuntimeError("instagram_send_disabled")
    if not INSTAGRAM_ACCESS_TOKEN:
        raise RuntimeError("instagram_credentials_missing")
    if not comment_id:
        raise RuntimeError("comment_id_missing")
    body = urllib.parse.urlencode({"message": text[:2200]}).encode("utf-8")
    url = f"{INSTAGRAM_GRAPH_BASE}/{INSTAGRAM_GRAPH_VERSION}/{comment_id}/replies"
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {INSTAGRAM_ACCESS_TOKEN}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "LUMEN-B2B/1.0",
        },
        method="POST",
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
        raise RuntimeError(f"Instagram comment reply HTTP {exc.code}: {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Instagram comment reply connection error: {exc.reason}") from exc


def _promote(item: Dict[str, Any]) -> Dict[str, Any]:
    if item.get("lead_id"):
        for lead in STATE.get("instagram_leads", []) or []:
            if lead.get("id") == item.get("lead_id"):
                return lead

    leads = list(STATE.get("instagram_leads", []) or [])
    lead = {
        "id": f"IGLEAD-{len(leads)+1:04d}",
        "created_at": _now_iso(),
        "source": "instagram",
        "source_event_id": item.get("id"),
        "instagram_user_id": item.get("sender_id"),
        "instagram_username": item.get("sender_username"),
        "intent": item.get("intent"),
        "need": _infer_need(str(item.get("text") or "")),
        "signal": item.get("text"),
        "priority": item.get("priority"),
        "status": "nuevo",
    }
    leads.insert(0, lead)
    STATE["instagram_leads"] = leads[:MAX_LEADS]
    item["lead_id"] = lead["id"]

    buyer_key = str(item.get("sender_id") or "")
    buyers = STATE.setdefault("buyers", [])
    if buyer_key and not any(str(x.get("instagram_user_id") or "") == buyer_key for x in buyers):
        buyers.append(
            {
                "name": item.get("sender_username") or f"Instagram {buyer_key}",
                "sector": "Instagram inbound",
                "need": lead["need"],
                "fit": min(98, max(55, int(item.get("priority") or 60))),
                "budget": 70,
                "email": None,
                "email_verified": False,
                "source": "instagram",
                "instagram_user_id": buyer_key,
            }
        )
    log(f"Instagram Operator convirtió {item.get('id')} en lead {lead['id']}.")
    return lead


@app.get("/health/instagram/operator", include_in_schema=False)
def instagram_operator_health():
    loaded = load_state()
    inbox = list(STATE.get("instagram_inbox", []) or [])
    leads = list(STATE.get("instagram_leads", []) or [])
    stats = _operator_stats(inbox, leads)
    return {"ok": bool(loaded), **stats}


@app.get("/api/instagram/operator", include_in_schema=False)
def instagram_operator_api(_=Depends(auth)):
    load_state()
    inbox = list(STATE.get("instagram_inbox", []) or [])
    leads = list(STATE.get("instagram_leads", []) or [])
    return {
        "operator": _operator_stats(inbox, leads),
        "inbox": inbox[:100],
        "leads": leads[:100],
    }


@app.post("/api/instagram/lead", include_in_schema=False)
def instagram_promote(item_id: str = Form(...), _=Depends(auth)):
    load_state()
    item = _find_item(item_id)
    _promote(item)
    STATE["instagram_operator"] = _operator_stats(
        list(STATE.get("instagram_inbox", []) or []),
        list(STATE.get("instagram_leads", []) or []),
    )
    save_state()
    return RedirectResponse("/instagram", status_code=303)


@app.post("/api/instagram/dismiss", include_in_schema=False)
def instagram_dismiss(item_id: str = Form(...), _=Depends(auth)):
    load_state()
    item = _find_item(item_id)
    item["status"] = "dismissed"
    item["reviewed_at"] = _now_iso()
    item["last_error"] = None
    log(f"Instagram Operator archivó {item_id}.")
    STATE["instagram_operator"] = _operator_stats(
        list(STATE.get("instagram_inbox", []) or []),
        list(STATE.get("instagram_leads", []) or []),
    )
    save_state()
    return RedirectResponse("/instagram", status_code=303)


@app.post("/api/instagram/reply", include_in_schema=False)
def instagram_reply(
    item_id: str = Form(...),
    reply_text: str = Form(...),
    promote_lead: str = Form(""),
    _=Depends(auth),
):
    load_state()
    item = _find_item(item_id)
    text = str(reply_text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="La respuesta no puede estar vacía")
    kind = str(item.get("kind") or "")
    if kind not in {"message", "postback", "comment"}:
        raise HTTPException(status_code=400, detail="Este tipo de evento no admite respuesta directa")
    if kind in {"message", "postback"} and not item.get("sender_id"):
        raise HTTPException(status_code=400, detail="El evento no tiene recipient Instagram ID")
    if kind == "comment" and not item.get("external_id"):
        raise HTTPException(status_code=400, detail="El comentario no tiene ID")

    if promote_lead:
        _promote(item)

    try:
        if kind == "comment":
            result = _send_comment_reply(str(item.get("external_id")), text)
        else:
            result = _send_message(str(item.get("sender_id")), text)
        item["status"] = "sent"
        item["approved_at"] = _now_iso()
        item["sent_at"] = _now_iso()
        item["approved_reply"] = text[:1000]
        item["sent_message_id"] = result.get("message_id") or result.get("id")
        item["last_error"] = None
        audit = list(STATE.get("instagram_sent_audit", []) or [])
        audit.insert(
            0,
            {
                "sent_at": item["sent_at"],
                "source_event_id": item_id,
                "recipient_id": item.get("sender_id"),
                "comment_id": item.get("external_id") if kind == "comment" else None,
                "message_id": result.get("message_id") or result.get("id"),
                "human_approved": True,
                "text": text[:1000],
            },
        )
        STATE["instagram_sent_audit"] = audit[:MAX_SENT_AUDIT]
        log(f"Instagram Operator envió respuesta aprobada para {kind} {item.get('id')}.")
    except Exception as exc:
        item["status"] = "send_failed"
        item["last_error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
        save_state()
        raise HTTPException(status_code=502, detail=item["last_error"]) from exc

    STATE["instagram_operator"] = _operator_stats(
        list(STATE.get("instagram_inbox", []) or []),
        list(STATE.get("instagram_leads", []) or []),
    )
    save_state()
    return RedirectResponse("/instagram", status_code=303)


def _render_item(item: Dict[str, Any]) -> str:
    status = str(item.get("status") or "")
    commercial = " · señal comercial" if item.get("commercial_signal") else ""
    lead = f" · {_esc(item.get('lead_id'))}" if item.get("lead_id") else ""
    text = _esc(item.get("text") or "[sin texto]")
    draft = _esc(item.get("draft_reply") or "")
    sender = _esc(item.get("sender_username") or item.get("sender_id") or "desconocido")
    actions = ""
    if status in {"pending_review", "send_failed"}:
        if item.get("kind") in {"message", "postback", "comment"}:
            actions += f"""
            <form method='post' action='/api/instagram/reply'>
              <input type='hidden' name='item_id' value='{_esc(item.get("id"))}'>
              <textarea name='reply_text' rows='4'>{draft}</textarea>
              <label class='check'><input type='checkbox' name='promote_lead' value='1' {'checked' if item.get('commercial_signal') else ''}> Convertir en lead comercial</label>
              <button class='primary' type='submit'>Aprobar y enviar</button>
            </form>"""
        if not item.get("lead_id") and item.get("commercial_signal"):
            actions += f"""
            <form class='inline' method='post' action='/api/instagram/lead'>
              <input type='hidden' name='item_id' value='{_esc(item.get("id"))}'>
              <button type='submit'>Solo crear lead</button>
            </form>"""
        actions += f"""
        <form class='inline' method='post' action='/api/instagram/dismiss'>
          <input type='hidden' name='item_id' value='{_esc(item.get("id"))}'>
          <button class='ghost' type='submit'>Archivar</button>
        </form>"""
    return f"""
    <article class='item'>
      <div class='itemtop'>
        <div><b>{sender}</b><span class='pill'>{_esc(item.get('kind'))}</span><span class='pill'>{_esc(item.get('intent'))}</span></div>
        <div class='score'>P{_esc(item.get('priority'))}</div>
      </div>
      <div class='msg'>{text}</div>
      <div class='meta'>{_esc(item.get('received_at'))} · {status}{commercial}{lead}</div>
      {f"<div class='error'>{_esc(item.get('last_error'))}</div>" if item.get('last_error') else ""}
      {actions}
    </article>"""


@app.get("/instagram", response_class=HTMLResponse, include_in_schema=False)
def instagram_dashboard(_=Depends(auth)):
    load_state()
    inbox = list(STATE.get("instagram_inbox", []) or [])
    leads = list(STATE.get("instagram_leads", []) or [])
    stats = _operator_stats(inbox, leads)
    rows = "".join(_render_item(x) for x in inbox[:80]) or "<div class='empty'>Todavía no hay conversaciones recibidas.</div>"
    lead_rows = "".join(
        f"<tr><td>{_esc(x.get('id'))}</td><td>{_esc(x.get('instagram_username') or x.get('instagram_user_id'))}</td><td>{_esc(x.get('intent'))}</td><td>{_esc(x.get('need'))}</td><td>{_esc(x.get('status'))}</td></tr>"
        for x in leads[:50]
    ) or "<tr><td colspan='5'>Sin leads todavía.</td></tr>"
    send_state = "ACTIVO · siempre con aprobación humana" if INSTAGRAM_SEND_ENABLED else "DESACTIVADO"
    return HTMLResponse(f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>LUMEN · Instagram Operator</title>
<style>
:root{{color-scheme:dark;--bg:#061018;--panel:#0b1822;--line:#1c3b4a;--muted:#8ea8b7;--text:#eef8fb;--lime:#d7ff64;--blue:#80cfff;--good:#78e7b0;--bad:#ff8e8e}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 20% -10%,#12314a 0,#061018 36%);color:var(--text);font:14px Inter,system-ui,-apple-system;padding:20px}}main{{max-width:1250px;margin:auto}}a{{color:var(--blue);text-decoration:none}}h1{{margin:8px 0 3px}}.sub{{color:var(--muted)}}.grid{{display:grid;grid-template-columns:repeat(5,1fr);gap:9px;margin:16px 0}}.card,.item{{background:#0b1822;border:1px solid var(--line);border-radius:15px;padding:14px}}.metric{{font-size:25px;font-weight:850;margin-top:5px}}.label{{font-size:10px;letter-spacing:.11em;text-transform:uppercase;color:var(--muted)}}.item{{margin:9px 0}}.itemtop{{display:flex;justify-content:space-between;gap:10px}}.pill{{display:inline-block;margin-left:6px;border:1px solid #315363;border-radius:999px;padding:3px 7px;font-size:10px;color:#bad1dc}}.score{{color:var(--lime);font-weight:800}}.msg{{font-size:16px;line-height:1.45;margin:12px 0}}.meta{{color:var(--muted);font-size:11px}}textarea{{width:100%;margin:11px 0 7px;background:#07131b;color:white;border:1px solid #2a4c5c;border-radius:9px;padding:10px;font:inherit}}button{{border:0;border-radius:9px;padding:9px 12px;font-weight:800;cursor:pointer;background:#d7ff64;color:#071018}}button.ghost{{background:#142631;color:#c7d9e2;border:1px solid #31505f}}form.inline{{display:inline-block;margin:7px 6px 0 0}}.check{{display:block;color:#b8ccd6;margin:5px 0 9px}}.error{{color:var(--bad);margin-top:8px}}.empty{{padding:25px;border:1px dashed #315363;border-radius:12px;color:var(--muted)}}table{{width:100%;border-collapse:collapse}}th,td{{border-bottom:1px solid #183541;padding:8px;text-align:left;vertical-align:top}}th{{color:var(--muted);font-size:11px}}.two{{display:grid;grid-template-columns:1.4fr .8fr;gap:12px}}@media(max-width:900px){{.grid{{grid-template-columns:1fr 1fr}}.two{{grid-template-columns:1fr}}}}@media(max-width:600px){{body{{padding:11px}}.grid{{grid-template-columns:1fr 1fr}}}}
</style></head><body><main>
<p><a href='/command-center'>← Centro de Comando</a></p>
<h1>Instagram Operator</h1>
<div class='sub'>@{_esc(INSTAGRAM_USERNAME or 'instagram')} · recepción, clasificación, CRM y respuesta con aprobación humana.</div>
<div class='grid'>
<div class='card'><div class='label'>Inbox</div><div class='metric'>{stats['inbox_total']}</div></div>
<div class='card'><div class='label'>Pendientes</div><div class='metric'>{stats['pending_review']}</div></div>
<div class='card'><div class='label'>Señales comerciales</div><div class='metric'>{stats['commercial_signals']}</div></div>
<div class='card'><div class='label'>Leads</div><div class='metric'>{stats['leads_total']}</div></div>
<div class='card'><div class='label'>Enviadas</div><div class='metric'>{stats['sent_total']}</div></div>
</div>
<div class='card' style='margin-bottom:12px'><b>Envío:</b> {_esc(send_state)}. LUMEN nunca envía una respuesta desde esta v1 sin que alguien pulse “Aprobar y enviar”.</div>
<div class='two'><section><h2>Bandeja inteligente</h2>{rows}</section><section><div class='card'><h2>CRM · Leads de Instagram</h2><table><thead><tr><th>ID</th><th>Contacto</th><th>Intención</th><th>Necesidad</th><th>Estado</th></tr></thead><tbody>{lead_rows}</tbody></table></div></section></div>
</main></body></html>""")


@app.middleware("http")
async def instagram_operator_after_webhook(request: Request, call_next):
    response = await call_next(request)
    if request.method == "POST" and request.url.path == "/webhooks/instagram" and 200 <= response.status_code < 300:
        try:
            if load_state():
                rows = list(STATE.get("instagram_webhook_events", []) or [])
                payload = rows[0].get("payload") if rows and isinstance(rows[0], dict) else None
                if isinstance(payload, dict):
                    process_instagram_webhook(payload, persist=True)
        except Exception as exc:
            print({"instagram_operator_webhook_bridge": {"status": "error", "error": f"{type(exc).__name__}: {str(exc)[:300]}"}}, flush=True)
    return response


def _startup_backfill() -> None:
    try:
        if not load_state():
            return
        created = 0
        for row in reversed(list(STATE.get("instagram_webhook_events", []) or [])[:40]):
            payload = row.get("payload") if isinstance(row, dict) else None
            if isinstance(payload, dict):
                created += int(process_instagram_webhook(payload).get("created") or 0)
        STATE["instagram_operator"] = _operator_stats(
            list(STATE.get("instagram_inbox", []) or []),
            list(STATE.get("instagram_leads", []) or []),
        )
        if created:
            save_state()
        print({"instagram_operator": {**dict(STATE["instagram_operator"]), "backfilled": created}}, flush=True)
    except Exception as exc:
        print({"instagram_operator": {"status": "startup_error", "error": f"{type(exc).__name__}: {str(exc)[:300]}"}}, flush=True)


_startup_backfill()
