import base from "./recovery_worker.js";

function friendlyCopy(html) {
  const replacements = [
    ['data-tab="overview">Resumen</button>', 'data-tab="overview">Hoy</button>'],
    ['data-tab="commercial">Comercial</button>', 'data-tab="commercial">Ventas</button>'],
    ['data-tab="scout">Scout</button>', 'data-tab="scout">Búsqueda</button>'],
    ['data-tab="infra">Sistema</button>', 'data-tab="infra">Técnico</button>'],
    ['data-tab="activity">Actividad</button>', 'data-tab="activity">Historial</button>'],
    ['>Ingresos realizados</div>', '>Ingresos cobrados</div>'],
    ['>Pipeline</div>', '>Valor en oportunidades</div>'],
    ['>Valor esperado</div>', '>Valor probable</div>'],
    ['>Ganancia potencial</div>', '>Ganancia estimada</div>'],
    ['>Watchdog</div>', '>Salud del sistema</div>'],
    ['>Agentes</div>', '>Agentes activos</div>'],
    ['>Elegibles outbound</div>', '>Listos para contactar</div>'],
    ['>Cierres pendientes</div>', '>Requieren tu decisión</div>'],
    ['>Ganancia registrada</div>', '>Ingresos cobrados</div>'],
    ['>Outbound enviado</div>', '>Contactos enviados</div>'],
    ['>Inbound</div>', '>Respuestas recibidas</div>'],
    ['<h2>Deals</h2>', '<h2>Negocios en curso</h2>'],
    ['<h2>Aprobaciones humanas</h2>', '<h2>Requieren tu aprobación</h2>'],
    ['<h2>Ofertas / cotizaciones</h2>', '<h2>Cotizaciones / propuestas</h2>'],
    ['<h2>Salida comercial</h2>', '<h2>Últimos contactos</h2>'],
    ['>Research leads</div>', '>Hallazgos de investigación</div>'],
    ['>Verificadas</div>', '>Empresas verificadas</div>'],
    ['<h2>Presupuesto de búsqueda</h2>', '<h2>Búsquedas gratuitas del día</h2>'],
    ['<h2>Leads recientes de investigación</h2>', '<h2>Hallazgos recientes</h2>'],
    ['>Inbox</div>', '>Mensajes recibidos</div>'],
    ['>Publicaciones preparadas</div>', '>Publicaciones en control</div>'],
    ['<h2>Consultas públicas recientes</h2>', '<h2>Consultas recibidas</h2>'],
    ['<h2>Infraestructura</h2>', '<h2>Estado técnico</h2>'],
    ['<h2>Gobernanza</h2>', '<h2>Qué necesita tu aprobación</h2>'],
    ['<h2>Diario de ciclos</h2>', '<h2>Ejecuciones de LUMEN</h2>'],
    ['<h2>Pendientes priorizados</h2>', '<h2>Qué falta resolver</h2>'],
    ['<h2>Actividad</h2>', '<h2>Historial reciente</h2>'],
  ];
  for (const [from, to] of replacements) html = html.replaceAll(from, to);

  if (!html.includes('id="lumenBudgetExplain"')) {
    html = html.replace(
      '<div id="searchBudget"></div>',
      '<div id="searchBudget"></div><div class="lumenExplain" id="lumenBudgetExplain"><b>No es dinero ni crédito.</b> Es un límite interno de consultas públicas gratuitas para mantener el costo en $0. El tope actual es 24 por día, se reparte automáticamente entre búsqueda de demanda y verificación/general, se libera por tramos durante el día y se reinicia a las 00:00 de Argentina. Cuando se agota, LUMEN sigue trabajando con D1, documentos, dominios y evidencia ya guardada.</div>'
    );
  }
  if (!html.includes('id="lumenGovernanceExplain"')) {
    html = html.replace(
      '<div id="governance"></div>',
      '<div id="governance"></div><div class="lumenExplain" id="lumenGovernanceExplain"><b>En simple:</b> LUMEN investiga, verifica, aprende, prioriza y prepara trabajo por sí solo. Vos intervenís únicamente para compromisos vinculantes: contratos, dinero, publicidad paga, conectores nuevos y cada publicación de Instagram.</div>'
    );
  }
  return html;
}

