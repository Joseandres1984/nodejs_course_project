from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Form, HTTPException, Query
from fastapi.responses import HTMLResponse

from main import STATE, load_state, save_state

router = APIRouter()

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
QTY_RE = re.compile(r"\b(\d{1,6})\s*(?:u\.?|unidades?|equipos?|piezas?|celulares?|relojes?|auriculares?)\b", re.I)
COMPANY_PATTERNS = (
    re.compile(r"(?:empresa|compañía|compania)\s+([A-ZÁÉÍÓÚÑ0-9][A-ZÁÉÍÓÚÑ0-9& ._-]{1,70})", re.I),
    re.compile(r"(?:soy|somos)\s+de\s+([A-ZÁÉÍÓÚÑ0-9][A-ZÁÉÍÓÚÑ0-9& ._-]{1,70})", re.I),
)
UNCERTAIN_REPLY_RE = re.compile(
    r"\b(?:no\s+s[eé]|a\s+definir|por\s+definir|todav[ií]a\s+no|sin\s+definir|no\s+definid[oa])\b",
    re.I,
)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _clean(value: Any, limit: int) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _listing(listing_id: str) -> Optional[Dict[str, Any]]:
    target = str(listing_id or "").strip()
    return next((x for x in STATE.get("autonomous_listings", []) or [] if str(x.get("id") or "") == target), None)


def _conversation(conversation_id: str) -> Optional[Dict[str, Any]]:
    target = str(conversation_id or "").strip()
    return next((x for x in STATE.get("market_conversations", []) or [] if str(x.get("id") or "") == target), None)


def _new_conversation(listing: Dict[str, Any]) -> Dict[str, Any]:
    rows = STATE.setdefault("market_conversations", [])
    conv = {
        "id": f"MCNV-{len(rows)+1:05d}",
        "listing_id": str(listing.get("id") or ""),
        "category": str(listing.get("category") or ""),
        "messages": [],
        "need_parts": [],
        "company": "",
        "email": "",
        "quantity": "",
        "delivery_location": "",
        "status": "collecting_need",
        "created_at": utcnow(),
        "updated_at": utcnow(),
    }
    rows.append(conv)
    STATE["market_conversations"] = rows[-500:]
    return conv


def _extract_company(text: str) -> str:
    for pattern in COMPANY_PATTERNS:
        match = pattern.search(text or "")
        if match:
            candidate = _clean(match.group(1), 80)
            candidate = re.split(r"\b(?:y|que|necesito|busco|quiero|para)\b", candidate, maxsplit=1, flags=re.I)[0].strip(" ,.-")
            if len(candidate) >= 2:
                return candidate
    return ""


def _is_explicit_answer(text: str) -> bool:
    value = _clean(text, 180)
    return bool(value) and not UNCERTAIN_REPLY_RE.search(value)


def _ingest_message(conv: Dict[str, Any], message: str) -> None:
    text = _clean(message, 1800)
    if not text:
        return
    status_before = str(conv.get("status") or "")
    conv.setdefault("messages", []).append({"role": "buyer", "text": text, "ts": utcnow()})
    conv["messages"] = conv["messages"][-20:]

    email = EMAIL_RE.search(text)
    if email:
        conv["email"] = email.group(0).lower()

    if not conv.get("company"):
        company = _extract_company(text)
        if company:
            conv["company"] = company
        elif status_before == "awaiting_company" and not email and _is_explicit_answer(text):
            conv["company"] = _clean(text, 80)

    if not conv.get("quantity"):
        qty = QTY_RE.search(text)
        if qty:
            conv["quantity"] = qty.group(1) + " unidades"
        elif status_before == "awaiting_quantity" and _is_explicit_answer(text) and re.search(r"\d", text):
            conv["quantity"] = _clean(text, 100)

    if (
        not conv.get("delivery_location")
        and status_before == "awaiting_delivery_location"
        and not email
        and _is_explicit_answer(text)
        and len(text) >= 3
    ):
        conv["delivery_location"] = _clean(text, 180)

    contact_only = bool(email and text.strip().lower() == email.group(0).lower())
    answer_only_statuses = {"awaiting_company", "awaiting_email", "awaiting_quantity", "awaiting_delivery_location"}
    if status_before not in answer_only_statuses and not contact_only:
        parts = conv.setdefault("need_parts", [])
        if text not in parts:
            parts.append(text)
        conv["need_parts"] = parts[-6:]
    conv["updated_at"] = utcnow()


