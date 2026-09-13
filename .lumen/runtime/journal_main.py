from __future__ import annotations

import html
import urllib.parse

from fastapi import Depends, Query, Request
from fastapi.responses import HTMLResponse, Response

from alert_main import app
from app import STATE, auth, load_state
from cycle_journal import bootstrap_current_cycle, fetch_cycles, inject_cycle_journal, render_cycle_journal_page
from market_concierge import router as market_concierge_router
from market_owner_panel import inject_owner_market_strip, render_owner_market_page
from elastic_workforce_panel import inject_workforce_strip, render_workforce_page
from professional_casework_panel import inject_casework_strip, render_casework_page


# The conversational concierge is the primary buyer intake. The structured form remains
# available only as a quiet fallback for buyers who explicitly prefer manual entry.
app.include_router(market_concierge_router)


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


@app.get('/market-owner', response_class=HTMLResponse, include_in_schema=False)
def market_owner_page(_=Depends(auth)):
    load_state()
    return HTMLResponse(render_owner_market_page(STATE))


@app.get('/workforce', response_class=HTMLResponse, include_in_schema=False)
def workforce_page(_=Depends(auth)):
    load_state()
    return HTMLResponse(render_workforce_page(STATE))


@app.get('/casework', response_class=HTMLResponse, include_in_schema=False)
def casework_page(_=Depends(auth)):
    load_state()
    return HTMLResponse(render_casework_page(STATE))


def _primary_market_html(text: str) -> str:
    text = text.replace('/market/inquiry?listing_id=', '/market/concierge?listing_id=')
    text = text.replace('Solicitar alternativa', 'Hablar con LUMEN')
    text = text.replace(
        'Cada consulta entra directamente al circuito autónomo de compradores y proveedores.',
        'El comprador habla con LUMEN en lenguaje normal; LUMEN entiende el requerimiento, pregunta solo lo imprescindible y toma el control del proceso comercial.',
    )
    return text


def _concierge_fallback_html(text: str, listing_id: str) -> str:
    if not listing_id or 'Prefiero completar los datos manualmente' in text:
        return text
    href = '/market/inquiry?listing_id=' + urllib.parse.quote(listing_id)
    fallback = (
        "<p style='margin:14px 0 0;text-align:center;font-size:11px;color:#6f8998'>"
        "<a style='color:#7894a3;text-decoration:underline;text-underline-offset:3px' href='"
        + html.escape(href, quote=True)
        + "'>Prefiero completar los datos manualmente</a></p>"
    )
    return text.replace('</main>', fallback + '</main>', 1)


def _owner_command_center_links(text: str) -> str:
    # In the authenticated owner interface, /market means management, not shopping.
    # The explicit public-store button is added afterwards by inject_owner_market_strip.
    text = text.replace("href='/market'", "href='/market-owner'")
    text = text.replace('href="/market"', 'href="/market-owner"')
    text = text.replace('>LUMEN Market<', '>Market · gestión<')
    return text


@app.middleware('http')
async def lumen_ui_runtime(request: Request, call_next):
    if request.url.path in {'/command-center', '/cycle-journal', '/api/cycle-journal', '/market-owner', '/workforce', '/casework'}:
        load_state()
        if request.url.path not in {'/market-owner', '/workforce', '/casework'}:
            bootstrap_current_cycle(STATE)

    response = await call_next(request)
    content_type = str(response.headers.get('content-type') or '')
    if 'text/html' not in content_type:
        return response

    path = request.url.path
    if path not in {'/command-center', '/market', '/market/concierge'}:
        return response

    body = b''
    async for chunk in response.body_iterator:
        body += chunk
    text = body.decode('utf-8', errors='replace')

    if path == '/command-center':
        text = _owner_command_center_links(text)
        text = inject_cycle_journal(text, STATE)
        text = inject_casework_strip(text, STATE)
        text = inject_workforce_strip(text, STATE)
        text = inject_owner_market_strip(text, STATE)
        if 'lumen-cycle-live-v1' not in text:
            text = text.replace('</body>', LIVE_JOURNAL_UI + '</body>', 1)
    elif path == '/market':
        text = _primary_market_html(text)
    elif path == '/market/concierge' and request.method == 'GET':
        text = _concierge_fallback_html(text, str(request.query_params.get('listing_id') or ''))

    headers = dict(response.headers)
    headers.pop('content-length', None)
    return Response(content=text, status_code=response.status_code, headers=headers, media_type='text/html')
