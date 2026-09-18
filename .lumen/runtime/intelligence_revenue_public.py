from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from app import STATE, app, load_state, save_state
import commercial_offer_engine_runtime as offer_engine
import landing_public
from intelligence_revenue_runtime import INTELLIGENCE_CATALOG, INTELLIGENCE_IDS


VERSION = "1.1-intelligence-launch-pricing"
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _clean(value: Any, limit: int) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _id(email: str, service_id: str, need: str) -> str:
    seed = f"{email.lower()}|{service_id}|{need}|{utcnow()}"
    return "INQ-INT-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12].upper()


def _surface_intelligence() -> None:
    if 'href="/intelligence"' in landing_public.LANDING_HTML:
        return
    service_link = '<a href="/services">Servicios</a>'
    if service_link in landing_public.LANDING_HTML:
        landing_public.LANDING_HTML = landing_public.LANDING_HTML.replace(
            service_link,
            '<a href="/services">Servicios</a>&nbsp;&nbsp;&nbsp;<a href="/intelligence">Intelligence</a>',
            1,
        )


_surface_intelligence()


def _page(result: str = "", selected: str = "") -> str:
    notice = ""
    if result == "received":
        notice = "<div class='notice'>Consulta recibida. LUMEN seleccionó un paquete orientativo y dejó el caso registrado para verificación. No se realizó ningún cargo y el precio final se confirma antes de contratar.</div>"

    cards = []
    for item in INTELLIGENCE_CATALOG:
        deliverables = "".join(f"<li>{_esc(x)}</li>" for x in item.get("deliverables", []) or [])
        cards.append(f"""
        <article class='card'>
          <div class='tag'>Producto de inteligencia</div>
          <h2>{_esc(item['name'])}</h2>
          <div class='price'>{_esc(offer_engine.public_price_label(str(item['id'])))} <span>· lanzamiento</span></div>
          <p>{_esc(item['promise'])}</p>
          <ul>{deliverables}</ul>
          <p class='small'>El motor ajusta el paquete según mercados, cantidad de alternativas, recurrencia, urgencia y complejidad técnica. Nunca aplica descuentos autónomos ni crea cobros.</p>
          <a class='cta secondary product-choice' href='#consulta' data-service='{_esc(item['id'])}'>Quiero analizar un caso</a>
        </article>
        """)

    options = []
    for item in INTELLIGENCE_CATALOG:
        is_selected = " selected" if str(item["id"]) == selected else ""
        options.append(f"<option value='{_esc(item['id'])}'{is_selected}>{_esc(item['name'])} · {_esc(offer_engine.public_price_label(str(item['id'])))}</option>")

    return f"""<!doctype html>
<html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>LUMEN Intelligence · Decisiones comerciales con evidencia</title>
<meta name='description' content='QuoteCheck, SupplierCheck, Export Scout y Tender Hunter con precios de lanzamiento claros y alcance gobernado.'>
<style>
:root{{--bg:#061117;--panel:#0b1d25;--line:#23404b;--text:#edf5f7;--muted:#9fb2bb;--accent:#d7ff64;--blue:#73d8ff}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 80% 0,#102731 0,#061117 45%,#061117 100%);color:var(--text);font-family:Inter,system-ui,-apple-system,Segoe UI,Arial,sans-serif;line-height:1.55}}a{{color:inherit}}main{{max-width:1180px;margin:auto;padding:28px 22px 72px}}nav{{display:flex;justify-content:space-between;gap:18px;align-items:center;margin-bottom:62px}}.brand{{font-weight:950;letter-spacing:.18em}}nav .links{{display:flex;gap:18px}}nav a{{color:var(--muted);text-decoration:none;font-weight:800}}.hero{{max-width:920px;margin-bottom:42px}}.eyebrow,.tag{{color:var(--accent);font-weight:950;text-transform:uppercase;letter-spacing:.11em;font-size:12px}}h1{{font-size:clamp(44px,7.6vw,78px);line-height:.98;letter-spacing:-.05em;margin:12px 0 18px}}.lead{{font-size:20px;color:var(--muted);max-width:850px}}.proof{{display:flex;gap:9px;flex-wrap:wrap;margin-top:22px}}.pill{{border:1px solid var(--line);border-radius:999px;padding:7px 11px;color:#c6d7de;background:#091920}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}.card,.formbox{{background:rgba(11,29,37,.94);border:1px solid var(--line);border-radius:20px;padding:26px}}.card h2{{font-size:27px;line-height:1.1;margin:8px 0}}.card p,.small{{color:var(--muted)}}.price{{font-size:24px;font-weight:950;color:var(--accent);margin:8px 0 12px}}.price span{{font-size:12px;color:var(--muted);font-weight:800;text-transform:uppercase;letter-spacing:.08em}}ul{{padding-left:20px;color:#cad8de}}li{{margin:8px 0}}.cta,button{{display:inline-block;background:var(--accent);color:#071018;text-decoration:none;font-weight:950;padding:13px 18px;border:0;border-radius:11px;cursor:pointer}}.secondary{{margin-top:8px}}.formbox{{margin-top:34px}}.cols{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}label{{display:block;font-weight:850;margin:14px 0 6px}}input,select,textarea{{width:100%;background:#07151b;border:1px solid #294653;color:var(--text);border-radius:10px;padding:12px;font:inherit}}textarea{{min-height:145px;resize:vertical}}details{{margin:14px 0;border-top:1px solid #1c3742;padding-top:12px}}summary{{cursor:pointer;color:var(--blue);font-weight:850}}.notice{{background:#123321;border:1px solid #34784f;border-radius:12px;padding:12px 14px;margin:0 0 22px}}.hp{{position:absolute;left:-9999px}}.fine{{font-size:12px;color:#718793;margin-top:18px}}@media(max-width:780px){{.grid,.cols{{grid-template-columns:1fr}}nav{{margin-bottom:42px}}}}
</style></head><body><main>
<nav><div class='brand'>LUMEN INTELLIGENCE</div><div class='links'><a href='/'>Inicio</a><a href='/services'>Servicios</a></div></nav>
{notice}
<section class='hero'>
<div class='eyebrow'>Nueva rama de ingresos · alcance global</div>
<h1>Convertimos información comercial en decisiones accionables.</h1>
<p class='lead'>Analizamos cotizaciones, proveedores, mercados de exportación y oportunidades públicas. LUMEN elige automáticamente el paquete orientativo según complejidad, manteniendo alcance, evidencia y precio bajo reglas explícitas.</p>
<div class='proof'><span class='pill'>Desde USD 59</span><span class='pill'>Multimoneda</span><span class='pill'>Sin compra automática</span><span class='pill'>Sin descuentos autónomos</span><span class='pill'>Precio final confirmado antes de contratar</span></div>
</section>
<section class='grid'>{''.join(cards)}</section>
<section class='formbox' id='consulta'>
<div class='eyebrow'>Diagnóstico inicial</div><h2>Contanos el problema comercial</h2>
<p class='small'>Sólo necesitamos un email y una descripción. Los datos adicionales ayudan a que el motor seleccione mejor el paquete.</p>
<form method='post' action='/api/intelligence/inquiry'>
<label>Producto LUMEN</label><select id='service_id' name='service_id' required>{''.join(options)}</select>
<label>Email de contacto</label><input type='email' name='email' maxlength='180' required autocomplete='email'>
<label>Qué querés resolver</label><textarea name='need' maxlength='1800' required placeholder='Ej.: recibí una cotización y quiero saber si tiene sentido / quiero validar un proveedor / quiero encontrar importadores / quiero detectar licitaciones compatibles.'></textarea>
<details open><summary>Datos del caso (opcionales)</summary>
<div class='cols'>
<div><label>Empresa</label><input name='company' maxlength='180' autocomplete='organization'></div>
<div><label>Nombre</label><input name='name' maxlength='120' autocomplete='name'></div>
<div><label>País o mercado</label><input name='country' maxlength='120' placeholder='Argentina, Chile, Estados Unidos...'></div>
<div><label>Producto / categoría</label><input name='product' maxlength='300'></div>
<div><label>Cantidad</label><input name='quantity' maxlength='120'></div>
<div><label>Proveedor a revisar</label><input name='supplier_name' maxlength='180'></div>
<div><label>Importe cotizado</label><input name='quote_amount' maxlength='120' inputmode='decimal'></div>
<div><label>Moneda</label><select name='quote_currency'><option value=''>Sin indicar</option><option>ARS</option><option>USD</option><option>EUR</option><option>BRL</option><option>CLP</option><option>MXN</option><option>COP</option><option>GBP</option><option>OTHER</option></select></div>
</div></details>
<label class='hp'>Sitio web<input name='website' tabindex='-1' autocomplete='off'></label>
<button type='submit'>Preparar caso y paquete orientativo</button>
</form>
<p class='fine'>Los precios publicados son de lanzamiento para alcances definidos. El envío no crea una contratación ni un cobro. Las referencias y oportunidades sólo se reportan cuando existe evidencia suficiente. Conversión a moneda local, precio final, contrato, pago, compra y participación vinculante requieren confirmación humana.</p>
</section>
<script>(function(){{var s=document.getElementById('service_id');document.querySelectorAll('.product-choice').forEach(function(el){{el.addEventListener('click',function(){{if(s)s.value=el.getAttribute('data-service')||s.value;}});}});}})();</script>
</main></body></html>"""


