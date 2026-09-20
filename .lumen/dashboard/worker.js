const STATE_KEY = "global";

function unauthorized() {
  return new Response("LUMEN · acceso restringido", {
    status: 401,
    headers: { "WWW-Authenticate": 'Basic realm="LUMEN"', "Cache-Control": "no-store" },
  });
}

function locked() {
  return new Response("LUMEN dashboard todavía no tiene contraseña configurada.", {
    status: 503,
    headers: { "Cache-Control": "no-store" },
  });
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
    const user = decoded.slice(0, i);
    const pass = decoded.slice(i + 1);
    return user === String(env.LUMEN_DASHBOARD_USER || "socio") && pass === password;
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
    "SELECT encoding, chunk_count, payload_sha256, uncompressed_bytes, updated_at FROM lumen_state_manifest WHERE state_key = ? LIMIT 1"
  ).bind(STATE_KEY).first();
  if (!manifest) throw new Error("state_not_initialized");
  if (manifest.encoding !== "zlib+base64+json") throw new Error("unsupported_state_encoding");

  const rows = await env.DB.prepare(
    "SELECT chunk_no, payload FROM lumen_state_chunks WHERE state_key = ? ORDER BY chunk_no ASC"
  ).bind(STATE_KEY).all();
  const chunks = rows.results || [];
  if (chunks.length !== Number(manifest.chunk_count || 0)) throw new Error("incomplete_state_chunks");

  const encoded = chunks.map((r) => String(r.payload || "")).join("");
  const binary = atob(encoded);
  const compressed = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) compressed[i] = binary.charCodeAt(i);

  const stream = new Blob([compressed]).stream().pipeThrough(new DecompressionStream("deflate"));
  const raw = new Uint8Array(await new Response(stream).arrayBuffer());
  const digest = await sha256Hex(raw);
  if (manifest.payload_sha256 && digest !== manifest.payload_sha256) throw new Error("state_checksum_mismatch");

  const state = JSON.parse(new TextDecoder().decode(raw));
  return { state, manifest };
}

function n(v) { return Number(v || 0); }
function arr(v) { return Array.isArray(v) ? v : []; }
function obj(v) { return v && typeof v === "object" && !Array.isArray(v) ? v : {}; }

function summarize(state, manifest) {
  const funnel = obj(state.business_funnel);
  const readiness = obj(state.external_market_readiness);
  const scout = obj(state.scout);
  const governor = obj(scout.search_budget_governor);
  const workforce = obj(state.agent_workforce);
  const watchdog = obj(state.system_watchdog);
  const revenue = obj(state.revenue_execution_v2);
  const revenueFunnel = obj(revenue.revenue_funnel);
  const revCounts = obj(revenueFunnel.counts);
  const secretary = obj(state.executive_secretary_private_bridge || state.executive_secretary);
  const activities = arr(state.activity).slice(0, 30).map((x) => ({ ts: x.ts || "", msg: x.msg || "" }));
  const pending = arr(secretary.pending).slice(0, 12).map((x) => ({
    title: x.title || "Pendiente", reason: x.reason || "", priority: n(x.priority), risk: x.risk || "",
  }));

  return {
    status: {
      runtime: "LUMEN Zero",
      persistence: "Cloudflare D1",
      state_updated_at: manifest.updated_at || state.last_tick || null,
      ticks: n(state.ticks),
      watchdog_status: watchdog.status || "unknown",
      watchdog_score: n(watchdog.score_pct),
      company_cycle: n(workforce.company_cycle),
      fleet_size: n(workforce.fleet_size),
      worker_status: workforce.status || "unknown",
    },
    funnel: {
      research_leads: n(funnel.research_leads ?? state.research_leads?.length),
      candidate_accounts: n(funnel.candidate_accounts ?? state.candidate_accounts?.length),
      verified_companies: n(funnel.verified_companies),
      verified_buyers: n(funnel.verified_buyers),
      verified_suppliers: n(funnel.verified_suppliers),
      verified_contacts: n(funnel.verified_commercial_channels || funnel.verified_corporate_emails),
      buyers_with_demand: n(funnel.buyers_with_public_demand),
      opportunities: n(funnel.evidence_backed_opportunities ?? revCounts.market_opportunities),
      outbound_sent: n(funnel.outbound_sent),
      inbound_received: n(funnel.inbound_received),
      proposals: n(funnel.proposals),
      close_ready: n(funnel.close_ready),
    },
    scout: {
      provider: obj(state.scout_status).provider || scout.provider || "unknown",
      paid_search: Boolean(obj(state.scout_status).paid_search),
      effective_used: n(governor.effective_total_used),
      effective_remaining: n(governor.effective_total_remaining),
      general_remaining: n(governor.general_retail_remaining),
      demand_remaining: n(governor.demand_remaining),
      hard_cap: n(governor.total_daily_cap || obj(state.scout_status).daily_query_budget),
      strategy: scout.strategy || "",
    },
    outbound: {
      live: Boolean(readiness.outbound_live),
      mail_ready: Boolean(readiness.mail_transport_ready),
      mail_provider: readiness.mail_provider || null,
      eligible_prospects: n(readiness.eligible_external_prospects),
      blocker: readiness.primary_blocker || null,
      outbox_ready: n(readiness.outbox_ready),
      sent_or_delivered: n(readiness.outbox_sent_or_delivered),
      failed: n(readiness.outbox_failed),
      social_waiting: n(readiness.social_jobs_awaiting_authorized_connector),
    },
    revenue: {
      realized_usd: n(obj(state.money_engine).realized_revenue_truth_usd || obj(state.service_growth_pipeline).realized_service_revenue_usd),
      opportunities: n(revCounts.market_opportunities),
      proposals: n(revCounts.proposals),
      active_deals: n(revCounts.active_deals),
      close_ready: n(revCounts.close_ready),
    },
    activity: activities,
    pending,
  };
}