function patchRefresh(html) {
  html = friendlyCopy(html);

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
.lumenExplain{margin-top:12px;padding:11px 12px;border:1px solid #294655;border-radius:11px;background:#08131a;color:#a9bfca;line-height:1.5;font-size:12px}.lumenExplain b{color:#eef5f7}
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
    demand_discovery: 'Descubrir demanda real',
    verification_contact: 'Verificar empresas y contactos',
    closing: 'Cierre comercial',
    sourcing: 'Buscar proveedores',
    outreach: 'Contacto comercial'
  };
  const phraseMap = {
    'evidence first and bounded public search next.': 'Primero usa evidencia guardada; después búsqueda pública acotada.',
    'no_eligible_external_prospects': 'sin empresas listas para contactar ahora',
    'demand_gap': 'falta demanda verificada'
  };
  const labelMap = {
    'Proveedor': 'Motor de búsqueda',
    'Tope diario': 'Máximo gratis por día',
    'General usado': 'Verificación/general usado',
    'Demanda usado': 'Búsqueda de demanda usada',
    'Restante': 'Disponible hoy',
    'Railway': 'Railway histórico'
  };

  let cleaning = false;
  function cleanOperationalTruth() {
    if (cleaning) return;
    cleaning = true;
    try {
      // WhatsApp fue retirado por decisión del dueño. Eliminar cualquier proyección vieja del panel,
      // sin importar en qué tarjeta haya quedado almacenada.
      [...document.querySelectorAll('.statusline')].forEach((row) => {
        const label = row.querySelector('span');
        const value = row.querySelector('strong');
        if (!label) return;
        const key = (label.textContent || '').trim();
        if (key === 'WhatsApp') {
          row.remove();
          return;
        }
        if (labelMap[key] && label.textContent !== labelMap[key]) label.textContent = labelMap[key];
        if (key === 'Pagos' && value) {
          label.textContent = 'Cobros';
          const desired = '<span class="chip ok">ARS · USD · EUR LISTOS</span>';
          if (value.innerHTML !== desired) value.innerHTML = desired;
        }
        if (key === 'Railway' && value) {
          label.textContent = 'Railway histórico';
          const desired = '<span class="chip">fuera del núcleo actual</span>';
          if (value.innerHTML !== desired) value.innerHTML = desired;
        }
      });

      const channels = document.getElementById('channels');
      if (channels && ![...channels.querySelectorAll('.statusline span')].some((x) => (x.textContent || '').trim() === 'Alertas internas')) {
        channels.insertAdjacentHTML('beforeend','<div class="statusline"><span>Alertas internas</span><strong><span class="chip ok">EMAIL + PANEL</span></strong></div>');
      }

      const priority = document.getElementById('priority');
      if (priority) {
        [...priority.querySelectorAll('strong')].forEach((node) => {
          const current = (node.textContent || '').trim();
          let text = current;
          if (laneMap[text]) text = laneMap[text];
          const normalized = text.toLowerCase();
          for (const [from, to] of Object.entries(phraseMap)) {
            if (normalized === from || normalized.includes(from)) {
              text = normalized === from ? to : text.replace(new RegExp(from, 'ig'), to);
            }
          }
          if (text !== current) node.textContent = text;
        });
      }

      // "sent" significa aceptado por el transporte, no entrega demostrada.
      const outbox = document.getElementById('outbox');
      if (outbox) {
        [...outbox.querySelectorAll('td')].forEach((cell) => {
          if ((cell.textContent || '').trim().toLowerCase() === 'sent') {
            cell.textContent = 'enviado · entrega no verificada';
          }
        });
      }

      const inquiries = document.querySelector('#inquiriesTable .empty');
      if (inquiries && inquiries.textContent !== 'Todavía no entró ninguna consulta por la web.') {
        inquiries.textContent = 'Todavía no entró ninguna consulta por la web.';
      }
    } finally {
      cleaning = false;
    }
  }

  let observerScheduled = false;
  const observer = new MutationObserver(() => {
    if (observerScheduled) return;
    observerScheduled = true;
    requestAnimationFrame(() => {
      observerScheduled = false;
      cleanOperationalTruth();
    });
  });
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
