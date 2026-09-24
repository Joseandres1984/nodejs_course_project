const VERSION = "1.0-portfolio-governor";
const LANE_ORDER = ["COLLECTION", "CLOSE", "INBOUND", "FOLLOW_UP", "NEW_BUSINESS", "EXPERIMENT"];
const BASE_ATTENTION = Object.freeze({ COLLECTION: 30, CLOSE: 25, INBOUND: 15, FOLLOW_UP: 10, NEW_BUSINESS: 15, EXPERIMENT: 5 });
const EXTERNAL_ACTIONS = new Set(["COMMISSION_AUTOPILOT", "FIRST_CASH", "COMMERCIAL_REPLY", "FOLLOWUP", "NEW_OUTREACH"]);

function json(data, status = 200) {
  return Response.json(data, { status, headers: { "cache-control": "no-store", "x-content-type-options": "nosniff", "access-control-allow-origin": "*" } });
}
function clean(value, limit = 5000) { return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit); }
function num(value, fallback = 0) { const n = Number(value); return Number.isFinite(n) ? n : fallback; }
function authorized(request, env) {
  const configured = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const provided = clean(request.headers.get("x-lumen-admin"), 500);
  return Boolean(configured && provided && configured === provided);
}
async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_portfolio_governor_state (id TEXT PRIMARY KEY,updated_at TEXT NOT NULL,cycle INTEGER NOT NULL DEFAULT 0,recommended_lane TEXT,recommended_action TEXT,recommended_source_type TEXT,recommended_source_id TEXT,attention_json TEXT NOT NULL,metrics_json TEXT NOT NULL,top_candidate_json TEXT,external_candidate_json TEXT,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_portfolio_governor_runs (id TEXT PRIMARY KEY,created_at TEXT NOT NULL,recommended_lane TEXT,recommended_action TEXT,active_candidates INTEGER NOT NULL DEFAULT 0,verified_revenue_usd REAL NOT NULL DEFAULT 0,details_json TEXT,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_portfolio_runs ON lumen_portfolio_governor_runs(created_at DESC)")
  ]);
  return true;
}
async function safeAll(env, sql, binds = []) {
  try {
    const q = env.DB.prepare(sql);
    const r = binds.length ? await q.bind(...binds).all() : await q.all();
    return r.results || [];
  } catch { return []; }
}
async function safeNumber(env, sql, binds = []) {
  try {
    const q = env.DB.prepare(sql);
    const r = binds.length ? await q.bind(...binds).first() : await q.first();
    return num(r?.n);
  } catch { return 0; }
}
function laneRank(lane) { const i = LANE_ORDER.indexOf(lane); return i < 0 ? 999 : i; }
function normalizeCandidate(row) {
  if (!row) return null;
  return {
    id: row.id,
    sourceType: row.source_type,
    sourceId: row.source_id,
    lane: row.lane,
    stage: row.stage,
    title: row.title || null,
    estimatedValueUsd: num(row.estimated_value_usd),
    probability: num(row.probability),
    urgency: num(row.urgency),
    evidenceScore: num(row.evidence_score),
    signalScore: num(row.signal_score),
    economicScore: num(row.economic_score),
    actionKind: row.action_kind,
    actionRef: row.action_ref || null,
    rationale: row.rationale || null,
    updatedAt: row.updated_at
  };
}
function activeAttention(counts) {
  const active = LANE_ORDER.filter(lane => num(counts[lane]) > 0);
  if (!active.length) return { ...BASE_ATTENTION };
  const denominator = active.reduce((n, lane) => n + BASE_ATTENTION[lane], 0) || 1;
  const result = Object.fromEntries(LANE_ORDER.map(lane => [lane, 0]));
  let allocated = 0;
  active.forEach((lane, index) => {
    if (index === active.length - 1) result[lane] = 100 - allocated;
    else {
      const share = Math.round(BASE_ATTENTION[lane] * 100 / denominator);
      result[lane] = share;
      allocated += share;
    }
  });
  return result;
}
function firstByHierarchy(rows) {
  return [...rows].sort((a, b) => laneRank(a.lane) - laneRank(b.lane) || num(b.economic_score) - num(a.economic_score) || String(b.updated_at || "").localeCompare(String(a.updated_at || "")))[0] || null;
}
function firstExternal(rows) {
  return [...rows].filter(x => EXTERNAL_ACTIONS.has(x.action_kind)).sort((a, b) => laneRank(a.lane) - laneRank(b.lane) || num(b.economic_score) - num(a.economic_score) || String(b.updated_at || "").localeCompare(String(a.updated_at || "")))[0] || null;
}

