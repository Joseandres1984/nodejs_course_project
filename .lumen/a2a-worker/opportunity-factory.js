const VERSION = "1.0-opportunity-factory-portfolio";

const LANE_ORDER = ["COLLECTION", "CLOSE", "INBOUND", "FOLLOW_UP", "NEW_BUSINESS", "EXPERIMENT"];
const EXTERNAL_ACTIONS = new Set(["COMMISSION_AUTOPILOT", "FIRST_CASH", "COMMERCIAL_REPLY", "FOLLOWUP", "NEW_OUTREACH"]);

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
function candidateId(sourceType, sourceId) {
  const left = clean(sourceType, 40).replace(/[^A-Za-z0-9]/g, "").slice(0, 14).toUpperCase();
  const right = clean(sourceId, 180).replace(/[^A-Za-z0-9_-]/g, "").slice(-56).toUpperCase();
  return `FACT-${left}-${right}`;
}
function overdue(dateText) {
  if (!dateText) return false;
  const t = new Date(dateText).getTime();
  return Number.isFinite(t) && t <= Date.now();
}
function scoreCandidate({ lane, valueUsd = 0, probability = 0, urgency = 0, evidenceScore = 0, signalScore = 0 }) {
  const laneBase = { COLLECTION: 60, CLOSE: 52, INBOUND: 45, FOLLOW_UP: 38, NEW_BUSINESS: 30, EXPERIMENT: 18 }[lane] || 10;
  const valueBoost = Math.min(12, Math.log10(1 + Math.max(0, valueUsd)) * 3.2);
  const probabilityBoost = clamp(probability, 0, 1) * 10;
  const urgencyBoost = clamp(urgency, 0, 1) * 8;
  const evidenceBoost = clamp(evidenceScore, 0, 100) * 0.06;
  const signalBoost = clamp(signalScore, 0, 100) * 0.04;
  return Math.round(clamp(laneBase + valueBoost + probabilityBoost + urgencyBoost + evidenceBoost + signalBoost, 0, 100));
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_opportunity_factory_candidates (id TEXT PRIMARY KEY,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,source_type TEXT NOT NULL,source_id TEXT NOT NULL,lane TEXT NOT NULL,stage TEXT NOT NULL,title TEXT,estimated_value_usd REAL NOT NULL DEFAULT 0,probability REAL NOT NULL DEFAULT 0,urgency REAL NOT NULL DEFAULT 0,evidence_score REAL NOT NULL DEFAULT 0,signal_score REAL NOT NULL DEFAULT 0,economic_score INTEGER NOT NULL DEFAULT 0,action_kind TEXT NOT NULL,action_ref TEXT,active INTEGER NOT NULL DEFAULT 1,rationale TEXT,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE UNIQUE INDEX IF NOT EXISTS idx_lumen_factory_source ON lumen_opportunity_factory_candidates(source_type,source_id)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_factory_rank ON lumen_opportunity_factory_candidates(active,lane,economic_score DESC,updated_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_opportunity_factory_runs (id TEXT PRIMARY KEY,started_at TEXT NOT NULL,finished_at TEXT NOT NULL,status TEXT NOT NULL,active_candidates INTEGER NOT NULL DEFAULT 0,details_json TEXT,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_factory_runs ON lumen_opportunity_factory_runs(started_at DESC)")
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

async function upsertCandidate(env, c) {
  const now = new Date().toISOString();
  const valueUsd = Math.max(0, num(c.valueUsd));
  const probability = clamp(c.probability, 0, 1);
  const urgency = clamp(c.urgency, 0, 1);
  const evidenceScore = clamp(c.evidenceScore, 0, 100);
  const signalScore = clamp(c.signalScore, 0, 100);
  const economicScore = scoreCandidate({ lane: c.lane, valueUsd, probability, urgency, evidenceScore, signalScore });
  const id = candidateId(c.sourceType, c.sourceId);
  await env.DB.prepare("INSERT INTO lumen_opportunity_factory_candidates(id,created_at,updated_at,source_type,source_id,lane,stage,title,estimated_value_usd,probability,urgency,evidence_score,signal_score,economic_score,action_kind,action_ref,active,rationale,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?) ON CONFLICT(source_type,source_id) DO UPDATE SET updated_at=excluded.updated_at,lane=excluded.lane,stage=excluded.stage,title=excluded.title,estimated_value_usd=excluded.estimated_value_usd,probability=excluded.probability,urgency=excluded.urgency,evidence_score=excluded.evidence_score,signal_score=excluded.signal_score,economic_score=excluded.economic_score,action_kind=excluded.action_kind,action_ref=excluded.action_ref,active=1,rationale=excluded.rationale,engine_version=excluded.engine_version")
    .bind(id, now, now, c.sourceType, c.sourceId, c.lane, c.stage, clean(c.title, 260) || null, valueUsd, probability, urgency, evidenceScore, signalScore, economicScore, c.actionKind, clean(c.actionRef, 260) || null, clean(c.rationale, 1500) || null, VERSION).run();
  return { id, ...c, valueUsd, probability, urgency, evidenceScore, signalScore, economicScore };
}

function commissionCandidate(row) {
  const status = clean(row.status, 80).toUpperCase();
  const dealValue = Math.max(0, num(row.deal_value_usd));
  const rate = Math.max(0, num(row.agreed_rate_pct || row.proposed_rate_pct));
  const exactAmount = Math.max(0, num(row.agreed_amount_usd || row.proposed_amount_usd));
  const derived = exactAmount || (dealValue > 0 && rate > 0 ? dealValue * rate / 100 : 0);
  if (status === "PAYMENT_DUE") return { lane: "COLLECTION", probability: 0.96, urgency: 1, evidenceScore: 95, actionKind: "COMMISSION_AUTOPILOT", rationale: "agreed_success_fee_is_due_and_checkout_ready" };
  if (status === "AGREED_PENDING_CLOSE") return { lane: "CLOSE", probability: 0.72, urgency: 0.78, evidenceScore: 85, actionKind: "COMMISSION_AUTOPILOT", rationale: "commission_terms_accepted_waiting_for_explicit_close_and_final_value" };
  if (status === "PROPOSAL_READY") return { lane: "NEW_BUSINESS", probability: 0.32, urgency: 0.45, evidenceScore: 62, actionKind: "COMMISSION_AUTOPILOT", rationale: "referral_success_fee_proposal_ready_for_explicit_acceptance" };
  return null;
}

function pipelineCandidate(row) {
  const stage = clean(row.stage, 80).toUpperCase();
  const responseClass = clean(row.response_class, 80).toUpperCase();
  if (stage === "NEGOTIATING") {
    if (responseClass === "COMMERCIAL_QUESTION") return { lane: "INBOUND", probability: 0.58, urgency: 0.9, evidenceScore: 86, actionKind: "COMMERCIAL_REPLY", rationale: "qualified_commercial_question_requires_response" };
    return { lane: "CLOSE", probability: responseClass === "PURCHASE_INTENT" ? 0.82 : 0.68, urgency: 0.95, evidenceScore: 90, actionKind: "FIRST_CASH", rationale: `qualified_${responseClass || "commercial_interest"}_ready_for_close` };
  }
  if (stage === "RESPONDED") return { lane: "INBOUND", probability: 0.45, urgency: 0.88, evidenceScore: 72, actionKind: "COMMERCIAL_REPLY", rationale: "response_received_requires_qualification_or_commercial_reply" };
  if (stage === "WAITING") return { lane: "FOLLOW_UP", probability: 0.24, urgency: overdue(row.next_action_at) ? 1 : 0.45, evidenceScore: 55, actionKind: "FOLLOWUP", rationale: overdue(row.next_action_at) ? "followup_due_now" : "followup_scheduled" };
  if (stage === "APPROVED" || stage === "PROPOSAL") return { lane: "NEW_BUSINESS", probability: 0.2, urgency: 0.5, evidenceScore: 58, actionKind: "NEW_OUTREACH", rationale: "approved_or_prepared_commercial_offer_waiting_for_initial_outreach" };
  if (stage === "WAITING_TASK") return { lane: "INBOUND", probability: 0.3, urgency: 0.6, evidenceScore: 60, actionKind: "POLL_ONLY", rationale: "remote_a2a_task_still_running" };
  return null;
}

export async function runOpportunityFactory(env) {
  if (!(await ensureSchema(env))) return { ok: false, error: "persistence_unavailable", version: VERSION };
  const startedAt = new Date().toISOString();
  const runId = `FACTRUN-${crypto.randomUUID().replaceAll("-", "").slice(0, 14).toUpperCase()}`;
  await env.DB.prepare("UPDATE lumen_opportunity_factory_candidates SET active=0").run();
  const created = [];

  const commissions = await safeAll(env, "SELECT referral_id,status,deal_value_usd,proposed_rate_pct,proposed_amount_usd,agreed_rate_pct,agreed_amount_usd,updated_at FROM lumen_referral_commissions WHERE status IN ('PROPOSAL_READY','AGREED_PENDING_CLOSE','PAYMENT_DUE') ORDER BY updated_at DESC LIMIT 200");
  for (const row of commissions) {
    const mapped = commissionCandidate(row); if (!mapped) continue;
    created.push(await upsertCandidate(env, { sourceType: "REFERRAL_COMMISSION", sourceId: row.referral_id, stage: row.status, title: `Referral commission ${row.referral_id}`, valueUsd: Math.max(0, num(row.agreed_amount_usd || row.proposed_amount_usd) || (num(row.deal_value_usd) * num(row.agreed_rate_pct || row.proposed_rate_pct) / 100)), signalScore: 80, actionRef: row.referral_id, ...mapped }));
  }

  const pipeline = await safeAll(env, "SELECT proposal_id,opportunity_id,target,offer_name,amount_usd,stage,response_class,next_action,next_action_at,last_contact_at,updated_at FROM lumen_sales_pipeline WHERE stage NOT IN ('LOST','NO_RESPONSE','BLOCKED') ORDER BY updated_at DESC LIMIT 300");
  for (const row of pipeline) {
    const mapped = pipelineCandidate(row); if (!mapped) continue;
    created.push(await upsertCandidate(env, { sourceType: "SALES_PIPELINE", sourceId: row.proposal_id, stage: row.stage, title: clean(`${row.offer_name || "LUMEN offer"} — ${row.target || row.opportunity_id}`, 260), valueUsd: Math.max(0, num(row.amount_usd)), signalScore: row.response_class ? 82 : 55, actionRef: row.proposal_id, ...mapped }));
  }

  const opportunities = await safeAll(env, "SELECT o.id,o.name,o.score,o.fit,o.demand_signal,o.revenue_offer_id,o.status,o.updated_at FROM lumen_opportunities o LEFT JOIN lumen_proposal_drafts p ON p.opportunity_id=o.id WHERE p.opportunity_id IS NULL AND o.status IN ('qualified','watching','new') AND o.score>=35 ORDER BY o.score DESC,o.updated_at DESC LIMIT 300");
  for (const row of opportunities) {
    const signal = clamp(row.score, 0, 100);
    const fit = clean(row.fit, 20).toUpperCase();
    created.push(await upsertCandidate(env, { sourceType: "DISCOVERY", sourceId: row.id, lane: "NEW_BUSINESS", stage: row.status, title: row.name || row.id, valueUsd: 0, probability: fit === "A" ? 0.36 : fit === "B" ? 0.28 : 0.18, urgency: num(row.demand_signal) ? 0.72 : 0.35, evidenceScore: num(row.demand_signal) ? 72 : 52, signalScore: signal, actionKind: "BUILD_PROPOSAL", actionRef: row.id, rationale: `public_or_a2a_signal_score_${signal}_fit_${fit || "UNKNOWN"}` }));
  }

  const ideas = await safeAll(env, "SELECT id,title,estimated_revenue_usd,estimated_cost_usd,revenue_confidence,total_score,status,evidence_score,updated_at FROM lumen_partner_ideas WHERE status IN ('HIGH_POTENTIAL','REVIEW') ORDER BY total_score DESC,updated_at DESC LIMIT 120");
  for (const row of ideas) {
    const upside = Math.max(0, num(row.estimated_revenue_usd) - Math.max(0, num(row.estimated_cost_usd)));
    created.push(await upsertCandidate(env, { sourceType: "VENTURE_IDEA", sourceId: row.id, lane: "EXPERIMENT", stage: row.status, title: row.title || row.id, valueUsd: upside, probability: clean(row.revenue_confidence, 40).toLowerCase() === "verified" ? 0.45 : 0.12, urgency: 0.15, evidenceScore: clamp(row.evidence_score || row.total_score, 0, 100), signalScore: clamp(row.total_score, 0, 100), actionKind: "EXPERIMENT_REVIEW", actionRef: row.id, rationale: "venture_idea_kept_below_live_commercial_work_until_evidence_improves" }));
  }

  const finishedAt = new Date().toISOString();
  const laneCounts = Object.fromEntries(LANE_ORDER.map(lane => [lane, created.filter(x => x.lane === lane).length]));
  const externalReady = created.filter(x => EXTERNAL_ACTIONS.has(x.actionKind)).length;
  await env.DB.prepare("INSERT INTO lumen_opportunity_factory_runs(id,started_at,finished_at,status,active_candidates,details_json,engine_version) VALUES(?,?,?,?,?,?,?)")
    .bind(runId, startedAt, finishedAt, "complete", created.length, JSON.stringify({ laneCounts, externalReady }).slice(0, 6000), VERSION).run();
  return { ok: true, version: VERSION, runId, activeCandidates: created.length, externalReady, laneCounts, topCandidates: [...created].sort((a, b) => b.economicScore - a.economicScore).slice(0, 12).map(x => ({ id: x.id, sourceType: x.sourceType, sourceId: x.sourceId, lane: x.lane, stage: x.stage, economicScore: x.economicScore, actionKind: x.actionKind, estimatedValueUsd: Number(x.valueUsd.toFixed(2)), rationale: x.rationale })), guardrails: { prioritizationOnly: true, createsExternalMessages: false, autonomousSpend: false, autonomousPurchase: false, autonomousContract: false, bindingActionsHumanGated: true } };
}

async function stats(env) {
  if (!(await ensureSchema(env))) return { version: VERSION, activeCandidates: 0, laneCounts: {} };
  const rows = await safeAll(env, "SELECT id,source_type,source_id,lane,stage,title,estimated_value_usd,probability,urgency,evidence_score,signal_score,economic_score,action_kind,action_ref,rationale,updated_at FROM lumen_opportunity_factory_candidates WHERE active=1 ORDER BY CASE lane WHEN 'COLLECTION' THEN 0 WHEN 'CLOSE' THEN 1 WHEN 'INBOUND' THEN 2 WHEN 'FOLLOW_UP' THEN 3 WHEN 'NEW_BUSINESS' THEN 4 ELSE 5 END,economic_score DESC,updated_at DESC LIMIT 50");
  const laneCounts = Object.fromEntries(LANE_ORDER.map(lane => [lane, rows.filter(x => x.lane === lane).length]));
  return { version: VERSION, activeCandidates: rows.length, laneCounts, candidates: rows.slice(0, 20), guardrails: { prioritizationOnly: true, createsExternalMessages: false, autonomousSpend: false, autonomousContract: false } };
}

export async function handleOpportunityFactory(request, env) {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/opportunity-factory/policy") return json({ version: VERSION, name: "LUMEN Opportunity Factory", objective: "normalize_existing_and_new_economic_opportunities_into_one_ranked_portfolio_without_replacing_existing_business_engines", laneHierarchy: LANE_ORDER, scoringInputs: ["stage_priority","expected_value","probability","urgency","evidence","signal_strength"], createsExternalMessages: false, maxExternalMessagesPerCycle: 1, autonomousSpend: false, autonomousPurchase: false, autonomousContract: false, bindingActionsHumanGated: true });
  if (request.method === "GET" && url.pathname === "/opportunity-factory/stats") return json(await stats(env));
  if (request.method === "POST" && url.pathname === "/opportunity-factory/run") {
    if (!authorized(request, env)) return json({ ok: false, error: "admin_token_required" }, 403);
    return json(await runOpportunityFactory(env), 202);
  }
  return null;
}
