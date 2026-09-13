from __future__ import annotations

from fastapi import Depends, Query, Request
from fastapi.responses import HTMLResponse, Response

from alert_main import app
from app import STATE, auth, load_state
from cycle_journal import bootstrap_current_cycle, fetch_cycles, inject_cycle_journal, render_cycle_journal_page


LIVE_JOURNAL_UI = r'''
<script id="lumen-cycle-live-v1">
(() => {
  const shownCycle = () => {
    const panel = document.querySelector('.cycle-journal-panel');
    if (!panel) return 0;
    const stat = Array.from(panel.querySelectorAll('.cj-stat')).find(x => /Último ciclo/i.test(x.textContent || ''));
    const value = stat?.querySelector('b')?.textContent || '';
    const n = parseInt(value.replace(/\D/g, ''), 10);
    return Number.isFinite(n) ? n : 0;
  };

  let current = shownCycle();
  const poll = async () => {
    if (document.hidden) return;
    try {
      const r = await fetch('/api/cycle-journal?page=1&per_page=1&_=' + Date.now(), {
        cache: 'no-store', headers: {'Accept': 'application/json'}
      });
      if (!r.ok) return;
      const data = await r.json();
      const latest = parseInt(data?.rows?.[0]?.cycle || 0, 10);
      if (!Number.isFinite(latest) || latest <= current) return;

      const active = document.activeElement;
      const editing = !!active && ['INPUT', 'TEXTAREA', 'SELECT'].includes(active.tagName);
      if (!editing) {
        window.location.reload();
      } else {
        const panel = document.querySelector('.cycle-journal-panel');
        if (panel) panel.dataset.newCycle = String(latest);
      }
    } catch (_) {}
  };

  setTimeout(poll, 5000);
  setInterval(poll, 30000);
})();
</script>
'''


@app.get('/cycle-journal', response_class=HTMLResponse, include_in_schema=False)
def cycle_journal_page(
    page: int = Query(1, ge=1),
    _=Depends(auth),
):
    load_state()
    bootstrap_current_cycle(STATE)
    return HTMLResponse(render_cycle_journal_page(STATE, page=page, per_page=50))


@app.get('/api/cycle-journal')
def api_cycle_journal(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    _=Depends(auth),
):
    load_state()
    bootstrap_current_cycle(STATE)
    return fetch_cycles(page=page, per_page=per_page)


@app.middleware('http')
async def cycle_journal_command_center_ui(request: Request, call_next):
    if request.url.path in {'/command-center', '/cycle-journal', '/api/cycle-journal'}:
        load_state()
        bootstrap_current_cycle(STATE)

    response = await call_next(request)
    if request.url.path != '/command-center' or 'text/html' not in str(response.headers.get('content-type') or ''):
        return response

    body = b''
    async for chunk in response.body_iterator:
        body += chunk
    text = body.decode('utf-8', errors='replace')
    text = inject_cycle_journal(text, STATE)
    if 'lumen-cycle-live-v1' not in text:
        text = text.replace('</body>', LIVE_JOURNAL_UI + '</body>', 1)

    headers = dict(response.headers)
    headers.pop('content-length', None)
    return Response(content=text, status_code=response.status_code, headers=headers, media_type='text/html')
