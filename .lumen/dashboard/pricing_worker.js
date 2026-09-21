import base from "./refresh_worker.js";

const PRICING_STYLE = `<style id="lumenPricingPatch">
.lumenOwnerFull{margin-bottom:11px;border-color:#416652;background:linear-gradient(135deg,#11251f,#0b1921 60%,#10252e);overflow:visible}.lumenOwnerFocus{font-size:24px;font-weight:950;color:#d9ff65;margin:5px 0 4px}.lumenOwnerGrid{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin-top:13px}.lumenOwnerGrid>div{background:#07131a;border:1px solid #1c3947;border-radius:11px;padding:10px}.lumenOwnerGrid span{display:block;color:#8fa7b3;font-size:10px;text-transform:uppercase;letter-spacing:.07em}.lumenOwnerGrid b{display:block;margin-top:5px;font-size:18px}.lumenOwnerBottom{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-top:10px;color:#a9bfca;font-size:12px}
.lumenPricingHero,.lumenMachineHero{border-color:#486532;background:linear-gradient(135deg,#13231a,#0b1921 58%,#10252e)}
.lumenPricingKpis,.lumenMachineKpis{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:12px}.lumenPricingKpis>div,.lumenMachineKpis>div,.lumenScenario{background:#07131a;border:1px solid #1c3947;border-radius:11px;padding:11px}.lumenPricingKpis span,.lumenMachineKpis span,.lumenScenario span{display:block;color:#8fa7b3;font-size:10px;text-transform:uppercase;letter-spacing:.07em}.lumenPricingKpis b,.lumenMachineKpis b,.lumenScenario b{display:block;margin-top:5px;font-size:20px}.lumenPlanGrid,.lumenMachineGrid{display:grid;grid-template-columns:repeat(3,1fr);gap:11px}.lumenRecurringGrid{display:grid;grid-template-columns:repeat(4,1fr);gap:11px}.lumenPlan,.lumenMachineProduct{min-height:195px}.lumenPlan .price,.lumenMachineProduct .price{font-size:25px;font-weight:950;color:#d9ff65;margin:6px 0}.lumenPlan .code,.lumenMachineProduct .code{font:11px ui-monospace,SFMono-Regular,Menlo,monospace;color:#8fa7b3;margin-top:12px}.lumenScenarioGrid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.lumenScenario b{color:#9de8c5}.lumenPriceNote{color:#8fa7b3;line-height:1.5}.lumenStatusReady{color:#9de8c5}.lumenStatusPending{color:#ffd37a}.lumenMachineSplit{display:grid;grid-template-columns:1.3fr .7fr;gap:11px}.lumenRevenueRule{border-left:3px solid #d9ff65;padding-left:12px}
@media(max-width:1050px){.lumenPlanGrid,.lumenMachineGrid{grid-template-columns:repeat(2,1fr)}.lumenRecurringGrid,.lumenScenarioGrid,.lumenPricingKpis,.lumenMachineKpis{grid-template-columns:repeat(2,1fr)}.lumenOwnerGrid{grid-template-columns:repeat(3,1fr)}.lumenMachineSplit{grid-template-columns:1fr}}
@media(max-width:650px){.lumenPlanGrid,.lumenMachineGrid,.lumenRecurringGrid,.lumenScenarioGrid,.lumenPricingKpis,.lumenMachineKpis{grid-template-columns:1fr}.lumenOwnerGrid{grid-template-columns:repeat(2,1fr)}.lumenOwnerFocus{font-size:21px}}
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

const MACHINE_SECTION = `<div class="card section lumenMachineHero" id="machineStore">
  <div class="lab">A2A · Machine Store</div>
  <h2>Productos que otros agentes pueden comprar</h2>
  <p class="lumenPriceNote">Carril seller-only: LUMEN descubre agentes compradores, ofrece servicios, cotiza y recibe pedidos sin autoridad para gastar. Los importes cotizados son pipeline; sólo un pago verificado cuenta como ingreso real.</p>
  <div class="lumenMachineKpis">
    <div><span>Microproductos</span><b id="lmProductsCount">6</b></div>
    <div><span>Entrada máquina</span><b id="lmFloor">USD 5</b></div>
    <div><span>Planes mensuales</span><b id="lmPlansCount">4</b></div>
    <div><span>x402</span><b id="lmX402">leyendo…</b></div>
  </div>
</div>
<div class="lumenMachineSplit section">
  <div><h2>Microservicios por pedido</h2><div class="lumenMachineGrid" id="lmProducts"><div class="empty">Leyendo Machine Store…</div></div></div>
  <div><h2>Estado del carril</h2><div class="card"><div class="module"><strong>Pedidos A2A registrados</strong><div class="metric" id="lmOrders">–</div></div><div class="module"><strong>Pipeline cotizado</strong><div class="metric" id="lmQuoted">–</div><div class="muted">No es ingreso realizado.</div></div><div class="module"><strong>Cobro máquina-a-máquina</strong><div class="muted" id="lmPaymentDetail">Leyendo…</div></div><div class="module lumenRevenueRule"><strong>Regla</strong><div class="muted">A2A descubre → cotiza → pedido → verificación → cobro → ejecución → entrega. LUMEN no compra ni paga por su cuenta.</div></div></div></div>
