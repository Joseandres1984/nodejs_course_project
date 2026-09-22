import base from "./pricing_worker.js";

const EXPERIMENT_STYLE = `<style id="lumenExperimentStyle">
.lumenExperimentHero{border-color:#496b34;background:linear-gradient(135deg,#13251b,#0b1921 62%,#10242e)}
.lumenExperimentKpis{display:grid;grid-template-columns:repeat(6,1fr);gap:9px;margin-top:12px}.lumenExperimentKpis>div{background:#07131a;border:1px solid #1c3947;border-radius:11px;padding:10px}.lumenExperimentKpis span{display:block;color:#8fa7b3;font-size:10px;text-transform:uppercase;letter-spacing:.07em}.lumenExperimentKpis b{display:block;margin-top:5px;font-size:18px}.lumenExperimentSplit{display:grid;grid-template-columns:1fr 1fr;gap:11px}.lumenExperimentTable{width:100%;border-collapse:collapse}.lumenExperimentTable th,.lumenExperimentTable td{padding:9px 7px;border-bottom:1px solid #17303e;text-align:left;vertical-align:top}.lumenExperimentTable th{font-size:10px;color:#7694a4;text-transform:uppercase;letter-spacing:.07em}.lumenExperimentPhase{display:inline-block;border:1px solid #365469;border-radius:999px;padding:3px 7px;font-size:11px}.lumenExperimentPhase.explore{color:#83d9ff}.lumenExperimentPhase.exploit{color:#d9ff65}.lumenExperimentGuard{color:#9de8c5}.lumenExperimentMuted{color:#8fa7b3}.lumenExperimentDecision{font-size:18px;font-weight:850;line-height:1.4;color:#eef5f7}.lumenExperimentEmpty{padding:20px;border:1px dashed #294655;border-radius:12px;color:#8fa7b3;text-align:center}
@media(max-width:1050px){.lumenExperimentKpis{grid-template-columns:repeat(3,1fr)}}@media(max-width:760px){.lumenExperimentKpis{grid-template-columns:1fr 1fr}.lumenExperimentSplit{grid-template-columns:1fr}.lumenExperimentTable{min-width:720px}}@media(max-width:430px){.lumenExperimentKpis{grid-template-columns:1fr}}
</style>`;

const EXPERIMENT_SECTION = `<section class="page" id="experiments">
  <div class="card lumenExperimentHero">
    <div class="lab">Experiment Engine v1</div>
    <h2>Qué está probando LUMEN y qué está aprendiendo</h2>
    <p class="note">Asignación deliberada 80/20: la mayor parte de la capacidad sigue al ganador actual y una parte pequeña prueba challengers. Sólo resultados atribuibles cambian la preferencia; actividad sin conversión no gana.</p>
    <div class="lumenExperimentKpis">
      <div><span>Estado</span><b id="lexStatus">–</b></div>
      <div><span>Experimentos activos</span><b id="lexActive">–</b></div>
      <div><span>Explotación</span><b id="lexExploit">80%</b></div>
      <div><span>Exploración</span><b id="lexExplore">20%</b></div>
      <div><span>Producto ganador</span><b id="lexProduct">–</b></div>
      <div><span>Canal ganador</span><b id="lexChannel">–</b></div>
    </div>
  </div>
  <div class="lumenExperimentSplit section">
    <div class="card"><h2>Próxima decisión</h2><div class="lumenExperimentDecision" id="lexDecision">Leyendo…</div><div class="note" id="lexBottleneck"></div></div>
    <div class="card"><h2>Guardrails</h2><div id="lexGuardrails"></div></div>
  </div>
  <div class="card section"><h2>Experimentos en curso</h2><div id="lexTable"><div class="lumenExperimentEmpty">Esperando el primer ciclo del Experiment Engine.</div></div></div>
</section>`;