@app.get("/intelligence", response_class=HTMLResponse, include_in_schema=False)
def intelligence_public(result: str = "", product: str = ""):
    selected = product if product in INTELLIGENCE_IDS else ""
    return HTMLResponse(_page(result=result, selected=selected))


@app.post("/api/intelligence/inquiry", include_in_schema=False)
def intelligence_inquiry(
    service_id: str = Form(...),
    email: str = Form(...),
    need: str = Form(...),
    company: str = Form(""),
    name: str = Form(""),
    country: str = Form(""),
    product: str = Form(""),
    quantity: str = Form(""),
    quote_amount: str = Form(""),
    quote_currency: str = Form(""),
    supplier_name: str = Form(""),
    website: str = Form(""),
):
    if _clean(website, 200):
        return RedirectResponse("/intelligence?result=received", status_code=303)

    sid = _clean(service_id, 80)
    clean_email = _clean(email, 180).lower()
    clean_need = _clean(need, 1800)
    if sid not in INTELLIGENCE_IDS:
        raise HTTPException(status_code=400, detail="intelligence_product_not_available")
    if not EMAIL_RE.match(clean_email) or len(clean_need) < 12:
        raise HTTPException(status_code=400, detail="invalid_intelligence_inquiry")
    if not load_state():
        raise HTTPException(status_code=503, detail="state_unavailable")

    row: Dict[str, Any] = {
        "id": _id(clean_email, sid, clean_need),
        "service_id": sid,
        "company": _clean(company, 180),
        "name": _clean(name, 120),
        "email": clean_email,
        "need": clean_need,
        "source": "public_intelligence_form_low_friction",
        "status": "new_unverified",
        "evidence_status": "user_submitted_unverified",
        "intelligence_payload": {
            "country": _clean(country, 120),
            "product": _clean(product, 300),
            "quantity": _clean(quantity, 120),
            "quote_amount": _clean(quote_amount, 120),
            "quote_currency": _clean(quote_currency, 20).upper(),
            "supplier_name": _clean(supplier_name, 180),
        },
        "binding_commitment": False,
        "payment_created": False,
        "created_at": utcnow(),
    }
    row["recommended_offer"] = offer_engine.recommend_offer(sid, row, STATE)
    row["price_status"] = "recommended_nonbinding_human_confirmation_required"
    rows = [x for x in STATE.setdefault("service_inquiries", []) if isinstance(x, dict)]
    rows.append(row)
    STATE["service_inquiries"] = rows[-300:]
    offer_engine.offer_engine_tick(STATE)
    if not save_state():
        raise HTTPException(status_code=503, detail="persistence_failed")
    return RedirectResponse("/intelligence?result=received", status_code=303)


