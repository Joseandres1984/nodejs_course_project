from __future__ import annotations

import hashlib
import html
import os
import re
import urllib.parse

from fastapi import Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app import auth
from executive_alerts import _task_signature, executive_alert_tick, resolve_executive_alert
from main import STATE, load_state, save_state
from mp_main import app


PUBLIC_CONTACT = os.getenv("LUMEN_PUBLIC_CONTACT_EMAIL", "Lumenstock2026@gmail.com").strip()
FREE_EMAIL_DOMAINS = {
    "gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "icloud.com", "live.com",
    "proton.me", "protonmail.com", "aol.com",
}

ACTION_UI = r'''
<style id="lumen-alert-actions-style">
.alertactions-live{display:flex;gap:7px;flex-wrap:wrap;margin-top:10px}
.alertactions-live form{display:inline;margin:0}
.alertactions-live button{border-radius:8px;padding:9px 13px;font-weight:900;cursor:pointer}
.alertactions-live .apply{background:#d7ff64;color:#0a1008;border:0}
.alertactions-live .snooze{background:#172631;color:#bdd3df;border:1px solid #345164}
.alertactions-live .recheck{background:#173141;color:#bfe7fa;border:1px solid #2b5770}
.lumen-market-link{position:fixed;right:18px;bottom:18px;z-index:9999;background:#d7ff64;color:#09120b!important;text-decoration:none;padding:11px 15px;border-radius:999px;font-weight:900;box-shadow:0 8px 30px #0008}
</style>
<script id="lumen-alert-actions-v3">
(() => {
  const esc = (v) => String(v == null ? '' : v);
  const form = (alertId, action, label, cls, confirmText) => {
    const f = document.createElement('form');
    f.method = 'post';
    f.action = '/api/executive-alert-action';
    if (confirmText) f.addEventListener('submit', (e) => { if (!confirm(confirmText)) e.preventDefault(); });
    const id = document.createElement('input'); id.type='hidden'; id.name='alert_id'; id.value=esc(alertId); f.appendChild(id);
    const a = document.createElement('input'); a.type='hidden'; a.name='action'; a.value=action; f.appendChild(a);
    const b = document.createElement('button'); b.type='submit'; b.className=cls; b.textContent=label; f.appendChild(b);
    return f;
  };
  const install = async () => {
    try {
      const r = await fetch('/api/control-tower', {cache:'no-store', headers:{'Accept':'application/json'}});
      if (r.ok) {
        const data = await r.json();
        const alerts = ((data.executive_alerts || {}).top || []).filter(x => x && x.status === 'open');
        document.querySelectorAll('.execalert').forEach(card => {
          if (card.querySelector('.alertactions-live')) return;
          const title = (card.querySelector('b')?.textContent || '').trim();
          const alert = alerts.find(x => String(x.title || '').trim() === title);
          if (!alert) return;
          const target = card.children.length > 1 ? card.children[1] : card;
          const wrap = document.createElement('div'); wrap.className='alertactions-live';
          const m = alert.metrics || {};
          if (alert.kind === 'human_control') {
            if (m.auto_action_available) {
              wrap.appendChild(form(alert.id, 'apply', 'Aplicar ajuste recomendado', 'apply', '¿Aplicar el ajuste reversible recomendado por LUMEN? No amplía permisos de pago, contratos ni gasto.'));
            }
            wrap.appendChild(form(alert.id, 'snooze', 'Posponer esta señal', 'snooze', '¿Posponer esta misma señal hasta que cambie la evidencia que la originó?'));
          } else if (alert.kind === 'operational_blocker' || alert.kind === 'engine_failure') {
            wrap.appendChild(form(alert.id, 'recheck', 'Revisar de nuevo', 'recheck', ''));
          }
          if (wrap.children.length) target.appendChild(wrap);
        });
      }
      if (!document.querySelector('.lumen-market-link')) {
        const link = document.createElement('a');
        link.href='/market'; link.target='_blank'; link.rel='noopener';
        link.className='lumen-market-link'; link.textContent='Ver LUMEN Market';
        document.body.appendChild(link);
      }
    } catch (_) {}
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install); else install();
})();
</script>
'''


