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
from service_revenue_runtime import SERVICE_CATALOG


VERSION = "1.4-public-launch-pricing"
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
ACTIVE_IDS = {str(x["id"]) for x in SERVICE_CATALOG if x.get("status") == "active"}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _clean(value: Any, limit: int) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _inquiry_id(email: str, service_id: str, need: str) -> str:
    seed = f"{email.lower()}|{service_id}|{need}|{utcnow()}"
    return "INQ-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12].upper()


def _surface_services_on_landing() -> None:
    marker = '<a href="#contacto">Contacto comercial</a>'
    replacement = '<div><a href="/services">Servicios</a>&nbsp;&nbsp;&nbsp;<a href="/intelligence">Intelligence</a>&nbsp;&nbsp;&nbsp;<a href="#contacto">Contacto comercial</a></div>'
    if marker in landing_public.LANDING_HTML and 'href="/services"' not in landing_public.LANDING_HTML:
        landing_public.LANDING_HTML = landing_public.LANDING_HTML.replace(marker, replacement, 1)


_surface_services_on_landing()


def _page(result: str = "") -> str:
    notice = ""
    if result == "received":
        notice = "<div class='notice'>Consulta recibida. LUMEN ya dejó preparado un paquete orientativo según el caso. El precio y alcance final se confirman antes de contratar y no se realizó ningún cargo.</div>"

    active = [x for x in SERVICE_CATALOG if x.get("status") == "active"]
    cards = []
    for item in active:
        deliverables = "".join(f"<li>{_esc(x)}</li>" for x in item.get("deliverables", []) or [])
        intelligence = str(item.get("id") or "") in {"SRV-QUOTECHECK", "SRV-SUPPLIERCHECK", "SRV-EXPORT-SCOUT", "SRV-TENDER-HUNTER"}
        label = "LUMEN Intelligence" if intelligence else "Servicio comercial"
        price = offer_engine.public_price_label(str(item.get("id") or ""))
        cards.append(f"""
        <article class='card'>
          <div class='tag'>{_esc(label)}</div>
          <h2>{_esc(item['name'])}</h2>
          <div class='price'>{_esc(price)} <span>· lanzamiento</span></div>
          <p class='promise'>{_esc(item['promise'])}</p>
          <ul>{deliverables}</ul>
          <p class='small'>El precio publicado corresponde al paquete inicial de alcance acotado. Si el caso requiere más mercados, proveedores, segmentos o profundidad, LUMEN recomienda automáticamente un paquete superior antes de cualquier contratación.</p>
          <a class='cta secondary service-choice' href='#consulta' data-service='{_esc(item['id'])}'>Consultar</a>
        </article>
        """)
    options = "".join(f"<option value='{_esc(x['id'])}'>{_esc(x['name'])} · {_esc(offer_engine.public_price_label(str(x['id'])))}</option>" for x in active)

    return f"""<!doctype html>
<html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>LUMEN · Servicios e Intelligence</title>
<meta name='description' content='Servicios LUMEN de sourcing, prospección e inteligencia comercial global con precios de lanzamiento transparentes.'>
<style>
:root{{--bg:#061117;--panel:#0b1d25;--line:#23404b;--text:#edf5f7;--muted:#9fb2bb;--accent:#d7ff64}}
*{{box-sizing:border-box}}body{{margin:0;background:linear-gradient(180deg,#061117,#08141b);color:var(--text);font-family:Inter,system-ui,-apple-system,Segoe UI,Arial,sans-serif;line-height:1.55}}a{{color:inherit}}main{{max-width:1160px;margin:auto;padding:28px 22px 70px}}nav{{display:flex;justify-content:space-between;align-items:center;margin-bottom:64px}}.navlinks{{display:flex;gap:18px}}.brand{{font-weight:950;letter-spacing:.18em}}nav a{{color:var(--muted);text-decoration:none;font-weight:700}}.hero{{max-width:900px;margin-bottom:42px}}.eyebrow,.tag{{color:var(--accent);font-weight:900;text-transform:uppercase;letter-spacing:.1em;font-size:12px}}h1{{font-size:clamp(42px,7vw,72px);line-height:1.02;letter-spacing:-.04em;margin:12px 0 18px}}.lead{{font-size:19px;color:var(--muted);max-width:820px}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}.card,.formbox{{background:var(--panel);border:1px solid var(--line);border-radius:20px;padding:26px}}.card h2{{font-size:25px;line-height:1.15;margin:8px 0}}.promise{{color:#dce9ed}}.price{{font-size:24px;font-weight:950;color:var(--accent);margin:8px 0 12px}}.price span{{font-size:12px;color:var(--muted);font-weight:800;text-transform:uppercase;letter-spacing:.08em}}ul{{padding-left:20px;color:#c8d7dd}}li{{margin:8px 0}}.small{{color:var(--muted);font-size:13px}}.cta,button{{display:inline-block;background:var(--accent);color:#071018;text-decoration:none;font-weight:950;padding:13px 18px;border:0;border-radius:11px;cursor:pointer}}.secondary{{margin-top:8px}}.formbox{{margin-top:34px}}label{{display:block;font-weight:800;margin:14px 0 6px}}input,select,textarea{{width:100%;background:#07151b;border:1px solid #294653;color:var(--text);border-radius:10px;padding:12px;font:inherit}}textarea{{min-height:150px;resize:vertical}}details{{margin:14px 0;border-top:1px solid #1c3742;padding-top:12px}}summary{{cursor:pointer;color:var(--muted);font-weight:800}}.notice{{background:#123321;border:1px solid #34784f;border-radius:12px;padding:12px 14px;margin:0 0 22px}}.hp{{position:absolute;left:-9999px}}.fine{{font-size:12px;color:#718793;margin-top:18px}}@media(max-width:760px){{.grid{{grid-template-columns:1fr}}nav{{margin-bottom:42px}}}}
</style></head><body><main>
<nav><div class='brand'>LUMEN</div><div class='navlinks'><a href='/'>Inicio</a><a href='/intelligence'>Intelligence</a></div></nav>
{notice}
<section class='hero'><div class='eyebrow'>Servicios e inteligencia comercial</div><h1>Productos concretos. Precios de entrada claros. Alcance controlado.</h1><p class='lead'>LUMEN combina sourcing, prospección e inteligencia comercial para monetizar investigación, comparación, verificación y detección de oportunidades. El motor selecciona el paquete adecuado por complejidad, pero no puede aceptar contratos, cobrar ni aplicar descuentos por sí solo.</p></section>
<section class='grid'>{''.join(cards)}</section>
<section class='formbox' id='consulta'><div class='eyebrow'>Consulta comercial</div><h2>Contanos qué necesitás</h2>
<p class='small'>Con un email y una descripción breve alcanza. LUMEN recomienda un paquete orientativo automáticamente y la propuesta final se confirma antes de contratar.</p>
<form method='post' action='/api/services/inquiry'>
<label>Servicio</label><select id='service_id' name='service_id' required>{options}</select>
<label>Email de contacto</label><input type='email' name='email' maxlength='180' required autocomplete='email'>
<label>Qué necesitás</label><textarea name='need' maxlength='1500' required placeholder='Ej.: encontrar proveedores / revisar una cotización / verificar un proveedor / detectar compradores o licitaciones.'></textarea>
<details><summary>Agregar empresa y nombre (opcional)</summary>
<label>Empresa <span class='small'>(opcional)</span></label><input name='company' maxlength='180' autocomplete='organization'>
<label>Nombre <span class='small'>(opcional)</span></label><input name='name' maxlength='120' autocomplete='name'>
</details>
<label class='hp'>Sitio web<input name='website' tabindex='-1' autocomplete='off'></label>
<button type='submit'>Preparar mi caso</button>
</form>
<p class='fine'>Los importes publicados son precios de lanzamiento para alcances definidos y se expresan en USD. Una moneda local sólo se cotiza con una fuente de cambio verificada y confirmación humana. El envío no constituye contratación, presupuesto final, cobro ni aceptación de términos.</p>
</section>
<script>
(function(){{
  var select=document.getElementById('service_id');
  document.querySelectorAll('.service-choice').forEach(function(el){{
    el.addEventListener('click',function(){{ if(select) select.value=el.getAttribute('data-service')||select.value; }});
  }});
}})();
</script>
</main></body></html>"""


