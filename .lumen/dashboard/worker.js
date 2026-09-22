const STATE_KEY = "global";
const PUBLIC_WEB = "https://lumen-zero-public.lumen-b2b.workers.dev";
const INSTAGRAM_URL = "https://www.instagram.com/lumen.b2b/";
const CATALOG_VERSION = "2026-09-21";
const SERVICE_CATALOG = [
  { id: "SRV-QUOTECHECK", name: "LUMEN QuoteCheck Global", from_usd: 59, desc: "Revisión documental y comparación estructurada de cotizaciones B2B con referencias públicas disponibles." },
  { id: "SRV-SUPPLIERCHECK", name: "LUMEN SupplierCheck", from_usd: 79, desc: "Investigación de identidad, canales oficiales, señales públicas y riesgo comercial de proveedores." },
  { id: "SRV-TENDER-HUNTER", name: "LUMEN Tender Hunter Global", from_usd: 99, desc: "Detección y preanálisis de oportunidades y licitaciones públicas relevantes." },
  { id: "SRV-SOURCING-EXPRESS", name: "LUMEN Sourcing Express", from_usd: 149, desc: "Investigación y preselección de proveedores para una necesidad B2B concreta." },
  { id: "SRV-B2B-PROSPECTING", name: "LUMEN Prospección B2B", from_usd: 199, desc: "Empresas objetivo, señales públicas y canales corporativos compatibles con una oferta B2B." },
  { id: "SRV-EXPORT-SCOUT", name: "LUMEN Export Scout", from_usd: 249, desc: "Búsqueda de mercados, importadores, distribuidores y compradores con evidencia pública." },
];

function unauthorized() {
  return new Response("LUMEN · acceso restringido", {
    status: 401,
    headers: {
      "WWW-Authenticate": 'Basic realm="LUMEN Centro de Comando", charset="UTF-8"',
      "Cache-Control": "no-store",
    },
  });
}
function locked() {
  return new Response("LUMEN dashboard todavía no tiene contraseña configurada.", {
    status: 503,
    headers: { "Cache-Control": "no-store" },
  });
}
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
    const user = decoded.slice(0, i);
    const pass = decoded.slice(i + 1);
    return constantTimeEqual(user, String(env.LUMEN_DASHBOARD_USER || "socio")) && constantTimeEqual(pass, password);
  } catch {
    return false;
  }
}
async function sha256Hex(bytes) {
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(hash)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
async function hmacHex(secret, value) {
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(String(secret || "")),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(value));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
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
  const encoded = chunks.map((r) => String(r.payload || "")).join("");
  const binary = atob(encoded);
  const compressed = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) compressed[i] = binary.charCodeAt(i);
  const stream = new Blob([compressed]).stream().pipeThrough(new DecompressionStream("deflate"));
  const raw = new Uint8Array(await new Response(stream).arrayBuffer());
  const digest = await sha256Hex(raw);
  if (manifest.payload_sha256 && digest !== manifest.payload_sha256) throw new Error("state_checksum_mismatch");
  return { state: JSON.parse(new TextDecoder().decode(raw)), manifest };
}
const n = (v) => Number(v || 0);
const arr = (v) => Array.isArray(v) ? v : [];
const obj = (v) => v && typeof v === "object" && !Array.isArray(v) ? v : {};
const s = (v, d = "") => String(v ?? d);

