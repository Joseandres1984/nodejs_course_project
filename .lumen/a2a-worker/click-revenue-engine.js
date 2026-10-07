const VERSION = "1.0-click-revenue-lane";
const TARGET_SCALE_EVENTS = 10000;

export const CLICK_REVENUE_POLICY = Object.freeze({
  version: VERSION,
  name: "LUMEN Click Revenue",
  objective: "monetize_legitimate_human_clicks_through_approved_cpc_programs",
  targetScaleEvents: TARGET_SCALE_EVENTS,
  clickIsRevenue: false,
  providerVerifiedPayoutIsRevenue: true,
  syntheticClicksForbidden: true,
  selfClicksForbidden: true,
  incentivizedInvalidTrafficForbidden: true,
  arbitraryOpenRedirectsForbidden: true,
  automaticEnrollment: false,
  autonomousSpendUsd: 0,
  autonomousPurchase: false,
  autonomousContract: false,
  bindingActionsHumanGated: true,
  projectedScaleIsNotRevenue: true,
  revenueTruth: "provider_verified_paid_click_or_payout_only"
});

const KNOWN_CANDIDATES = Object.freeze([
  {
    id: "sovrn-commerce-cpc",
    provider: "Sovrn Commerce",
    name: "Sovrn Commerce CPC",
    model: "CPC",
    sourceUrl: "https://www.sovrn.com/sovrn-for-creators/",
    status: "REQUIRES_ENROLLMENT"
  },
  {
    id: "impact-cpc",
    provider: "impact.com",
    name: "Impact CPC campaigns",
    model: "CPC",
    sourceUrl: "https://impact.com/",
    status: "REQUIRES_ENROLLMENT"
  }
]);

