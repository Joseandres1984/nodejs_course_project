import base from "./pricing_worker.js";

const obj = (v) => v && typeof v === "object" && !Array.isArray(v) ? v : {};
const arr = (v) => Array.isArray(v) ? v : [];
const num = (v) => Number(v || 0);
const str = (v, d = "") => String(v ?? d);

function rootState(payload) {
  if (payload && payload.state && typeof payload.state === "object") return payload.state;
  if (payload && payload.data && typeof payload.data === "object") return payload.data;
  return payload && typeof payload === "object" ? payload : {};
}

function summarizeExperiment(state) {
  const engine = obj(state.experiment_engine);
  const current = obj(engine.current_experiment);
  const learning = obj(state.cognitive_director_learning);
  const product = obj(learning.top_product);
  const channel = obj(learning.top_channel);
  const director = obj(state.autonomous_director);
  const samples = num(engine.outcome_samples || product.samples);
  const settlementRate = num(product.settlement_rate);
  const derivedSettlements = Math.max(0, Math.round(settlementRate * samples));
  const history = arr(engine.history).slice(-20).reverse().map((row) => ({
    id: str(row.id, "—"), created_at: str(row.created_at), mode: str(row.mode, "—"),
    campaign_id: str(row.campaign_id, "—"), variant_id: str(row.variant_id, "—"), angle: str(row.angle, "—"),
    clicks: num(row.observed_clicks || row.baseline_clicks), leads: num(row.observed_leads || row.baseline_leads),
    verified_companies: num(row.observed_verified_companies || row.baseline_verified_companies),
    conversion_rate: num(row.observed_conversion_rate || row.baseline_conversion_rate), result: str(row.result, "observing"),
  }));
  return {
    version: str(engine.version, "not_initialized"), status: str(engine.status, "not_initialized"),
    updated_at: engine.updated_at || null, policy: str(engine.policy, "80_20_exploit_explore"),
    exploit_share: num(engine.exploit_share || 0.80), explore_share: num(engine.explore_share || 0.20),
    experiment_id: str(current.id, "—"), mode: str(current.mode, "waiting"),
    campaign_id: str(current.campaign_id, "—"), variant_id: str(current.variant_id, "—"),
    audience: str(current.audience, "—"), angle: str(current.angle, "—"),
    hypothesis: str(current.hypothesis, "Sin experimento activo todavía."),
    dispatch_channel: str(obj(current.dispatch).channel, "—"), dispatch_status: str(obj(current.dispatch).reason, "—"),
    sample_clicks: num(current.baseline_clicks), sample_leads: num(current.baseline_leads),
    sample_verified_companies: num(current.baseline_verified_companies), conversion_rate: num(current.baseline_conversion_rate),
    product_winner: str(engine.winner_product || product.product_slug, "—"), product_evidence: str(product.evidence_class, "—"),
    channel_winner: str(engine.winner_channel || channel.source, "—"), channel_campaign: str(channel.campaign, "—"),
    outcome_samples: samples, verified_settlements: num(engine.verified_settlements || product.settled_count || derivedSettlements),
    verified_revenue_usd: num(engine.verified_revenue_usd || product.realized_revenue_usd),
    bottleneck: str(engine.bottleneck || director.bottleneck, "—"),
    next_decision: str(engine.next_decision || current.next_decision, "Esperando evidencia atribuible."),
    decision_sequence: num(engine.decision_sequence), exploit_decisions: num(engine.exploit_decisions), explore_decisions: num(engine.explore_decisions),
    history,
    guardrails: {
      monetary_budget_usd: 0, paid_media_authority_changed: false, binding_authority_changed: false,
      search_budget_increased: false, hard_bottleneck_override: false,
    },
  };
}

async function experimentData(request, env, ctx) {
  const url = new URL(request.url);
  url.pathname = "/api/full-state";
  url.search = "";
  const upstream = await base.fetch(new Request(url.toString(), {method:"GET", headers:request.headers}), env, ctx);
  if (!upstream.ok) return upstream;
  const payload = await upstream.json();
  return Response.json(summarizeExperiment(rootState(payload)), {headers:{"Cache-Control":"no-store","X-Content-Type-Options":"nosniff"}});
}