def _prune_resolved_human_tasks() -> int:
    resolutions = STATE.get("executive_control_resolutions", {}) or {}
    queue = list(STATE.get("operating_action_queue", []) or [])
    kept = []
    removed = 0
    for task in queue:
        if task.get("autonomous", True):
            kept.append(task)
            continue
        signature = _task_signature(task)
        if signature in resolutions:
            removed += 1
            continue
        kept.append(task)
    if removed:
        STATE["operating_action_queue"] = kept
        STATE.setdefault("activity", []).insert(0, {
            "msg": f"Se retiraron {removed} señal(es) ejecutivas ya resueltas de José debe decidir."
        })
        STATE["activity"] = STATE["activity"][:100]
    return removed


def _listing(listing_id: str):
    target = str(listing_id or "").strip()
    return next((x for x in STATE.get("autonomous_listings", []) or [] if str(x.get("id") or "") == target), None)


def _clean(value: str, limit: int) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _email_domain(email: str) -> str:
    value = str(email or "").strip().lower()
    if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", value):
        return ""
    return value.rsplit("@", 1)[-1]


def _market_form(listing, success: bool = False, error: str = "") -> HTMLResponse:
    listing_id = html.escape(str(listing.get("id") or ""))
    title = html.escape(str(listing.get("title") or listing.get("category") or "Oportunidad B2B"))
    category = html.escape(str(listing.get("category") or ""))
    if success:
        body = f"""
        <div class='ok'><b>Consulta recibida.</b><br>LUMEN ya la incorporó a su circuito comercial para analizar comprador, requerimiento y alternativas de suministro.</div>
        <a class='cta' href='/market'>Volver a LUMEN Market</a>
        """
    else:
        err = f"<div class='err'>{html.escape(error)}</div>" if error else ""
        body = f"""
        {err}
        <form method='post' action='/market/inquiry'>
          <input type='hidden' name='listing_id' value='{listing_id}'>
          <input class='hp' type='text' name='website' tabindex='-1' autocomplete='off'>
          <label>Empresa<input name='company' maxlength='160' required></label>
          <label>Nombre y apellido<input name='name' maxlength='120' required></label>
          <label>Email de contacto<input name='email' type='email' maxlength='180' required></label>
          <label>Teléfono <span>(opcional)</span><input name='phone' maxlength='80'></label>
          <label>Cantidad / volumen estimado <span>(opcional)</span><input name='quantity' maxlength='100'></label>
          <label>¿Qué necesitás exactamente?<textarea name='need' maxlength='1800' required></textarea></label>
          <label>Fecha objetivo <span>(opcional)</span><input name='deadline' maxlength='100'></label>
          <label>Lugar de entrega <span>(opcional)</span><input name='delivery_location' maxlength='180'></label>
          <button class='cta' type='submit'>Enviar requerimiento a LUMEN</button>
        </form>
        <p class='fine'>El envío no genera una compra ni un compromiso. LUMEN valida la necesidad y las alternativas antes de avanzar.</p>
        """
    return HTMLResponse(f"""<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>LUMEN · Solicitar alternativa</title><style>
:root{{--bg:#061018;--panel:#0d1f2b;--line:#25475d;--text:#eef7fb;--muted:#91a9b8;--lime:#d7ff64}}
*{{box-sizing:border-box}}body{{margin:0;background:#061018;color:var(--text);font-family:Inter,system-ui,-apple-system,sans-serif}}.wrap{{max-width:760px;margin:0 auto;padding:42px 20px 70px}}.brand{{font-weight:950;letter-spacing:.2em;color:var(--lime)}}h1{{font-size:36px;line-height:1.05;margin:12px 0}}.lead,.fine{{color:var(--muted);line-height:1.55}}.box{{margin-top:24px;background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:24px}}label{{display:block;font-weight:800;margin:15px 0 0}}label span{{font-weight:500;color:var(--muted)}}input,textarea{{width:100%;margin-top:7px;background:#07141d;border:1px solid #315269;border-radius:10px;color:white;padding:12px;font:inherit}}textarea{{min-height:120px;resize:vertical}}.cta{{display:inline-block;margin-top:18px;background:var(--lime);color:#07100a;border:0;border-radius:10px;padding:12px 16px;font-weight:900;text-decoration:none;cursor:pointer}}.ok{{background:#123321;border:1px solid #2f754b;border-radius:12px;padding:18px;line-height:1.5}}.err{{background:#3b1818;border:1px solid #864141;border-radius:10px;padding:12px}}.hp{{position:absolute;left:-10000px;width:1px;height:1px}}
</style></head><body><main class='wrap'><div class='brand'>LUMEN MARKET</div><h1>{title}</h1><p class='lead'>Categoría: {category}</p><section class='box'>{body}</section></main></body></html>""")