const EXPERIMENT_SCRIPT = `<script id="lumenExperimentScript">
(() => {
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const el = (id) => document.getElementById(id);
  const text = (id,v) => { const x=el(id); if(x) x.textContent=String(v ?? '–'); };
  const pct = (v) => Math.round(Number(v||0)*100)+'%';
  const line = (a,b) => '<div class="statusline"><span>'+esc(a)+'</span><strong>'+b+'</strong></div>';
  function rootState(payload){
    if(payload && payload.state && typeof payload.state==='object') return payload.state;
    if(payload && payload.data && typeof payload.data==='object') return payload.data;
    return payload && typeof payload==='object' ? payload : {};
  }
  function perf(p){ p=p||{}; return Number(p.clicks||0)+' clics · '+Number(p.leads||0)+' leads · '+Number(p.verified_companies||0)+' verificadas'; }
  function render(engine){
    engine=engine||{};
    const allocation=engine.allocation_policy||{};
    const cognitive=engine.cognitive_focus||{};
    const product=(cognitive.top_product||{}).product_slug||'sin muestra suficiente';
    const channel=(cognitive.top_channel||{}).source||'sin muestra suficiente';
    text('lexStatus',engine.status||'esperando');
    text('lexActive',Number(engine.experiments_active||0));
    text('lexExploit',pct(allocation.exploit_share||0.8));
    text('lexExplore',pct(allocation.explore_share||0.2));
    text('lexProduct',product);
    text('lexChannel',channel);
    text('lexDecision',engine.next_decision||'Crear resultados atribuibles antes de optimizar.');
    text('lexBottleneck','Cuello de botella canónico: '+String(engine.hard_bottleneck||'aún no disponible'));
    const g=engine.guardrails||{};
    const guard=el('lexGuardrails');
    if(guard) guard.innerHTML=
      line('Gasto autónomo añadido','<span class="lumenExperimentGuard">USD '+Number(g.monetary_budget_usd||0)+'</span>')+
      line('Publicidad paga','<span class="lumenExperimentGuard">NO autónoma</span>')+
      line('Presupuesto de búsqueda aumentado','<span class="lumenExperimentGuard">NO</span>')+
      line('Autoridad vinculante ampliada','<span class="lumenExperimentGuard">NO</span>')+
      line('Puede saltar el cuello de botella','<span class="lumenExperimentGuard">NO</span>');
    const rows=Array.isArray(engine.experiments)?engine.experiments:[];
    const box=el('lexTable');
    if(!box) return;
    if(!rows.length){box.innerHTML='<div class="lumenExperimentEmpty">Todavía no hay experimentos con campañas activas. LUMEN no inventa un ganador sin datos.</div>';return;}
    box.innerHTML='<div style="overflow:auto"><table class="lumenExperimentTable"><thead><tr><th>Campaña</th><th>Fase</th><th>Ganador</th><th>Challenger</th><th>Usando ahora</th><th>Evidencia ganador</th><th>Evidencia challenger</th><th>Evaluación</th></tr></thead><tbody>'+rows.map(r=>{
      const ev=r.evaluation||{};
      return '<tr><td><b>'+esc(r.campaign_id||'–')+'</b><div class="lumenExperimentMuted">'+esc(r.audience||'')+'</div></td><td><span class="lumenExperimentPhase '+esc(r.phase||'')+'">'+esc(r.phase||'–')+'</span></td><td>'+esc(r.champion_variant_id||'–')+'</td><td>'+esc(r.challenger_variant_id||'–')+'</td><td><b>'+esc(r.selected_variant_id||'–')+'</b></td><td>'+esc(perf(r.champion_performance))+'</td><td>'+esc(r.challenger_performance?perf(r.challenger_performance):'sin challenger')+'</td><td><b>'+esc(ev.status||r.status||'–')+'</b><div class="lumenExperimentMuted">'+esc(ev.reason||'')+'</div></td></tr>';
    }).join('')+'</tbody></table></div>';
  }
  async function loadExperimentEngine(){
    try{
      const r=await fetch('/api/full-state',{cache:'no-store'});
      if(!r.ok) throw new Error('HTTP '+r.status);
      const payload=await r.json();
      const state=rootState(payload);
      render(state.experiment_engine||{});
    }catch(error){
      text('lexStatus','sin lectura');
      const box=el('lexTable'); if(box) box.innerHTML='<div class="lumenExperimentEmpty">No pude leer Experiment Engine: '+esc(error?.message||error)+'</div>';
    }
  }
  loadExperimentEngine();
  setInterval(loadExperimentEngine,60000);
})();
</script>`;

function injectExperimentUI(html) {
  if (!html.includes('id="lumenExperimentStyle"')) html = html.replace('</head>', EXPERIMENT_STYLE + '</head>');
  if (!html.includes('data-tab="experiments"')) {
    const targets = ['data-tab="commercial">Ventas</button>', 'data-tab="commercial">Comercial</button>'];
    for (const target of targets) {
      if (html.includes(target)) { html = html.replace(target, target + '<button class="tab" data-tab="experiments">Experimentos</button>'); break; }
    }
  }
  if (!html.includes('id="experiments"')) {
    if (html.includes('<section class="page" id="infra">')) html = html.replace('<section class="page" id="infra">', EXPERIMENT_SECTION + '<section class="page" id="infra">');
    else html = html.replace('</footer>', EXPERIMENT_SECTION + '</footer>');
  }
  if (!html.includes('id="lumenExperimentScript"')) html = html.replace('</body>', EXPERIMENT_SCRIPT + '</body>');
  return html;
}

export default {
  async fetch(request, env, ctx) {
    const response = await base.fetch(request, env, ctx);
    if (request.method !== 'GET') return response;
    const url = new URL(request.url);
    if (!(url.pathname === '/' || url.pathname === '/index.html' || url.pathname === '/full')) return response;
    const contentType = response.headers.get('content-type') || '';
    if (!contentType.includes('text/html')) return response;
    const html = injectExperimentUI(await response.text());
    const headers = new Headers(response.headers);
    headers.delete('content-length');
    headers.set('cache-control','no-store');
    return new Response(html,{status:response.status,statusText:response.statusText,headers});
  },
};