async function ensureControlSchema(env) {
  await env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_instagram_control_posts (job_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, audience TEXT, campaign_id TEXT, caption TEXT, image_url TEXT, state_status TEXT, approval_status TEXT, last_error TEXT, created_at TEXT, updated_at TEXT NOT NULL)").run();
  await env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_instagram_control_commands (id TEXT PRIMARY KEY, job_id TEXT NOT NULL, fingerprint TEXT NOT NULL, action TEXT NOT NULL, created_at TEXT NOT NULL, processed INTEGER NOT NULL DEFAULT 0, processed_at TEXT, result TEXT)").run();
  await env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_instagram_control_commands_pending ON lumen_instagram_control_commands(processed,created_at)").run();
}
async function safeRows(env, sql, binds = []) {
  try {
    let q = env.DB.prepare(sql);
    if (binds.length) q = q.bind(...binds);
    const result = await q.all();
    return result.results || [];
  } catch {
    return [];
  }
}
async function publicHealth() {
  try {
    const r = await fetch(`${PUBLIC_WEB}/health`, { headers: { "Accept": "application/json" }, cf: { cacheTtl: 0 } });
    return r.ok ? "online" : `http_${r.status}`;
  } catch {
    return "unreachable";
  }
}
function summarize(state, manifest) {
  const funnel = obj(state.business_funnel);
  const readiness = obj(state.external_market_readiness);
  const scoutStatus = obj(state.scout_status);
  const scoutBudget = obj(state.scout_budget);
  const demandBudget = obj(state.demand_search_budget);
  const adaptiveBudget = obj(state.adaptive_search_budget);
  const governor = obj(obj(state.scout).search_budget_governor || state.search_budget_governor);
  const watchdog = obj(state.system_watchdog);
  const workforceRoot = obj(state.agent_workforce);
  const workforce = obj(workforceRoot.last_cycle);
  const moneyEngine = obj(state.money_engine);
  const secretary = obj(state.executive_secretary_private_bridge || state.executive_secretary);
  const policies = obj(state.policies);
  const instagram = obj(state.instagram_publish_control);
  const instagramPoller = obj(state.instagram_conversation_poller);
  const instagramOperator = obj(state.instagram_operator);
  const zeroOwner = obj(state.zero_owner_notifications);
  const marketIntel = obj(state.market_intelligence_runtime || obj(state.partner_network).market_intelligence);
  const expansion = obj(state.expansion_revenue_runtime);
  const continuous = obj(state.continuous_revenue_drive);
  const learning = obj(state.continuous_learning);
  const revenueOS = obj(state.revenue_os_v3);

  const allOpportunities = arr(state.opportunities);
  const allDeals = arr(state.deals);
  const allApprovals = arr(state.approvals).filter((a) => s(a.status).toLowerCase() === "pending");
  const opportunities = allOpportunities.slice().sort((a,b)=>n(b.score)-n(a.score)).slice(0,20).map((o)=>({
    id:s(o.id,"—"), buyer:s(o.buyer || o.company || o.account,"—"), need:s(o.need || o.category || o.title,"—"),
    supplier:s(o.supplier,"—"), score:n(o.score), pipeline:n(o.pipeline || o.value || o.amount), status:s(o.status || o.stage,"—"), source:s(o.source,"—")
  }));
  const deals = allDeals.slice().sort((a,b)=>n(b.expected_value || b.pipeline)-n(a.expected_value || a.pipeline)).slice(0,20).map((d)=>({
    id:s(d.id,"—"), buyer:s(d.buyer || d.company || d.account,"—"), stage:s(d.stage || d.status,"—"),
    close_prob:n(d.close_prob), expected_value:n(d.expected_value), pipeline:n(d.pipeline), company_profit:n(d.company_profit), company_share_pct:n(d.company_share_pct), source:s(d.source,"—")
  }));
  const approvals = allApprovals.slice(0,20).map((a)=>({
    id:s(a.id,"—"), deal_id:s(a.deal_id,"—"), company_profit:n(a.company_profit), company_share_pct:n(a.company_share_pct), reason:s(a.reason || a.kind,"requiere aprobación humana")
  }));
  const outbox = arr(state.outbox).slice(-20).reverse().map((m)=>({
    id:s(m.id,"—"), counterparty:s(m.counterparty || m.to || m.company,"—"), kind:s(m.kind || m.channel || m.type,"—"), status:s(m.status,"—")
  }));
  const offers = [...arr(state.offers), ...arr(state.supplier_quotes), ...arr(state.quotes)].slice(-20).reverse().map((o)=>({
    id:s(o.id,"—"), supplier:s(o.supplier || o.company || o.vendor,"—"), amount:n(o.amount || o.amount_usd || o.total), lead_days:n(o.lead_days || o.delivery_days), source:s(o.source,"—"), status:s(o.status,"—")
  }));
  const activity = arr(state.activity).slice(0,50).map((x)=>({ts:s(x.ts),msg:s(x.msg)}));
  const pending = arr(secretary.pending).slice(0,20).map((x)=>({title:s(x.title,"Pendiente"),reason:s(x.reason),priority:n(x.priority),risk:s(x.risk),owner:s(x.owner,"LUMEN")}));
  const goals = arr(state.standing_goals).slice(0,10);
  const researchLeads = arr(state.research_leads).slice(-20).reverse().map((x)=>({
    title:s(x.title || x.name || x.company || x.domain,"Lead"), url:s(x.url || x.source_url), source:s(x.source || x.provider), status:s(x.status || x.verification_status,"research")
  }));

  const pipeline = allOpportunities.reduce((a,o)=>a+n(o.pipeline || o.value || o.amount),0);
  const expectedValue = allDeals.reduce((a,d)=>a+n(d.expected_value),0);
  const potentialProfit = allDeals.filter((d)=>!s(d.stage || d.status).toLowerCase().includes("cerrado")).reduce((a,d)=>a+n(d.company_profit),0);
  const transactions = arr(state.transactions);
  const registeredProfit = transactions.reduce((a,t)=>a+n(t.company_profit || t.profit || t.amount),0);
  const realizedRevenue = n(moneyEngine.realized_revenue_truth_usd || obj(state.service_growth_pipeline).realized_service_revenue_usd || expansion.revenue_generated_usd);
  const generalDaily = n(adaptiveBudget.general_pool_daily || scoutBudget.daily_budget || scoutStatus.general_retail_pool_daily || governor.general_retail_pool_daily);
  const demandDaily = n(adaptiveBudget.demand_reserved_daily || demandBudget.daily_budget || scoutStatus.demand_reserved_daily || governor.demand_reserved_daily);
  const hardCap = n(adaptiveBudget.total_daily_cap || scoutStatus.daily_query_budget || scoutBudget.total_daily_cap || governor.total_daily_cap || generalDaily + demandDaily);
  const generalUsed = n(governor.general_retail_used ?? scoutBudget.queries_used);
  const demandUsed = n(governor.demand_used ?? demandBudget.queries_used);
  const totalUsed = Math.min(hardCap || generalUsed + demandUsed, generalUsed + demandUsed);
  const remaining = Math.max(0, hardCap - generalUsed - demandUsed);
  const fleetSize = n(workforce.fleet_size || workforceRoot.roster_count || arr(workforceRoot.roster).length);

  return {
    status:{
      updated_at:manifest.updated_at || state.last_tick || null, ticks:n(state.ticks), last_tick:s(state.last_tick), last_origin:s(state.last_tick_origin,"—"),
      watchdog_score:n(watchdog.score_pct), watchdog_status:s(watchdog.status,"unknown"), watchdog_passed:n(watchdog.passed), watchdog_total:n(watchdog.total),
      fleet_size:fleetSize, worker_status:s(workforce.status,fleetSize?"healthy":"unknown"), persistence:"Cloudflare D1", state_bytes:n(manifest.uncompressed_bytes), cycle:n(workforce.company_cycle || state.ticks)
    },
    money:{pipeline,expected_value:expectedValue,potential_profit:potentialProfit,registered_profit:registeredProfit,realized_revenue:realizedRevenue,pending_closures:allApprovals.length},
    goals, opportunities, deals, approvals, outbox, offers, activity, pending, researchLeads,
    policies:{min_share:n(policies.min_company_share_pct),target_share:n(policies.target_company_share_pct),risk_reserve:n(policies.risk_reserve_pct)},
    funnel:{
      leads:n(funnel.research_leads ?? arr(state.research_leads).length), candidates:n(funnel.candidate_accounts ?? arr(state.candidate_accounts).length),
      verified:n(funnel.verified_companies), buyers:n(funnel.verified_buyers), suppliers:n(funnel.verified_suppliers), contacts:n(funnel.verified_commercial_channels || funnel.verified_corporate_emails),
      demand:n(funnel.buyers_with_public_demand), opportunities:n(funnel.evidence_backed_opportunities), proposals:n(funnel.proposals), close_ready:n(funnel.close_ready), outbound_sent:n(funnel.outbound_sent), inbound:n(funnel.inbound_received)
    },
    scout:{provider:s(scoutStatus.provider,"bing_rss_public"),used:totalUsed,remaining,hard_cap:hardCap,general_used:generalUsed,demand_used:demandUsed,budget_exhausted:remaining<=0},
    outbound:{
      live:Boolean(readiness.outbound_live), mail_ready:Boolean(readiness.mail_transport_ready), mail_provider:s(readiness.mail_provider,"—"),
      eligible:n(readiness.eligible_external_prospects), blocker:s(readiness.primary_blocker), failed:n(readiness.outbox_failed),
      instagram:Boolean(instagram.connector_configured), instagram_send:Boolean(instagramOperator.send_enabled), instagram_inbox:s(instagramPoller.status,"—"),
      whatsapp:false, owner_email_fallback:Boolean(zeroOwner.active), social_waiting:n(readiness.social_jobs_awaiting_authorized_connector)
    },
    intelligence:{
      market_status:s(marketIntel.status,"active"), authority:s(marketIntel.authority,"research_only"), observations:n(marketIntel.observations_total),
      products:n(expansion.products_known), companies:n(expansion.companies_known), catalogs:n(expansion.catalogs_indexed), lane:s(continuous.primary_lane,"—"),
      action:s(continuous.primary_action,"—"), learning_status:s(learning.status,"active"), revenue_os:s(revenueOS.status,"active")
    },
    governance:{
      financial_commitments:false, contracts:"aprobación humana", unverified_contact:"no enviar", live_outbound:Boolean(readiness.outbound_live),
      automation_disclosed:Boolean(readiness.automation_disclosure || state.disclose_automation), instagram_posts:"aprobación humana por publicación", paid_media:"aprobación humana", new_connectors:"aprobación humana"
    }
  };
}
async function instagramPosts(env) {
  await ensureControlSchema(env);
  return safeRows(env, "SELECT job_id,fingerprint,audience,campaign_id,caption,image_url,state_status,approval_status,last_error,created_at,updated_at FROM lumen_instagram_control_posts ORDER BY updated_at DESC LIMIT 50");
}
async function withCommandTokens(rows, env) {
  const secret = String(env.LUMEN_DASHBOARD_PASSWORD || "");
  const out = [];
  for (const row of rows) {
    const approve = await hmacHex(secret, `${row.job_id}|${row.fingerprint}|approve`);
    const reject = await hmacHex(secret, `${row.job_id}|${row.fingerprint}|reject`);
    out.push({ ...row, approve_token: approve, reject_token: reject });
  }
  return out;
}
async function readUnifiedData(env) {
  const {state,manifest} = await loadState(env);
  const [postsRaw,inquiries,journal,commands,webStatus] = await Promise.all([
    instagramPosts(env),
    safeRows(env, "SELECT id,created_at,service_id,email,company,name,need,source,processed,processed_at FROM lumen_public_inquiries ORDER BY created_at DESC LIMIT 30"),
    safeRows(env, "SELECT cycle,recorded_at,local_time,status,source FROM lumen_cycle_journal ORDER BY cycle DESC LIMIT 30"),
    safeRows(env, "SELECT id,job_id,action,created_at,processed,processed_at,result FROM lumen_instagram_control_commands ORDER BY created_at DESC LIMIT 20"),
    publicHealth(),
  ]);
  const posts = await withCommandTokens(postsRaw, env);
  const catalogAverage = SERVICE_CATALOG.reduce((a,x)=>a+x.from_usd,0) / SERVICE_CATALOG.length;
  return {
    ...summarize(state,manifest),
    catalog:{ version:CATALOG_VERSION, services:SERVICE_CATALOG, floor_usd:Math.min(...SERVICE_CATALOG.map(x=>x.from_usd)), ceiling_usd:Math.max(...SERVICE_CATALOG.map(x=>x.from_usd)), average_usd:catalogAverage },
    instagram_posts: posts,
    instagram_commands: commands,
    public_inquiries: inquiries,
    cycle_journal: journal,
    services:{ public_web:{url:PUBLIC_WEB,status:webStatus}, instagram:{url:INSTAGRAM_URL,status:posts.length?"operational":"connected"}, dashboard:{status:"online"} }
  };
}
async function handleInstagramCommand(request, env) {
  const form = await request.formData();
  const jobId = String(form.get("job_id") || "").slice(0,220);
  const fingerprint = String(form.get("fingerprint") || "").slice(0,128);
  const action = String(form.get("action") || "").toLowerCase();
  const token = String(form.get("token") || "");
  if (!jobId || !fingerprint || !["approve","reject"].includes(action)) return new Response("invalid_command", {status:400});
  const expected = await hmacHex(String(env.LUMEN_DASHBOARD_PASSWORD || ""), `${jobId}|${fingerprint}|${action}`);
  if (!constantTimeEqual(token, expected)) return new Response("invalid_command_token", {status:403});
  await ensureControlSchema(env);
  const current = await env.DB.prepare("SELECT fingerprint,state_status,approval_status FROM lumen_instagram_control_posts WHERE job_id=? LIMIT 1").bind(jobId).first();
  if (!current) return new Response("post_not_found", {status:404});
  if (!constantTimeEqual(String(current.fingerprint || ""), fingerprint)) return new Response("content_changed_reload", {status:409});
  if (String(current.state_status || "").toUpperCase() === "PUBLISHED") return new Response("already_published", {status:409});
  await env.DB.prepare("INSERT INTO lumen_instagram_control_commands(id,job_id,fingerprint,action,created_at,processed) VALUES(?,?,?,?,?,0)")
    .bind(crypto.randomUUID(), jobId, fingerprint, action, new Date().toISOString()).run();
  return new Response(null, {status:303, headers:{Location:`/?tab=instagram&result=${encodeURIComponent(action === "approve" ? "Aprobación registrada. LUMEN la procesará en el próximo ciclo." : "Publicación descartada. LUMEN procesará el descarte en el próximo ciclo.")}`}});
}