@app.get("/services", response_class=HTMLResponse, include_in_schema=False)
def services_public(result: str = ""):
    return HTMLResponse(_page(result=result))


@app.post("/api/services/inquiry", include_in_schema=False)
def service_inquiry(
    service_id: str = Form(...),
    email: str = Form(...),
    need: str = Form(...),
    company: str = Form(""),
    name: str = Form(""),
    website: str = Form(""),
):
    if _clean(website, 200):
        return RedirectResponse("/services?result=received", status_code=303)

    sid = _clean(service_id, 80)
    clean_email = _clean(email, 180).lower()
    clean_company = _clean(company, 180)
    clean_name = _clean(name, 120)
    clean_need = _clean(need, 1500)
    if sid not in ACTIVE_IDS:
        raise HTTPException(status_code=400, detail="service_not_available")
    if len(clean_need) < 12 or not EMAIL_RE.match(clean_email):
        raise HTTPException(status_code=400, detail="invalid_inquiry")
    if not load_state():
        raise HTTPException(status_code=503, detail="state_unavailable")

    rows = STATE.setdefault("service_inquiries", [])
    row: Dict[str, Any] = {
        "id": _inquiry_id(clean_email, sid, clean_need),
        "service_id": sid,
        "company": clean_company,
        "name": clean_name,
        "email": clean_email,
        "need": clean_need,
        "source": "public_service_form_low_friction",
        "status": "new_unverified",
        "evidence_status": "user_submitted_unverified",
        "binding_commitment": False,
        "payment_created": False,
        "created_at": utcnow(),
    }
    row["recommended_offer"] = offer_engine.recommend_offer(sid, row, STATE)
    row["price_status"] = "recommended_nonbinding_human_confirmation_required"
    rows.append(row)
    STATE["service_inquiries"] = rows[-300:]
    offer_engine.offer_engine_tick(STATE)
    if not save_state():
        raise HTTPException(status_code=503, detail="persistence_failed")
    return RedirectResponse("/services?result=received", status_code=303)


