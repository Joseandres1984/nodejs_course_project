from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from app import STATE, app, load_state, save_state
import landing_public
from service_revenue_runtime import SERVICE_CATALOG


VERSION = "1.1-service-inquiry-public"
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
    # Keep the established public landing intact and add one visible path to the new service catalog.
    marker = '<a href="#contacto">Contacto comercial</a>'
    replacement = '<div><a href="/services">Servicios</a>&nbsp;&nbsp;&nbsp;<a href="#contacto">Contacto comercial</a></div>'
    if marker in landing_public.LANDING_HTML and 'href="/services"' not in landing_public.LANDING_HTML:
        landing_public.LANDING_HTML = landing_public.LANDING_HTML.replace(marker, replacement, 1)


_surface_services_on_landing()


def _page(result: str = "") -> str:
    notice = ""
    if result == "received":
        notice = "<div class='notice'>Consulta recibida. LUMEN la revisará antes de cualquier propuesta o compromiso comercial.</div>"
    cards = []
    for item in SERVICE_CATALOG:
        if item.get("status") != "active":
            continue
        deliverables = "".join(f"<li>{_esc(x)}</li>" for x in item.get("deliverables", []) or [])
        cards.append(f"""
        <article class='card'>
          <div class='tag'>{_esc(item['name'])}</div>
          <h2>{_esc(item['promise'])}</h2>
          <ul>{deliverables}</ul>
          <p class='small'>Los alcances, precio y condiciones finales se confirman caso por caso. No hay compromiso vinculante hasta su aceptación expresa.</p>
          <a class='cta secondary' href='#consulta' data-service='{_esc(item['id'])}'>Consultar</a>
        </article>
        """)
    return f"""<!doctype html>
<html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>LUMEN · Servicios B2B</title>
<meta name='description' content='Servicios LUMEN de sourcing de proveedores y prospección comercial B2B.'>
<style>
:root{{--bg:#061117;--panel:#0b1d25;--line:#23404b;--text:#edf5f7;--muted:#9fb2bb;--accent:#d7ff64}}
*{{box-sizing:border-box}}body{{margin:0;background:linear-gradient(180deg,#061117,#08141b);color:var(--text);font-family:Inter,system-ui,-apple-system,Segoe UI,Arial,sans-serif;line-height:1.55}}a{{color:inherit}}main{{max-width:1100px;margin:auto;padding:28px 22px 70px}}nav{{display:flex;justify-content:space-between;align-items:center;margin-bottom:64px}}.brand{{font-weight:950;letter-spacing:.18em}}nav a{{color:var(--muted);text-decoration:none;font-weight:700}}.hero{{max-width:840px;margin-bottom:42px}}.eyebrow,.tag{{color:var(--accent);font-weight:900;text-transform:uppercase;letter-spacing:.1em;font-size:12px}}h1{{font-size:clamp(42px,7vw,72px);line-height:1.02;letter-spacing:-.04em;margin:12px 0 18px}}.lead{{font-size:19px;color:var(--muted);max-width:760px}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}.card,.formbox{{background:var(--panel);border:1px solid var(--line);border-radius:20px;padding:26px}}.card h2{{font-size:24px;line-height:1.15}}ul{{padding-left:20px;color:#c8d7dd}}li{{margin:8px 0}}.small{{color:var(--muted);font-size:13px}}.cta,button{{display:inline-block;background:var(--accent);color:#071018;text-decoration:none;font-weight:950;padding:13px 18px;border:0;border-radius:11px;cursor:pointer}}.secondary{{margin-top:8px}}.formbox{{margin-top:34px}}label{{display:block;font-weight:800;margin:14px 0 6px}}input,select,textarea{{width:100%;background:#07151b;border:1px solid #294653;color:var(--text);border-radius:10px;padding:12px;font:inherit}}textarea{{min-height:150px;resize:vertical}}.notice{{background:#123321;border:1px solid #34784f;border-radius:12px;padding:12px 14px;margin:0 0 22px}}.hp{{position:absolute;left:-9999px}}.fine{{font-size:12px;color:#718793;margin-top:18px}}@media(max-width:760px){{.grid{{grid-template-columns:1fr}}nav{{margin-bottom:42px}}}}
</style></head><body><main>
<nav><div class='brand'>LUMEN</div><a href='/'>Inicio</a></nav>
{notice}
<section class='hero'><div class='eyebrow'>Servicios comerciales B2B</div><h1>Dos caminos para generar valor antes del cierre.</h1><p class='lead'>LUMEN mantiene su modelo de oportunidades y comisiones, y suma servicios concretos que pueden contratarse por el trabajo de investigación y desarrollo comercial.</p></section>
<section class='grid'>{''.join(cards)}</section>
<section class='formbox' id='consulta'><div class='eyebrow'>Consulta comercial</div><h2>Contanos qué necesitás</h2>
<form method='post' action='/api/services/inquiry'>
<label>Servicio</label><select name='service_id' required>
<option value='SRV-SOURCING-EXPRESS'>LUMEN Sourcing Express</option>
<option value='SRV-B2B-PROSPECTING'>LUMEN Prospección B2B</option>
</select>
<label>Empresa</label><input name='company' maxlength='180' required>
<label>Nombre</label><input name='name' maxlength='120' required>
<label>Email corporativo</label><input type='email' name='email' maxlength='180' required>
<label>Qué necesitás</label><textarea name='need' maxlength='1500' required placeholder='Ej.: necesitamos encontrar proveedores de... / vendemos... y queremos detectar empresas objetivo.'></textarea>
<label class='hp'>Sitio web<input name='website' tabindex='-1' autocomplete='off'></label>
<button type='submit'>Enviar consulta</button>
</form>
<p class='fine'>El envío de este formulario no constituye una contratación, presupuesto ni aceptación de términos. LUMEN verifica la consulta antes de incorporarla al proceso comercial.</p>
</section>
</main></body></html>"""


@app.get("/services", response_class=HTMLResponse, include_in_schema=False)
def services_public(result: str = ""):
    return HTMLResponse(_page(result=result))


@app.post("/api/services/inquiry", include_in_schema=False)
def service_inquiry(
    service_id: str = Form(...),
    company: str = Form(...),
    name: str = Form(...),
    email: str = Form(...),
    need: str = Form(...),
    website: str = Form(""),
):
    # Honeypot: do not persist obvious bot submissions.
    if _clean(website, 200):
        return RedirectResponse("/services?result=received", status_code=303)

    sid = _clean(service_id, 80)
    clean_email = _clean(email, 180).lower()
    clean_company = _clean(company, 180)
    clean_name = _clean(name, 120)
    clean_need = _clean(need, 1500)
    if sid not in ACTIVE_IDS:
        raise HTTPException(status_code=400, detail="service_not_available")
    if not clean_company or not clean_name or len(clean_need) < 12 or not EMAIL_RE.match(clean_email):
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
        "source": "public_service_form",
        "status": "new_unverified",
        "evidence_status": "user_submitted_unverified",
        "binding_commitment": False,
        "created_at": utcnow(),
    }
    rows.append(row)
    STATE["service_inquiries"] = rows[-200:]
    if not save_state():
        raise HTTPException(status_code=503, detail="persistence_failed")
    return RedirectResponse("/services?result=received", status_code=303)


print({"service_revenue_public": {"version": VERSION, "status": "active", "inquiry_capture": True, "landing_link": True, "binding_terms": False}}, flush=True)
