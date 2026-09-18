from __future__ import annotations

import hashlib
import html
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from main import STATE, load_state, save_state

router = APIRouter()
FREE_EMAIL_DOMAINS = {"gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "icloud.com", "live.com", "proton.me", "protonmail.com"}
LANDING_VERSION = "1.2-low-friction"


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _clean(value: Any, limit: int = 800) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _email_domain(email: str) -> str:
    value = _clean(email.lower(), 180)
    if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", value):
        return ""
    return value.rsplit("@", 1)[-1]


def _variant(token: str) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    target = str(token or "").strip().upper()
    for campaign in STATE.get("acquisition_campaigns", []) or []:
        for variant in campaign.get("variants", []) or []:
            if str(variant.get("token") or "").upper() == target:
                return campaign, variant
    return None, None


def _event(event: str, campaign: Optional[Dict[str, Any]], variant: Optional[Dict[str, Any]], **extra: Any) -> None:
    rows = STATE.setdefault("acquisition_events", [])
    rows.append({
        "id": f"AEV-{len(rows)+1:07d}",
        "event": event,
        "campaign_id": (campaign or {}).get("id"),
        "variant_id": (variant or {}).get("id"),
        "audience": (campaign or {}).get("audience"),
        "landing_version": LANDING_VERSION,
        "created_at": utcnow(),
        **extra,
    })
    STATE["acquisition_events"] = rows[-5000:]


def _join_path(audience: str, token: str) -> str:
    if audience not in {"buyer", "supplier", "partner"}:
        audience = "buyer"
    return f"/join/{audience}?c={urllib.parse.quote(token)}"


@router.get("/c/{token}", include_in_schema=False)
def acquisition_redirect(token: str, request: Request):
    load_state()
    campaign, variant = _variant(token)
    if not campaign or not variant or campaign.get("status") != "active":
        raise HTTPException(status_code=404, detail="campaign_not_available")
    ref_host = ""
    try:
        ref_host = urllib.parse.urlparse(str(request.headers.get("referer") or "")).hostname or ""
    except Exception:
        pass
    _event("click", campaign, variant, referrer_host=ref_host[:180])
    save_state()
    return RedirectResponse(_join_path(str(campaign.get("audience") or "buyer"), str(variant.get("token") or "")), status_code=302)


def _landing_copy(audience: str) -> tuple[str, str, str, str, str]:
    if audience == "supplier":
        return (
            "Sumate a la red de proveedores de LUMEN",
            "Contanos qué vende tu empresa. LUMEN investiga oportunidades compatibles y organiza conversaciones comerciales cuando existe encaje real.",
            "Quiero recibir oportunidades",
            "¿Qué productos o servicios ofrecés?",
            "Ej.: válvulas industriales, instrumentación, mantenimiento eléctrico, logística...",
        )
    if audience == "partner":
        return (
            "Convertí tu catálogo en un canal de oportunidades atribuibles",
            "Tu tienda sigue cobrando y entregando. LUMEN puede originar compradores y trabajar con comisión o success fee únicamente bajo un acuerdo comercial válido.",
            "Quiero ser partner",
            "¿Qué vendés y qué tipo de partnership te interesa?",
            "Ej.: tenemos catálogo online de herramientas y buscamos ventas B2B a comisión...",
        )
    return (
        "Contanos qué necesitás. LUMEN busca alternativas por vos.",
        "Partimos de una necesidad real, investigamos proveedores y organizamos la comparación. Para empezar alcanza con tu contacto y una descripción breve.",
        "Buscar alternativas",
        "¿Qué necesitás comprar?",
        "Ej.: 20 sensores de nivel, entrega en Buenos Aires, alternativa equivalente aceptada...",
    )


def _render_form(audience: str, token: str, done: bool = False, error: str = "") -> HTMLResponse:
    title, lead, cta, details_label, placeholder = _landing_copy(audience)
    if done:
        body = "<div class='ok'><b>Listo.</b><br>La información ya entró al circuito comercial de LUMEN. La vamos a validar antes de cualquier contacto o compromiso.</div>"
    else:
        body = f"""
        {f"<div class='err'>{html.escape(error)}</div>" if error else ""}
        <div class='fast'><b>Solo 2 datos para empezar.</b><span> Podés completar el resto después.</span></div>
        <form method='post' action='/join/{html.escape(audience)}'>
          <input type='hidden' name='c' value='{html.escape(token)}'>
          <input class='hp' name='website_check' autocomplete='off' tabindex='-1'>
          <label>Email de contacto<input name='email' type='email' maxlength='180' autocomplete='email' placeholder='tu@email.com' required></label>
          <label>{html.escape(details_label)}<textarea name='details' maxlength='1800' placeholder='{html.escape(placeholder)}' required></textarea></label>
          <details>
            <summary>Agregar datos de empresa <span>(opcional)</span></summary>
            <div class='optional'>
              <label>Empresa o negocio<input name='company' maxlength='160' autocomplete='organization'></label>
              <label>Sitio web<input name='website' maxlength='300' inputmode='url' placeholder='https://...'></label>
              <label>Categoría<input name='category' maxlength='160' placeholder='Ej.: electricidad industrial'></label>
            </div>
          </details>
          <button type='submit'>{html.escape(cta)}</button>
        </form>
        """
    return HTMLResponse(f"""<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>LUMEN · {html.escape(title)}</title><meta name='description' content='Contacto comercial B2B con LUMEN.'><style>
    :root{{--bg:#061018;--panel:#0c1d27;--line:#285166;--text:#edf7fb;--muted:#91a9b8;--lime:#d7ff64;--blue:#8bd8ff}}*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 10% 0,#12334a 0,#061018 38%);color:var(--text);font-family:Inter,system-ui,-apple-system,sans-serif}}.wrap{{max-width:700px;margin:auto;padding:38px 20px 72px}}.brand{{font-weight:950;letter-spacing:.18em;color:var(--lime)}}h1{{font-size:clamp(35px,7vw,58px);line-height:1.03;margin:14px 0}}.lead{{font-size:18px;color:var(--muted);line-height:1.55;max-width:640px}}.box{{margin-top:24px;border:1px solid var(--line);border-radius:20px;background:linear-gradient(180deg,#0d202b,#08151d);padding:22px}}.fast{{padding:11px 13px;border:1px solid #31576d;background:#0b2532;border-radius:11px;color:#dff5ff}}.fast span{{color:var(--muted)}}label{{display:block;font-weight:850;margin:14px 0}}label span,summary span{{font-weight:500;color:var(--muted)}}input,textarea{{display:block;width:100%;margin-top:7px;padding:13px;border:1px solid #31576d;border-radius:11px;background:#06131b;color:#fff;font:inherit;outline:none}}input:focus,textarea:focus{{border-color:var(--blue);box-shadow:0 0 0 3px #8bd8ff18}}textarea{{min-height:125px;resize:vertical}}details{{margin:8px 0 18px;border-top:1px solid #183748;padding-top:14px}}summary{{cursor:pointer;color:#b8cad4;font-weight:800}}.optional{{padding-top:1px}}button{{width:100%;background:var(--lime);color:#061008;border:0;border-radius:11px;padding:14px 17px;font-weight:950;font-size:16px;cursor:pointer}}button:hover{{filter:brightness(1.03)}}.fine{{color:#7893a2;font-size:12px;line-height:1.5;margin-top:14px}}.ok,.err{{padding:15px;border-radius:12px;line-height:1.5}}.ok{{background:#123321;border:1px solid #34784f}}.err{{background:#3a1818;border:1px solid #7c3b3b}}.hp{{position:absolute;left:-10000px;width:1px;height:1px}}@media(max-width:540px){{.wrap{{padding:28px 16px 58px}}.box{{padding:18px}}}}
    </style></head><body><main class='wrap'><div class='brand'>LUMEN</div><h1>{html.escape(title)}</h1><p class='lead'>{html.escape(lead)}</p><section class='box'>{body}</section><p class='fine'>LUMEN no genera compras, contratos ni pagos desde este formulario. La información se usa para investigación comercial y validación de encaje.</p></main></body></html>""")


@router.get("/join/{audience}", response_class=HTMLResponse, include_in_schema=False)
def acquisition_landing(audience: str, c: str = Query("")):
    if audience not in {"buyer", "supplier", "partner"}:
        raise HTTPException(status_code=404, detail="audience_not_available")
    load_state()
    campaign, variant = _variant(c) if c else (None, None)
    _event("landing_view", campaign, variant, audience=audience)
    save_state()
    return _render_form(audience, c)


@router.post("/join/{audience}", response_class=HTMLResponse, include_in_schema=False)
def acquisition_submit(
    audience: str,
    c: str = Form(""),
    email: str = Form(...),
    details: str = Form(...),
    company: str = Form(""),
    website: str = Form(""),
    category: str = Form(""),
    website_check: str = Form(""),
):
    if audience not in {"buyer", "supplier", "partner"}:
        raise HTTPException(status_code=404, detail="audience_not_available")
    load_state()
    campaign, variant = _variant(c) if c else (None, None)
    if website_check.strip():
        return _render_form(audience, c, done=True)

    email = _clean(email.lower(), 180)
    details = _clean(details, 1800)
    company = _clean(company, 160)
    website = _clean(website, 300)
    category = _clean(category, 160)
    domain = _email_domain(email)
    if not details or not domain:
        return _render_form(audience, c, error="Completá un email válido y una descripción breve.")

    company_display = company or (domain if domain not in FREE_EMAIL_DOMAINS else "Contacto entrante")
    fingerprint = hashlib.sha1(f"{audience}|{email}|{details.lower()}".encode("utf-8")).hexdigest()[:20]
    rows = STATE.setdefault("acquisition_leads", [])
    if any(x.get("fingerprint") == fingerprint for x in rows):
        return _render_form(audience, c, done=True)
    lid = f"ACLEAD-{len(rows)+1:06d}"
    row = {
        "id": lid,
        "fingerprint": fingerprint,
        "audience": audience,
        "company": company_display,
        "company_supplied": bool(company),
        "email": email,
        "email_domain": domain,
        "website": website,
        "category": category,
        "details": details,
        "campaign_id": (campaign or {}).get("id"),
        "variant_id": (variant or {}).get("id"),
        "source": "lumen_acquisition_campaign",
        "landing_version": LANDING_VERSION,
        "status": "new",
        "created_at": utcnow(),
    }
    rows.append(row)
    STATE["acquisition_leads"] = rows[-2000:]

    source_url = website.strip()
    if source_url and not source_url.startswith(("http://", "https://")):
        source_url = "https://" + source_url
    if not source_url and domain not in FREE_EMAIL_DOMAINS:
        source_url = "https://" + domain + "/"
    if source_url:
        leads = STATE.setdefault("research_leads", [])
        rlid = f"LEAD-{len(leads)+1:05d}"
        lead_type = "buyer" if audience == "buyer" else "supplier"
        leads.append({
            "id": rlid,
            "type": lead_type,
            "category": category or ("general B2B" if audience != "partner" else "tienda partner"),
            "title": company_display,
            "url": source_url,
            "snippet": f"Lead entrante de campaña LUMEN ({audience}). {details[:700]}",
            "status": "research_required",
            "confidence": 0.82 if audience == "buyer" else 0.75,
            "verified_company": False,
            "verified_contact": False,
            "acquisition_campaign_id": (campaign or {}).get("id"),
            "acquisition_variant_id": (variant or {}).get("id"),
            "acquisition_lead_id": lid,
            "direct_inbound_demand": audience == "buyer",
            "demand_signal": audience == "buyer",
        })
        row["research_lead_id"] = rlid
    _event("lead", campaign, variant, acquisition_lead_id=lid, audience=audience)
    STATE.setdefault("activity", []).insert(0, {"ts": utcnow(), "msg": f"Growth: nueva captación {audience} de {company_display}."})
    STATE["activity"] = STATE["activity"][:100]
    if not save_state():
        raise HTTPException(status_code=503, detail="lead_received_but_persistence_unavailable")
    return _render_form(audience, c, done=True)


@router.post("/track/market-view", include_in_schema=False)
def track_market_view(request: Request):
    load_state()
    ref_host = ""
    try:
        ref_host = urllib.parse.urlparse(str(request.headers.get("referer") or "")).hostname or ""
    except Exception:
        pass
    rows = STATE.setdefault("market_reach_events", [])
    rows.append({"event": "market_page_view", "created_at": utcnow(), "referrer_host": ref_host[:180]})
    STATE["market_reach_events"] = rows[-5000:]
    save_state()
    return Response(status_code=204)


@router.post("/track/market-click", include_in_schema=False)
def track_market_click(listing_id: str = Query("")):
    load_state()
    rows = STATE.setdefault("market_reach_events", [])
    rows.append({"event": "listing_cta_click", "listing_id": _clean(listing_id, 120), "created_at": utcnow()})
    STATE["market_reach_events"] = rows[-5000:]
    save_state()
    return Response(status_code=204)


print({"acquisition_routes": {"version": LANDING_VERSION, "status": "active", "required_fields": ["email", "details"], "optional_fields": ["company", "website", "category"]}}, flush=True)