@app.get("/api/services/pricing", include_in_schema=False)
def service_pricing_status():
    load_state()
    return {
        "version": offer_engine.VERSION,
        "pricing_mode": offer_engine.PRICING_MODE,
        "currency": offer_engine.CANONICAL_CURRENCY,
        "services": [
            {
                "service_id": sid,
                "name": item.get("name"),
                "billing": item.get("billing"),
                "public_from_usd": item.get("public_from_usd"),
                "tiers": [
                    {"id": tier.get("id"), "label": tier.get("label"), "price_usd": tier.get("price_usd"), "scope": tier.get("scope")}
                    for tier in item.get("tiers", [])
                ],
            }
            for sid, item in offer_engine.PRICEBOOK.items()
        ],
        "engine": dict(STATE.get("commercial_offer_engine", {}) or {}),
        "autonomous_discount_allowed": False,
        "payment_created": False,
        "binding": False,
    }


print({"service_revenue_public": {"version": VERSION, "status": "active", "active_catalog_entries": len(ACTIVE_IDS), "inquiry_capture": True, "public_launch_pricing": True, "offer_engine": offer_engine.VERSION, "required_fields": ["email", "need"], "optional_fields": ["company", "name"], "landing_link": True, "intelligence_link": True, "binding_terms": False}}, flush=True)