const HTML = `<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>LUMEN · Centro de Comando</title>
<style>
:root{color-scheme:dark;--bg:#071018;--card:#0c1720;--line:#183343;--muted:#87a1b2;--lime:#d7ff64;--good:#9ce8c5;--bad:#ff9d9d}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at top right,#102b38 0,#071018 38%);color:#eef6fa;font:14px Inter,system-ui,-apple-system,sans-serif;padding:18px}.wrap{max-width:1280px;margin:auto}.top{display:flex;justify-content:space-between;gap:16px;align-items:end;margin:10px 0 18px}.logo{font-size:30px;font-weight:900;letter-spacing:.17em}.sub{color:var(--muted);margin-top:5px}.pill{border:1px solid #2a5163;border-radius:999px;padding:8px 11px;color:var(--good);background:#0b211b}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.card{background:linear-gradient(180deg,#0e1c26,#0a151d);border:1px solid var(--line);border-radius:16px;padding:15px;box-shadow:0 14px 30px #0004}.label{text-transform:uppercase;letter-spacing:.12em;font-size:10px;color:var(--muted)}.kpi{font-size:28px;font-weight:850;margin-top:7px}.good{color:var(--good)}.bad{color:var(--bad)}.section{margin-top:12px}.cols{display:grid;grid-template-columns:1.25fr 1fr;gap:12px}.bar{height:8px;background:#071018;border:1px solid #173241;border-radius:999px;overflow:hidden;margin-top:10px}.bar>i{display:block;height:100%;background:var(--lime);width:0}.row{display:flex;justify-content:space-between;gap:10px;padding:9px 0;border-bottom:1px solid #17303e}.tiny{font-size:12px;color:var(--muted)}.activity{max-height:420px;overflow:auto}.event{padding:10px 0;border-bottom:1px solid #17303e}.time{font-size:11px;color:#668396}.btn{background:var(--lime);color:#071018;border:0;border-radius:10px;padding:10px 13px;font-weight:850;cursor:pointer}.statusline{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.dot{width:8px;height:8px;border-radius:50%;background:var(--good)}@media(max-width:850px){.grid{grid-template-columns:1fr 1fr}.cols{grid-template-columns:1fr}.top{align-items:flex-start;flex-direction:column}}@media(max-width:520px){body{padding:12px}.grid{grid-template-columns:1fr 1fr}.kpi{font-size:24px}.logo{font-size:26px}}
</style></head><body><div class="wrap">
<div class="top"><div><div class="logo">LUMEN</div><div class="sub">Centro de Comando · Zero Cost Runtime</div></div><div class="statusline"><span class="pill" id="updated">Cargando…</span><button class="btn" onclick="load()">Actualizar</button></div></div>
<div class="grid">
<div class="card"><div class="label">Leads de investigación</div><div class="kpi" id="leads">–</div></div>
<div class="card"><div class="label">Empresas verificadas</div><div class="kpi" id="verified">–</div></div>
<div class="card"><div class="label">Prospectos habilitados</div><div class="kpi" id="eligible">–</div></div>
<div class="card"><div class="label">Ingresos realizados USD</div><div class="kpi good" id="revenue">–</div></div>
</div>
<div class="grid section">
<div class="card"><div class="label">Watchdog</div><div class="kpi" id="watchdog">–</div><div class="bar"><i id="watchbar"></i></div></div>
<div class="card"><div class="label">Scout · búsquedas restantes</div><div class="kpi" id="searches">–</div><div class="tiny" id="searchdetail"></div></div>
<div class="card"><div class="label">Email</div><div class="kpi" id="mail">–</div><div class="tiny" id="maildetail"></div></div>
<div class="card"><div class="label">Fuerza digital</div><div class="kpi" id="fleet">–</div><div class="tiny" id="fleetdetail"></div></div>
</div>
<div class="cols section">
<div class="card"><div class="label">Embudo comercial real</div><div id="funnel"></div></div>
<div class="card"><div class="label">Bloqueo actual</div><div class="kpi" id="blocker">–</div><div class="tiny" id="blockerdetail"></div></div>
</div>
<div class="cols section">
<div class="card"><div class="label">Actividad reciente</div><div class="activity" id="activity"></div></div>
<div class="card"><div class="label">Prioridades de LUMEN</div><div id="pending"></div></div>
</div>
</div><script>
const $=id=>document.getElementById(id); const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function rows(items){return items.map(([a,b])=>'<div class="row"><span>'+esc(a)+'</span><b>'+esc(b)+'</b></div>').join('')}
async function load(){try{const r=await fetch('/api/summary',{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);const d=await r.json();$('updated').textContent='Estado: '+(d.status.state_updated_at||'sin fecha');$('leads').textContent=d.funnel.research_leads;$('verified').textContent=d.funnel.verified_companies;$('eligible').textContent=d.outbound.eligible_prospects;$('revenue').textContent='$'+Number(d.revenue.realized_usd||0).toFixed(2);$('watchdog').textContent=d.status.watchdog_score.toFixed(1)+'%';$('watchbar').style.width=Math.max(0,Math.min(100,d.status.watchdog_score))+'%';$('searches').textContent=d.scout.effective_remaining+'/'+d.scout.hard_cap;$('searchdetail').textContent='General '+d.scout.general_remaining+' · Demanda '+d.scout.demand_remaining+' · '+d.scout.provider;$('mail').textContent=d.outbound.mail_ready&&d.outbound.live?'OPERATIVO':'EN ESPERA';$('mail').className='kpi '+(d.outbound.mail_ready&&d.outbound.live?'good':'bad');$('maildetail').textContent=(d.outbound.mail_provider||'sin proveedor')+' · enviados '+d.funnel.outbound_sent;$('fleet').textContent=d.status.fleet_size;$('fleetdetail').textContent='ciclo '+d.status.company_cycle+' · '+d.status.worker_status;$('blocker').textContent=d.outbound.blocker||'SIN BLOQUEO';$('blocker').className='kpi '+(d.outbound.blocker?'bad':'good');$('blockerdetail').textContent='Elegibles '+d.outbound.eligible_prospects+' · outbox '+d.outbound.outbox_ready+' · social en espera '+d.outbound.social_waiting;$('funnel').innerHTML=rows([['Leads',d.funnel.research_leads],['Candidatas',d.funnel.candidate_accounts],['Verificadas',d.funnel.verified_companies],['Compradores verificados',d.funnel.verified_buyers],['Proveedores verificados',d.funnel.verified_suppliers],['Con contacto verificado',d.funnel.verified_contacts],['Demanda pública',d.funnel.buyers_with_demand],['Oportunidades',d.funnel.opportunities],['Propuestas',d.funnel.proposals],['Close ready',d.funnel.close_ready]]);$('activity').innerHTML=d.activity.length?d.activity.map(x=>'<div class="event"><div>'+esc(x.msg)+'</div><div class="time">'+esc(x.ts)+'</div></div>').join(''):'<div class="tiny">Sin actividad.</div>';$('pending').innerHTML=d.pending.length?d.pending.map(x=>'<div class="event"><b>'+esc(x.title)+'</b><div class="tiny">'+esc(x.reason)+'</div></div>').join(''):'<div class="tiny">Sin pendientes prioritarios.</div>';}catch(e){$('updated').textContent='Error leyendo estado';console.error(e)}}load();setInterval(load,30000);
</script></body></html>`;

export default {
  async fetch(request, env) {
    const auth = authOK(request, env);
    if (auth === null) return locked();
    if (!auth) return unauthorized();

    const url = new URL(request.url);
    if (url.pathname === "/health") {
      return Response.json({ ok: true, service: "lumen-zero-dashboard", backend: "cloudflare-worker+d1" }, { headers: { "Cache-Control": "no-store" } });
    }
    if (url.pathname === "/api/summary") {
      try {
        const { state, manifest } = await loadState(env);
        return Response.json(summarize(state, manifest), { headers: { "Cache-Control": "no-store" } });
      } catch (e) {
        return Response.json({ ok: false, error: String(e && e.message || e) }, { status: 503, headers: { "Cache-Control": "no-store" } });
      }
    }
    if (url.pathname === "/" || url.pathname === "/index.html") {
      return new Response(HTML, { headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff" } });
    }
    return new Response("Not found", { status: 404 });
  },
};