function clean(value, limit = 1200) {
  return String(value ?? "").trim().replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").slice(0, limit);
}
function num(value, fallback = 0) {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}
function bool(value) {
  if (typeof value === "boolean") return value;
  return ["1","true","yes","on"].includes(String(value ?? "").toLowerCase());
}
function json(data, status = 200) {
  return Response.json(data, {
    status,
    headers: {
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "access-control-allow-origin": "*",
      "access-control-allow-headers": "content-type,x-lumen-admin",
      "access-control-allow-methods": "GET,POST,OPTIONS"
    }
  });
}
function authorized(request, env) {
  const expected = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const provided = clean(request.headers.get("x-lumen-admin"), 500);
  return Boolean(expected && provided && expected === provided);
}
function safeHttps(value) {
  const raw = clean(value, 1800);
  if (!raw) return null;
  try {
    const u = new URL(raw);
    if (u.protocol !== "https:") return null;
    const h = u.hostname.toLowerCase();
    if (h === "localhost" || h.endsWith(".local") || h === "::1" || /^127\./.test(h) || /^10\./.test(h) || /^192\.168\./.test(h) || /^169\.254\./.test(h)) return null;
    const m = h.match(/^172\.(\d+)\./);
    if (m && Number(m[1]) >= 16 && Number(m[1]) <= 31) return null;
    return u.toString();
  } catch {
    return null;
  }
}
async function sha256(text) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(String(text)));
  return [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, "0")).join("");
}
function parseArray(value) {
  try {
    const parsed = typeof value === "string" ? JSON.parse(value || "[]") : value;
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function normalizeClickProgram(raw = {}) {
  const id = clean(raw.id || raw.programId || raw.program_id, 120).toLowerCase().replace(/[^a-z0-9_-]+/g, "-");
  const trackingUrl = safeHttps(raw.trackingUrl || raw.tracking_url);
  const sourceUrl = safeHttps(raw.sourceUrl || raw.source_url);
  const approved = bool(raw.approved);
  const termsVerified = bool(raw.termsVerified ?? raw.terms_verified);
  const model = clean(raw.model || "CPC", 20).toUpperCase();
  const active = Boolean(id && model === "CPC" && trackingUrl && approved && termsVerified);
  return {
    id,
    provider: clean(raw.provider || "unknown", 160),
    name: clean(raw.name || raw.programName || raw.program_name || id || "unnamed", 220),
    model,
    trackingUrl,
    sourceUrl,
    expectedCpcUsd: Math.max(0, num(raw.expectedCpcUsd ?? raw.expected_cpc_usd, 0)),
    currency: clean(raw.currency || "USD", 12).toUpperCase(),
    approved,
    termsVerified,
    clickIdParam: clean(raw.clickIdParam || raw.click_id_param, 80),
    status: active ? "ACTIVE" : clean(raw.status || "CONFIG_REQUIRED", 60).toUpperCase(),
    active
  };
}

export function scoreClickProgram(program = {}, metrics = {}) {
  const cpc = Math.max(0, num(metrics.verifiedEpcUsd ?? program.expectedCpcUsd, 0));
  const paidClicks = Math.max(0, num(metrics.verifiedPaidClicks, 0));
  const observedClicks = Math.max(0, num(metrics.observedClicks, 0));
  const payoutConfidence = observedClicks > 0 ? Math.min(1, paidClicks / observedClicks) : 0;
  const evidence = paidClicks > 0 ? 1 : (program.active ? 0.45 : 0.1);
  const cpcSignal = Math.min(1, Math.log10(1 + cpc * 100) / 2);
  return Number(Math.max(0, Math.min(1, evidence * 0.55 + cpcSignal * 0.3 + payoutConfidence * 0.15)).toFixed(4));
}

export function buildTrackedDestination(program, clickId) {
  if (!program?.active || !program?.trackingUrl) return null;
  const u = new URL(program.trackingUrl);
  if (program.clickIdParam) u.searchParams.set(program.clickIdParam, clickId);
  return u.toString();
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_click_programs (id TEXT PRIMARY KEY,provider TEXT NOT NULL,name TEXT NOT NULL,model TEXT NOT NULL,tracking_url TEXT,source_url TEXT,currency TEXT NOT NULL DEFAULT 'USD',expected_cpc_usd REAL NOT NULL DEFAULT 0,status TEXT NOT NULL,approved INTEGER NOT NULL DEFAULT 0,terms_verified INTEGER NOT NULL DEFAULT 0,click_id_param TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,metadata_json TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_click_programs_status ON lumen_click_programs(status,updated_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_click_events (id TEXT PRIMARY KEY,program_id TEXT NOT NULL,created_at TEXT NOT NULL,source_tag TEXT,status TEXT NOT NULL,referrer_host TEXT,user_agent_class TEXT,metadata_json TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_click_events_program ON lumen_click_events(program_id,created_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_click_settlements (provider_event_id TEXT PRIMARY KEY,program_id TEXT NOT NULL,click_id TEXT,amount_usd REAL NOT NULL,currency TEXT NOT NULL,status TEXT NOT NULL,verified_at TEXT NOT NULL,evidence_ref TEXT NOT NULL,revenue_event_id TEXT,created_at TEXT NOT NULL,metadata_json TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_click_settlements_program ON lumen_click_settlements(program_id,verified_at)")
  ]);
  return true;
}

function configuredPrograms(env) {
  const rows = parseArray(env?.CLICK_REVENUE_PROGRAMS_JSON).map(normalizeClickProgram).filter(x => x.id);
  return rows;
}

export async function syncClickRevenuePrograms(env) {
  if (!(await ensureSchema(env))) return { ok:false, error:"persistence_unavailable", version:VERSION };
  const now = new Date().toISOString();
  const configured = configuredPrograms(env);
  const merged = new Map();
  for (const seed of KNOWN_CANDIDATES) merged.set(seed.id, normalizeClickProgram(seed));
  for (const row of configured) merged.set(row.id, row);
  let active = 0;
  for (const p of merged.values()) {
    if (p.active) active += 1;
    await env.DB.prepare("INSERT INTO lumen_click_programs(id,provider,name,model,tracking_url,source_url,currency,expected_cpc_usd,status,approved,terms_verified,click_id_param,created_at,updated_at,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET provider=excluded.provider,name=excluded.name,model=excluded.model,tracking_url=excluded.tracking_url,source_url=excluded.source_url,currency=excluded.currency,expected_cpc_usd=excluded.expected_cpc_usd,status=excluded.status,approved=excluded.approved,terms_verified=excluded.terms_verified,click_id_param=excluded.click_id_param,updated_at=excluded.updated_at,metadata_json=excluded.metadata_json")
      .bind(p.id,p.provider,p.name,p.model,p.trackingUrl,p.sourceUrl,p.currency,p.expectedCpcUsd,p.status,p.approved?1:0,p.termsVerified?1:0,p.clickIdParam||null,now,now,JSON.stringify({version:VERSION,active:p.active,projectedScaleIsNotRevenue:true,targetScaleEvents:TARGET_SCALE_EVENTS}))
      .run();
  }
  return { ok:true, version:VERSION, knownPrograms:merged.size, configuredPrograms:configured.length, activePrograms:active };
}

async function programById(env, id) {
  const row = await env.DB.prepare("SELECT * FROM lumen_click_programs WHERE id=? LIMIT 1").bind(id).first();
  if (!row) return null;
  return normalizeClickProgram({
    id: row.id,
    provider: row.provider,
    name: row.name,
    model: row.model,
    trackingUrl: row.tracking_url,
    sourceUrl: row.source_url,
    currency: row.currency,
    expectedCpcUsd: row.expected_cpc_usd,
    status: row.status,
    approved: Number(row.approved) === 1,
    termsVerified: Number(row.terms_verified) === 1,
    clickIdParam: row.click_id_param
  });
}

function classifyUserAgent(ua) {
  const s = clean(ua, 500).toLowerCase();
  if (!s) return "UNKNOWN";
  if (/bot|crawler|spider|headless|preview|monitor|curl|wget|python-requests/.test(s)) return "AUTOMATION";
  return "HUMAN_LIKELY";
}

async function recordObservedClick(env, programId, request, sourceTag) {
  const clickId = `CLK-${crypto.randomUUID().replaceAll("-","").slice(0,24).toUpperCase()}`;
  const ref = clean(request.headers.get("referer"), 1200);
  let referrerHost = null;
  try { referrerHost = ref ? new URL(ref).hostname.slice(0,240) : null; } catch {}
  const uaClass = classifyUserAgent(request.headers.get("user-agent"));
  await env.DB.prepare("INSERT INTO lumen_click_events(id,program_id,created_at,source_tag,status,referrer_host,user_agent_class,metadata_json) VALUES(?,?,?,?,?,?,?,?)")
    .bind(clickId,programId,new Date().toISOString(),clean(sourceTag,120)||null,uaClass==="AUTOMATION"?"IGNORED_AUTOMATION":"OBSERVED",referrerHost,uaClass,JSON.stringify({version:VERSION,revenueRecognized:false,clickIsWeakSignal:true}))
    .run();
  return { clickId, uaClass };
}

async function ensureRevenueEventsTable(env) {
  await env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_revenue_events (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, event_type TEXT NOT NULL, source TEXT NOT NULL, item_id TEXT, amount_usd REAL, status TEXT NOT NULL, evidence TEXT, metadata TEXT)").run();
}

export async function syncClickRevenueSettlementsToRevenue(env) {
  if (!(await ensureSchema(env))) return { ok:false, error:"persistence_unavailable", version:VERSION };
  await ensureRevenueEventsTable(env);
  const rows = await env.DB.prepare("SELECT provider_event_id,program_id,click_id,amount_usd,currency,verified_at,evidence_ref FROM lumen_click_settlements WHERE status='PROVIDER_VERIFIED' AND revenue_event_id IS NULL ORDER BY verified_at ASC LIMIT 500").all();
  const results = [];
  for (const row of rows.results || []) {
    const eventId = `REVT-CPC-${(await sha256(row.provider_event_id)).slice(0,16).toUpperCase()}`;
    const evidence = `cpc_provider:${row.provider_event_id}`;
    const metadata = {
      clickRevenue: {
        programId: row.program_id,
        clickId: row.click_id || null,
        providerEventId: row.provider_event_id,
        evidenceRef: row.evidence_ref,
        verification: "provider_reported"
      },
      attribution: { rule: "verified_cpc_provider_event_exact_program_id" }
    };
    await env.DB.prepare("INSERT OR IGNORE INTO lumen_revenue_events(id,created_at,event_type,source,item_id,amount_usd,status,evidence,metadata) VALUES(?,?,'payment_settled','click_cpc',?,?,'verified',?,?)")
      .bind(eventId,row.verified_at,row.program_id,Math.max(0,num(row.amount_usd)),evidence,JSON.stringify(metadata)).run();
    await env.DB.prepare("UPDATE lumen_click_settlements SET revenue_event_id=? WHERE provider_event_id=? AND revenue_event_id IS NULL")
      .bind(eventId,row.provider_event_id).run();
    results.push({ providerEventId:row.provider_event_id, revenueEventId:eventId, amountUsd:Math.max(0,num(row.amount_usd)), programId:row.program_id });
  }
  return { ok:true, version:VERSION, processed:results.length, results:results.slice(0,50), revenueTruth:"provider_verified_paid_click_or_payout_only" };
}

async function statusData(env) {
  await ensureSchema(env);
  const p = await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN status='ACTIVE' THEN 1 ELSE 0 END) active,COALESCE(MAX(expected_cpc_usd),0) best_expected_cpc FROM lumen_click_programs").first();
  const c = await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN status='OBSERVED' THEN 1 ELSE 0 END) legitimate,SUM(CASE WHEN status='IGNORED_AUTOMATION' THEN 1 ELSE 0 END) ignored FROM lumen_click_events").first();
  const s = await env.DB.prepare("SELECT COUNT(*) total,COALESCE(SUM(amount_usd),0) revenue FROM lumen_click_settlements WHERE status='PROVIDER_VERIFIED'").first();
  const verifiedRevenueUsd = Math.max(0,num(s?.revenue));
  const observed = Math.max(0,num(c?.legitimate));
  const verifiedPaidClicks = Math.max(0,num(s?.total));
  const verifiedEpcUsd = observed > 0 ? verifiedRevenueUsd / observed : 0;
  return {
    programs:Number(p?.total||0),
    activePrograms:Number(p?.active||0),
    observedLegitimateClicks:observed,
    ignoredAutomationClicks:Number(c?.ignored||0),
    verifiedPaidClickEvents:verifiedPaidClicks,
    verifiedRevenueUsd:Number(verifiedRevenueUsd.toFixed(4)),
    verifiedEpcUsd:Number(verifiedEpcUsd.toFixed(6)),
    bestConfiguredExpectedCpcUsd:Number(num(p?.best_expected_cpc).toFixed(4)),
    targetScaleEvents:TARGET_SCALE_EVENTS,
    scaleProgress:Math.min(1, observed / TARGET_SCALE_EVENTS),
    revenueTruth:"provider_verified_paid_click_or_payout_only"
  };
}

export async function runClickRevenueEngine(env) {
  const programs = await syncClickRevenuePrograms(env);
  const revenue = await syncClickRevenueSettlementsToRevenue(env);
  return { ok:programs.ok !== false && revenue.ok !== false, version:VERSION, programs, revenue, status:await statusData(env), guardrails:CLICK_REVENUE_POLICY };
}

async function ingestProviderSettlements(request, env) {
  if (!authorized(request, env)) return json({ ok:false, error:"admin_token_required" }, 403);
  if (!bool(env?.CLICK_REVENUE_PROVIDER_IMPORT_ENABLED)) return json({ ok:false, error:"provider_import_disabled" }, 403);
  let body;
  try { body = await request.json(); } catch { return json({ ok:false, error:"invalid_json" }, 400); }
  const events = Array.isArray(body?.events) ? body.events : [];
  const now = new Date().toISOString();
  let accepted = 0;
  const rejected = [];
  for (const raw of events.slice(0,500)) {
    const providerEventId = clean(raw.provider_event_id || raw.providerEventId, 220);
    const programId = clean(raw.program_id || raw.programId, 120);
    const clickId = clean(raw.click_id || raw.clickId, 120) || null;
    const amountUsd = Math.max(0,num(raw.amount_usd ?? raw.amountUsd));
    const evidenceRef = clean(raw.evidence_ref || raw.evidenceRef, 1200);
    const verifiedByProvider = raw.verified_by_provider === true || raw.verifiedByProvider === true;
    if (!providerEventId || !programId || !(amountUsd > 0) || !evidenceRef || !verifiedByProvider) {
      rejected.push({ providerEventId:providerEventId||null, reason:"missing_provider_verification_evidence" });
      continue;
    }
    const program = await programById(env, programId);
    if (!program || !program.approved || !program.termsVerified) {
      rejected.push({ providerEventId, reason:"program_not_approved" });
      continue;
    }
    await env.DB.prepare("INSERT OR IGNORE INTO lumen_click_settlements(provider_event_id,program_id,click_id,amount_usd,currency,status,verified_at,evidence_ref,revenue_event_id,created_at,metadata_json) VALUES(?,?,?,?,?,'PROVIDER_VERIFIED',?,?,NULL,?,?)")
      .bind(providerEventId,programId,clickId,amountUsd,clean(raw.currency||"USD",12).toUpperCase(),clean(raw.verified_at||raw.verifiedAt||now,60),evidenceRef,now,JSON.stringify({version:VERSION,provider:program.provider,verification:"provider_reported",synthetic:false}))
      .run();
    accepted += 1;
  }
  const bridged = await syncClickRevenueSettlementsToRevenue(env);
  return json({ ok:true, version:VERSION, accepted, rejected:rejected.slice(0,50), bridged, status:await statusData(env) }, 202);
}

export async function handleClickRevenue(request, env) {
  const url = new URL(request.url);
  if (!url.pathname.startsWith("/click-revenue/")) return null;

  if (request.method === "OPTIONS") return new Response(null,{status:204,headers:{"access-control-allow-origin":"*","access-control-allow-headers":"content-type,x-lumen-admin","access-control-allow-methods":"GET,POST,OPTIONS"}});
  if (request.method === "GET" && url.pathname === "/click-revenue/policy") return json(CLICK_REVENUE_POLICY);
  if (request.method === "GET" && url.pathname === "/click-revenue/status") {
    await syncClickRevenuePrograms(env);
    return json({ ok:true, version:VERSION, ...(await statusData(env)) });
  }
  if (request.method === "GET" && url.pathname === "/click-revenue/programs") {
    await syncClickRevenuePrograms(env);
    const rows = await env.DB.prepare("SELECT id,provider,name,model,currency,expected_cpc_usd,status,approved,terms_verified,source_url FROM lumen_click_programs ORDER BY status='ACTIVE' DESC,expected_cpc_usd DESC,provider ASC").all();
    return json({ ok:true, version:VERSION, programs:(rows.results||[]).map(r=>({id:r.id,provider:r.provider,name:r.name,model:r.model,currency:r.currency,expectedCpcUsd:Number(r.expected_cpc_usd||0),status:r.status,approved:Number(r.approved)===1,termsVerified:Number(r.terms_verified)===1,sourceUrl:r.source_url||null})) });
  }
  if (request.method === "POST" && url.pathname === "/click-revenue/settlements/provider") return ingestProviderSettlements(request, env);

  const match = request.method === "GET" ? url.pathname.match(/^\/click-revenue\/go\/([a-z0-9_-]{1,120})$/i) : null;
  if (match) {
    await syncClickRevenuePrograms(env);
    const program = await programById(env, match[1].toLowerCase());
    if (!program || !program.active) return json({ ok:false, error:"program_not_active_or_not_approved" }, 404);
    const observed = await recordObservedClick(env, program.id, request, url.searchParams.get("src"));
    if (observed.uaClass === "AUTOMATION") return json({ ok:false, error:"automated_traffic_not_redirected", revenueRecognized:false }, 403);
    const destination = buildTrackedDestination(program, observed.clickId);
    if (!destination) return json({ ok:false, error:"tracking_destination_unavailable" }, 503);
    return new Response(null,{status:302,headers:{location:destination,"cache-control":"no-store","x-lumen-click-id":observed.clickId,"referrer-policy":"strict-origin-when-cross-origin"}});
  }

  return json({ ok:false, error:"not_found" }, 404);
}
