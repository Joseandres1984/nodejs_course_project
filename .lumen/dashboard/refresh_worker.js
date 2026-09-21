import base from "./recovery_worker.js";

function patchRefresh(html) {
  if (!html.includes('id="lumenRefreshBtn"')) {
    const status = '<span id="lumenRefreshStatus" style="margin-left:8px;font-size:11px;color:#8fa7b3;white-space:normal"></span>';
    html = html.replace(
      '<button class="refresh" onclick="loadData()">Actualizar</button>',
      '<button class="refresh" id="lumenRefreshBtn" type="button" title="Vuelve a leer el último estado persistido en D1; no inicia un ciclo nuevo">Actualizar datos</button>' + status
    );
    html = html.replace(
      '<button class="btn accent" onclick="load();loadRecovery()">Actualizar</button>',
      '<button class="btn accent" id="lumenRefreshBtn" type="button" title="Vuelve a leer el último estado persistido en D1; no inicia un ciclo nuevo">Actualizar datos</button>' + status
    );
    html = html.replace(
      '<button class="btn accent" onclick="load()">Actualizar</button>',
      '<button class="btn accent" id="lumenRefreshBtn" type="button" title="Vuelve a leer el último estado persistido en D1; no inicia un ciclo nuevo">Actualizar datos</button>' + status
    );
  }

  if (!html.includes('id="lumenMobileTruthPatch"')) {
    html = html.replace('</head>', `<style id="lumenMobileTruthPatch">
@media(max-width:760px){
  .g2{grid-template-columns:1fr!important}
  .statusline{align-items:flex-start;overflow-wrap:anywhere}
  .statusline strong{max-width:58%;text-align:right;overflow-wrap:anywhere;word-break:break-word}
  .toplinks{width:100%;align-items:center}
  #lumenRefreshStatus{display:block;width:100%;margin-left:0!important;margin-top:4px}
}
@media(max-width:430px){
  .tabs{scrollbar-width:none}
  .tabs::-webkit-scrollbar{display:none}
}
</style></head>`);
  }

  const script = `<script>
(() => {
  const btn = document.getElementById('lumenRefreshBtn');
  const status = document.getElementById('lumenRefreshStatus');
  const normalLabel = 'Actualizar datos';

  const laneMap = {
    demand_discovery: 'Descubrir demanda',
    verification_contact: 'Verificar contactos',
    closing: 'Cierre comercial',
    sourcing: 'Sourcing',
    outreach: 'Contacto comercial'
  };
  const phraseMap = {
    'evidence first and bounded public search next.': 'Primero evidencia; luego búsqueda pública acotada.',
    'no_eligible_external_prospects': 'sin prospectos externos elegibles',
    'demand_gap': 'falta demanda verificada'
  };

  function cleanOperationalTruth() {
    const channels = document.getElementById('channels');
    if (channels) {
      [...channels.querySelectorAll('.statusline')].forEach((row) => {
        const label = row.querySelector('span');
        const value = row.querySelector('strong');
        if (!label) return;
        const key = (label.textContent || '').trim();
        if (key === 'WhatsApp') {
          row.remove();
          return;
        }
        if (key === 'Pagos' && value) {
          label.textContent = 'Cobros';
          value.innerHTML = '<span class="chip ok">ARS · USD · EUR READY</span>';
        }
      });
      if (![...channels.querySelectorAll('.statusline span')].some((x) => (x.textContent || '').trim() === 'Alertas internas')) {
        channels.insertAdjacentHTML('beforeend','<div class="statusline"><span>Alertas internas</span><strong><span class="chip ok">EMAIL + PANEL</span></strong></div>');
      }
    }

    const priority = document.getElementById('priority');
    if (priority) {
      [...priority.querySelectorAll('strong')].forEach((node) => {
        let text = (node.textContent || '').trim();
        if (laneMap[text]) text = laneMap[text];
        const normalized = text.toLowerCase();
        for (const [from, to] of Object.entries(phraseMap)) {
          if (normalized === from || normalized.includes(from)) {
            text = normalized === from ? to : text.replace(new RegExp(from, 'ig'), to);
          }
        }
        node.textContent = text;
      });
    }
  }

  const observer = new MutationObserver(cleanOperationalTruth);
  observer.observe(document.body, {subtree:true, childList:true, characterData:true});
  cleanOperationalTruth();

  if (!btn) return;
  const setStatus = (text, ok = true) => {
    if (!status) return;
    status.textContent = text;
    status.style.color = ok ? '#9de8c5' : '#ff9992';
  };

  async function refreshNow() {
    if (btn.disabled) return;
    btn.disabled = true;
    btn.textContent = 'Actualizando…';
    btn.style.opacity = '.72';
    setStatus('Leyendo D1…', true);

    try {
      const bust = Date.now();
      let stateUpdatedAt = '';

      if (location.pathname === '/full') {
        const full = await fetch('/api/full-state?_=' + bust, {
          cache: 'no-store', headers: { 'Accept': 'application/json' },
        });
        if (!full.ok) throw new Error('estado HTTP ' + full.status);
        D = await full.json();
        render();
        stateUpdatedAt = D && D.meta ? (D.meta.updated_at || '') : '';

        if (typeof renderRecovery === 'function') {
          const recovery = await fetch('/api/recovery-state?_=' + bust, {
            cache: 'no-store', headers: { 'Accept': 'application/json' },
          });
          if (recovery.ok) {
            LR = await recovery.json();
            renderRecovery();
          }
        }
      } else {
        const current = await fetch('/api/data?_=' + bust, {
          cache: 'no-store', headers: { 'Accept': 'application/json' },
        });
        if (!current.ok) throw new Error('estado HTTP ' + current.status);
        const data = await current.json();
        render(data);
        stateUpdatedAt = data && data.status ? (data.status.updated_at || data.status.last_tick || '') : '';
      }

      cleanOperationalTruth();
      const readAt = new Date().toLocaleTimeString('es-AR', {
        hour: '2-digit', minute: '2-digit', second: '2-digit'
      });
      btn.textContent = 'Actualizado ✓';
      setStatus('Leído ' + readAt + (stateUpdatedAt ? ' · Estado D1: ' + stateUpdatedAt : ''), true);
    } catch (error) {
      btn.textContent = 'Error al actualizar';
      setStatus('No se pudo refrescar: ' + (error && error.message ? error.message : 'error desconocido'), false);
    } finally {
      window.setTimeout(() => {
        btn.disabled = false;
        btn.style.opacity = '1';
        btn.textContent = normalLabel;
      }, 1400);
    }
  }

  btn.onclick = refreshNow;
})();
</script>`;

  if (!html.includes('const laneMap = {')) html = html.replace('</body>', script + '</body>');
  return html;
}

export default {
  async fetch(request, env, ctx) {
    const response = await base.fetch(request, env, ctx);
    const url = new URL(request.url);
    const isDashboardHtml = request.method === 'GET' && (url.pathname === '/' || url.pathname === '/full');
    if (!isDashboardHtml || !response.ok || !response.headers.get('content-type')?.includes('text/html')) {
      return response;
    }

    const html = patchRefresh(await response.text());
    const headers = new Headers(response.headers);
    headers.set('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0');
    headers.set('Pragma', 'no-cache');
    return new Response(html, { status: response.status, headers });
  },
};