def _need(conv: Dict[str, Any]) -> str:
    return _clean(" ".join(conv.get("need_parts", []) or []), 1800)


def _next_question(conv: Dict[str, Any], listing: Dict[str, Any]) -> str:
    need = _need(conv)
    if len(need) < 8:
        conv["status"] = "collecting_need"
        return f"Contame qué necesitás de {listing.get('category') or 'este producto'}: modelo, especificación o cualquier detalle que tengas."
    if not conv.get("quantity"):
        conv["status"] = "awaiting_quantity"
        return "¿Qué cantidad necesitás? Puede ser aproximada, pero necesito una cantidad indicada por vos para pedir cotizaciones comparables."
    if not conv.get("delivery_location"):
        conv["status"] = "awaiting_delivery_location"
        return "¿Dónde sería la entrega? Con ciudad, provincia o planta alcanza; no voy a asumir ese dato por vos."
    if not conv.get("email"):
        conv["status"] = "awaiting_email"
        return "Perfecto. ¿A qué email te puedo responder? Podés escribirlo solo, sin completar ningún formulario."
    if not conv.get("company"):
        conv["status"] = "awaiting_company"
        return "¿De qué empresa o negocio viene la consulta? Con el nombre alcanza; LUMEN valida el resto."
    conv["status"] = "ready"
    return ""


def _render(listing: Dict[str, Any], conv: Optional[Dict[str, Any]], assistant_message: str, done: bool = False) -> HTMLResponse:
    listing_id = html.escape(str(listing.get("id") or ""))
    title = html.escape(str(listing.get("title") or listing.get("category") or "Oportunidad"))
    conv_id = html.escape(str((conv or {}).get("id") or ""))
    transcript = []
    for msg in (conv or {}).get("messages", []) or []:
        cls = "buyer" if msg.get("role") == "buyer" else "lumen"
        transcript.append(f"<div class='bubble {cls}'>{html.escape(str(msg.get('text') or ''))}</div>")
    if assistant_message:
        transcript.append(f"<div class='bubble lumen'>{html.escape(assistant_message)}</div>")
    if done:
        composer = "<a class='cta' href='/market'>Volver a LUMEN Market</a>"
    else:
        composer = f"""
        <form method='post' action='/market/concierge'>
          <input type='hidden' name='listing_id' value='{listing_id}'>
          <input type='hidden' name='conversation_id' value='{conv_id}'>
          <textarea name='message' maxlength='1800' autofocus required placeholder='Escribile a LUMEN como le escribirías a una persona…'></textarea>
          <button type='submit'>Enviar</button>
        </form>
        """
    return HTMLResponse(f"""<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>LUMEN Concierge</title><style>
:root{{--bg:#061018;--panel:#0d1f2b;--line:#25475d;--text:#eef7fb;--muted:#91a9b8;--lime:#d7ff64}}
*{{box-sizing:border-box}}body{{margin:0;background:#061018;color:var(--text);font-family:Inter,system-ui,-apple-system,sans-serif}}.wrap{{max-width:780px;margin:auto;padding:34px 18px 70px}}.brand{{color:var(--lime);font-weight:950;letter-spacing:.18em}}h1{{font-size:32px;margin:12px 0 6px}}.sub{{color:var(--muted);line-height:1.5}}.chat{{margin-top:24px;background:var(--panel);border:1px solid var(--line);border-radius:20px;padding:18px;min-height:360px}}.bubble{{max-width:88%;padding:12px 14px;border-radius:14px;margin:9px 0;line-height:1.5}}.lumen{{background:#112b39;border:1px solid #285169}}.buyer{{background:#273119;margin-left:auto;border:1px solid #536632}}form{{display:grid;grid-template-columns:1fr auto;gap:9px;margin-top:18px}}textarea{{min-height:62px;resize:vertical;background:#07141d;color:white;border:1px solid #315269;border-radius:12px;padding:12px;font:inherit}}button,.cta{{align-self:end;background:var(--lime);color:#07100a;border:0;border-radius:10px;padding:13px 16px;font-weight:900;text-decoration:none;cursor:pointer}}.fine{{color:var(--muted);font-size:12px;margin-top:12px}}@media(max-width:620px){{form{{grid-template-columns:1fr}}button{{width:100%}}.bubble{{max-width:96%}}}}
</style></head><body><main class='wrap'><div class='brand'>LUMEN CONCIERGE</div><h1>{title}</h1><p class='sub'>Decime lo que necesitás en lenguaje normal. LUMEN extrae los datos útiles, pregunta únicamente lo que falte y lo incorpora al circuito de compradores y proveedores.</p><section class='chat'>{''.join(transcript)}{composer}</section><p class='fine'>No se genera una compra ni un compromiso. Precio, disponibilidad y condiciones se validan antes de avanzar.</p></main></body></html>""")


