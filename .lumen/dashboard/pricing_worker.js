import base from "./refresh_worker.js";

const PRICING_STYLE = `<style id="lumenPricingPatch">
.lumenOwnerFull{margin-bottom:11px;border-color:#416652;background:linear-gradient(135deg,#11251f,#0b1921 60%,#10252e);overflow:visible}.lumenOwnerFocus{font-size:24px;font-weight:950;color:#d9ff65;margin:5px 0 4px}.lumenOwnerGrid{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin-top:13px}.lumenOwnerGrid>div{background:#07131a;border:1px solid #1c3947;border-radius:11px;padding:10px}.lumenOwnerGrid span{display:block;color:#8fa7b3;font-size:10px;text-transform:uppercase;letter-spacing:.07em}.lumenOwnerGrid b{display:block;margin-top:5px;font-size:18px}.lumenOwnerBottom{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-top:10px;color:#a9bfca;font-size:12px}
.lumenPricingHero{border-color:#486532;background:linear-gradient(135deg,#13231a,#0b1921 58%,#10252e)}
.lumenPricingKpis{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:12px}.lumenPricingKpis>div,.lumenScenario{background:#07131a;border:1px solid #1c3947;border-radius:11px;padding:11px}.lumenPricingKpis span,.lumenScenario span{display:block;color:#8fa7b3;font-size:10px;text-transform:uppercase;letter-spacing:.07em}.lumenPricingKpis b,.lumenScenario b{display:block;margin-top:5px;font-size:20px}.lumenPlanGrid{display:grid;grid-template-columns:repeat(3,1fr);gap:11px}.lumenPlan{min-height:210px}.lumenPlan .price{font-size:25px;font-weight:950;color:#d9ff65;margin:6px 0}.lumenPlan .code{font:11px ui-monospace,SFMono-Regular,Menlo,monospace;color:#8fa7b3;margin-top:12px}.lumenScenarioGrid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.lumenScenario b{color:#9de8c5}.lumenPriceNote{color:#8fa7b3;line-height:1.5}
@media(max-width:1050px){.lumenPlanGrid{grid-template-columns:repeat(2,1fr)}.lumenScenarioGrid,.lumenPricingKpis{grid-template-columns:repeat(2,1fr)}.lumenOwnerGrid{grid-template-columns:repeat(3,1fr)}}
@media(max-width:650px){.lumenPlanGrid,.lumenScenarioGrid,.lumenPricingKpis{grid-template-columns:1fr}.lumenOwnerGrid{grid-template-columns:repeat(2,1fr)}.lumenOwnerFocus{font-size:21px}}
</style>`;

const OWNER_SUMMARY = `<div class="card lumenOwnerFull" id="lumenFullOwnerSummary">
  <div class="lab">LUMEN ahora</div>
  <div class="lumenOwnerFocus" id="lfFocus">Leyendo prioridad comercial…</div>
  <div class="muted" id="lfDetail">Resultados reales primero; actividad sin avance comercial no cuenta como éxito.</div>
  <div class="lumenOwnerGrid">
    <div><span>Ingresos cobrados</span><b id="lfRevenue">–</b></div>
    <div><span>Demanda real</span><b id="lfDemand">–</b></div>
    <div><span>Oportunidades</span><b id="lfOpps">–</b></div>
    <div><span>Propuestas</span><b id="lfProposals">–</b></div>
    <div><span>Listos para cierre</span><b id="lfClose">–</b></div>
    <div><span>Respuestas</span><b id="lfReplies">–</b></div>
  </div>
  <div class="lumenOwnerBottom"><span id="lfAutonomy">Autonomía: –</span><span id="lfSearch">Búsquedas gratuitas: –</span><span id="lfBlocker">Bloqueo: –</span></div>
</div>`;

const PRICING_SECTION = `<section class="page" id="services">
  <div class="card lumenPricingHero">
    <div class="lab">Oferta comercial vigente</div>
    <h2>Servicios, precios y objetivo de facturación</h2>
    <div class="lumenPriceNote">Catálogo comercial en USD conectado al estado real de LUMEN. Desde USD 59 · hasta USD 249. Los escenarios de abajo son matemáticos y orientativos; no son una promesa de ventas.</div>
    <div class="lumenPricingKpis">
      <div><span>Servicios activos</span><b id="lpCount">6</b></div>
      <div><span>Precio de entrada</span><b id="lpFloor">USD 59</b></div>
      <div><span>Ticket medio catálogo</span><b id="lpAverage">USD 139</b></div>
      <div><span>Mayor precio base</span><b id="lpCeiling">USD 249</b></div>
    </div>
  </div>
  <div class="lumenPlanGrid section" id="lpPlans"><div class="empty">Leyendo catálogo comercial…</div></div>
  <div class="card section">
    <h2>Escenarios de facturación</h2>
    <p class="lumenPriceNote">Referencia simple usando el ticket medio vigente. Sirve para visualizar escala; los ingresos reales sólo se contabilizan cuando están verificados.</p>
    <div class="lumenScenarioGrid" id="lpScenarios"></div>
  </div>
  <div class="grid g2 section">
    <div class="card"><h2>Cómo cobramos</h2><div class="module"><strong>Argentina</strong><div class="muted">ARS · Mercado Pago</div></div><div class="module"><strong>Exterior</strong><div class="muted">USD · Payoneer</div></div><div class="module"><strong>Europa / EUR</strong><div class="muted">EUR · Prex / IBAN</div></div></div>
    <div class="card"><h2>Regla de resultado</h2><div class="module"><strong>Prioridad</strong><div class="muted">demanda real → propuesta → cobro</div></div><div class="module"><strong>Autonomía</strong><div class="muted">investigar, verificar, priorizar y preparar trabajo sin gasto pago</div></div><div class="module"><strong>Límite humano</strong><div class="muted">contratos, pagos, publicidad paga y publicaciones vinculantes</div></div></div>
  </div>
</section>`;

