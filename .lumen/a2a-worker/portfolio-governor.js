const VERSION = "2.0-economic-autonomy-governor";
const LANE_ORDER = ["COLLECTION", "CLOSE", "INBOUND", "FOLLOW_UP", "NEW_BUSINESS", "EXPERIMENT"];
const BUSINESS_FAMILIES = ["B2B_A2A", "REFERRAL", "COMMERCE", "TRAVEL", "VENTURE", "OTHER"];
const BASE_ATTENTION = Object.freeze({ COLLECTION: 30, CLOSE: 25, INBOUND: 15, FOLLOW_UP: 10, NEW_BUSINESS: 15, EXPERIMENT: 5 });
const EXTERNAL_ACTIONS = new Set(["COMMISSION_AUTOPILOT", "FIRST_CASH", "COMMERCIAL_REPLY", "FOLLOWUP", "NEW_OUTREACH"]);
const TIME_TO_CASH = Object.freeze({ COLLECTION: 1.0, CLOSE: 0.94, INBOUND: 0.84, FOLLOW_UP: 0.67, NEW_BUSINESS: 0.50, EXPERIMENT: 0.24 });

function json(data, status = 200) {
  return Response.json(data, { status, headers: { "cache-control": "no-store", "x-content-type-options": "nosniff", "access-control-allow-origin": "*" } });
}
function clean(value, limit = 5000) { return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit); }
function num(value, fallback = 0) { const n = Number(value); return Number.isFinite(n) ? n : fallback; }
function clamp(value, min = 0, max = 100) { return Math.max(min, Math.min(max, num(value))); }
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
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_portfolio_runs ON lumen_portfolio_governor_runs(created_at DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_portfolio_family_state (family TEXT PRIMARY KEY,updated_at TEXT NOT NULL,cycles_seen INTEGER NOT NULL DEFAULT 0,selected_cycles INTEGER NOT NULL DEFAULT 0,last_selected_at TEXT,last_score REAL NOT NULL DEFAULT 0,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_portfolio_family_rank ON lumen_portfolio_family_state(last_score DESC,selected_cycles ASC)")
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

export function businessFamily(row) {
  const source = clean(row?.source_type || row?.sourceType, 80).toUpperCase();
  const title = clean(row?.title, 300).toLowerCase();
  if (source.includes("COMMERCE")) return "COMMERCE";
  if (source.includes("REFERRAL")) return "REFERRAL";
  if (source.includes("VENTURE")) return "VENTURE";
  if (source.includes("TRAVEL") || /travel|hotel|tour|alojamiento|viaje/.test(title)) return "TRAVEL";
  if (["SALES_PIPELINE", "DISCOVERY", "SERVICE", "A2A"].some(token => source.includes(token))) return "B2B_A2A";
  return "OTHER";
}

export function economicPriority(row, feedbackAdjustment = 0, explorationBonus = 0) {
  if (!row) return 0;
  const lane = clean(row.lane, 30).toUpperCase();
  const probability = clamp(row.probability, 0, 1);
  const urgency = clamp(row.urgency, 0, 1);
  const evidence = clamp(row.evidence_score ?? row.evidenceScore, 0, 100) / 100;
  const signal = clamp(row.signal_score ?? row.signalScore, 0, 100) / 100;
  const valueUsd = Math.max(0, num(row.estimated_value_usd ?? row.estimatedValueUsd));
  const timeToCash = TIME_TO_CASH[lane] ?? 0.35;
  const valueScore = Math.min(18, Math.log10(1 + valueUsd) * 4.2);
  const feedback = clamp(feedbackAdjustment, -12, 20);
  const exploration = clamp(explorationBonus, 0, 6);
  const score = probability * 24 + evidence * 20 + urgency * 14 + signal * 10 + timeToCash * 14 + valueScore + feedback + exploration;
  return Math.round(clamp(score, 0, 100) * 100) / 100;
}

function normalizeCandidate(row) {
  if (!row) return null;
  return {
    id: row.id,
    sourceType: row.source_type,
    sourceId: row.source_id,
    businessFamily: row.business_family || businessFamily(row),
    lane: row.lane,
    stage: row.stage,
    title: row.title || null,
    estimatedValueUsd: num(row.estimated_value_usd),
    probability: num(row.probability),
    urgency: num(row.urgency),
    evidenceScore: num(row.evidence_score),
    signalScore: num(row.signal_score),
    economicScore: num(row.economic_score),
    autonomyScore: num(row.autonomy_score),
    feedbackAdjustment: num(row.feedback_adjustment),
    explorationBonus: num(row.exploration_bonus),
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

function familyAttention(rows) {
  const groups = Object.fromEntries(BUSINESS_FAMILIES.map(f => [f, []]));
  for (const row of rows) (groups[row.business_family] || groups.OTHER).push(row);
  const weights = {};
  for (const family of BUSINESS_FAMILIES) {
    const members = groups[family] || [];
    const top = members.reduce((m, row) => Math.max(m, num(row.autonomy_score)), 0);
    weights[family] = members.length ? Math.max(5, top) ** 1.35 : 0;
  }
  const total = Object.values(weights).reduce((a, b) => a + b, 0);
  if (!total) return Object.fromEntries(BUSINESS_FAMILIES.map(f => [f, 0]));
  const result = {};
  let allocated = 0;
  const active = BUSINESS_FAMILIES.filter(f => weights[f] > 0);
  active.forEach((family, index) => {
    if (index === active.length - 1) result[family] = 100 - allocated;
    else {
      const share = Math.max(1, Math.round(weights[family] * 100 / total));
      result[family] = share;
      allocated += share;
    }
  });
  for (const family of BUSINESS_FAMILIES) if (!(family in result)) result[family] = 0;
  return result;
}

async function loadFeedbackAdjustments(env) {
  const map = new Map();
  const proposalRows = await safeAll(env, "SELECT p.proposal_id source_id,COALESCE(f.priority_adjustment,0) adjustment FROM lumen_proposal_drafts p LEFT JOIN lumen_offer_performance f ON f.offer_id=p.offer_id");
  for (const row of proposalRows) map.set(`SALES_PIPELINE:${row.source_id}`, num(row.adjustment));
  const oppRows = await safeAll(env, "SELECT o.id source_id,COALESCE(f.priority_adjustment,0) adjustment FROM lumen_opportunities o LEFT JOIN lumen_offer_performance f ON f.offer_id=o.revenue_offer_id");
  for (const row of oppRows) map.set(`DISCOVERY:${row.source_id}`, num(row.adjustment));
  return map;
}

async function familyLearning(env) {
  const rows = await safeAll(env, "SELECT family,cycles_seen,selected_cycles,last_selected_at,last_score FROM lumen_portfolio_family_state");
  return Object.fromEntries(rows.map(row => [clean(row.family, 50), row]));
}

function explorationBonusFor(family, learning) {
  const row = learning[family] || {};
  const selected = Math.max(0, num(row.selected_cycles));
  if (selected === 0) return 6;
  if (selected <= 2) return 4;
  if (selected <= 5) return 2;
  return 0;
}

async function virtualCommerceCandidates(env) {
  const rows = [];
  const paid = await safeAll(env, "SELECT event_id,external_order_id,event_type,received_at,total_amount,currency FROM lumen_commerce_order_events WHERE verified=1 AND event_type IN ('PAID','ORDER_PAID','PAYMENT_CONFIRMED') ORDER BY received_at DESC LIMIT 20");
  for (const row of paid) {
    rows.push({
      id: `VCOM-ORDER-${clean(row.event_id, 140)}`,
      source_type: "COMMERCE_ORDER",
      source_id: row.event_id,
      lane: "CLOSE",
      stage: row.event_type,
      title: `Verified commerce order ${row.external_order_id}`,
      estimated_value_usd: 0,
      probability: 0.9,
      urgency: 0.95,
      evidence_score: 94,
      signal_score: 90,
      economic_score: 0,
      action_kind: "COMMERCE_FULFILLMENT_REVIEW",
      action_ref: row.external_order_id,
      rationale: "verified_paid_commerce_order_requires_governed_fulfillment;currency_not_assumed_usd",
      updated_at: row.received_at
    });
  }
  const drafts = await safeAll(env, "SELECT d.draft_id,d.title,d.projected_margin_pct,d.market_sample_count,d.competitiveness,d.status,d.updated_at,MAX(CASE WHEN p.state='PUBLISHED' THEN 1 ELSE 0 END) published FROM lumen_commerce_catalog_drafts d LEFT JOIN lumen_commerce_channel_plans p ON p.draft_id=d.draft_id WHERE d.status IN ('SHADOW_READY','APPROVED','PUBLISHED') GROUP BY d.draft_id,d.title,d.projected_margin_pct,d.market_sample_count,d.competitiveness,d.status,d.updated_at ORDER BY d.updated_at DESC LIMIT 40");
  for (const row of drafts) {
    const published = num(row.published) > 0 || clean(row.status, 30).toUpperCase() === "PUBLISHED";
    const samples = Math.max(0, num(row.market_sample_count));
    const margin = clamp(row.projected_margin_pct, 0, 60);
    rows.push({
      id: `VCOM-DRAFT-${clean(row.draft_id, 140)}`,
      source_type: "COMMERCE_PRODUCT",
      source_id: row.draft_id,
      lane: published ? "NEW_BUSINESS" : "EXPERIMENT",
      stage: published ? "PUBLISHED" : row.status,
      title: row.title || row.draft_id,
      estimated_value_usd: 0,
      probability: published ? 0.12 : 0.06,
      urgency: published ? 0.32 : 0.12,
      evidence_score: Math.min(82, 48 + Math.min(20, samples * 2) + (clean(row.competitiveness, 50) === "COMPETITIVE" ? 10 : 0)),
      signal_score: Math.min(90, 35 + margin),
      economic_score: 0,
      action_kind: published ? "COMMERCE_OBSERVE_CONVERSION" : "COMMERCE_REVIEW",
      action_ref: row.draft_id,
      rationale: published ? "commerce_is_live_but_must_earn_attention_from_real_conversion" : "commerce_candidate_remains_an_experiment_until_market_and_conversion_evidence_improve",
      updated_at: row.updated_at
    });
  }
  return rows;
}

function enrichRows(rows, feedbackMap, learning) {
  return rows.map(row => {
    const family = businessFamily(row);
    const feedback = num(feedbackMap.get(`${clean(row.source_type, 80)}:${clean(row.source_id, 180)}`));
    const exploration = explorationBonusFor(family, learning);
    return { ...row, business_family: family, feedback_adjustment: feedback, exploration_bonus: exploration, autonomy_score: economicPriority(row, feedback, exploration) };
  });
}

export function chooseEconomicCandidate(rows, { externalOnly = false } = {}) {
  let candidates = [...(rows || [])].filter(Boolean);
  if (externalOnly) candidates = candidates.filter(row => EXTERNAL_ACTIONS.has(row.action_kind));
  if (!candidates.length) return null;
  const collection = candidates.filter(row => clean(row.lane, 30).toUpperCase() === "COLLECTION");
  const pool = collection.length ? collection : candidates;
  return pool.sort((a, b) => num(b.autonomy_score) - num(a.autonomy_score) || num(b.evidence_score) - num(a.evidence_score) || num(b.probability) - num(a.probability) || laneRank(a.lane) - laneRank(b.lane) || String(b.updated_at || "").localeCompare(String(a.updated_at || "")))[0] || null;
}

async function updateFamilyState(env, rows, selectedFamily, now) {
  for (const family of BUSINESS_FAMILIES) {
    const members = rows.filter(row => row.business_family === family);
    if (!members.length) continue;
    const topScore = members.reduce((m, row) => Math.max(m, num(row.autonomy_score)), 0);
    const selected = family === selectedFamily ? 1 : 0;
    await env.DB.prepare("INSERT INTO lumen_portfolio_family_state(family,updated_at,cycles_seen,selected_cycles,last_selected_at,last_score,engine_version) VALUES(?,?,1,?,?,?,?) ON CONFLICT(family) DO UPDATE SET updated_at=excluded.updated_at,cycles_seen=lumen_portfolio_family_state.cycles_seen+1,selected_cycles=lumen_portfolio_family_state.selected_cycles+?,last_selected_at=CASE WHEN ?=1 THEN excluded.last_selected_at ELSE lumen_portfolio_family_state.last_selected_at END,last_score=excluded.last_score,engine_version=excluded.engine_version")
      .bind(family, now, selected, selected ? now : null, topScore, VERSION, selected, selected).run();
  }
}

export async function recomputePortfolioGovernor(env) {
  if (!(await ensureSchema(env))) return { ok: false, error: "persistence_unavailable", version: VERSION };
  const factoryRows = await safeAll(env, "SELECT id,source_type,source_id,lane,stage,title,estimated_value_usd,probability,urgency,evidence_score,signal_score,economic_score,action_kind,action_ref,rationale,updated_at FROM lumen_opportunity_factory_candidates WHERE active=1 ORDER BY economic_score DESC,updated_at DESC LIMIT 500");
  const [commerceRows, feedbackMap, learning] = await Promise.all([virtualCommerceCandidates(env), loadFeedbackAdjustments(env), familyLearning(env)]);
  const rows = enrichRows([...factoryRows, ...commerceRows], feedbackMap, learning);
  const counts = Object.fromEntries(LANE_ORDER.map(lane => [lane, rows.filter(x => x.lane === lane).length]));
  const attention = activeAttention(counts);
  const familyCounts = Object.fromEntries(BUSINESS_FAMILIES.map(family => [family, rows.filter(x => x.business_family === family).length]));
  const familyAttentionPct = familyAttention(rows);
  const top = chooseEconomicCandidate(rows);
  const external = chooseEconomicCandidate(rows, { externalOnly: true });
  const verifiedRevenueUsd = await safeNumber(env, "SELECT COALESCE(SUM(amount_usd),0) n FROM lumen_revenue_events WHERE event_type='payment_settled' AND status='verified'");
  const verifiedSettlements = await safeNumber(env, "SELECT COUNT(*) n FROM lumen_revenue_events WHERE event_type='payment_settled' AND status='verified'");
  const previous = await env.DB.prepare("SELECT cycle FROM lumen_portfolio_governor_state WHERE id='GLOBAL' LIMIT 1").first();
  const cycle = num(previous?.cycle) + 1;
  const now = new Date().toISOString();
  const recommendedLane = top?.lane || "NEW_BUSINESS";
  const recommendedFamily = top?.business_family || "B2B_A2A";
  const recommendedAction = external?.action_kind || "NONE";
  const metrics = {
    activeCandidates: rows.length,
    factoryCandidates: factoryRows.length,
    commerceCandidates: commerceRows.length,
    laneCounts: counts,
    businessFamilyCounts: familyCounts,
    businessFamilyAttention: familyAttentionPct,
    recommendedBusinessFamily: recommendedFamily,
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
  await updateFamilyState(env, rows, recommendedFamily, now);
  const runId = `PG-${crypto.randomUUID().replaceAll("-", "").slice(0, 14).toUpperCase()}`;
  await env.DB.prepare("INSERT INTO lumen_portfolio_governor_runs(id,created_at,recommended_lane,recommended_action,active_candidates,verified_revenue_usd,details_json,engine_version) VALUES(?,?,?,?,?,?,?,?)")
    .bind(runId, now, recommendedLane, recommendedAction, rows.length, verifiedRevenueUsd, JSON.stringify({ counts, attention, familyCounts, familyAttentionPct, recommendedFamily, top: normalizedTop, external: normalizedExternal, selection: "economic_truth_first" }).slice(0, 8000), VERSION).run();
  return {
    ok: true,
    version: VERSION,
    cycle,
    objective: "maximize_verified_revenue_probability_under_zero_spend_and_authority_constraints",
    recommendedBusinessFamily: recommendedFamily,
    recommendedLane,
    recommendedExternalAction: recommendedAction,
    attention,
    businessFamilyAttention: familyAttentionPct,
    metrics,
    topCandidate: normalizedTop,
    externalCandidate: normalizedExternal,
    guardrails: {
      selectionRule: "collection_if_due_else_highest_economic_autonomy_score_across_business_families",
      verifiedRevenueFeedbackApplied: true,
      explorationBonusMax: 6,
      commerceIsCapabilityNotDefaultStrategy: true,
      existingBusinessProtected: true,
      collectionBeforeExploration: true,
      technicalRepliesDoNotCreateRevenueCredit: true,
      prioritizationDoesNotChangePrices: true,
      maxExternalMessagesPerCycle: 1,
      autonomousSpendUsd: 0,
      autonomousPurchase: false,
      autonomousContract: false,
      bindingActionsHumanGated: true
    }
  };
}

async function state(env) {
  if (!(await ensureSchema(env))) return { version: VERSION, initialized: false };
  const row = await env.DB.prepare("SELECT * FROM lumen_portfolio_governor_state WHERE id='GLOBAL' LIMIT 1").first();
  if (!row) return { version: VERSION, initialized: false, objective: "maximize_verified_revenue_probability_under_zero_spend_and_authority_constraints", baseAttention: BASE_ATTENTION };
  const parse = (v, fallback) => { try { return JSON.parse(v || ""); } catch { return fallback; } };
  const metrics = parse(row.metrics_json, {});
  return {
    version: VERSION,
    initialized: true,
    updatedAt: row.updated_at,
    cycle: num(row.cycle),
    recommendedBusinessFamily: metrics.recommendedBusinessFamily || null,
    recommendedLane: row.recommended_lane,
    recommendedExternalAction: row.recommended_action,
    recommendedSourceType: row.recommended_source_type,
    recommendedSourceId: row.recommended_source_id,
    attention: parse(row.attention_json, {}),
    businessFamilyAttention: metrics.businessFamilyAttention || {},
    metrics,
    topCandidate: parse(row.top_candidate_json, null),
    externalCandidate: parse(row.external_candidate_json, null),
    guardrails: { maxExternalMessagesPerCycle: 1, autonomousSpendUsd: 0, autonomousPurchase: false, autonomousContract: false, bindingActionsHumanGated: true }
  };
}

export async function handlePortfolioGovernor(request, env) {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/portfolio-governor/policy") return json({
    version: VERSION,
    name: "LUMEN Economic Autonomy Governor",
    objective: "maximize_verified_revenue_probability_under_zero_spend_and_authority_constraints",
    businessFamilies: BUSINESS_FAMILIES,
    selectionRule: "collection_if_due_else_probability_x_evidence_x_urgency_x_time_to_cash_x_verified_profit_feedback_plus_bounded_exploration",
    externalActionRule: "best_safe_external_action_by_economic_autonomy_score_with_at_most_one_external_message_per_cycle",
    learningRule: "verified_settlement_feedback_adjusts_service_and_a2a_priority; repeated_no_settlement_can_reduce_priority; cold_start_is_neutral",
    commerceRule: "commerce_competes_as_one_capability_and_receives_no_special_priority_without_conversion_evidence",
    changesPrices: false,
    createsContracts: false,
    autonomousSpendUsd: 0,
    autonomousPurchase: false,
    maxExternalMessagesPerCycle: 1,
    bindingActionsHumanGated: true
  });
  if (request.method === "GET" && url.pathname === "/portfolio-governor/state") return json(await state(env));
  if (request.method === "POST" && url.pathname === "/portfolio-governor/recompute") {
    if (!authorized(request, env)) return json({ ok: false, error: "admin_token_required" }, 403);
    return json(await recomputePortfolioGovernor(env), 202);
  }
  return null;
}
