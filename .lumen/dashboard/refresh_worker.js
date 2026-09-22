import base from "./recovery_worker.js";

const SERVICE_CATALOG = [
  { id: "SRV-QUOTECHECK", name: "QuoteCheck Global", price: 59, desc: "Revisión y comparación estructurada de cotizaciones B2B con referencias públicas." },
  { id: "SRV-SUPPLIERCHECK", name: "SupplierCheck", price: 79, desc: "Identidad, canales oficiales, señales públicas y riesgo comercial de proveedores." },
  { id: "SRV-TENDER-HUNTER", name: "Tender Hunter Global", price: 99, desc: "Detección y preanálisis de oportunidades y licitaciones públicas relevantes." },
  { id: "SRV-SOURCING-EXPRESS", name: "Sourcing Express", price: 149, desc: "Investigación y preselección de proveedores para una necesidad B2B concreta." },
  { id: "SRV-B2B-PROSPECTING", name: "Prospección B2B", price: 199, desc: "Empresas objetivo, señales públicas y canales corporativos compatibles con una oferta B2B." },
  { id: "SRV-EXPORT-SCOUT", name: "Export Scout", price: 249, desc: "Búsqueda de mercados, importadores, distribuidores y compradores con evidencia pública." },
];

function servicesSection() {
  const cards = SERVICE_CATALOG.map((service) => `
    <article class="card lumenServiceCard">
      <div class="klabel">${service.id}</div>
      <h2>LUMEN ${service.name}</h2>
      <div class="lumenPrice">Desde USD ${service.price}</div>
      <p class="note">${service.desc}</p>
    </article>`).join("");
  return `<section class="page" id="services">
    <div class="card lumenServiceIntro">
      <div><div class="klabel">Oferta comercial vigente</div><h2>Qué vende LUMEN</h2><p class="note">Seis servicios de entrada con precio de lanzamiento y alcance acotado. El precio final de casos más amplios se confirma antes de contratar.</p></div>
      <div><a class="link" href="https://lumen-zero-public.lumen-b2b.workers.dev/services" target="_blank" rel="noreferrer">Ver página pública de servicios ↗</a></div>
    </div>
    <div class="lumenServiceGrid section">${cards}</div>
    <div class="grid g2 section">
      <div class="card"><h2>Cómo cobramos</h2><div class="statusline"><span>Argentina</span><strong>ARS · Mercado Pago</strong></div><div class="statusline"><span>Exterior</span><strong>USD · Payoneer</strong></div><div class="statusline"><span>Europa / EUR</span><strong>EUR · Prex / IBAN</strong></div><p class="note">Los canales están configurados para recibir cobros. Ejecutar pagos, asumir compromisos o aceptar contratos sigue requiriendo autorización humana.</p></div>
      <div class="card"><h2>Objetivo comercial</h2><div class="statusline"><span>Prioridad</span><strong>Conseguir demanda real</strong></div><div class="statusline"><span>Éxito</span><strong>consulta → propuesta → cobro</strong></div><div class="statusline"><span>Regla</span><strong>evidencia antes de oportunidad</strong></div><p class="note">LUMEN no cuenta actividad como resultado: una venta sólo existe cuando el ingreso está efectivamente verificado.</p></div>
    </div>
  </section>`;
}

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

  if (!html.includes('data-tab="services"')) {
    html = html.replace(
      'data-tab="commercial">Ventas</button>',
      'data-tab="commercial">Ventas</button><button class="tab" data-tab="services">Servicios y precios</button>'
    );
  }
  if (!html.includes('id="services"')) {
    html = html.replace('<section class="page" id="scout">', servicesSection() + '<section class="page" id="scout">');
  }
  if (!html.includes('id="lumenOwnerSummary"')) {
    html = html.replace(
      '<section class="page active" id="overview">',
      '<section class="page active" id="overview"><div class="card lumenOwnerSummary" id="lumenOwnerSummary"><div><div class="klabel">LUMEN ahora</div><div class="lumenFocus" id="lumenFocus">Leyendo estado…</div><div class="note" id="lumenFocusDetail">—</div></div><div class="lumenResultGrid"><div><span>Demanda real</span><b id="lumenDemand">–</b></div><div><span>Oportunidades</span><b id="lumenOpps">–</b></div><div><span>Respuestas</span><b id="lumenReplies">–</b></div><div><span>Propuestas</span><b id="lumenProposals">–</b></div><div><span>Ingresos</span><b id="lumenRevenue">–</b></div><div><span>Autonomía</span><b id="lumenAutonomy">–</b></div></div><div class="lumenOwnerBottom"><span id="lumenBudgetNow">Búsquedas: –</span><span id="lumenNeedsYou">Necesita de vos: –</span></div></div>'
    );
  }

  if (!html.includes('id="lumenBudgetExplain"')) {
    html = html.replace(
      '<div id="searchBudget"></div>',
      '<div id="searchBudget"></div><div class="lumenExplain" id="lumenBudgetExplain"><b>No es dinero ni crédito.</b> Es un límite interno de consultas públicas gratuitas para mantener el costo en $0. Máximo: 24 por día. Para que el Autopilot no las gaste de golpe, se habilitan por tramos en hora Argentina: 4 hasta las 06:00, 10 hasta las 12:00, 17 hasta las 18:00 y las 24 desde las 18:00. Mientras haya compradores sin demanda confirmada, la mayor parte del cupo se orienta a descubrir necesidades reales. Cuando no hay búsquedas habilitadas, LUMEN sigue procesando D1, evidencia, documentos y dominios ya guardados.</div>'
    );
  }
  if (!html.includes('id="lumenGovernanceExplain"')) {
    html = html.replace(
      '<div id="governance"></div>',
      '<div id="governance"></div><div class="lumenExplain" id="lumenGovernanceExplain"><b>En simple:</b> LUMEN investiga, verifica, aprende, prioriza, reintenta y prepara trabajo por sí solo. Vos intervenís únicamente para compromisos vinculantes: contratos, dinero, publicidad paga, conectores nuevos y cada publicación de Instagram.</div>'
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
.lumenOwnerSummary{margin-bottom:12px;border-color:#416652;background:linear-gradient(135deg,#11251f,#0b1921 60%,#10252e);overflow:visible}.lumenFocus{font-size:25px;font-weight:950;color:#d9ff65;margin:5px 0 4px}.lumenResultGrid{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin-top:15px}.lumenResultGrid>div{background:#07131a;border:1px solid #1c3947;border-radius:11px;padding:10px}.lumenResultGrid span{display:block;color:#8fa7b3;font-size:10px;text-transform:uppercase;letter-spacing:.07em}.lumenResultGrid b{display:block;margin-top:5px;font-size:18px}.lumenOwnerBottom{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-top:11px;color:#a9bfca;font-size:12px}.lumenServiceIntro{display:flex;align-items:center;justify-content:space-between;gap:18px}.lumenServiceGrid{display:grid;grid-template-columns:repeat(3,1fr);gap:11px}.lumenServiceCard h2{margin-top:7px}.lumenPrice{font-size:25px;font-weight:950;color:#d9ff65;margin:3px 0 8px}
@media(max-width:1050px){.lumenResultGrid{grid-template-columns:repeat(3,1fr)}.lumenServiceGrid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:760px){
  .g2{grid-template-columns:1fr!important}
  .statusline{align-items:flex-start;overflow-wrap:anywhere}
  .statusline strong{max-width:58%;text-align:right;overflow-wrap:anywhere;word-break:break-word}
  .toplinks{width:100%;align-items:center}
  #lumenRefreshStatus{display:block;width:100%;margin-left:0!important;margin-top:4px}
  .lumenServiceIntro{align-items:flex-start;flex-direction:column}.lumenServiceGrid{grid-template-columns:1fr}.lumenResultGrid{grid-template-columns:repeat(2,1fr)}
}
@media(max-width:430px){
  .tabs{scrollbar-width:none}
  .tabs::-webkit-scrollbar{display:none}
  .lumenFocus{font-size:21px}.lumenResultGrid{grid-template-columns:1fr 1fr}
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
    'Restante': 'Disponible dentro del tope diario',
    'Railway': 'Railway histórico'
  };

  function argentinaHour() {
    try {
      const parts = new Intl.DateTimeFormat('en-US',{timeZone:'America/Argentina/Buenos_Aires',hour:'2-digit',hourCycle:'h23'}).formatToParts(new Date());
      return Number((parts.find(x=>x.type==='hour')||{}).value||0);
    } catch { return new Date().getHours(); }
  }
  function unlockedCap() {
    const h = argentinaHour();
    if (h < 6) return 4;
    if (h < 12) return 10;
    if (h < 18) return 17;
    return 24;
  }
  function nextUnlock() {
    const h = argentinaHour();
    if (h < 6) return '06:00';
    if (h < 12) return '12:00';
    if (h < 18) return '18:00';
    return '00:00';
  }
  function setText(id, value) { const el=document.getElementById(id); if(el) el.textContent=value; }
  function renderOwnerSummary(d) {
    if (!d || !d.funnel || !d.scout) return;
    const demand = Number(d.funnel.demand||0);
    const opps = Number(d.funnel.opportunities||0);
    const proposals = Number(d.funnel.proposals||0);
    const replies = Number(d.funnel.inbound||0);
    const revenue = Number((d.money||{}).realized_revenue||0);
    const approvals = Array.isArray(d.approvals) ? d.approvals.length : 0;
    const posts = Array.isArray(d.instagram_posts) ? d.instagram_posts : [];
    const igPending = posts.filter(p => String(p.state_status||'').toUpperCase()!=='PUBLISHED' && !['APPROVED','REJECTED'].includes(String(p.approval_status||'').toUpperCase())).length;
    const autonomyOk = Number((d.status||{}).watchdog_score||0)===100 && String((d.status||{}).worker_status||'').toLowerCase()!=='failed';

    let focus='Convertir actividad en negocio real';
    let detail='LUMEN prioriza la etapa más cercana a producir una conversación, propuesta o cobro verificable.';
    if (demand===0) { focus='Encontrar la primera demanda verificable'; detail='Ya hay empresas y contactos: el bloqueo es descubrir una necesidad de compra real con evidencia suficiente.'; }
    else if (opps===0) { focus='Convertir demanda en oportunidad'; detail='Hay demanda confirmada; ahora hay que vincular requisito, comprador y una ruta comercial ejecutable.'; }
    else if (proposals===0) { focus='Llevar oportunidades a propuesta'; detail='El foco pasa de investigar a preparar una oferta concreta y comparable.'; }
    else if (revenue===0) { focus='Conseguir el primer cobro'; detail='Ya existe trabajo comercial avanzado; el resultado que importa ahora es ingreso efectivamente verificado.'; }
    else { focus='Repetir y escalar lo que ya convirtió'; detail='LUMEN debe aprender de los negocios reales y asignar más capacidad a los patrones que producen ingresos.'; }

    setText('lumenFocus',focus); setText('lumenFocusDetail',detail); setText('lumenDemand',demand); setText('lumenOpps',opps); setText('lumenReplies',replies); setText('lumenProposals',proposals); setText('lumenRevenue','USD '+revenue.toLocaleString('es-AR',{maximumFractionDigits:0})); setText('lumenAutonomy',autonomyOk?'OPERANDO':'REVISAR');
    const used=Number(d.scout.used||0), hard=Number(d.scout.hard_cap||24), unlocked=Math.min(hard,unlockedCap()), availableNow=Math.max(0,Math.min(hard-used,unlocked-used));
    setText('lumenBudgetNow','Búsquedas gratis: '+used+'/'+hard+' usadas · '+availableNow+' habilitadas ahora'+(availableNow===0 && used<hard?' · próximo tramo '+nextUnlock():'') );
    const needs=[]; if(approvals) needs.push(approvals+' decisión/es comercial/es'); if(igPending) needs.push(igPending+' publicación/es de Instagram');
    setText('lumenNeedsYou','Necesita de vos: '+(needs.length?needs.join(' · '):'nada ahora'));
  }

  if (typeof window.render === 'function' && !window.__lumenResultRenderWrapped) {
    const originalRender = window.render;
    window.render = function(data) { const out=originalRender(data); renderOwnerSummary(data); return out; };
    window.__lumenResultRenderWrapped = true;
  }

  let cleaning = false;
  function cleanOperationalTruth() {
    if (cleaning) return;
    cleaning = true;
    try {
      [...document.querySelectorAll('.statusline')].forEach((row) => {
        const label = row.querySelector('span');
        const value = row.querySelector('strong');
        if (!label) return;
        const key = (label.textContent || '').trim();
        if (key === 'WhatsApp') { row.remove(); return; }
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
            if (normalized === from || normalized.includes(from)) text = normalized === from ? to : text.replace(new RegExp(from, 'ig'), to);
          }
          if (text !== current) node.textContent = text;
        });
      }

      const outbox = document.getElementById('outbox');
      if (outbox) {
        [...outbox.querySelectorAll('td')].forEach((cell) => {
          if ((cell.textContent || '').trim().toLowerCase() === 'sent') cell.textContent = 'enviado · entrega no verificada';
        });
      }

      const inquiries = document.querySelector('#inquiriesTable .empty');
      if (inquiries && inquiries.textContent !== 'Todavía no entró ninguna consulta por la web.') inquiries.textContent = 'Todavía no entró ninguna consulta por la web.';
    } finally { cleaning = false; }
  }

  let observerScheduled = false;
  const observer = new MutationObserver(() => {
    if (observerScheduled) return;
    observerScheduled = true;
    requestAnimationFrame(() => { observerScheduled = false; cleanOperationalTruth(); });
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
        const full = await fetch('/api/full-state?_=' + bust, { cache: 'no-store', headers: { 'Accept': 'application/json' } });
        if (!full.ok) throw new Error('estado HTTP ' + full.status);
        D = await full.json(); render(); stateUpdatedAt = D && D.meta ? (D.meta.updated_at || '') : '';
        if (typeof renderRecovery === 'function') {
          const recovery = await fetch('/api/recovery-state?_=' + bust, { cache: 'no-store', headers: { 'Accept': 'application/json' } });
          if (recovery.ok) { LR = await recovery.json(); renderRecovery(); }
        }
      } else {
        const current = await fetch('/api/data?_=' + bust, { cache: 'no-store', headers: { 'Accept': 'application/json' } });
        if (!current.ok) throw new Error('estado HTTP ' + current.status);
        const data = await current.json(); render(data); renderOwnerSummary(data); stateUpdatedAt = data && data.status ? (data.status.updated_at || data.status.last_tick || '') : '';
      }

      cleanOperationalTruth();
      const readAt = new Date().toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      btn.textContent = 'Actualizado ✓';
      setStatus('Leído ' + readAt + (stateUpdatedAt ? ' · Estado D1: ' + stateUpdatedAt : ''), true);
    } catch (error) {
      btn.textContent = 'Error al actualizar';
      setStatus('No se pudo refrescar: ' + (error && error.message ? error.message : 'error desconocido'), false);
    } finally {
      window.setTimeout(() => { btn.disabled = false; btn.style.opacity = '1'; btn.textContent = normalLabel; }, 1400);
    }
  }

  btn.onclick = refreshNow;
})();
</script>`;

  if (!html.includes('window.__lumenResultRenderWrapped')) html = html.replace('</body>', script + '</body>');
  return html;
}

export default {
  async fetch(request, env, ctx) {
    const response = await base.fetch(request, env, ctx);
    const url = new URL(request.url);
    const isDashboardHtml = request.method === 'GET' && (url.pathname === '/' || url.pathname === '/full');
    if (!isDashboardHtml || !response.ok || !response.headers.get('content-type')?.includes('text/html')) return response;

    const html = patchRefresh(await response.text());
    const headers = new Headers(response.headers);
    headers.set('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0');
    headers.set('Pragma', 'no-cache');
    return new Response(html, { status: response.status, headers });
  },
};