@router.get("/market/concierge", response_class=HTMLResponse, include_in_schema=False)
def concierge_start(listing_id: str = Query(...)):
    load_state()
    listing = _listing(listing_id)
    if not listing or listing.get("status") != "published":
        raise HTTPException(status_code=404, detail="listing_not_available")
    greeting = "Hola. Contame qué necesitás y LUMEN se ocupa de ordenar el requerimiento. Podés escribir algo tan simple como: ‘necesito 3 unidades para octubre en Buenos Aires’."
    return _render(listing, None, greeting)


@router.post("/market/concierge", response_class=HTMLResponse, include_in_schema=False)
def concierge_message(
    listing_id: str = Form(...),
    message: str = Form(...),
    conversation_id: str = Form(""),
):
    load_state()
    listing = _listing(listing_id)
    if not listing or listing.get("status") != "published":
        raise HTTPException(status_code=404, detail="listing_not_available")

    conv = _conversation(conversation_id) if conversation_id else None
    if not conv:
        conv = _new_conversation(listing)
    _ingest_message(conv, message)
    question = _next_question(conv, listing)

    if question:
        conv.setdefault("messages", []).append({"role": "lumen", "text": question, "ts": utcnow()})
        conv["updated_at"] = utcnow()
        if not save_state():
            raise HTTPException(status_code=503, detail="conversation_persistence_unavailable")
        return _render(listing, conv, "")

    # Reuse the production Market ingestion path so conversational demand enters the same governed pipeline.
    import alert_main

    need = _need(conv)
    response = alert_main.market_inquiry_submit(
        listing_id=str(listing.get("id") or ""),
        company=str(conv.get("company") or ""),
        name=f"Contacto de {conv.get('company') or 'LUMEN Market'}",
        email=str(conv.get("email") or ""),
        need=need,
        phone="",
        quantity=str(conv.get("quantity") or ""),
        deadline="",
        delivery_location=str(conv.get("delivery_location") or ""),
        website="",
    )
    conv["status"] = "converted_to_market_inquiry"
    conv["converted_at"] = utcnow()
    conv.setdefault("messages", []).append({
        "role": "lumen",
        "text": "Listo. Ya entendí la consulta y la incorporé al circuito comercial. LUMEN va a validar comprador, disponibilidad y alternativas antes de avanzar.",
        "ts": utcnow(),
    })
    save_state()
    return _render(listing, conv, "", done=True)