export async function recomputePortfolioGovernor(env) {
  if (!(await ensureSchema(env))) return { ok: false, error: "persistence_unavailable", version: VERSION };
  const rows = await safeAll(env, "SELECT id,source_type,source_id,lane,stage,title,estimated_value_usd,probability,urgency,evidence_score,signal_score,economic_score,action_kind,action_ref,rationale,updated_at FROM lumen_opportunity_factory_candidates WHERE active=1 ORDER BY economic_score DESC,updated_at DESC LIMIT 500");
  const counts = Object.fromEntries(LANE_ORDER.map(lane => [lane, rows.filter(x => x.lane === lane).length]));
  const attention = activeAttention(counts);
  const top = firstByHierarchy(rows);
  const external = firstExternal(rows);
  const verifiedRevenueUsd = await safeNumber(env, "SELECT COALESCE(SUM(amount_usd),0) n FROM lumen_revenue_events WHERE event_type='payment_settled' AND status='verified'");
  const verifiedSettlements = await safeNumber(env, "SELECT COUNT(*) n FROM lumen_revenue_events WHERE event_type='payment_settled' AND status='verified'");
  const previous = await env.DB.prepare("SELECT cycle FROM lumen_portfolio_governor_state WHERE id='GLOBAL' LIMIT 1").first();
  const cycle = num(previous?.cycle) + 1;
  const now = new Date().toISOString();
  const recommendedLane = top?.lane || "NEW_BUSINESS";
  const recommendedAction = external?.action_kind || "NONE";
  const metrics = {
    activeCandidates: rows.length,
    laneCounts: counts,
    verifiedSettlements,
    verifiedRevenueUsd,
    collectionReady: counts.COLLECTION,
    closeReady: counts.CLOSE,
    inboundReady: counts.INBOUND,
    followupReady: counts.FOLLOW_UP,
    newBusinessReady: counts.NEW_BUSINESS,
    experimentsReady: counts.EXPERIMENT
  };
  const normalizedTop = normalizeCandidate(top);
  const normalizedExternal = normalizeCandidate(external);
  await env.DB.prepare("INSERT INTO lumen_portfolio_governor_state(id,updated_at,cycle,recommended_lane,recommended_action,recommended_source_type,recommended_source_id,attention_json,metrics_json,top_candidate_json,external_candidate_json,engine_version) VALUES('GLOBAL',?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,cycle=excluded.cycle,recommended_lane=excluded.recommended_lane,recommended_action=excluded.recommended_action,recommended_source_type=excluded.recommended_source_type,recommended_source_id=excluded.recommended_source_id,attention_json=excluded.attention_json,metrics_json=excluded.metrics_json,top_candidate_json=excluded.top_candidate_json,external_candidate_json=excluded.external_candidate_json,engine_version=excluded.engine_version")
    .bind(now, cycle, recommendedLane, recommendedAction, external?.source_type || null, external?.source_id || null, JSON.stringify(attention), JSON.stringify(metrics), normalizedTop ? JSON.stringify(normalizedTop) : null, normalizedExternal ? JSON.stringify(normalizedExternal) : null, VERSION).run();
  const runId = `PG-${crypto.randomUUID().replaceAll("-", "").slice(0, 14).toUpperCase()}`;
  await env.DB.prepare("INSERT INTO lumen_portfolio_governor_runs(id,created_at,recommended_lane,recommended_action,active_candidates,verified_revenue_usd,details_json,engine_version) VALUES(?,?,?,?,?,?,?,?)")
    .bind(runId, now, recommendedLane, recommendedAction, rows.length, verifiedRevenueUsd, JSON.stringify({ counts, attention, top: normalizedTop, external: normalizedExternal }).slice(0, 8000), VERSION).run();
  return {
    ok: true,
    version: VERSION,
    cycle,
    recommendedLane,
    recommendedExternalAction: recommendedAction,
    attention,
    metrics,
    topCandidate: normalizedTop,
    externalCandidate: normalizedExternal,
    guardrails: {
      hierarchy: LANE_ORDER,
      existingBusinessProtected: true,
      collectionBeforeExploration: true,
      experimentsLowestPriority: true,
      prioritizationDoesNotChangePrices: true,
      maxExternalMessagesPerCycle: 1,
      autonomousSpend: false,
      autonomousPurchase: false,
      autonomousContract: false,
      bindingActionsHumanGated: true
    }
  };
}

async function state(env) {
  if (!(await ensureSchema(env))) return { version: VERSION, initialized: false };
  const row = await env.DB.prepare("SELECT * FROM lumen_portfolio_governor_state WHERE id='GLOBAL' LIMIT 1").first();
  if (!row) return { version: VERSION, initialized: false, baseAttention: BASE_ATTENTION, hierarchy: LANE_ORDER };
  const parse = (v, fallback) => { try { return JSON.parse(v || ""); } catch { return fallback; } };
  return {
    version: VERSION,
    initialized: true,
    updatedAt: row.updated_at,
    cycle: num(row.cycle),
    recommendedLane: row.recommended_lane,
    recommendedExternalAction: row.recommended_action,
    recommendedSourceType: row.recommended_source_type,
    recommendedSourceId: row.recommended_source_id,
    attention: parse(row.attention_json, {}),
    metrics: parse(row.metrics_json, {}),
    topCandidate: parse(row.top_candidate_json, null),
    externalCandidate: parse(row.external_candidate_json, null),
    guardrails: { existingBusinessProtected: true, maxExternalMessagesPerCycle: 1, autonomousSpend: false, autonomousContract: false, bindingActionsHumanGated: true }
  };
}

export async function handlePortfolioGovernor(request, env) {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/portfolio-governor/policy") return json({ version: VERSION, name: "LUMEN Portfolio Governor", objective: "allocate_attention_across_existing_businesses_new_opportunities_and_experiments_without_starving_live_revenue_work", hierarchy: LANE_ORDER, baseAttentionPercent: BASE_ATTENTION, selectionRule: "highest_priority_nonempty_lane_then_highest_economic_score_within_lane", externalActionRule: "at_most_one_external_message_per_cycle_across_commercial_engines", experimentsRule: "experiments_are_lowest_priority_and_never_preempt_collection_close_inbound_or_followup", changesPrices: false, createsContracts: false, autonomousSpend: false, autonomousPurchase: false, maxExternalMessagesPerCycle: 1, bindingActionsHumanGated: true });
  if (request.method === "GET" && url.pathname === "/portfolio-governor/state") return json(await state(env));
  if (request.method === "POST" && url.pathname === "/portfolio-governor/recompute") {
    if (!authorized(request, env)) return json({ ok: false, error: "admin_token_required" }, 403);
    return json(await recomputePortfolioGovernor(env), 202);
  }
  return null;
}
