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
  return { state: JSON.parse(new TextDecoder().decode(raw)), manifest };
}

const obj = (v) => v && typeof v === "object" && !Array.isArray(v) ? v : {};
const arr = (v) => Array.isArray(v) ? v : [];
const num = (v) => Number(v || 0);
const str = (v, d = "") => String(v ?? d);

function experimentSummary(state, manifest) {
  const engine = obj(state.experiment_engine);
  const allocation = obj(engine.allocation_policy);
  const cognitive = obj(engine.cognitive_focus);
  const product = obj(cognitive.top_product);
  const channel = obj(cognitive.top_channel);
  const guardrails = obj(engine.guardrails);
  const experiments = arr(engine.experiments).map((row) => ({
    id: str(row.id, "—"),
    campaign_id: str(row.campaign_id, "—"),
    audience: str(row.audience, "—"),
    phase: str(row.phase, "waiting"),
    allocation: num(row.allocation),
    champion_variant_id: str(row.champion_variant_id, "—"),
    challenger_variant_id: str(row.challenger_variant_id, "—"),
    selected_variant_id: str(row.selected_variant_id, "—"),
    champion_performance: obj(row.champion_performance),
    challenger_performance: row.challenger_performance ? obj(row.challenger_performance) : null,
    evaluation: obj(row.evaluation),
    status: str(row.status, "waiting"),
    hypothesis: str(row.hypothesis),
    updated_at: str(row.updated_at),
  }));
  return {
    version: str(engine.version, "not_initialized"),
    status: str(engine.status, "not_initialized"),
    updated_at: engine.updated_at || manifest.updated_at || null,
    cycle: num(engine.cycle),
    exploit_share: num(allocation.exploit_share || 0.80),
    explore_share: num(allocation.explore_share || 0.20),
    experiments_active: num(engine.experiments_active),
    experiments_total: num(engine.experiments_total),
    distribution_entries_active: num(engine.distribution_entries_active),
    product_winner: str(product.product_slug, "sin muestra suficiente"),
    product_samples: num(product.samples),
    product_settlement_rate: num(product.settlement_rate),
    channel_winner: str(channel.source, "sin muestra suficiente"),
    channel_campaign: str(channel.campaign),
    channel_samples: num(channel.samples),
    hard_bottleneck: str(engine.hard_bottleneck, "aún no disponible"),
    next_decision: str(engine.next_decision, "Crear resultados atribuibles antes de optimizar."),
    experiments,
    guardrails: {
      monetary_budget_usd: num(guardrails.monetary_budget_usd),
      paid_media_autonomous: guardrails.paid_media_autonomous === true,
      search_budget_increased: guardrails.search_budget_increased === true,
      binding_authority_changed: guardrails.binding_authority_changed === true,
      new_connector_authority: guardrails.new_connector_authority === true,
      production_self_modify: guardrails.production_self_modify === true,
      hard_bottleneck_override: guardrails.hard_bottleneck_override === true,
    },
  };
}

const EXP_STYLE = `<style id="lumenExperimentStyle">
.lumenExpHero{border-color:#4d6b28;background:linear-gradient(135deg,#142018,#09151d 58%,#10252e)}.lumenExpKpis{display:grid;grid-template-columns:repeat(6,1fr);gap:9px;margin-top:12px}.lumenExpKpis>div{background:#07131a;border:1px solid #1c3947;border-radius:11px;padding:10px}.lumenExpKpis span{display:block;color:#8fa7b3;font-size:10px;text-transform:uppercase;letter-spacing:.07em}.lumenExpKpis b{display:block;margin-top:5px;font-size:18px;overflow-wrap:anywhere}.lumenExpSplit{display:grid;grid-template-columns:1fr 1fr;gap:11px}.lumenExpTable{overflow:auto}.lumenExpTable table{min-width:850px}.lumenExpPhase{display:inline-block;border:1px solid #365469;border-radius:999px;padding:3px 7px;font-size:11px}.lumenExpPhase.explore{color:#83d9ff}.lumenExpPhase.exploit{color:#d9ff65}.lumenExpGood{color:#9de8c5}.lumenExpDecision{font-size:18px;font-weight:850;line-height:1.4}@media(max-width:1050px){.lumenExpKpis{grid-template-columns:repeat(3,1fr)}}@media(max-width:760px){.lumenExpKpis{grid-template-columns:1fr 1fr}.lumenExpSplit{grid-template-columns:1fr}}@media(max-width:430px){.lumenExpKpis{grid-template-columns:1fr}}
</style>`;

const EXP_SECTION = `<section class="page" id="experiments"><div class="card lumenExpHero"><div class="klabel">Experiment Engine v1 · Zero Cost</div><h2>Qué está probando LUMEN y qué está aprendiendo</h2><p class="note">80% de la capacidad experimental sigue al ganador observable y 20% prueba challengers. Sólo evidencia atribuible puede cambiar la preferencia; actividad sin conversión no gana.</p><div class="lumenExpKpis"><div><span>Estado</span><b id="leStatus">–</b></div><div><span>Experimentos activos</span><b id="leActive">–</b></div><div><span>Explotación</span><b id="leExploit">80%</b></div><div><span>Exploración</span><b id="leExplore">20%</b></div><div><span>Producto ganador</span><b id="leProduct">–</b></div><div><span>Canal ganador</span><b id="leChannel">–</b></div></div></div><div class="lumenExpSplit section"><div class="card"><h2>Próxima decisión</h2><div class="lumenExpDecision" id="leDecision">Leyendo…</div><div class="note" id="leBottleneck"></div></div><div class="card"><h2>Guardrails</h2><div id="leGuardrails"></div></div></div><div class="card section"><h2>Experimentos en curso</h2><div class="lumenExpTable" id="leTable"><div class="empty">Esperando el primer ciclo del Experiment Engine.</div></div></div></section>`;