</div>
<div class="section"><h2>Ingresos recurrentes</h2><div class="lumenRecurringGrid" id="lmPlans"><div class="empty">Leyendo planes…</div></div></div>`;

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
  ${MACHINE_SECTION}
  <div class="grid g2 section">
    <div class="card"><h2>Cómo cobramos</h2><div class="module"><strong>Argentina</strong><div class="muted">ARS · Mercado Pago</div></div><div class="module"><strong>Exterior</strong><div class="muted">USD · Payoneer</div></div><div class="module"><strong>Europa / EUR</strong><div class="muted">EUR · Prex / IBAN</div></div><div class="module"><strong>Agentes</strong><div class="muted">x402 listo para activarse al configurar receptor; mientras tanto usa settlement comercial validado.</div></div></div>
    <div class="card"><h2>Regla de resultado</h2><div class="module"><strong>Prioridad</strong><div class="muted">demanda real → propuesta → cobro</div></div><div class="module"><strong>Autonomía</strong><div class="muted">investigar, descubrir agentes, ofrecer, cotizar, verificar y preparar trabajo sin gasto pago</div></div><div class="module"><strong>Límite humano</strong><div class="muted">gasto saliente, contratos, compromisos vinculantes y cualquier movimiento no autorizado</div></div></div>
  </div>
</section>`;

const PRICING_SCRIPT = `<script id="lumenPricingScript">
(() => {
  const A2A='https://lumen-zero-a2a.joseandresceol1-jac.workers.dev';
  const escPrice = (v) => String(v ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const usdPrice = (v) => 'USD ' + Number(v || 0).toLocaleString('es-AR',{maximumFractionDigits:2});
  const text = (id,value) => { const el=document.getElementById(id); if(el) el.textContent=value; };
  async function loadMachineStore(){
    const productsBox=document.getElementById('lmProducts');
    const plansBox=document.getElementById('lmPlans');
    try{
      const [catalogResponse,statsResponse]=await Promise.all([fetch(A2A+'/machine/catalog',{cache:'no-store'}),fetch(A2A+'/machine/stats',{cache:'no-store'})]);
      if(!catalogResponse.ok) throw new Error('Machine Store HTTP '+catalogResponse.status);
      const catalog=await catalogResponse.json();
      const stats=statsResponse.ok?await statsResponse.json():{};
      const products=Array.isArray(catalog.machineProducts)?catalog.machineProducts:[];
      const plans=Array.isArray(catalog.recurringPlans)?catalog.recurringPlans:[];
      text('lmProductsCount',products.length);
      text('lmFloor',usdPrice(catalog.pricing?.machine?.floor_usd));
      text('lmPlansCount',plans.length);
      const x402=String(catalog.payments?.x402?.status||'UNKNOWN');
      text('lmX402',x402==='READY'?'READY':'SETUP');
      const xel=document.getElementById('lmX402'); if(xel) xel.className=x402==='READY'?'lumenStatusReady':'lumenStatusPending';
      text('lmPaymentDetail',x402==='READY'?'x402 habilitado para cobro programático.':'x402 preparado; falta configurar una wallet receptora real. No se simulan cobros.');
      text('lmOrders',Number(stats.orders||0).toLocaleString('es-AR'));
      text('lmQuoted',usdPrice(stats.quotedPipelineUsd||0));
      if(productsBox) productsBox.innerHTML=products.map(p=>'<article class="card lumenMachineProduct"><div class="lab">Por pedido</div><h2>'+escPrice(p.name)+'</h2><div class="price">'+usdPrice(p.price_usd)+'</div><div class="muted">'+escPrice(p.desc)+'</div><div class="code">'+escPrice(p.id)+' → '+escPrice(p.service_id)+'</div></article>').join('');
      if(plansBox) plansBox.innerHTML=plans.map(p=>'<article class="card lumenMachineProduct"><div class="lab">Recurrente</div><h2>'+escPrice(p.name)+'</h2><div class="price">'+usdPrice(p.price_usd)+'/mes</div><div class="muted">'+escPrice(p.desc)+'</div><div class="code">'+escPrice(p.id)+'</div></article>').join('');
    }catch(error){
      if(productsBox) productsBox.innerHTML='<div class="empty">Machine Store no disponible: '+escPrice(error?.message||'error')+'</div>';
      text('lmPaymentDetail','No se pudo leer el gateway A2A.');
    }
  }
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
  loadLumenCommercialView(); loadMachineStore();
  setInterval(loadLumenCommercialView,60000); setInterval(loadMachineStore,60000);
})();
</script>`;

function patchFullPricing(html) {
  if (!html.includes('data-p="services"')) html = html.replace('<button class="tab" data-p="commercial">Comercial</button>','<button class="tab" data-p="commercial">Comercial</button><button class="tab" data-p="services">Servicios y precios</button>');
  if (!html.includes('id="services"')) html = html.replace('<section class="page" id="accounts">', PRICING_SECTION + '<section class="page" id="accounts">');
  if (!html.includes('id="lumenFullOwnerSummary"')) html = html.replace('<section class="page on" id="overview">', '<section class="page on" id="overview">' + OWNER_SUMMARY);
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
