from __future__ import annotations

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from app import auth
from executive_alerts import executive_alert_tick, resolve_executive_alert
from main import STATE, load_state, save_state
from mp_main import app


ACTION_UI = r'''
<style id="lumen-alert-actions-style">
.alertactions-live{display:flex;gap:7px;flex-wrap:wrap;margin-top:10px}
.alertactions-live form{display:inline;margin:0}
.alertactions-live button{border-radius:8px;padding:9px 13px;font-weight:900;cursor:pointer}
.alertactions-live .apply{background:#d7ff64;color:#0a1008;border:0}
.alertactions-live .snooze{background:#172631;color:#bdd3df;border:1px solid #345164}
.alertactions-live .recheck{background:#173141;color:#bfe7fa;border:1px solid #2b5770}
</style>
<script id="lumen-alert-actions-v2">
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
      if (!r.ok) return;
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
        result = resolve_executive_alert(STATE, alert_id, action)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    executive_alert_tick(STATE)
    if not save_state():
        raise HTTPException(status_code=503, detail='La acción se procesó en memoria pero no pudo persistirse')
    return RedirectResponse('/command-center', status_code=303)


@app.middleware('http')
async def executive_alert_action_ui(request: Request, call_next):
    response = await call_next(request)
    if request.url.path != '/command-center' or 'text/html' not in str(response.headers.get('content-type') or ''):
        return response

    body = b''
    async for chunk in response.body_iterator:
        body += chunk
    text = body.decode('utf-8', errors='replace')
    if 'lumen-alert-actions-v2' not in text:
        text = text.replace('</body>', ACTION_UI + '</body>', 1)

    headers = dict(response.headers)
    headers.pop('content-length', None)
    return Response(content=text, status_code=response.status_code, headers=headers, media_type='text/html')