const EXP_SCRIPT = `<script id="lumenExperimentScript">
(() => { const e=id=>document.getElementById(id); const esc=v=>String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])); const pct=v=>Math.round(Number(v||0)*100)+'%'; const line=(a,b)=>'<div class="statusline"><span>'+esc(a)+'</span><strong>'+b+'</strong></div>'; const perf=p=>{p=p||{};return Number(p.clicks||0)+' clics · '+Number(p.leads||0)+' leads · '+Number(p.verified_companies||0)+' verificadas'};
async function loadExperiments(){try{const r=await fetch('/api/experiments',{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);const d=await r.json(); if(e('leStatus'))e('leStatus').textContent=d.status||'esperando';if(e('leActive'))e('leActive').textContent=Number(d.experiments_active||0);if(e('leExploit'))e('leExploit').textContent=pct(d.exploit_share||.8);if(e('leExplore'))e('leExplore').textContent=pct(d.explore_share||.2);if(e('leProduct'))e('leProduct').textContent=d.product_winner||'–';if(e('leChannel'))e('leChannel').textContent=d.channel_winner||'–';if(e('leDecision'))e('leDecision').textContent=d.next_decision||'Esperando evidencia atribuible.';if(e('leBottleneck'))e('leBottleneck').textContent='Cuello de botella canónico: '+String(d.hard_bottleneck||'–');const g=d.guardrails||{};if(e('leGuardrails'))e('leGuardrails').innerHTML=line('Gasto autónomo añadido','<span class="lumenExpGood">USD '+Number(g.monetary_budget_usd||0)+'</span>')+line('Publicidad paga','<span class="lumenExpGood">NO autónoma</span>')+line('Búsquedas aumentadas','<span class="lumenExpGood">NO</span>')+line('Autoridad vinculante ampliada','<span class="lumenExpGood">NO</span>')+line('Puede saltar bottleneck','<span class="lumenExpGood">NO</span>');const rows=Array.isArray(d.experiments)?d.experiments:[];if(e('leTable'))e('leTable').innerHTML=rows.length?'<table><thead><tr><th>Campaña</th><th>Fase</th><th>Ganador</th><th>Challenger</th><th>Usando ahora</th><th>Evidencia ganador</th><th>Evidencia challenger</th><th>Evaluación</th></tr></thead><tbody>'+rows.map(x=>{const ev=x.evaluation||{};return '<tr><td><b>'+esc(x.campaign_id)+'</b><div class="small">'+esc(x.audience)+'</div></td><td><span class="lumenExpPhase '+esc(x.phase)+'">'+esc(x.phase)+'</span></td><td>'+esc(x.champion_variant_id)+'</td><td>'+esc(x.challenger_variant_id)+'</td><td><b>'+esc(x.selected_variant_id)+'</b></td><td>'+esc(perf(x.champion_performance))+'</td><td>'+esc(x.challenger_performance?perf(x.challenger_performance):'sin challenger')+'</td><td><b>'+esc(ev.status||x.status)+'</b><div class="small">'+esc(ev.reason||'')+'</div></td></tr>'}).join('')+'</tbody></table>':'<div class="empty">Todavía no hay experimentos activos. LUMEN no inventa un ganador sin datos.</div>'; }catch(err){if(e('leStatus'))e('leStatus').textContent='sin lectura';if(e('leTable'))e('leTable').innerHTML='<div class="empty">No pude leer Experiment Engine: '+esc(err.message)+'</div>';}}
loadExperiments();setInterval(loadExperiments,60000);})();
</script>`;

function injectExperimentPanel(html) {
  if (!html.includes('id="lumenExperimentStyle"')) html = html.replace("</head>", EXP_STYLE + "</head>");
  if (!html.includes('data-tab="experiments"')) {
    for (const target of ['data-tab="commercial">Ventas</button>', 'data-tab="commercial">Comercial</button>']) {
      if (html.includes(target)) { html = html.replace(target, target + '<button class="tab" data-tab="experiments">Experimentos</button>'); break; }
    }
  }
  if (!html.includes('id="experiments"')) {
    if (html.includes('<section class="page" id="infra">')) html = html.replace('<section class="page" id="infra">', EXP_SECTION + '<section class="page" id="infra">');
    else html = html.replace('<footer class="footer">', EXP_SECTION + '<footer class="footer">');
  }
  if (!html.includes('id="lumenExperimentScript"')) html = html.replace("</body>", EXP_SCRIPT + "</body>");
  return html;
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/api/experiments") {
      const auth = authOK(request, env);
      if (auth === null) return new Response("LUMEN dashboard todavía no tiene contraseña configurada.", { status: 503, headers: { "Cache-Control": "no-store" } });
      if (!auth) return new Response("LUMEN · acceso restringido", { status: 401, headers: { "WWW-Authenticate": 'Basic realm="LUMEN Centro de Comando", charset="UTF-8"', "Cache-Control": "no-store" } });
      try {
        const { state, manifest } = await loadState(env);
        return Response.json(experimentSummary(state, manifest), { headers: { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" } });
      } catch (error) {
        return Response.json({ ok: false, error: String(error?.message || error) }, { status: 503, headers: { "Cache-Control": "no-store" } });
      }
    }
    const response = await base.fetch(request, env, ctx);
    const contentType = String(response.headers.get("content-type") || "");
    if (request.method !== "GET" || response.status !== 200 || !contentType.includes("text/html")) return response;
    const html = injectExperimentPanel(await response.text());
    const headers = new Headers(response.headers);
    headers.delete("content-length");
    headers.set("cache-control", "no-store");
    return new Response(html, { status: response.status, statusText: response.statusText, headers });
  },
};
