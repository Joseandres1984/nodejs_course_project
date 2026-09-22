import base from "./pricing_worker.js";

const STATE_KEY = "global";

function constantTimeEqual(a, b) {
  a = String(a || ""); b = String(b || "");
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function authOK(request, env) {
  const password = String(env.LUMEN_DASHBOARD_PASSWORD || "");
  if (!password) return null;
  const header = request.headers.get("Authorization") || "";
  if (!header.startsWith("Basic ")) return false;
  try {
    const decoded = atob(header.slice(6));
    const i = decoded.indexOf(":");
    if (i < 0) return false;
    return constantTimeEqual(decoded.slice(0, i), String(env.LUMEN_DASHBOARD_USER || "socio")) && constantTimeEqual(decoded.slice(i + 1), password);
  } catch {
    return false;
  }
}

async function sha256Hex(bytes) {
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(hash)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function loadState(env) {
  const manifest = await env.DB.prepare(
    "SELECT encoding, chunk_count, payload_sha256, uncompressed_bytes, updated_at FROM lumen_state_manifest WHERE state_key=? LIMIT 1"
  ).bind(STATE_KEY).first();
  if (!manifest) throw new Error("state_not_initialized");
  if (manifest.encoding !== "zlib+base64+json") throw new Error("unsupported_state_encoding");
  const rows = await env.DB.prepare(
    "SELECT chunk_no,payload FROM lumen_state_chunks WHERE state_key=? ORDER BY chunk_no ASC"
  ).bind(STATE_KEY).all();
  const chunks = rows.results || [];
  if (chunks.length !== Number(manifest.chunk_count || 0)) throw new Error("incomplete_state_chunks");
  const encoded = chunks.map((row) => String(row.payload || "")).join("");
  const binary = atob(encoded);
  const compressed = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) compressed[i] = binary.charCodeAt(i);
  const stream = new Blob([compressed]).stream().pipeThrough(new DecompressionStream("deflate"));
  const raw = new Uint8Array(await new Response(stream).arrayBuffer());
  const digest = await sha256Hex(raw);
  if (manifest.payload_sha256 && digest !== manifest.payload_sha256) throw new Error("state_checksum_mismatch");
  return {state: JSON.parse(new TextDecoder().decode(raw)), manifest};
}

const obj = (v) => v && typeof v === "object" && !Array.isArray(v) ? v : {};
const arr = (v) => Array.isArray(v) ? v : [];
const num = (v) => Number(v || 0);
const str = (v, d = "") => String(v ?? d);

function summary(state, manifest) {
  const engine = obj(state.experiment_engine);
  const current = obj(engine.current_experiment);
  const cognitive = obj(state.cognitive_director_learning);
  const product = obj(cognitive.top_product);
  const channel = obj(cognitive.top_channel);
  const director = obj(state.autonomous_director);
  const history = arr(engine.history).slice(-20).reverse().map((row) => ({
    id: str(row.id, "—"),
    created_at: str(row.created_at),
    mode: str(row.mode, "—"),
    campaign_id: str(row.campaign_id, "—"),
    variant_id: str(row.variant_id, "—"),
    angle: str(row.angle, "—"),
    baseline_clicks: num(row.baseline_clicks),
    baseline_leads: num(row.baseline_leads),
    baseline_conversion_rate: num(row.baseline_conversion_rate),
    observed_clicks: num(row.observed_clicks),
    observed_leads: num(row.observed_leads),
    observed_conversion_rate: num(row.observed_conversion_rate),
    result: str(row.result, "observing"),
  }));
  return {
    version: str(engine.version, "not_initialized"),
    status: str(engine.status, "not_initialized"),
    updated_at: engine.updated_at || manifest.updated_at || null,
    policy: str(engine.policy, "80_20_exploit_explore"),
    exploit_share: num(engine.exploit_share || 0.80),
    explore_share: num(engine.explore_share || 0.20),
    experiment_id: str(current.id, "—"),
    mode: str(current.mode, "waiting"),
    campaign_id: str(current.campaign_id, "—"),
    variant_id: str(current.variant_id, "—"),
    audience: str(current.audience, "—"),
    angle: str(current.angle, "—"),
    hypothesis: str(current.hypothesis, "Sin experimento activo todavía."),
    dispatch_channel: str(obj(current.dispatch).channel, "—"),
    dispatch_status: str(obj(current.dispatch).reason, "—"),
    sample_clicks: num(current.baseline_clicks),
    sample_leads: num(current.baseline_leads),
    sample_verified_companies: num(current.baseline_verified_companies),
    conversion_rate: num(current.baseline_conversion_rate),
    product_winner: str(engine.winner_product || product.product_slug, "—"),
    product_evidence: str(product.evidence_class, "—"),
    channel_winner: str(engine.winner_channel || channel.source, "—"),
    channel_campaign: str(channel.campaign, "—"),
    outcome_samples: num(engine.outcome_samples || product.samples),
    verified_settlements: num(engine.verified_settlements || product.settled_count),
    verified_revenue_usd: num(engine.verified_revenue_usd || product.realized_revenue_usd),
    bottleneck: str(engine.bottleneck || director.bottleneck, "—"),
    next_decision: str(engine.next_decision || current.next_decision, "Esperando evidencia atribuible."),
    decision_sequence: num(engine.decision_sequence),
    exploit_decisions: num(engine.exploit_decisions),
    explore_decisions: num(engine.explore_decisions),
    history,
    guardrails: {
      monetary_budget_usd: 0,
      paid_media_authority_changed: false,
      binding_authority_changed: false,
      search_budget_increased: false,
      hard_bottleneck_override: false,
    },
  };
}

const EXP_STYLE = `<style id="lumenExperimentStyle">
.lumenExpHero{border-color:#4d6b28;background:linear-gradient(135deg,#142018,#09151d 58%,#10252e)}
.lumenExpKpis{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.lumenExpKpis .card{min-height:108px}.lumenExpValue{font-size:22px;font-weight:950;margin-top:7px;color:#d9ff65;overflow-wrap:anywhere}.lumenExpSplit{display:grid;grid-template-columns:1fr 1fr;gap:11px}.lumenExpTable{overflow:auto}.lumenExpTable table{min-width:780px}
@media(max-width:900px){.lumenExpKpis{grid-template-columns:repeat(2,1fr)}.lumenExpSplit{grid-template-columns:1fr}}@media(max-width:520px){.lumenExpKpis{grid-template-columns:1fr}}
</style>`;

const EXP_SECTION = `<section class="page" id="experiments">
<div class="card lumenExpHero"><div class="klabel">Experiment Engine · Zero Cost</div><h2>Aprender qué vende mejor</h2><p class="note">LUMEN asigna 80% de capacidad experimental al mejor brazo observable y 20% a explorar challengers. Un cobro verificado pesa más que un checkout y un lead pesa más que un click. Los experimentos no habilitan gasto pago, contratos ni nuevos permisos.</p></div>
<div class="lumenExpKpis section">
<div class="card"><div class="klabel">Producto ganador</div><div class="lumenExpValue" id="leProduct">–</div></div>
<div class="card"><div class="klabel">Canal ganador</div><div class="lumenExpValue" id="leChannel">–</div></div>
<div class="card"><div class="klabel">Modo actual</div><div class="lumenExpValue" id="leMode">–</div></div>
<div class="card"><div class="klabel">Experimento</div><div class="lumenExpValue mono" id="leExperiment">–</div></div>
<div class="card"><div class="klabel">Muestra / clicks</div><div class="lumenExpValue" id="leSample">0</div></div>
<div class="card"><div class="klabel">Conversión lead</div><div class="lumenExpValue" id="leConversion">0%</div></div>
<div class="card"><div class="klabel">Cobros verificados</div><div class="lumenExpValue" id="leSettlements">0</div></div>
<div class="card"><div class="klabel">Ingresos verificados</div><div class="lumenExpValue" id="leRevenue">USD 0</div></div>
</div>
<div class="lumenExpSplit section"><div class="card"><h2>Decisión actual</h2><div id="leDecision"></div></div><div class="card"><h2>Control 80/20</h2><div id="lePolicy"></div></div></div>
<div class="card section"><h2>Historial experimental</h2><div class="lumenExpTable" id="leHistory"><div class="empty">Todavía no hay experimentos registrados.</div></div></div>
</section>`;

const EXP_SCRIPT = `<script id="lumenExperimentScript">
(() => {
 const e=id=>document.getElementById(id); const esc=v=>String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
 const usd=v=>'USD '+Number(v||0).toLocaleString('es-AR',{maximumFractionDigits:2}); const pct=v=>(Number(v||0)*100).toLocaleString('es-AR',{maximumFractionDigits:1})+'%';
 const line=(a,b)=>'<div class="statusline"><span>'+esc(a)+'</span><strong>'+b+'</strong></div>';
 async function loadExperiments(){try{const r=await fetch('/api/experiments',{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);const d=await r.json();
  if(e('leProduct'))e('leProduct').textContent=d.product_winner||'—'; if(e('leChannel'))e('leChannel').textContent=d.channel_winner||'—'; if(e('leMode'))e('leMode').textContent=String(d.mode||'waiting').toUpperCase(); if(e('leExperiment'))e('leExperiment').textContent=d.experiment_id||'—';
  if(e('leSample'))e('leSample').textContent=Number(d.sample_clicks||0).toLocaleString('es-AR'); if(e('leConversion'))e('leConversion').textContent=pct(d.conversion_rate); if(e('leSettlements'))e('leSettlements').textContent=Number(d.verified_settlements||0).toLocaleString('es-AR'); if(e('leRevenue'))e('leRevenue').textContent=usd(d.verified_revenue_usd);
  if(e('leDecision'))e('leDecision').innerHTML=line('Cuello de botella',esc(d.bottleneck))+line('Campaña',esc(d.campaign_id))+line('Variante',esc(d.variant_id))+line('Ángulo',esc(d.angle))+line('Canal de prueba',esc(d.dispatch_channel))+line('Estado dispatch',esc(d.dispatch_status))+'<p class="note">'+esc(d.next_decision)+'</p><p class="small">Hipótesis: '+esc(d.hypothesis)+'</p>';
  if(e('lePolicy'))e('lePolicy').innerHTML=line('Explotación',pct(d.exploit_share))+line('Exploración',pct(d.explore_share))+line('Secuencia',String(d.decision_sequence||0))+line('Decisiones exploit',String(d.exploit_decisions||0))+line('Decisiones explore',String(d.explore_decisions||0))+line('Presupuesto autónomo','USD 0')+line('Gasto pago','NO')+line('Override bottleneck','NO');
  const rows=Array.isArray(d.history)?d.history:[]; if(e('leHistory'))e('leHistory').innerHTML=rows.length?'<table><thead><tr><th>Modo</th><th>Campaña</th><th>Variante</th><th>Clicks</th><th>Leads</th><th>Conversión</th><th>Resultado</th></tr></thead><tbody>'+rows.map(x=>'<tr><td>'+esc(String(x.mode||'').toUpperCase())+'</td><td>'+esc(x.campaign_id)+'</td><td class="mono">'+esc(x.variant_id)+'</td><td>'+Number(x.observed_clicks||x.baseline_clicks||0)+'</td><td>'+Number(x.observed_leads||x.baseline_leads||0)+'</td><td>'+pct(x.observed_conversion_rate||x.baseline_conversion_rate)+'</td><td>'+esc(x.result||'observing')+'</td></tr>').join('')+'</tbody></table>':'<div class="empty">Todavía no hay experimentos registrados.</div>';
 }catch(err){if(e('leDecision'))e('leDecision').innerHTML='<div class="empty">No pude leer Experiment Engine: '+esc(err.message)+'</div>';}}
 loadExperiments(); setInterval(loadExperiments,60000);
})();
</script>`;

function injectExperimentPanel(html) {
  if (html.includes('id="lumenExperimentScript"')) return html;
  if (html.includes("</head>")) html = html.replace("</head>", EXP_STYLE + "</head>");
  if (html.includes("</nav>")) html = html.replace("</nav>", '<button class="tab" data-tab="experiments">Experimentos</button></nav>');
  const footer = '<footer class="footer">';
  if (html.includes(footer)) html = html.replace(footer, EXP_SECTION + footer);
  else if (html.includes("</body>")) html = html.replace("</body>", EXP_SECTION + "</body>");
  if (html.includes("</body>")) html = html.replace("</body>", EXP_SCRIPT + "</body>");
  return html;
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/api/experiments") {
      const auth = authOK(request, env);
      if (auth === null) return new Response("LUMEN dashboard todavía no tiene contraseña configurada.", {status:503, headers:{"Cache-Control":"no-store"}});
      if (!auth) return new Response("LUMEN · acceso restringido", {status:401, headers:{"WWW-Authenticate":'Basic realm="LUMEN Centro de Comando", charset="UTF-8"',"Cache-Control":"no-store"}});
      try {
        const {state,manifest} = await loadState(env);
        return Response.json(summary(state,manifest), {headers:{"Cache-Control":"no-store","X-Content-Type-Options":"nosniff"}});
      } catch (error) {
        return Response.json({ok:false,error:String(error?.message||error)}, {status:503,headers:{"Cache-Control":"no-store"}});
      }
    }

    const response = await base.fetch(request, env, ctx);
    const contentType = String(response.headers.get("content-type") || "");
    if (request.method !== "GET" || response.status !== 200 || !contentType.includes("text/html")) return response;
    const html = injectExperimentPanel(await response.text());
    const headers = new Headers(response.headers);
    headers.set("content-length", String(new TextEncoder().encode(html).length));
    headers.set("cache-control", "no-store");
    return new Response(html, {status:response.status,statusText:response.statusText,headers});
  },
};
