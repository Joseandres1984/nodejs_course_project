import { recomputeCapabilityGaps } from "./capability-gap-engine.js";

const VERSION = "1.0-growth-engine-foundry";
const MAX_HISTORY = 120;
const MAX_CANDIDATES = 40;
const ALLOWED_PRIMITIVES = [
  "B2B_DISCOVERY",
  "B2B_CONVERSION",
  "PARTNER_NETWORK",
  "VENTURE_INTAKE",
  "REFERRAL_MONETIZATION",
  "TRAVEL_ACQUISITION"
];

function clean(value, limit = 4000) {
  return String(value ?? "").trim().replace(/[\r\n\t]+/g, " ").slice(0, limit);
}
function num(value) {
  const n = Number(value || 0);
  return Number.isFinite(n) ? n : 0;
}
function clamp(value, min = 0, max = 100) {
  return Math.max(min, Math.min(max, num(value)));
}
function parse(value, fallback = {}) {
  try { return JSON.parse(value || ""); } catch { return fallback; }
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
  const supplied = clean(request.headers.get("x-lumen-admin"), 500);
  return Boolean(expected && supplied && expected === supplied);
}
async function first(env, sql, bind = []) {
  try {
    const q = env.DB.prepare(sql);
    return bind.length ? await q.bind(...bind).first() : await q.first();
  } catch {
    return null;
  }
}
async function all(env, sql, bind = []) {
  try {
    const q = env.DB.prepare(sql);
    const r = bind.length ? await q.bind(...bind).all() : await q.all();
    return r.results || [];
  } catch {
    return [];
  }
}
async function scalar(env, sql, bind = []) {
  const row = await first(env, sql, bind);
  return num(row?.n);
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_growth_foundry_candidates (id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,name TEXT NOT NULL,source_key TEXT NOT NULL,source_reason TEXT NOT NULL,gap_capability TEXT,primitives_json TEXT NOT NULL,source_strength REAL NOT NULL,status TEXT NOT NULL,score REAL NOT NULL DEFAULT 0,incumbent_score REAL NOT NULL DEFAULT 0,trials INTEGER NOT NULL DEFAULT 0,positive_trials INTEGER NOT NULL DEFAULT 0,stalls INTEGER NOT NULL DEFAULT 0,cumulative_delta REAL NOT NULL DEFAULT 0,verified_revenue_delta_usd REAL NOT NULL DEFAULT 0,baseline_json TEXT,last_observation_json TEXT,promoted_at TEXT,rejected_at TEXT,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_growth_foundry_candidates_rank ON lumen_growth_foundry_candidates(status,score DESC,updated_at DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_growth_foundry_state (id TEXT PRIMARY KEY,updated_at TEXT NOT NULL,cycle INTEGER NOT NULL,selected_candidate_id TEXT,execution_action TEXT NOT NULL,baseline_json TEXT,incumbent_lane TEXT,incumbent_score REAL NOT NULL DEFAULT 0,summary_json TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_growth_foundry_history (id TEXT PRIMARY KEY,created_at TEXT NOT NULL,trigger TEXT NOT NULL,cycle INTEGER NOT NULL,selected_candidate_id TEXT,execution_action TEXT NOT NULL,evaluation_json TEXT NOT NULL,summary_json TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_growth_foundry_history_created ON lumen_growth_foundry_history(created_at DESC)")
  ]);
  return true;
}

function candidateId(fingerprint) {
  const safe = clean(fingerprint, 180).toUpperCase().replace(/[^A-Z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return `GFM-${safe}`.slice(0, 220);
}

function blueprint({ name, sourceKey, sourceReason, gapCapability = "", primitives = [], sourceStrength = 50 }) {
  const normalized = [...new Set(primitives)].filter(x => ALLOWED_PRIMITIVES.includes(x)).slice(0, 3);
  const fingerprint = `${sourceKey}|${clean(gapCapability, 80).toLowerCase()}|${normalized.join("+")}`;
  return {
    id: candidateId(fingerprint),
    fingerprint,
    name: clean(name, 180),
    sourceKey: clean(sourceKey, 80),
    sourceReason: clean(sourceReason, 1200),
    gapCapability: clean(gapCapability, 80),
    primitives: normalized,
    sourceStrength: clamp(sourceStrength)
  };
}

export function deriveGrowthMotorBlueprints(signals = {}) {
  const out = [];
  const gap = signals.topGap || null;
  const b2b = signals.B2B || {};
  const partner = signals.PARTNER || {};
  const venture = signals.VENTURE || {};
  const referral = signals.REFERRAL || {};
  const travel = signals.TRAVEL || {};

  if (gap?.capability) {
    out.push(blueprint({
      name: `Capability Bridge: ${gap.capability}`,
      sourceKey: "CAPABILITY_GAP",
      sourceReason: `highest uncovered capability=${gap.capability}; priority=${num(gap.priority)}; status=${gap.status || "OPEN"}`,
      gapCapability: gap.capability,
      primitives: ["PARTNER_NETWORK", "B2B_DISCOVERY"],
      sourceStrength: 55 + num(gap.priority) * .38
    }));
  }

  if (num(venture.highPotential) + num(venture.review) + num(venture.ingestedPass) > 0) {
    out.push(blueprint({
      name: "Venture-to-Market Converter",
      sourceKey: "VENTURE_DEMAND_BRIDGE",
      sourceReason: `high_potential=${num(venture.highPotential)}; review=${num(venture.review)}; ingested_pass=${num(venture.ingestedPass)}`,
      primitives: ["VENTURE_INTAKE", "B2B_DISCOVERY", "B2B_CONVERSION"],
      sourceStrength: 48 + num(venture.highPotential) * 9 + num(venture.review) * 3 + num(venture.ingestedPass) * 4
    }));
  }

  if (num(referral.paymentDue) + num(referral.agreedPendingClose) + num(referral.proposalReady) + num(partner.matches) > 0) {
    out.push(blueprint({
      name: "Partner Referral Flywheel",
      sourceKey: "REFERRAL_NETWORK",
      sourceReason: `payment_due=${num(referral.paymentDue)}; agreed=${num(referral.agreedPendingClose)}; proposal_ready=${num(referral.proposalReady)}; matches=${num(partner.matches)}`,
      primitives: ["PARTNER_NETWORK", "REFERRAL_MONETIZATION"],
      sourceStrength: 46 + num(referral.paymentDue) * 12 + num(referral.agreedPendingClose) * 7 + num(referral.proposalReady) * 3 + num(partner.matches) * .8
    }));
  }

  if (num(travel.confirmations30d) + num(travel.clicks7d) + num(travel.recommendedCampaigns) > 0) {
    out.push(blueprint({
      name: "Travel Demand Partner Loop",
      sourceKey: "TRAVEL_PARTNER_COMPOUNDER",
      sourceReason: `confirmations=${num(travel.confirmations30d)}; clicks7d=${num(travel.clicks7d)}; recommended=${num(travel.recommendedCampaigns)}`,
      primitives: ["TRAVEL_ACQUISITION", "PARTNER_NETWORK"],
      sourceStrength: 44 + num(travel.confirmations30d) * 12 + num(travel.clicks7d) * .35 + num(travel.recommendedCampaigns) * .7
    }));
  }

  if (num(b2b.activeCandidates) + num(b2b.quotes7d) + num(b2b.negotiating) > 0 || out.length === 0) {
    out.push(blueprint({
      name: "Demand-to-Conversion Motor",
      sourceKey: "B2B_DEMAND_COMPOUNDER",
      sourceReason: `active_candidates=${num(b2b.activeCandidates)}; quotes7d=${num(b2b.quotes7d)}; negotiating=${num(b2b.negotiating)}`,
      primitives: ["B2B_DISCOVERY", "B2B_CONVERSION"],
      sourceStrength: 45 + num(b2b.negotiating) * 10 + num(b2b.quotes7d) * 3 + num(b2b.activeCandidates) * .7
    }));
  }

  return out
    .filter(x => x.primitives.length >= 2)
    .sort((a, b) => b.sourceStrength - a.sourceStrength)
    .slice(0, 8);
}

async function topCapabilityGap(env) {
  return first(env, "SELECT capability,priority,status,reason,current_candidates,strong_candidates,observed_confident_candidates FROM lumen_capability_gap_queue WHERE status<>'COVERED' ORDER BY priority DESC,updated_at DESC LIMIT 1");
}

async function incumbent(env) {
  const row = await first(env, "SELECT primary_lane,scores_json FROM lumen_growth_multiplier_state WHERE id='CURRENT' LIMIT 1");
  const scores = parse(row?.scores_json, []);
  const ranked = Array.isArray(scores) ? scores.slice().sort((a, b) => num(b.score) - num(a.score)) : [];
  const best = ranked[0] || null;
  return {
    lane: clean(best?.lane || row?.primary_lane || "UNKNOWN", 80),
    rawScore: num(best?.score),
    score: clamp(best?.score, 0, 100)
  };
}

async function signalSnapshot(env) {
  const [
    verifiedRevenueUsd30d, verifiedSettlements30d,
    negotiating, quotes7d, inbound7d, activeCandidates,
    partnerAgents, partnerMatches, partnerCouncils,
    ventureHighPotential, ventureReview, ventureIngestedPass,
    referralRevenueUsd30d, referralSettlements30d, referralPaymentDue, referralAgreed, referralProposalReady,
    travelRevenueUsd30d, travelRewards30d, travelConfirmations30d, travelClicks7d, travelRecommended
  ] = await Promise.all([
    scalar(env, "SELECT COALESCE(SUM(amount_usd),0) n FROM lumen_revenue_events WHERE event_type='payment_settled' AND source='x402' AND status='verified' AND datetime(created_at)>=datetime('now','-30 days')"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_revenue_events WHERE event_type='payment_settled' AND source='x402' AND status='verified' AND datetime(created_at)>=datetime('now','-30 days')"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_sales_pipeline WHERE stage='NEGOTIATING'"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_a2a_quotes WHERE datetime(created_at)>=datetime('now','-7 days')"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_a2a_inbound WHERE binding_intent=0 AND datetime(received_at)>=datetime('now','-7 days')"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_opportunity_factory_candidates WHERE active=1"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_partner_agents"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_partner_matches"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_partner_councils"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_partner_ideas WHERE status='HIGH_POTENTIAL'"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_partner_ideas WHERE status='REVIEW'"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_venture_suggestion_intake WHERE status='INGESTED_PASS'"),
    scalar(env, "SELECT COALESCE(SUM(settled_amount_usd),0) n FROM lumen_referral_commissions WHERE status='SETTLED' AND datetime(updated_at)>=datetime('now','-30 days')"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_referral_commissions WHERE status='SETTLED' AND datetime(updated_at)>=datetime('now','-30 days')"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_referral_commissions WHERE status='PAYMENT_DUE'"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_referral_commissions WHERE status='AGREED_PENDING_CLOSE'"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_referral_commissions WHERE status='PROPOSAL_READY'"),
    scalar(env, "SELECT COALESCE(SUM(amount_usd),0) n FROM lumen_revenue_events WHERE event_type='affiliate_reward_confirmed' AND source='travelpayouts' AND status='verified' AND datetime(created_at)>=datetime('now','-30 days')"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_revenue_events WHERE event_type='affiliate_reward_confirmed' AND source='travelpayouts' AND status='verified' AND datetime(created_at)>=datetime('now','-30 days')"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_viator_booking_events WHERE event_type='CONFIRMATION' AND datetime(last_updated)>=datetime('now','-30 days')"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_travel_events WHERE event_type='click' AND datetime(created_at)>=datetime('now','-7 days')"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_travel_acquisition_campaigns WHERE status IN ('RECOMMENDED','APPROVED')")
  ]);

  const topGap = await topCapabilityGap(env);
  return {
    capturedAt: new Date().toISOString(),
    topGap,
    B2B: { verifiedRevenueUsd30d, verifiedSettlements30d, negotiating, quotes7d, inbound7d, activeCandidates },
    PARTNER: { partnerAgents, matches:partnerMatches, councils:partnerCouncils },
    VENTURE: { highPotential:ventureHighPotential, review:ventureReview, ingestedPass:ventureIngestedPass },
    REFERRAL: { verifiedRevenueUsd30d:referralRevenueUsd30d, verifiedSettlements30d:referralSettlements30d, paymentDue:referralPaymentDue, agreedPendingClose:referralAgreed, proposalReady:referralProposalReady },
    TRAVEL: { verifiedRevenueUsd30d:travelRevenueUsd30d, verifiedRewards30d:travelRewards30d, confirmations30d:travelConfirmations30d, clicks7d:travelClicks7d, recommendedCampaigns:travelRecommended }
  };
}

function uniquePrimitives(candidate) {
  const list = Array.isArray(candidate?.primitives) ? candidate.primitives : parse(candidate?.primitives_json, []);
  return [...new Set(list)].filter(x => ALLOWED_PRIMITIVES.includes(x));
}

export function proofForCandidate(candidate, snapshot = {}) {
  const b = snapshot.B2B || {};
  const p = snapshot.PARTNER || {};
  const v = snapshot.VENTURE || {};
  const r = snapshot.REFERRAL || {};
  const t = snapshot.TRAVEL || {};
  let proof = 0;
  for (const primitive of uniquePrimitives(candidate)) {
    if (primitive === "B2B_DISCOVERY") proof += num(b.activeCandidates) * 2 + num(b.quotes7d) * 3 + num(b.inbound7d) + num(b.verifiedSettlements30d) * 20;
    if (primitive === "B2B_CONVERSION") proof += num(b.negotiating) * 9 + num(b.quotes7d) * 4 + num(b.verifiedSettlements30d) * 30;
    if (primitive === "PARTNER_NETWORK") proof += num(p.partnerAgents) * .5 + num(p.matches) * 4 + num(p.councils) * 7;
    if (primitive === "VENTURE_INTAKE") proof += num(v.highPotential) * 9 + num(v.review) * 3 + num(v.ingestedPass) * 6;
    if (primitive === "REFERRAL_MONETIZATION") proof += num(r.proposalReady) * 2 + num(r.agreedPendingClose) * 7 + num(r.paymentDue) * 12 + num(r.verifiedSettlements30d) * 35;
    if (primitive === "TRAVEL_ACQUISITION") proof += num(t.clicks7d) * 1.2 + num(t.confirmations30d) * 18 + num(t.verifiedRewards30d) * 35 + num(t.recommendedCampaigns) * .4;
  }
  return Number(proof.toFixed(2));
}

function verifiedRevenueForCandidate(candidate, snapshot = {}) {
  const primitives = uniquePrimitives(candidate);
  let value = 0;
  if (primitives.includes("B2B_DISCOVERY") || primitives.includes("B2B_CONVERSION")) value += num(snapshot.B2B?.verifiedRevenueUsd30d);
  if (primitives.includes("REFERRAL_MONETIZATION")) value += num(snapshot.REFERRAL?.verifiedRevenueUsd30d);
  if (primitives.includes("TRAVEL_ACQUISITION")) value += num(snapshot.TRAVEL?.verifiedRevenueUsd30d);
  return Number(value.toFixed(2));
}

export function scoreFoundryCandidate(candidate = {}, incumbentScore = 0) {
  const sourceStrength = clamp(candidate.sourceStrength ?? candidate.source_strength, 0, 100);
  const positive = num(candidate.positiveTrials ?? candidate.positive_trials);
  const stalls = num(candidate.stalls);
  const delta = Math.max(0, num(candidate.cumulativeDelta ?? candidate.cumulative_delta));
  const verified = Math.max(0, num(candidate.verifiedRevenueDeltaUsd ?? candidate.verified_revenue_delta_usd));
  const status = clean(candidate.status, 40);
  const evidence = Math.min(22, positive * 7 + Math.log1p(delta) * 3.5 + Math.log1p(verified) * 8);
  const penalty = Math.min(22, stalls * 4.5);
  const promotionBonus = status === "PROMOTED" ? 10 : 0;
  const challengerBonus = clamp(incumbentScore, 0, 100) < 60 ? 5 : 0;
  return Number(clamp(sourceStrength * .62 + 18 + evidence + promotionBonus + challengerBonus - penalty, 0, 100).toFixed(2));
}

export function decideCandidateLifecycle(candidate = {}, incumbentScore = 0) {
  const score = num(candidate.score);
  const trials = num(candidate.trials);
  const positive = num(candidate.positiveTrials ?? candidate.positive_trials);
  const stalls = num(candidate.stalls);
  const delta = num(candidate.cumulativeDelta ?? candidate.cumulative_delta);
  const verified = num(candidate.verifiedRevenueDeltaUsd ?? candidate.verified_revenue_delta_usd);
  const promotionThreshold = Math.max(55, Math.min(82, clamp(incumbentScore) * .68));

  if ((verified > 0 && positive >= 1 && delta > 0 && score >= 50) || (positive >= 2 && delta >= 2 && score >= promotionThreshold)) {
    return { status:"PROMOTED", reason:verified > 0 ? "verified_economic_progress_observed" : "repeated_observed_progress_beats_promotion_threshold", promotionThreshold };
  }
  if ((stalls >= 4 && positive === 0) || (trials >= 6 && positive / Math.max(1, trials) < .25 && delta <= 0)) {
    return { status:"REJECTED", reason:"repeated_trials_failed_to_create_observed_progress", promotionThreshold };
  }
  return { status:trials > 0 ? "TRIAL" : "DISCOVERED", reason:"more_evidence_required", promotionThreshold };
}

async function upsertBlueprints(env, blueprints) {
  const now = new Date().toISOString();
  for (const b of blueprints) {
    await env.DB.prepare("INSERT INTO lumen_growth_foundry_candidates(id,fingerprint,created_at,updated_at,name,source_key,source_reason,gap_capability,primitives_json,source_strength,status,score,incumbent_score,trials,positive_trials,stalls,cumulative_delta,verified_revenue_delta_usd,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,'DISCOVERED',0,0,0,0,0,0,0,?) ON CONFLICT(fingerprint) DO UPDATE SET updated_at=excluded.updated_at,name=excluded.name,source_reason=excluded.source_reason,gap_capability=excluded.gap_capability,primitives_json=excluded.primitives_json,source_strength=excluded.source_strength,engine_version=excluded.engine_version")
      .bind(b.id,b.fingerprint,now,now,b.name,b.sourceKey,b.sourceReason,b.gapCapability||null,JSON.stringify(b.primitives),b.sourceStrength,VERSION).run();
  }
}

async function loadCandidate(env, id) {
  if (!id) return null;
  return first(env, "SELECT * FROM lumen_growth_foundry_candidates WHERE id=? LIMIT 1", [id]);
}

async function evaluatePrevious(env, state, snapshot, incumbentState) {
  if (!state?.selected_candidate_id || !state?.baseline_json) return { evaluated:false, reason:"no_previous_probe" };
  const candidate = await loadCandidate(env, state.selected_candidate_id);
  if (!candidate || candidate.status === "REJECTED") return { evaluated:false, reason:"candidate_not_evaluable" };
  const before = parse(state.baseline_json, {});
  const beforeProof = proofForCandidate(candidate, before);
  const afterProof = proofForCandidate(candidate, snapshot);
  const delta = Number((afterProof - beforeProof).toFixed(2));
  const beforeRevenue = verifiedRevenueForCandidate(candidate, before);
  const afterRevenue = verifiedRevenueForCandidate(candidate, snapshot);
  const verifiedRevenueDeltaUsd = Number(Math.max(0, afterRevenue - beforeRevenue).toFixed(2));
  const positive = delta >= 1 || (verifiedRevenueDeltaUsd > 0 && delta > 0);
  const positiveTrials = num(candidate.positive_trials) + (positive ? 1 : 0);
  const stalls = positive ? 0 : num(candidate.stalls) + 1;
  const cumulativeDelta = Number((num(candidate.cumulative_delta) + delta).toFixed(2));
  const verifiedTotal = Number((num(candidate.verified_revenue_delta_usd) + verifiedRevenueDeltaUsd).toFixed(2));
  const scored = scoreFoundryCandidate({ ...candidate, positive_trials:positiveTrials, stalls, cumulative_delta:cumulativeDelta, verified_revenue_delta_usd:verifiedTotal }, incumbentState.score);
  const lifecycle = decideCandidateLifecycle({ ...candidate, score:scored, positive_trials:positiveTrials, stalls, cumulative_delta:cumulativeDelta, verified_revenue_delta_usd:verifiedTotal }, incumbentState.score);
  const now = new Date().toISOString();
  await env.DB.prepare("UPDATE lumen_growth_foundry_candidates SET updated_at=?,status=?,score=?,incumbent_score=?,positive_trials=?,stalls=?,cumulative_delta=?,verified_revenue_delta_usd=?,last_observation_json=?,promoted_at=CASE WHEN ?='PROMOTED' AND promoted_at IS NULL THEN ? ELSE promoted_at END,rejected_at=CASE WHEN ?='REJECTED' AND rejected_at IS NULL THEN ? ELSE rejected_at END,engine_version=? WHERE id=?")
    .bind(now,lifecycle.status,scored,incumbentState.score,positiveTrials,stalls,cumulativeDelta,verifiedTotal,JSON.stringify({beforeProof,afterProof,delta,beforeRevenue,afterRevenue,verifiedRevenueDeltaUsd,positive,attribution:"observational_not_causal"}),lifecycle.status,now,lifecycle.status,now,VERSION,candidate.id).run();
  return { evaluated:true, candidateId:candidate.id, candidateName:candidate.name, beforeProof, afterProof, delta, verifiedRevenueDeltaUsd, positive, score:scored, status:lifecycle.status, lifecycleReason:lifecycle.reason, promotionThreshold:lifecycle.promotionThreshold, attribution:"observational_not_causal" };
}

async function rankCandidates(env, incumbentState) {
  const rows = await all(env, "SELECT * FROM lumen_growth_foundry_candidates WHERE status<>'REJECTED' ORDER BY updated_at DESC LIMIT 100");
  const ranked = rows.map(row => ({
    ...row,
    primitives:parse(row.primitives_json, []),
    score:scoreFoundryCandidate(row, incumbentState.score)
  })).sort((a,b) => b.score - a.score || num(b.positive_trials) - num(a.positive_trials) || a.created_at.localeCompare(b.created_at));
  for (const row of ranked) {
    await env.DB.prepare("UPDATE lumen_growth_foundry_candidates SET score=?,incumbent_score=?,engine_version=? WHERE id=?")
      .bind(row.score,incumbentState.score,VERSION,row.id).run();
  }
  return ranked;
}

export function chooseFoundryCandidate(ranked = [], cycle = 1, incumbentScore = 0) {
  const promoted = ranked.filter(x => x.status === "PROMOTED" && num(x.score) >= Math.max(48, clamp(incumbentScore) * .6));
  const trials = ranked.filter(x => x.status === "TRIAL" && num(x.trials) < 6);
  const discovered = ranked.filter(x => x.status === "DISCOVERED");
  const challenger = [...trials, ...discovered].sort((a,b) => num(b.score) - num(a.score))[0] || null;
  const periodicChallenge = cycle % 4 === 0;
  if (periodicChallenge && challenger && num(challenger.score) >= 40) return challenger;
  if (promoted[0]) return promoted[0];
  if (trials[0] && num(trials[0].score) >= 38) return trials[0];
  if (discovered[0] && num(discovered[0].score) >= 38) return discovered[0];
  return null;
}

async function markSelected(env, candidate, snapshot, incumbentState) {
  if (!candidate) return null;
  const now = new Date().toISOString();
  const nextStatus = candidate.status === "PROMOTED" ? "PROMOTED" : "TRIAL";
  await env.DB.prepare("UPDATE lumen_growth_foundry_candidates SET updated_at=?,status=?,trials=trials+1,baseline_json=?,incumbent_score=?,engine_version=? WHERE id=?")
    .bind(now,nextStatus,JSON.stringify(snapshot),incumbentState.score,VERSION,candidate.id).run();
  return { ...candidate, status:nextStatus, trials:num(candidate.trials)+1, primitives:uniquePrimitives(candidate) };
}

function guardrails() {
  return {
    autonomousSpendUsd:0,
    autonomousPurchase:false,
    autonomousContract:false,
    paidMedia:false,
    createsExternalMessages:false,
    executesGeneratedCode:false,
    selfModifyingCode:false,
    newConnectors:false,
    maxGeneratedMotorPrimitives:3,
    oneFoundryMotorExecutionPerCycle:true,
    primitiveExecutionRequiresStaticWhitelist:true,
    bindingActionsHumanGated:true,
    verifiedRevenueOnly:true,
    learningAttribution:"observational_not_causal"
  };
}

async function trim(env) {
  try {
    await env.DB.prepare(`DELETE FROM lumen_growth_foundry_history WHERE id NOT IN (SELECT id FROM lumen_growth_foundry_history ORDER BY created_at DESC LIMIT ${MAX_HISTORY})`).run();
    await env.DB.prepare(`DELETE FROM lumen_growth_foundry_candidates WHERE id IN (SELECT id FROM lumen_growth_foundry_candidates WHERE status IN ('REJECTED','PARKED') ORDER BY updated_at DESC LIMIT -1 OFFSET ${MAX_CANDIDATES})`).run();
  } catch {}
}

export async function runGrowthEngineFoundryCycle(env, options = {}) {
  if (!(await ensureSchema(env))) return { ok:false, error:"persistence_unavailable", version:VERSION };

  const gapRefresh = await recomputeCapabilityGaps(env).catch(error => ({ ok:false, error:String(error?.message || error).slice(0,220) }));
  const previousState = await first(env, "SELECT * FROM lumen_growth_foundry_state WHERE id='CURRENT' LIMIT 1");
  const incumbentState = await incumbent(env);
  const snapshot = await signalSnapshot(env);
  const evaluation = await evaluatePrevious(env, previousState, snapshot, incumbentState);
  const blueprints = deriveGrowthMotorBlueprints(snapshot);
  await upsertBlueprints(env, blueprints);
  const ranked = await rankCandidates(env, incumbentState);
  const cycle = Math.max(1, num(previousState?.cycle) + 1);
  const selected = chooseFoundryCandidate(ranked, cycle, incumbentState.score);
  const selectedLive = await markSelected(env, selected, snapshot, incumbentState);

  let action = "NONE";
  if (selectedLive?.status === "PROMOTED") action = "RUN_PROMOTED_MOTOR";
  else if (selectedLive) action = "PROBE_CANDIDATE";

  const comparison = selectedLive ? {
    foundryScore:num(selectedLive.score),
    incumbentLane:incumbentState.lane,
    incumbentScore:incumbentState.score,
    ratio:incumbentState.score > 0 ? Number((num(selectedLive.score) / incumbentState.score).toFixed(3)) : null,
    incorporationRule:"promote_only_after_observed_progress_and_threshold_or_verified_economic_progress"
  } : null;

  const directive = selectedLive ? {
    action,
    candidate:{
      id:selectedLive.id,
      name:selectedLive.name,
      status:selectedLive.status,
      score:num(selectedLive.score),
      sourceKey:selectedLive.source_key,
      sourceReason:selectedLive.source_reason,
      gapCapability:selectedLive.gap_capability || null,
      primitives:selectedLive.primitives,
      trials:num(selectedLive.trials),
      positiveTrials:num(selectedLive.positive_trials),
      stalls:num(selectedLive.stalls)
    },
    comparison,
    generatedCode:false,
    staticPrimitiveWhitelist:true
  } : { action:"NONE", candidate:null, comparison:null, generatedCode:false, staticPrimitiveWhitelist:true };

  const summary = {
    gapRefresh:{ ok:gapRefresh?.ok !== false, evaluated:num(gapRefresh?.evaluated), open:num(gapRefresh?.open), weakCoverage:num(gapRefresh?.weakCoverage), covered:num(gapRefresh?.covered) },
    incumbent:incumbentState,
    blueprintsGenerated:blueprints.length,
    candidateCounts:{
      promoted:ranked.filter(x=>x.status==='PROMOTED').length,
      trial:ranked.filter(x=>x.status==='TRIAL').length,
      discovered:ranked.filter(x=>x.status==='DISCOVERED').length
    },
    selected:directive.candidate,
    comparison,
    evaluation
  };

  const now = new Date().toISOString();
  const trigger = clean(options.trigger || "operator", 100);
  await env.DB.prepare("INSERT OR REPLACE INTO lumen_growth_foundry_state(id,updated_at,cycle,selected_candidate_id,execution_action,baseline_json,incumbent_lane,incumbent_score,summary_json,engine_version) VALUES('CURRENT',?,?,?,?,?,?,?,?,?)")
    .bind(now,cycle,selectedLive?.id||null,action,selectedLive?JSON.stringify(snapshot):null,incumbentState.lane,incumbentState.score,JSON.stringify(summary),VERSION).run();
  await env.DB.prepare("INSERT INTO lumen_growth_foundry_history(id,created_at,trigger,cycle,selected_candidate_id,execution_action,evaluation_json,summary_json,engine_version) VALUES(?,?,?,?,?,?,?,?,?)")
    .bind(`GFH-${Date.now()}-${crypto.randomUUID().slice(0,8).toUpperCase()}`,now,trigger,cycle,selectedLive?.id||null,action,JSON.stringify(evaluation),JSON.stringify(summary),VERSION).run();
  await trim(env);

  return {
    ok:true,
    version:VERSION,
    cycle,
    directive,
    incumbent:incumbentState,
    blueprintsGenerated:blueprints.length,
    topCandidates:ranked.slice(0,6).map(x=>({ id:x.id,name:x.name,status:x.status,score:num(x.score),primitives:x.primitives,trials:num(x.trials),positiveTrials:num(x.positive_trials),stalls:num(x.stalls),sourceReason:x.source_reason })),
    evaluation,
    guardrails:guardrails()
  };
}

async function status(env) {
  await ensureSchema(env);
  const row = await first(env, "SELECT * FROM lumen_growth_foundry_state WHERE id='CURRENT' LIMIT 1");
  if (!row) return { ok:true, version:VERSION, initialized:false, guardrails:guardrails() };
  const selected = row.selected_candidate_id ? await loadCandidate(env, row.selected_candidate_id) : null;
  return {
    ok:true,
    version:VERSION,
    initialized:true,
    updatedAt:row.updated_at,
    cycle:num(row.cycle),
    executionAction:row.execution_action,
    incumbent:{ lane:row.incumbent_lane, score:num(row.incumbent_score) },
    selected:selected ? { id:selected.id,name:selected.name,status:selected.status,score:num(selected.score),primitives:parse(selected.primitives_json,[]),trials:num(selected.trials),positiveTrials:num(selected.positive_trials),stalls:num(selected.stalls),verifiedRevenueDeltaUsd:num(selected.verified_revenue_delta_usd) } : null,
    summary:parse(row.summary_json,{}),
    guardrails:guardrails()
  };
}

async function candidates(env) {
  await ensureSchema(env);
  const rows = await all(env, "SELECT id,name,source_key,source_reason,gap_capability,primitives_json,source_strength,status,score,incumbent_score,trials,positive_trials,stalls,cumulative_delta,verified_revenue_delta_usd,promoted_at,rejected_at,updated_at FROM lumen_growth_foundry_candidates ORDER BY CASE status WHEN 'PROMOTED' THEN 0 WHEN 'TRIAL' THEN 1 WHEN 'DISCOVERED' THEN 2 ELSE 3 END,score DESC,updated_at DESC LIMIT 60");
  return rows.map(row => ({ ...row, primitives:parse(row.primitives_json,[]) }));
}

async function history(env, limit = 12) {
  await ensureSchema(env);
  const n = Math.max(1, Math.min(30, Number(limit) || 12));
  const rows = await all(env, `SELECT id,created_at,trigger,cycle,selected_candidate_id,execution_action,evaluation_json,summary_json,engine_version FROM lumen_growth_foundry_history ORDER BY created_at DESC LIMIT ${n}`);
  return rows.map(row => ({ ...row, evaluation:parse(row.evaluation_json,{}), summary:parse(row.summary_json,{}) }));
}

export async function handleGrowthEngineFoundry(request, env) {
  const url = new URL(request.url);
  if (request.method === "OPTIONS" && url.pathname.startsWith("/growth-foundry/")) {
    return new Response(null, { status:204, headers:{ "access-control-allow-origin":"*", "access-control-allow-headers":"content-type,x-lumen-admin", "access-control-allow-methods":"GET,POST,OPTIONS" } });
  }
  if (request.method === "GET" && url.pathname === "/growth-foundry/policy") {
    return json({
      ok:true,
      version:VERSION,
      name:"LUMEN Growth Engine Foundry",
      objective:"detect capability and market gaps, synthesize new declarative growth-motor candidates, test them against observed outcomes, compare them with the incumbent growth lanes and promote only candidates that earn evidence",
      synthesis:"bounded_composition_of_static_safe_primitives",
      allowedPrimitives:ALLOWED_PRIMITIVES,
      lifecycle:["DISCOVERED","TRIAL","PROMOTED","REJECTED"],
      comparison:"candidate_score_vs_current_growth_multiplier_incumbent",
      incorporation:"only_PROMOTED_candidates_receive_recurring_foundry_execution",
      guardrails:guardrails()
    });
  }
  if (request.method === "GET" && url.pathname === "/growth-foundry/status") return json(await status(env));
  if (request.method === "GET" && url.pathname === "/growth-foundry/candidates") {
    if (!authorized(request, env)) return json({ ok:false, error:"admin_token_required", version:VERSION }, 403);
    return json({ ok:true, version:VERSION, candidates:await candidates(env), guardrails:guardrails() });
  }
  if (request.method === "GET" && url.pathname === "/growth-foundry/history") {
    if (!authorized(request, env)) return json({ ok:false, error:"admin_token_required", version:VERSION }, 403);
    return json({ ok:true, version:VERSION, history:await history(env, url.searchParams.get("limit")) });
  }
  if (request.method === "POST" && url.pathname === "/growth-foundry/run") {
    if (!authorized(request, env)) return json({ ok:false, error:"admin_token_required", version:VERSION }, 403);
    return json(await runGrowthEngineFoundryCycle(env, { trigger:"autonomous_operator_or_admin" }), 202);
  }
  return null;
}