const STYLE = `<style id="lumenExperimentStyle">
.lumenExpHero{border-color:#4d6b28;background:linear-gradient(135deg,#142018,#09151d 58%,#10252e)}.lumenExpKpis{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.lumenExpKpis .card{min-height:106px}.lumenExpValue{font-size:21px;font-weight:950;margin-top:7px;color:#d9ff65;overflow-wrap:anywhere}.lumenExpSplit{display:grid;grid-template-columns:1fr 1fr;gap:11px}.lumenExpTable{overflow:auto}.lumenExpTable table{min-width:760px}@media(max-width:900px){.lumenExpKpis{grid-template-columns:repeat(2,1fr)}.lumenExpSplit{grid-template-columns:1fr}}@media(max-width:520px){.lumenExpKpis{grid-template-columns:1fr}}
</style>`;

const SECTION = `<section class="page" id="experiments"><div class="card lumenExpHero"><div class="klabel">Experiment Engine · Zero Cost</div><h2>Aprender qué vende mejor</h2><p class="note">80% de capacidad experimental sigue la mejor evidencia disponible y 20% prueba challengers. Cobros y leads verificables pesan más que actividad. Esta capa no habilita gasto pago, contratos ni nuevos permisos.</p></div><div class="lumenExpKpis section"><div class="card"><div class="klabel">Producto ganador</div><div class="lumenExpValue" id="leProduct">–</div></div><div class="card"><div class="klabel">Canal ganador</div><div class="lumenExpValue" id="leChannel">–</div></div><div class="card"><div class="klabel">Modo actual</div><div class="lumenExpValue" id="leMode">–</div></div><div class="card"><div class="klabel">Experimento</div><div class="lumenExpValue mono" id="leExperiment">–</div></div><div class="card"><div class="klabel">Muestra / clicks</div><div class="lumenExpValue" id="leSample">0</div></div><div class="card"><div class="klabel">Conversión lead</div><div class="lumenExpValue" id="leConversion">0%</div></div><div class="card"><div class="klabel">Cobros verificados</div><div class="lumenExpValue" id="leSettlements">0</div></div><div class="card"><div class="klabel">Ingresos verificados</div><div class="lumenExpValue" id="leRevenue">USD 0</div></div></div><div class="lumenExpSplit section"><div class="card"><h2>Decisión actual</h2><div id="leDecision"></div></div><div class="card"><h2>Control 80/20</h2><div id="lePolicy"></div></div></div><div class="card section"><h2>Historial experimental</h2><div class="lumenExpTable" id="leHistory"><div class="empty">Todavía no hay experimentos registrados.</div></div></div></section>`;

