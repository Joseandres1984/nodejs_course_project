from __future__ import annotations

import html
import os
import urllib.parse

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app import auth
from executive_alerts import executive_alert_tick, resolve_executive_alert
from main import STATE, load_state, save_state
from mp_main import app


PUBLIC_CONTACT = os.getenv("LUMEN_PUBLIC_CONTACT_EMAIL", "Lumenstock2026@gmail.com").strip()

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
        link.className='lumen-market-link'; link.textContent='Ver catálogo autónomo';
        document.body.appendChild(link);
      }
    } catch (_) {}
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install); else install();
})();
</script>
'''


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
    }


@app.get('/market', response_class=HTMLResponse, include_in_schema=False)
def public_market():
    load_state()
    rows = [x for x in STATE.get('autonomous_listings', []) or [] if x.get('status') == 'published']
    rows = sorted(rows, key=lambda x: float(x.get('score') or 0), reverse=True)[:24]
    cards = []
    for row in rows:
        listing_id = html.escape(str(row.get('id') or ''))
        title = html.escape(str(row.get('title') or row.get('category') or 'Oportunidad B2B'))
        summary = html.escape(str(row.get('summary') or ''))
        category = html.escape(str(row.get('category') or ''))
        evidence = row.get('evidence', {}) or {}
        proof = []
        if int(evidence.get('verified_suppliers') or 0) > 0:
            proof.append(f"{int(evidence.get('verified_suppliers') or 0)} proveedor(es) verificado(s)")
        if int(evidence.get('demand_signals') or 0) > 0:
            proof.append(f"{int(evidence.get('demand_signals') or 0)} señal(es) de demanda")
        if int(evidence.get('real_offers') or 0) > 0:
            proof.append(f"{int(evidence.get('real_offers') or 0)} cotización(es) real(es)")
        proof_html = ' · '.join(html.escape(x) for x in proof[:3]) or 'Sourcing B2B activo'
        subject = urllib.parse.quote(f"Consulta {listing_id} - {category}")
        contact = html.escape(PUBLIC_CONTACT)
        cards.append(f"""
          <article class='card'>
            <div class='id'>{listing_id}</div>
            <h2>{title}</h2>
            <p>{summary}</p>
            <div class='proof'>{proof_html}</div>
            <p class='small'>Disponibilidad, precio, plazo y condiciones se confirman para cada requerimiento. LUMEN actúa como intermediario comercial; comprador y proveedor operan directamente entre sí.</p>
            <a class='cta' href='mailto:{contact}?subject={subject}'>Consultar esta oportunidad</a>
          </article>
        """)
    if not cards:
        cards.append("<div class='empty'>LUMEN está evaluando oportunidades. Las publicaciones aparecen únicamente cuando existe evidencia suficiente de demanda y oferta.</div>")

    updated = html.escape(str((STATE.get('autonomous_distribution', {}) or {}).get('updated_at') or ''))
    return HTMLResponse(f"""<!doctype html>
<html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<meta name='robots' content='index,follow'><meta name='description' content='Catálogo B2B de oportunidades de suministro coordinadas por LUMEN.'>
<title>LUMEN · Catálogo B2B</title>
<style>
:root{{--bg:#061018;--panel:#0c1a24;--line:#214054;--text:#eef7fb;--muted:#91a9b8;--lime:#d7ff64;--blue:#8bd8ff}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 10% 0,#12334a 0,#061018 34%);color:var(--text);font-family:Inter,system-ui,-apple-system,sans-serif}}
.wrap{{max-width:1120px;margin:auto;padding:30px 20px 60px}}.top{{padding:34px 0 24px}}.brand{{font-weight:950;letter-spacing:.2em;color:var(--lime)}}h1{{font-size:clamp(38px,7vw,68px);line-height:1;margin:12px 0}}.lead{{color:var(--muted);font-size:18px;max-width:760px;line-height:1.55}}
.grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:14px;margin-top:28px}}.card{{background:linear-gradient(180deg,#0d1f2b,#091720);border:1px solid var(--line);border-radius:18px;padding:22px}}.card h2{{font-size:20px;margin:7px 0 12px}}.card p{{color:#b8c9d3;line-height:1.55}}.id{{font:12px ui-monospace,monospace;color:var(--blue)}}.proof{{color:var(--lime);font-size:12px;font-weight:800;margin:16px 0}}.small{{font-size:12px}}.cta{{display:inline-block;margin-top:9px;background:var(--lime);color:#0a1008;text-decoration:none;font-weight:900;padding:11px 14px;border-radius:9px}}.empty{{border:1px dashed #35586d;border-radius:16px;padding:30px;color:var(--muted)}}.foot{{margin-top:28px;color:#6f8998;font-size:12px}}@media(max-width:720px){{.grid{{grid-template-columns:1fr}}}}
</style></head><body><main class='wrap'><section class='top'><div class='brand'>LUMEN</div><h1>Oportunidades de suministro B2B</h1><p class='lead'>LUMEN detecta demanda, contrasta oferta y publica únicamente oportunidades con evidencia suficiente. No compramos stock ni cobramos el valor de la mercadería: coordinamos la operación como intermediarios.</p></section><section class='grid'>{''.join(cards)}</section><div class='foot'>Actualización: {updated or 'en curso'} · LUMEN · Argentina</div></main></body></html>""")


@app.middleware('http')
async def executive_alert_action_ui(request: Request, call_next):
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