@app.get("/api/intelligence/status", include_in_schema=False)
def intelligence_status():
    if not load_state():
        raise HTTPException(status_code=503, detail="state_unavailable")
    report = dict(STATE.get("intelligence_revenue_runtime", {}) or {})
    return {
        "status": report.get("status") or "initializing",
        "version": report.get("version") or VERSION,
        "products": [
            {"id": x["id"], "name": x["name"], "status": x["status"], "promise": x["promise"], "public_from_usd": offer_engine.public_from_usd(x["id"])}
            for x in INTELLIGENCE_CATALOG
        ],
        "public_inquiries": report.get("public_inquiries", 0),
        "verified_product_fit_candidates": report.get("verified_product_fit_candidates", 0),
        "outbound_attention_active": report.get("outbound_attention_active", 0),
        "real_contacted": report.get("real_contacted", 0),
        "replies": report.get("replies", 0),
        "realized_intelligence_revenue_usd": report.get("realized_intelligence_revenue_usd", 0.0),
        "offer_engine": dict(STATE.get("commercial_offer_engine", {}) or {}),
        "searches_used": report.get("searches_used", 0),
        "paid_spend": False,
    }


print({
    "intelligence_revenue_public": {
        "version": VERSION,
        "status": "active",
        "products": len(INTELLIGENCE_CATALOG),
        "public_launch_pricing": True,
        "offer_engine": offer_engine.VERSION,
        "required_fields": ["service_id", "email", "need"],
        "multicurrency_capture": True,
        "payment_created": False,
        "binding_terms": False,
    }
}, flush=True)