const SCRIPT = `<script id="lumenExperimentScript">(()=>{const e=id=>document.getElementById(id),esc=v=>String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot',"'":'&#39;'}[m])),usd=v=>'USD '+Number(v||0).toLocaleString('es-AR',{maximumFractionDigits:2}),pct=v=>(Number(v||0)*100).toLocaleString('es-AR',{maximumFractionDigits:1})+'%',line=(a,b)=>'<div class="statusline"><span>'+esc(a)+'</span><strong>'+b+'</strong></div>';async function load(){try{const r=await fetch('/api/experiments',{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);const d=await r.json();e('leProduct').textContent=d.product_winner||'—';e('leChannel').textContent=d.channel_winner||'—';e('leMode').textContent=String(d.mode||'waiting').toUpperCase();e('leExperiment').textContent=d.experiment_id||'—';e('leSample').textContent=Number(d.sample_clicks||0).toLocaleString('es-AR');e('leConversion').textContent=pct(d.conversion_rate);e('leSettlements').textContent=Number(d.verified_settlements||0).toLocaleString('es-AR');e('leRevenue').textContent=usd(d.verified_revenue_usd);e('leDecision').innerHTML=line('Cuello de botella',esc(d.bottleneck))+line('Campaña',esc(d.campaign_id))+line('Variante',esc(d.variant_id))+line('Ángulo',esc(d.angle))+line('Canal de prueba',esc(d.dispatch_channel))+line('Estado dispatch',esc(d.dispatch_status))+'<p class="note">'+esc(d.next_decision)+'</p><p class="small">Hipótesis: '+esc(d.hypothesis)+'</p>';e('lePolicy').innerHTML=line('Explotación',pct(d.exploit_share))+line('Exploración',pct(d.explore_share))+line('Secuencia',String(d.decision_sequence||0))+line('Decisiones exploit',String(d.exploit_decisions||0))+line('Decisiones explore',String(d.explore_decisions||0))+line('Presupuesto autónomo','USD 0')+line('Gasto pago','NO')+line('Override bottleneck','NO');const rows=Array.isArray(d.history)?d.history:[];e('leHistory').innerHTML=rows.length?'<table><thead><tr><th>Modo</th><th>Campaña</th><th>Variante</th><th>Clicks</th><th>Leads</th><th>Conversión</th><th>Resultado</th></tr></thead><tbody>'+rows.map(x=>'<tr><td>'+esc(String(x.mode||'').toUpperCase())+'</td><td>'+esc(x.campaign_id)+'</td><td class="mono">'+esc(x.variant_id)+'</td><td>'+Number(x.clicks||0)+'</td><td>'+Number(x.leads||0)+'</td><td>'+pct(x.conversion_rate)+'</td><td>'+esc(x.result||'observing')+'</td></tr>').join('')+'</tbody></table>':'<div class="empty">Todavía no hay experimentos registrados.</div>'}catch(err){if(e('leDecision'))e('leDecision').innerHTML='<div class="empty">No pude leer Experiment Engine: '+esc(err.message)+'</div>'}}load();setInterval(load,60000)})();</script>`;

function inject(html) {
  if (html.includes('id="lumenExperimentScript"')) return html;
  html = html.replace("</head>", STYLE + "</head>");

  // The compact dashboard uses data-tab, while /full uses data-p. Support both so the panel is
  // actually navigable in every command-center surface instead of only being appended to markup.
  if (html.includes('data-p="services"')) {
    const target = '<button class="tab" data-p="services">Servicios y precios</button>';
    if (html.includes(target)) html = html.replace(target, target + '<button class="tab" data-p="experiments">Experimentos</button>');
    else html = html.replace('</nav>', '<button class="tab" data-p="experiments">Experimentos</button></nav>');
  } else {
    const navTarget = html.includes('data-tab="commercial">Ventas</button>') ? 'data-tab="commercial">Ventas</button>' : 'data-tab="commercial">Comercial</button>';
    if (html.includes(navTarget)) html = html.replace(navTarget, navTarget + '<button class="tab" data-tab="experiments">Experimentos</button>');
    else html = html.replace('</nav>', '<button class="tab" data-tab="experiments">Experimentos</button></nav>');
  }

  if (html.includes('<section class="page" id="accounts">')) html = html.replace('<section class="page" id="accounts">', SECTION + '<section class="page" id="accounts">');
  else if (html.includes('<section class="page" id="infra">')) html = html.replace('<section class="page" id="infra">', SECTION + '<section class="page" id="infra">');
  else html = html.replace("</body>", SECTION + "</body>");
  return html.replace("</body>", SCRIPT + "</body>");
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/api/experiments") return experimentData(request, env, ctx);
    const response = await base.fetch(request, env, ctx);
    if (request.method !== "GET" || response.status !== 200) return response;
    if (!["/", "/index.html", "/full"].includes(url.pathname)) return response;
    if (!String(response.headers.get("content-type") || "").includes("text/html")) return response;
    const html = inject(await response.text());
    const headers = new Headers(response.headers); headers.delete("content-length"); headers.set("cache-control", "no-store");
    return new Response(html, {status:response.status,statusText:response.statusText,headers});
  },
};