@app.post('/api/executive-alert-action')
def executive_alert_action(
    alert_id: str = Form(...),
    action: str = Form(...),
    _=Depends(auth),
):
    load_state()
    try:
        resolve_executive_alert(STATE, alert_id, action)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    executive_alert_tick(STATE)
    _prune_resolved_human_tasks()
    if not save_state():
        raise HTTPException(status_code=503, detail='La acción se procesó en memoria pero no pudo persistirse')
    return RedirectResponse('/command-center', status_code=303)


@app.get('/api/distribution-status')
def distribution_status(_=Depends(auth)):
    load_state()
    return {
        'distribution': STATE.get('autonomous_distribution', {}),
        'listings': STATE.get('autonomous_listings', []),
        'connector_queue': STATE.get('distribution_connector_queue', []),
        'market_inquiries': len(STATE.get('market_inquiries', []) or []),
    }


@app.get('/market/inquiry', response_class=HTMLResponse, include_in_schema=False)
def market_inquiry_form(listing_id: str = Query(...)):
    load_state()
    listing = _listing(listing_id)
    if not listing or listing.get('status') != 'published':
        raise HTTPException(status_code=404, detail='listing_not_available')
    return _market_form(listing)


@app.post('/market/inquiry', response_class=HTMLResponse, include_in_schema=False)
def market_inquiry_submit(
    listing_id: str = Form(...),
    company: str = Form(...),
    name: str = Form(...),
    email: str = Form(...),
    need: str = Form(...),
    phone: str = Form(''),
    quantity: str = Form(''),
    deadline: str = Form(''),
    delivery_location: str = Form(''),
    website: str = Form(''),
):
    load_state()
    listing = _listing(listing_id)
    if not listing or listing.get('status') != 'published':
        raise HTTPException(status_code=404, detail='listing_not_available')
    if website.strip():
        return _market_form(listing, success=True)

    company = _clean(company, 160)
    name = _clean(name, 120)
    email = _clean(email.lower(), 180)
    phone = _clean(phone, 80)
    quantity = _clean(quantity, 100)
    need = _clean(need, 1800)
    deadline = _clean(deadline, 100)
    delivery_location = _clean(delivery_location, 180)
    domain = _email_domain(email)
    if not company or not name or not need or not domain:
        return _market_form(listing, error='Completá empresa, contacto, email válido y requerimiento.')

    fingerprint = hashlib.sha1(f"{listing_id}|{email}|{need.lower()}".encode('utf-8')).hexdigest()[:20]
    inquiries = STATE.setdefault('market_inquiries', [])
    existing = next((x for x in inquiries if x.get('fingerprint') == fingerprint), None)
    if existing:
        return _market_form(listing, success=True)

    inquiry_id = f"MINQ-{len(inquiries)+1:05d}"
    inquiry = {
        'id': inquiry_id,
        'fingerprint': fingerprint,
        'listing_id': str(listing.get('id') or ''),
        'category': str(listing.get('category') or ''),
        'company': company,
        'contact_name': name,
        'email': email,
        'email_domain': domain,
        'phone': phone,
        'quantity': quantity,
        'need': need,
        'deadline': deadline,
        'delivery_location': delivery_location,
        'source': 'lumen_market',
        'status': 'new_buyer_demand',
    }
    inquiries.append(inquiry)
    STATE['market_inquiries'] = inquiries[-500:]

    events = STATE.setdefault('distribution_events', [])
    events.append({
        'channel': 'lumen_public_catalog',
        'event': 'inquiry',
        'listing_id': inquiry['listing_id'],
        'category': inquiry['category'],
        'inquiry_id': inquiry_id,
    })
    STATE['distribution_events'] = events[-1000:]

    # Corporate-domain inquiries become unverified buyer research leads. Existing verification engines
    # decide whether the company is real before any governed outbound or commercial promotion occurs.
    if domain not in FREE_EMAIL_DOMAINS:
        source_url = f"https://{domain}/"
        lead_key = f"market|{inquiry['listing_id']}|{domain}|{fingerprint}"
        leads = STATE.setdefault('research_leads', [])
        if not any(str(x.get('market_inquiry_key') or '') == lead_key for x in leads):
            leads.append({
                'id': f"LEAD-{len(leads)+1:05d}",
                'type': 'buyer',
                'category': inquiry['category'],
                'title': company,
                'url': source_url,
                'snippet': f"Demanda entrante vía LUMEN Market. Requerimiento: {need[:700]}",
                'market': str(listing.get('market') or 'Argentina'),
                'status': 'research_required',
                'confidence': 0.82,
                'verified_company': False,
                'verified_contact': False,
                'direct_inbound_demand': True,
                'demand_signal': True,
                'market_inquiry_id': inquiry_id,
                'market_inquiry_key': lead_key,
            })

    STATE.setdefault('activity', []).insert(0, {
        'msg': f"LUMEN Market recibió demanda entrante de {company} para {inquiry['category']}."
    })
    STATE['activity'] = STATE['activity'][:100]

    if not save_state():
        raise HTTPException(status_code=503, detail='inquiry_received_but_persistence_unavailable')
    return _market_form(listing, success=True)