const PRICING_SCRIPT = `<script id="lumenPricingScript">
(() => {
  const escPrice = (v) => String(v ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const usdPrice = (v) => 'USD ' + Number(v || 0).toLocaleString('es-AR',{maximumFractionDigits:0});
  const text = (id,value) => { const el=document.getElementById(id); if(el) el.textContent=value; };
  async function loadLumenCommercialView(){
    const box = document.getElementById('lpPlans');
    try {
      const response = await fetch('/api/data',{cache:'no-store'});
      if (!response.ok) throw new Error('HTTP '+response.status);
      const data = await response.json();
      const catalog = data.catalog || {};
      const services = Array.isArray(catalog.services) ? catalog.services : [];
      if (!services.length) throw new Error('catálogo vacío');

      text('lpCount',services.length);
      text('lpFloor',usdPrice(catalog.floor_usd));
      text('lpAverage',usdPrice(catalog.average_usd));
      text('lpCeiling',usdPrice(catalog.ceiling_usd));
      if (box) box.innerHTML = services.map(service => '<article class="card lumenPlan"><div class="lab">Servicio LUMEN</div><h2>'+escPrice(service.name)+'</h2><div class="price">Desde '+usdPrice(service.from_usd)+'</div><div class="muted">'+escPrice(service.desc)+'</div><div class="code">'+escPrice(service.id)+'</div></article>').join('');
      const average = Number(catalog.average_usd || 0);
      const scenarios = document.getElementById('lpScenarios');
      if (scenarios) scenarios.innerHTML = [10,25,50,100].map(q => '<div class="lumenScenario"><span>'+q+' ventas / mes</span><b>'+usdPrice(q*average)+'</b><span>al ticket medio actual</span></div>').join('');

      const funnel = data.funnel || {};
      const intelligence = data.intelligence || {};
      const outbound = data.outbound || {};
      const scout = data.scout || {};
      const money = data.money || {};
      const action = String(intelligence.action || '').trim();
      const lane = String(intelligence.lane || '').trim();
      text('lfFocus',action || lane || 'Convertir evidencia en oportunidades y cobros');
      text('lfDetail','Carril: '+(lane || 'prioridad comercial automática')+' · el sistema reutiliza evidencia antes de gastar nuevas búsquedas.');
      text('lfRevenue',usdPrice(money.realized_revenue));
      text('lfDemand',Number(funnel.demand || 0).toLocaleString('es-AR'));
      text('lfOpps',Number(funnel.opportunities || 0).toLocaleString('es-AR'));
      text('lfProposals',Number(funnel.proposals || 0).toLocaleString('es-AR'));
      text('lfClose',Number(funnel.close_ready || 0).toLocaleString('es-AR'));
      text('lfReplies',Number(funnel.inbound || 0).toLocaleString('es-AR'));
      text('lfAutonomy','Autonomía: '+(outbound.live ? 'operativa + outbound habilitado' : 'operativa; outbound condicionado'));
      text('lfSearch','Búsquedas gratuitas: '+Number(scout.remaining || 0)+' restantes de '+Number(scout.hard_cap || 0));
      text('lfBlocker','Bloqueo: '+(outbound.blocker || 'ninguno reportado'));
    } catch (error) {
      if (box) box.innerHTML = '<div class="empty">No se pudo leer el catálogo: '+escPrice(error && error.message ? error.message : 'error')+'</div>';
      text('lfDetail','No se pudo leer /api/data: '+(error && error.message ? error.message : 'error'));
    }
  }
  loadLumenCommercialView();
  setInterval(loadLumenCommercialView,60000);
})();
</script>`;

function patchFullPricing(html) {
  if (!html.includes('data-p="services"')) {
    html = html.replace(
      '<button class="tab" data-p="commercial">Comercial</button>',
      '<button class="tab" data-p="commercial">Comercial</button><button class="tab" data-p="services">Servicios y precios</button>'
    );
  }
  if (!html.includes('id="services"')) {
    html = html.replace('<section class="page" id="accounts">', PRICING_SECTION + '<section class="page" id="accounts">');
  }
  if (!html.includes('id="lumenFullOwnerSummary"')) {
    html = html.replace('<section class="page on" id="overview">', '<section class="page on" id="overview">' + OWNER_SUMMARY);
  }
  if (!html.includes('id="lumenPricingPatch"')) html = html.replace('</head>', PRICING_STYLE + '</head>');
  if (!html.includes('id="lumenPricingScript"')) html = html.replace('</body>', PRICING_SCRIPT + '</body>');
  return html;
}

export default {
  async fetch(request, env, ctx) {
    const response = await base.fetch(request, env, ctx);
    const url = new URL(request.url);
    if (request.method !== 'GET' || url.pathname !== '/full' || !response.ok || !response.headers.get('content-type')?.includes('text/html')) return response;
    const html = patchFullPricing(await response.text());
    const headers = new Headers(response.headers);
    headers.set('Cache-Control','no-store, no-cache, must-revalidate, max-age=0');
    headers.set('Pragma','no-cache');
    return new Response(html,{status:response.status,headers});
  },
};