const HTML = `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#061019"><title>LUMEN · Centro de Comando</title><style>
:root{color-scheme:dark;--bg:#061019;--panel:#0c1821;--panel2:#101f29;--line:#1d3847;--text:#eef5f7;--muted:#8fa7b3;--lime:#d9ff65;--good:#9de8c5;--bad:#ff9992;--warn:#ffd36e;--blue:#83d9ff}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:radial-gradient(circle at 100% 0,#12303d 0,#061019 36%) fixed;color:var(--text);font:14px Inter,system-ui,-apple-system,Segoe UI,Arial,sans-serif}.wrap{max-width:1450px;margin:auto;padding:18px}.top{display:flex;align-items:flex-end;justify-content:space-between;gap:16px}.brand{font-weight:950;font-size:34px;letter-spacing:.16em}.subtitle{color:var(--muted);margin-top:4px}.toplinks{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}.link,.refresh{border:1px solid #2c5264;background:#0c1d27;color:#d9edf5;border-radius:10px;padding:9px 11px;text-decoration:none;font-weight:800;cursor:pointer}.refresh{background:var(--lime);color:#061019;border-color:var(--lime)}.tabs{display:flex;gap:8px;overflow:auto;padding:18px 0 12px;position:sticky;top:0;z-index:5;background:linear-gradient(180deg,#061019 74%,transparent)}.tab{white-space:nowrap;border:1px solid var(--line);border-radius:999px;background:#0b1720;color:var(--muted);padding:9px 13px;font-weight:850;cursor:pointer}.tab.active{background:var(--lime);color:#061019;border-color:var(--lime)}.page{display:none}.page.active{display:block}.grid{display:grid;gap:11px}.g6{grid-template-columns:repeat(6,1fr)}.g5{grid-template-columns:repeat(5,1fr)}.g4{grid-template-columns:repeat(4,1fr)}.g3{grid-template-columns:repeat(3,1fr)}.g2{grid-template-columns:repeat(2,1fr)}.card{background:linear-gradient(180deg,#0e1b24,#09151d);border:1px solid var(--line);border-radius:16px;padding:15px;overflow:auto;box-shadow:0 10px 28px #0004}.klabel{font-size:10px;text-transform:uppercase;letter-spacing:.11em;color:var(--muted);font-weight:900}.kpi{font-size:27px;font-weight:950;margin-top:7px}.good{color:var(--good)}.bad{color:var(--bad)}.warn{color:var(--warn)}.blue{color:var(--blue)}.lime{color:var(--lime)}h2{font-size:20px;margin:0 0 12px}.section{margin-top:12px}.note{color:var(--muted);line-height:1.5}.statusline{display:flex;justify-content:space-between;gap:12px;padding:10px 0;border-bottom:1px solid #17303e}.statusline:last-child{border:0}.chip{display:inline-block;border:1px solid #2b4a58;border-radius:999px;padding:4px 8px;font-size:11px;color:var(--muted)}.chip.ok{color:var(--good);border-color:#315d50}.chip.no{color:var(--bad);border-color:#653d3d}.bar{height:8px;border:1px solid #23404d;background:#071019;border-radius:99px;overflow:hidden;margin-top:9px}.bar i{height:100%;display:block;background:linear-gradient(90deg,var(--lime),var(--good));width:0}table{width:100%;border-collapse:collapse;min-width:600px}th,td{text-align:left;padding:9px 7px;border-bottom:1px solid #17303e;vertical-align:top}th{font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:#7694a4}.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px}.small{font-size:12px;color:var(--muted)}.empty{padding:22px;color:var(--muted);text-align:center;border:1px dashed var(--line);border-radius:12px}.post{display:grid;grid-template-columns:260px 1fr;gap:16px;margin-bottom:12px}.post img{width:100%;aspect-ratio:4/5;object-fit:cover;border-radius:12px;background:#061019}.post pre{font:inherit;white-space:pre-wrap;color:#dce8ec;max-height:260px;overflow:auto}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:13px}.actions form{margin:0}.approve,.reject{border:0;border-radius:9px;padding:10px 14px;font-weight:950;cursor:pointer}.approve{background:var(--lime);color:#061019}.reject{background:#35191c;color:#ffd2ce;border:1px solid #6d383d}.result{margin:0 0 12px;padding:11px 13px;border:1px solid #397454;background:#133322;border-radius:11px;color:var(--good)}.activity{max-height:560px;overflow:auto}.event{padding:9px 0;border-bottom:1px solid #17303e}.footer{padding:30px 0 15px;color:#607c8a;font-size:12px}.plans{display:grid;grid-template-columns:repeat(3,1fr);gap:11px}.plan{position:relative;min-height:205px}.plan .price{font-size:28px;font-weight:950;color:var(--lime);margin:8px 0}.plan .desc{color:#b5c8d1;line-height:1.5}.plan .code{margin-top:14px}.scenario{padding:14px;border:1px solid #23404d;border-radius:12px;background:#08141c}.scenario strong{display:block;font-size:20px;color:var(--good);margin-top:5px}.focus{border-color:#4d6b28;background:linear-gradient(180deg,#142018,#09151d)}@media(max-width:1150px){.g6,.g5{grid-template-columns:repeat(3,1fr)}.g4{grid-template-columns:repeat(2,1fr)}.g3{grid-template-columns:1fr 1fr}.plans{grid-template-columns:repeat(2,1fr)}}@media(max-width:760px){.wrap{padding:12px}.top{align-items:flex-start;flex-direction:column}.toplinks{justify-content:flex-start}.brand{font-size:29px}.g6,.g5,.g4,.g3,.g2{grid-template-columns:1fr 1fr}.post{grid-template-columns:1fr}.post img{max-width:360px}.tabs{margin:0 -12px;padding-left:12px;padding-right:12px}.kpi{font-size:24px}.plans{grid-template-columns:1fr}}@media(max-width:430px){.g6,.g5,.g4,.g3,.g2{grid-template-columns:1fr}.toplinks .link{font-size:12px;padding:8px}.card{padding:13px}table{min-width:520px}}
</style></head><body><div class="wrap"><header class="top"><div><div class="brand">LUMEN</div><div class="subtitle">Centro de Comando · autonomía orientada a resultados · Zero Cost</div></div><div class="toplinks"><a class="link" href="${PUBLIC_WEB}" target="_blank" rel="noreferrer">Web pública ↗</a><a class="link" href="${INSTAGRAM_URL}" target="_blank" rel="noreferrer">Instagram ↗</a><button class="refresh" onclick="loadData()">Actualizar</button></div></header><nav class="tabs" id="tabs"><button class="tab active" data-tab="overview">Resumen</button><button class="tab" data-tab="commercial">Comercial</button><button class="tab" data-tab="plans">Planes USD</button><button class="tab" data-tab="scout">Scout</button><button class="tab" data-tab="instagram">Instagram</button><button class="tab" data-tab="inquiries">Consultas</button><button class="tab" data-tab="infra">Sistema</button><button class="tab" data-tab="activity">Actividad</button></nav><div id="result"></div>
<section class="page active" id="overview"><div class="grid g6"><div class="card"><div class="klabel">Ingresos realizados</div><div class="kpi good" id="realized">–</div></div><div class="card"><div class="klabel">Pipeline</div><div class="kpi" id="pipeline">–</div></div><div class="card"><div class="klabel">Valor esperado</div><div class="kpi" id="expected">–</div></div><div class="card"><div class="klabel">Ganancia potencial</div><div class="kpi" id="potential">–</div></div><div class="card"><div class="klabel">Watchdog</div><div class="kpi" id="watchdog">–</div></div><div class="card"><div class="klabel">Agentes</div><div class="kpi blue" id="fleet">–</div></div></div><div class="grid g2 section"><div class="card focus"><h2>Motor de resultados</h2><div id="resultEngine"></div></div><div class="card"><h2>Prioridad operativa</h2><div id="priority"></div></div></div><div class="grid g2 section"><div class="card"><h2>Embudo comercial</h2><div id="funnel"></div></div><div class="card"><h2>Canales y autonomía</h2><div id="channels"></div></div></div></section>
<section class="page" id="commercial"><div class="grid g5"><div class="card"><div class="klabel">Elegibles outbound</div><div class="kpi" id="eligible">–</div></div><div class="card"><div class="klabel">Cierres pendientes</div><div class="kpi" id="closures">–</div></div><div class="card"><div class="klabel">Ganancia registrada</div><div class="kpi" id="registered">–</div></div><div class="card"><div class="klabel">Outbound enviado</div><div class="kpi" id="outboundSent">–</div></div><div class="card"><div class="klabel">Inbound</div><div class="kpi" id="inbound">–</div></div></div><div class="card section"><h2>Oportunidades</h2><div id="opportunities"></div></div><div class="grid g2 section"><div class="card"><h2>Deals</h2><div id="deals"></div></div><div class="card"><h2>Aprobaciones humanas</h2><div id="approvals"></div></div></div><div class="grid g2 section"><div class="card"><h2>Ofertas / cotizaciones</h2><div id="offers"></div></div><div class="card"><h2>Salida comercial</h2><div id="outbox"></div></div></div></section>
<section class="page" id="plans"><div class="grid g4"><div class="card"><div class="klabel">Servicios activos</div><div class="kpi good" id="catalogCount">–</div></div><div class="card"><div class="klabel">Entrada</div><div class="kpi" id="catalogFloor">–</div></div><div class="card"><div class="klabel">Ticket medio catálogo</div><div class="kpi blue" id="catalogAverage">–</div></div><div class="card"><div class="klabel">Mayor precio base</div><div class="kpi" id="catalogCeiling">–</div></div></div><div class="section plans" id="plansGrid"></div><div class="card section"><h2>Escenarios de facturación</h2><p class="note">Modelo orientativo usando el ticket medio actual del catálogo. No es una promesa ni una proyección de ventas.</p><div class="grid g4" id="revenueScenarios"></div></div></section>
<section class="page" id="scout"><div class="grid g5"><div class="card"><div class="klabel">Research leads</div><div class="kpi" id="leads">–</div></div><div class="card"><div class="klabel">Verificadas</div><div class="kpi good" id="verified">–</div></div><div class="card"><div class="klabel">Contactos verificados</div><div class="kpi" id="contacts">–</div></div><div class="card"><div class="klabel">Búsquedas usadas</div><div class="kpi" id="searchUsed">–</div></div><div class="card"><div class="klabel">Restantes hoy</div><div class="kpi" id="searchRemaining">–</div></div></div><div class="grid g2 section"><div class="card"><h2>Presupuesto de búsqueda</h2><div id="searchBudget"></div></div><div class="card"><h2>Inteligencia</h2><div id="intel"></div></div></div><div class="card section"><h2>Leads recientes de investigación</h2><div id="researchLeads"></div></div></section>
<section class="page" id="instagram"><div class="grid g3"><div class="card"><div class="klabel">Conector</div><div class="kpi" id="igConnector">–</div></div><div class="card"><div class="klabel">Inbox</div><div class="kpi" id="igInbox">–</div></div><div class="card"><div class="klabel">Publicaciones preparadas</div><div class="kpi" id="igPostsCount">–</div></div></div><div class="section" id="instagramPosts"></div><div class="card section"><h2>Comandos recientes</h2><div id="instagramCommands"></div></div></section>
<section class="page" id="inquiries"><div class="grid g4"><div class="card"><div class="klabel">Consultas web recientes</div><div class="kpi" id="inquiryCount">–</div></div><div class="card"><div class="klabel">Servicios activos</div><div class="kpi" id="inquiryServiceCount">–</div></div><div class="card"><div class="klabel">Precio inicial</div><div class="kpi" id="inquiryFloor">–</div></div><div class="card"><div class="klabel">Ticket medio</div><div class="kpi" id="inquiryAvg">–</div></div></div><div class="card section"><h2>Consultas públicas recientes</h2><div id="inquiriesTable"></div></div></section>
<section class="page" id="infra"><div class="grid g2"><div class="card"><h2>Infraestructura</h2><div id="infraStatus"></div></div><div class="card"><h2>Gobernanza</h2><div id="governance"></div></div></div><div class="grid g2 section"><div class="card"><h2>Estado general</h2><div id="systemSummary"></div></div><div class="card"><h2>Diario de ciclos</h2><div id="journal"></div></div></div></section>
<section class="page" id="activity"><div class="grid g2"><div class="card"><h2>Pendientes priorizados</h2><div id="pending"></div></div><div class="card"><h2>Actividad</h2><div class="activity" id="activityList"></div></div></div></section><footer class="footer">LUMEN Zero · control, trazabilidad y foco comercial. Acciones vinculantes y movimientos de dinero continúan bajo aprobación humana.</footer></div><script>
const $=id=>document.getElementById(id); const esc=v=>String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])); const num=v=>Number(v||0); const usd=v=>'USD '+num(v).toLocaleString('es-AR',{maximumFractionDigits:0}); const yn=v=>v?'<span class="chip ok">OK</span>':'<span class="chip no">NO</span>'; const line=(a,b)=>'<div class="statusline"><span>'+esc(a)+'</span><strong>'+b+'</strong></div>';
function table(cols,rows){if(!rows?.length)return '<div class="empty">Sin registros todavía.</div>';return '<div style="overflow:auto"><table><thead><tr>'+cols.map(c=>'<th>'+esc(c[0])+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+cols.map(c=>'<td>'+c[1](r)+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>'}
function activate(name){document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('active',x.dataset.tab===name));document.querySelectorAll('.page').forEach(x=>x.classList.toggle('active',x.id===name));history.replaceState(null,'','?tab='+encodeURIComponent(name));}
document.querySelectorAll('.tab').forEach(x=>x.onclick=()=>activate(x.dataset.tab));
async function loadData(){try{const r=await fetch('/api/data',{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);render(await r.json())}catch(e){$('result').innerHTML='<div class="result" style="border-color:#7a3d3d;background:#35191c;color:#ffc4be">No pude leer el estado: '+esc(e.message)+'</div>'}}
function render(d){
  $('realized').textContent=usd(d.money.realized_revenue);$('pipeline').textContent=usd(d.money.pipeline);$('expected').textContent=usd(d.money.expected_value);$('potential').textContent=usd(d.money.potential_profit);$('watchdog').innerHTML='<span class="'+(d.status.watchdog_score===100?'good':'warn')+'">'+d.status.watchdog_score+'%</span>';$('fleet').textContent=d.status.fleet_size;
  const oppToProposal=d.funnel.opportunities?Math.round(d.funnel.proposals/d.funnel.opportunities*100):0;const proposalToClose=d.funnel.proposals?Math.round(d.funnel.close_ready/d.funnel.proposals*100):0;
  $('resultEngine').innerHTML=line('Ingresos reales',usd(d.money.realized_revenue))+line('Oportunidades con evidencia',d.funnel.opportunities)+line('Propuestas',d.funnel.proposals+' · '+oppToProposal+'% de oportunidades')+line('Close-ready',d.funnel.close_ready+' · '+proposalToClose+'% de propuestas')+line('Outbound enviado',d.funnel.outbound_sent)+line('Inbound recibido',d.funnel.inbound)+'<p class="note">La prioridad es aumentar evidencia útil, propuestas y cierres; volumen de actividad sin avance comercial no cuenta como resultado.</p>';
  $('funnel').innerHTML=line('Investigación',d.funnel.leads)+line('Candidatas',d.funnel.candidates)+line('Empresas verificadas',d.funnel.verified)+line('Compradores',d.funnel.buyers)+line('Proveedores',d.funnel.suppliers)+line('Contactos verificados',d.funnel.contacts)+line('Demanda verificada',d.funnel.demand)+line('Oportunidades',d.funnel.opportunities)+line('Propuestas',d.funnel.proposals)+line('Close-ready',d.funnel.close_ready);
  $('priority').innerHTML=line('Carril',esc(d.intelligence.lane))+line('Acción',esc(d.intelligence.action))+line('Bloqueo externo',esc(d.outbound.blocker||'ninguno'))+line('Elegibles',d.outbound.eligible)+line('Búsquedas restantes',d.scout.remaining)+'<p class="note">Primero demanda e inbound con intención; después verificación, contacto y cierre. Investigación general sólo cuando aporta al embudo.</p>';
  $('channels').innerHTML=line('Gmail',yn(d.outbound.mail_ready))+line('Instagram',yn(d.outbound.instagram))+line('Web pública',d.services.public_web.status==='online'?'<span class="chip ok">ONLINE</span>':'<span class="chip no">'+esc(d.services.public_web.status)+'</span>')+line('Outbound autónomo',yn(d.outbound.live))+line('Persistencia','<span class="chip ok">D1</span>')+line('Pagos / contratos','<span class="chip">HUMANO</span>');
  $('systemSummary').innerHTML=line('Persistencia',esc(d.status.persistence))+line('Watchdog',d.status.watchdog_passed+'/'+d.status.watchdog_total)+line('Worker',esc(d.status.worker_status))+line('Ciclo',d.status.cycle)+line('Última actualización',esc(d.status.updated_at||'—'))+line('Estado D1',Math.round(num(d.status.state_bytes)/1024).toLocaleString('es-AR')+' KB');
  $('eligible').textContent=d.outbound.eligible;$('closures').textContent=d.money.pending_closures;$('registered').textContent=usd(d.money.registered_profit);$('outboundSent').textContent=d.funnel.outbound_sent;$('inbound').textContent=d.funnel.inbound;
  $('opportunities').innerHTML=table([['Comprador',r=>esc(r.buyer)],['Necesidad',r=>esc(r.need)],['Score',r=>esc(r.score)],['Pipeline',r=>usd(r.pipeline)],['Estado',r=>esc(r.status)]],d.opportunities);
  $('deals').innerHTML=table([['Comprador',r=>esc(r.buyer)],['Etapa',r=>esc(r.stage)],['Valor',r=>usd(r.expected_value||r.pipeline)],['Ganancia',r=>usd(r.company_profit)]],d.deals);
  $('approvals').innerHTML=table([['Deal',r=>esc(r.deal_id)],['Motivo',r=>esc(r.reason)],['Ganancia',r=>usd(r.company_profit)]],d.approvals);
  $('offers').innerHTML=table([['Proveedor',r=>esc(r.supplier)],['Monto',r=>usd(r.amount)],['Estado',r=>esc(r.status)],['Fuente',r=>'<span class="small">'+esc(r.source)+'</span>']],d.offers);
  $('outbox').innerHTML=table([['Contraparte',r=>esc(r.counterparty)],['Tipo',r=>esc(r.kind)],['Estado',r=>esc(r.status)]],d.outbox);
  renderCatalog(d.catalog);
  $('leads').textContent=d.funnel.leads;$('verified').textContent=d.funnel.verified;$('contacts').textContent=d.funnel.contacts;$('searchUsed').textContent=d.scout.used;$('searchRemaining').textContent=d.scout.remaining;
  let pct=d.scout.hard_cap?Math.min(100,d.scout.used/d.scout.hard_cap*100):0;$('searchBudget').innerHTML=line('Proveedor',esc(d.scout.provider))+line('Tope diario',d.scout.hard_cap)+line('General usado',d.scout.general_used)+line('Demanda usado',d.scout.demand_used)+line('Restante',d.scout.remaining)+'<div class="bar"><i style="width:'+pct+'%"></i></div>';
  $('intel').innerHTML=line('Market Intelligence',esc(d.intelligence.market_status))+line('Autoridad',esc(d.intelligence.authority))+line('Observaciones',d.intelligence.observations)+line('Empresas conocidas',d.intelligence.companies)+line('Catálogos',d.intelligence.catalogs)+line('Productos',d.intelligence.products)+line('Learning',esc(d.intelligence.learning_status));
  $('researchLeads').innerHTML=table([['Lead',r=>esc(r.title)],['Fuente',r=>esc(r.source)],['Estado',r=>esc(r.status)],['URL',r=>r.url?'<a class="small" target="_blank" rel="noreferrer" href="'+esc(r.url)+'">abrir ↗</a>':'—']],d.researchLeads);
  $('igConnector').innerHTML=d.outbound.instagram?'<span class="good">ACTIVO</span>':'<span class="bad">NO</span>';$('igInbox').innerHTML='<span class="blue">'+esc(d.outbound.instagram_inbox||'—')+'</span>';$('igPostsCount').textContent=d.instagram_posts.length;renderPosts(d.instagram_posts);$('instagramCommands').innerHTML=table([['Acción',r=>esc(r.action)],['Publicación',r=>'<span class="mono">'+esc(r.job_id)+'</span>'],['Estado',r=>r.processed?esc(r.result||'procesado'):'pendiente'],['Fecha',r=>'<span class="small">'+esc(r.created_at)+'</span>']],d.instagram_commands);
  const catalogMap=Object.fromEntries((d.catalog.services||[]).map(x=>[x.id,x]));$('inquiryCount').textContent=d.public_inquiries.length;$('inquiryServiceCount').textContent=d.catalog.services.length;$('inquiryFloor').textContent=usd(d.catalog.floor_usd);$('inquiryAvg').textContent=usd(d.catalog.average_usd);$('inquiriesTable').innerHTML=table([['Fecha',r=>'<span class="small">'+esc(r.created_at)+'</span>'],['Servicio',r=>{const x=catalogMap[r.service_id];return x?esc(x.name)+'<br><span class="small">Desde '+usd(x.from_usd)+'</span>':esc(r.service_id)}],['Empresa',r=>esc(r.company||'—')],['Contacto',r=>esc(r.name||'—')+'<br><span class="small">'+esc(r.email)+'</span>'],['Necesidad',r=>esc(r.need)],['Estado',r=>r.processed?'<span class="chip ok">procesada</span>':'<span class="chip">nueva</span>']],d.public_inquiries);
  $('infraStatus').innerHTML=line('Dashboard unificado','<span class="chip ok">ONLINE</span>')+line('Cloudflare D1','<span class="chip ok">CANÓNICO</span>')+line('Web pública',d.services.public_web.status==='online'?'<span class="chip ok">ONLINE</span>':'<span class="chip no">'+esc(d.services.public_web.status)+'</span>')+line('Gmail SMTP/IMAP',yn(d.outbound.mail_ready))+line('Instagram',yn(d.outbound.instagram))+line('Alerta interna email',yn(d.outbound.owner_email_fallback))+line('WhatsApp','<span class="chip">sin verificación empresarial</span>')+line('Railway','<span class="chip">no requerido para el núcleo</span>');
  $('governance').innerHTML=line('Contratos',esc(d.governance.contracts))+line('Pagos/compromisos','aprobación humana')+line('Contacto no verificado',esc(d.governance.unverified_contact))+line('Instagram',esc(d.governance.instagram_posts))+line('Publicidad paga',esc(d.governance.paid_media))+line('Nuevos conectores',esc(d.governance.new_connectors));
  $('journal').innerHTML=table([['Ciclo',r=>esc(r.cycle)],['Fecha',r=>esc(r.local_time||r.recorded_at)],['Estado',r=>esc(r.status)],['Origen',r=>esc(r.source)]],d.cycle_journal);
  $('pending').innerHTML=d.pending.length?d.pending.map(x=>'<div class="event"><strong>'+esc(x.title)+'</strong><div class="small">'+esc(x.reason)+'</div><div class="small">Prioridad '+esc(x.priority)+' · '+esc(x.owner)+' · riesgo '+esc(x.risk)+'</div></div>').join(''):'<div class="empty">Sin pendientes.</div>';
  $('activityList').innerHTML=d.activity.length?d.activity.map(x=>'<div class="event">'+esc(x.msg)+'<div class="small">'+esc(x.ts)+'</div></div>').join(''):'<div class="empty">Sin actividad registrada.</div>';
}
function renderCatalog(c){
  const rows=c.services||[];$('catalogCount').textContent=rows.length;$('catalogFloor').textContent=usd(c.floor_usd);$('catalogAverage').textContent=usd(c.average_usd);$('catalogCeiling').textContent=usd(c.ceiling_usd);
  $('plansGrid').innerHTML=rows.map(x=>'<article class="card plan"><div class="klabel">Servicio LUMEN</div><h2>'+esc(x.name)+'</h2><div class="price">Desde '+usd(x.from_usd)+'</div><div class="desc">'+esc(x.desc)+'</div><div class="code small mono">'+esc(x.id)+'</div></article>').join('');
  $('revenueScenarios').innerHTML=[10,25,50,100].map(q=>'<div class="scenario"><span class="small">'+q+' ventas / mes</span><strong>'+usd(q*c.average_usd)+'</strong><span class="small">al ticket medio del catálogo</span></div>').join('');
}
function renderPosts(rows){if(!rows?.length){$('instagramPosts').innerHTML='<div class="empty">Todavía no hay publicaciones preparadas.</div>';return}$('instagramPosts').innerHTML=rows.map(r=>{const published=String(r.state_status||'').toUpperCase()==='PUBLISHED';const rejected=String(r.approval_status||'').toUpperCase()==='REJECTED';const approved=String(r.approval_status||'').toUpperCase()==='APPROVED';const label=published?'Publicado':rejected?'Descartado':approved?'Aprobado · pendiente':'Listo para aprobación';return '<article class="card post"><div>'+(r.image_url?'<img src="'+esc(r.image_url)+'" alt="Publicación preparada">':'<div class="empty">Sin imagen</div>')+'</div><div><div class="klabel">'+esc(r.audience||'B2B')+' · '+esc(r.campaign_id||'')+'</div><h2>'+esc(label)+'</h2><pre>'+esc(r.caption||'')+'</pre><div class="small mono">'+esc(r.job_id)+'</div>'+(r.last_error?'<p class="bad">'+esc(r.last_error)+'</p>':'')+((published||rejected||approved)?'':'<div class="actions"><form method="post" action="/instagram/command"><input type="hidden" name="job_id" value="'+esc(r.job_id)+'"><input type="hidden" name="fingerprint" value="'+esc(r.fingerprint)+'"><input type="hidden" name="action" value="approve"><input type="hidden" name="token" value="'+esc(r.approve_token)+'"><button class="approve">APROBAR PUBLICACIÓN</button></form><form method="post" action="/instagram/command"><input type="hidden" name="job_id" value="'+esc(r.job_id)+'"><input type="hidden" name="fingerprint" value="'+esc(r.fingerprint)+'"><input type="hidden" name="action" value="reject"><input type="hidden" name="token" value="'+esc(r.reject_token)+'"><button class="reject">DESCARTAR</button></form></div>')+'</div></article>'}).join('')}
const params=new URLSearchParams(location.search);if(params.get('result'))$('result').innerHTML='<div class="result">'+esc(params.get('result'))+'</div>';activate(params.get('tab')||'overview');loadData();setInterval(loadData,60000);
</script></body></html>`;