@app.get('/market', response_class=HTMLResponse, include_in_schema=False)
def public_market():
    load_state()
    rows = [x for x in STATE.get('autonomous_listings', []) or [] if x.get('status') == 'published']
    rows = sorted(rows, key=lambda x: float(x.get('score') or 0), reverse=True)[:24]
    cards = []
    for row in rows:
        raw_listing_id = str(row.get('id') or '')
        listing_id = html.escape(raw_listing_id)
        title = html.escape(str(row.get('title') or row.get('category') or 'Oportunidad B2B'))
        summary = html.escape(str(row.get('summary') or ''))
        evidence = row.get('evidence', {}) or {}
        proof = []
        if int(evidence.get('verified_suppliers') or 0) > 0:
            proof.append(f"{int(evidence.get('verified_suppliers') or 0)} proveedor(es) verificado(s)")
        if int(evidence.get('demand_signals') or 0) > 0:
            proof.append(f"{int(evidence.get('demand_signals') or 0)} señal(es) de demanda")
        if int(evidence.get('real_offers') or 0) > 0:
            proof.append(f"{int(evidence.get('real_offers') or 0)} cotización(es) real(es)")
        proof_html = ' · '.join(html.escape(x) for x in proof[:3]) or 'Sourcing B2B activo'
        inquiry_href = '/market/inquiry?listing_id=' + urllib.parse.quote(raw_listing_id)
        cards.append(f"""
          <article class='card'>
            <div class='id'>{listing_id}</div>
            <h2>{title}</h2>
            <p>{summary}</p>
            <div class='proof'>{proof_html}</div>
            <p class='small'>Disponibilidad, precio, plazo y condiciones se confirman para cada requerimiento. LUMEN actúa como intermediario comercial; comprador y proveedor operan directamente entre sí.</p>
            <a class='cta' href='{html.escape(inquiry_href)}'>Solicitar alternativa</a>
          </article>
        """)
    if not cards:
        cards.append("<div class='empty'>LUMEN está evaluando oportunidades. Las publicaciones aparecen únicamente cuando existe evidencia suficiente de demanda y oferta.</div>")

    updated = html.escape(str((STATE.get('autonomous_distribution', {}) or {}).get('updated_at') or ''))
    return HTMLResponse(f"""<!doctype html>
<html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<meta name='robots' content='index,follow'><meta name='description' content='Catálogo B2B de oportunidades de suministro coordinadas por LUMEN.'>
<title>LUMEN · Market B2B</title>
<style>
:root{{--bg:#061018;--panel:#0c1a24;--line:#214054;--text:#eef7fb;--muted:#91a9b8;--lime:#d7ff64;--blue:#8bd8ff}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 10% 0,#12334a 0,#061018 34%);color:var(--text);font-family:Inter,system-ui,-apple-system,sans-serif}}
.wrap{{max-width:1120px;margin:auto;padding:30px 20px 60px}}.top{{padding:34px 0 24px}}.brand{{font-weight:950;letter-spacing:.2em;color:var(--lime)}}h1{{font-size:clamp(38px,7vw,68px);line-height:1;margin:12px 0}}.lead{{color:var(--muted);font-size:18px;max-width:760px;line-height:1.55}}
.grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:14px;margin-top:28px}}.card{{background:linear-gradient(180deg,#0d1f2b,#091720);border:1px solid var(--line);border-radius:18px;padding:22px}}.card h2{{font-size:20px;margin:7px 0 12px}}.card p{{color:#b8c9d3;line-height:1.55}}.id{{font:12px ui-monospace,monospace;color:var(--blue)}}.proof{{color:var(--lime);font-size:12px;font-weight:800;margin:16px 0}}.small{{font-size:12px}}.cta{{display:inline-block;margin-top:9px;background:var(--lime);color:#0a1008;text-decoration:none;font-weight:900;padding:11px 14px;border-radius:9px}}.empty{{border:1px dashed #35586d;border-radius:16px;padding:30px;color:var(--muted)}}.foot{{margin-top:28px;color:#6f8998;font-size:12px}}@media(max-width:720px){{.grid{{grid-template-columns:1fr}}}}
</style></head><body><main class='wrap'><section class='top'><div class='brand'>LUMEN MARKET</div><h1>Oportunidades de suministro B2B</h1><p class='lead'>LUMEN detecta demanda, contrasta oferta y publica únicamente oportunidades con evidencia suficiente. Cada consulta entra directamente al circuito autónomo de compradores y proveedores.</p></section><section class='grid'>{''.join(cards)}</section><div class='foot'>Actualización: {updated or 'en curso'} · LUMEN · Argentina</div></main></body></html>""")


@app.middleware('http')
async def executive_alert_action_ui(request: Request, call_next):
    if request.url.path in {'/command-center', '/api/control-tower'}:
        load_state()
        executive_alert_tick(STATE)
        if _prune_resolved_human_tasks():
            save_state()

    response = await call_next(request)
    if request.url.path != '/command-center' or 'text/html' not in str(response.headers.get('content-type') or ''):
        return response

    body = b''
    async for chunk in response.body_iterator:
        body += chunk
    text = body.decode('utf-8', errors='replace')
    if 'lumen-alert-actions-v3' not in text:
        text = text.replace('</body>', ACTION_UI + '</body>', 1)

    headers = dict(response.headers)
    headers.pop('content-length', None)
    return Response(content=text, status_code=response.status_code, headers=headers, media_type='text/html')