export default {
  async fetch(request, env) {
    const auth = authOK(request, env);
    if (auth === null) return locked();
    if (!auth) return unauthorized();
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") {
      try {
        const {manifest} = await loadState(env);
        return Response.json({ok:true,service:"lumen-unified-command-center",persistence:"cloudflare_d1",catalog_version:CATALOG_VERSION,updated_at:manifest.updated_at},{headers:{"Cache-Control":"no-store"}});
      } catch (e) {
        return Response.json({ok:false,error:String(e?.message||e)},{status:503,headers:{"Cache-Control":"no-store"}});
      }
    }
    if (request.method === "GET" && url.pathname === "/api/data") {
      try {
        return Response.json(await readUnifiedData(env), {headers:{"Cache-Control":"no-store","X-Content-Type-Options":"nosniff"}});
      } catch (e) {
        return Response.json({ok:false,error:String(e?.message||e)},{status:503,headers:{"Cache-Control":"no-store"}});
      }
    }
    if (request.method === "POST" && url.pathname === "/instagram/command") return handleInstagramCommand(request, env);
    if (request.method === "GET" && (url.pathname === "/" || url.pathname === "/index.html")) {
      return new Response(HTML,{headers:{"Content-Type":"text/html; charset=utf-8","Cache-Control":"no-store","X-Frame-Options":"DENY","Referrer-Policy":"no-referrer","X-Content-Type-Options":"nosniff","Content-Security-Policy":"default-src 'self'; img-src 'self' https:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"}});
    }
    return new Response("Not found",{status:404,headers:{"Cache-Control":"no-store"}});
  }
};