import { recomputeCapabilityGaps } from "./capability-gap-engine.js";
import {
  deriveGrowthMotorBlueprints,
  proofForCandidate,
  scoreFoundryCandidate,
  decideCandidateLifecycle
} from "./growth-engine-foundry.js";

const VERSION = "2.0-growth-engine-foundry-experiment-optimizer";
const BASE_ENGINE_VERSION = "1.0-growth-engine-foundry";
const EXPERIMENT_CYCLES = 4;
const EXHAUSTION_COOLDOWN_HOURS = 12;
const MAX_HISTORY = 160;
const MAX_CANDIDATES = 60;
const ALLOWED_PRIMITIVES = new Set([
  "B2B_DISCOVERY",
  "B2B_CONVERSION",
  "PARTNER_NETWORK",
  "VENTURE_INTAKE",
  "REFERRAL_MONETIZATION",
  "TRAVEL_ACQUISITION"
]);

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
function isoPlusHours(hours) {
  return new Date(Date.now() + Math.max(0, num(hours)) * 3600000).toISOString();
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
    const result = bind.length ? await q.bind(...bind).all() : await q.all();
    return result.results || [];
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
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_growth_foundry_v2_state (id TEXT PRIMARY KEY,updated_at TEXT NOT NULL,cycle INTEGER NOT NULL,selected_candidate_id TEXT,experiment_id TEXT,experiment_arm TEXT,execution_action TEXT NOT NULL,baseline_json TEXT,attention_json TEXT NOT NULL,summary_json TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_growth_foundry_experiments (id TEXT PRIMARY KEY,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,status TEXT NOT NULL,champion_id TEXT NOT NULL,challenger_id TEXT NOT NULL,planned_cycles INTEGER NOT NULL,cycles_observed INTEGER NOT NULL DEFAULT 0,champion_runs INTEGER NOT NULL DEFAULT 0,challenger_runs INTEGER NOT NULL DEFAULT 0,champion_proof_gain REAL NOT NULL DEFAULT 0,challenger_proof_gain REAL NOT NULL DEFAULT 0,champion_conversion_gain REAL NOT NULL DEFAULT 0,challenger_conversion_gain REAL NOT NULL DEFAULT 0,champion_revenue_gain_usd REAL NOT NULL DEFAULT 0,challenger_revenue_gain_usd REAL NOT NULL DEFAULT 0,winner_id TEXT,loser_id TEXT,confidence REAL NOT NULL DEFAULT 0,reason TEXT,completed_at TEXT,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_growth_foundry_experiments_status ON lumen_growth_foundry_experiments(status,updated_at DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_growth_foundry_health (candidate_id TEXT PRIMARY KEY,updated_at TEXT NOT NULL,peak_score REAL NOT NULL DEFAULT 0,last_score REAL NOT NULL DEFAULT 0,consecutive_no_progress INTEGER NOT NULL DEFAULT 0,exhaustion_score REAL NOT NULL DEFAULT 0,exhausted INTEGER NOT NULL DEFAULT 0,exhausted_at TEXT,cooldown_until TEXT,last_progress_at TEXT,last_evidence_json TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_growth_foundry_health_exhausted ON lumen_growth_foundry_health(exhausted,cooldown_until,updated_at DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_growth_foundry_v2_history (id TEXT PRIMARY KEY,created_at TEXT NOT NULL,trigger TEXT NOT NULL,cycle INTEGER NOT NULL,selected_candidate_id TEXT,experiment_id TEXT,experiment_arm TEXT,execution_action TEXT NOT NULL,evaluation_json TEXT NOT NULL,attention_json TEXT NOT NULL,summary_json TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_growth_foundry_v2_history_created ON lumen_growth_foundry_v2_history(created_at DESC)")
  ]);
  return true;
}

async function topCapabilityGap(env) {
  return first(env, "SELECT capability,priority,status,reason,current_candidates,strong_candidates,observed_confident_candidates FROM lumen_capability_gap_queue WHERE status<>'COVERED' ORDER BY priority DESC,updated_at DESC LIMIT 1");
}

async function signalSnapshot(env) {
  const [
    b2bRevenue, b2bSettlements, negotiating, quotes7d, inbound7d, activeCandidates,
    partnerAgents, partnerMatches, partnerCouncils,
    ventureHighPotential, ventureReview, ventureIngestedPass,
    referralRevenue, referralSettlements, referralPaymentDue, referralAgreed, referralProposalReady,
    travelRevenue, travelRewards, travelConfirmations, travelClicks, travelRecommended
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
  return {
    capturedAt:new Date().toISOString(),
    topGap:await topCapabilityGap(env),
    B2B:{ verifiedRevenueUsd30d:b2bRevenue, verifiedSettlements30d:b2bSettlements, negotiating, quotes7d, inbound7d, activeCandidates },
    PARTNER:{ partnerAgents, matches:partnerMatches, councils:partnerCouncils },
    VENTURE:{ highPotential:ventureHighPotential, review:ventureReview, ingestedPass:ventureIngestedPass },
    REFERRAL:{ verifiedRevenueUsd30d:referralRevenue, verifiedSettlements30d:referralSettlements, paymentDue:referralPaymentDue, agreedPendingClose:referralAgreed, proposalReady:referralProposalReady },
    TRAVEL:{ verifiedRevenueUsd30d:travelRevenue, verifiedRewards30d:travelRewards, confirmations30d:travelConfirmations, clicks7d:travelClicks, recommendedCampaigns:travelRecommended }
  };
}

function primitives(candidate = {}) {
  const list = Array.isArray(candidate.primitives) ? candidate.primitives : parse(candidate.primitives_json, []);
  return [...new Set(list)].filter(x => ALLOWED_PRIMITIVES.has(x)).slice(0, 3);
}

function verifiedRevenueForCandidate(candidate, snapshot = {}) {
  const p = primitives(candidate);
  let value = 0;
  if (p.includes("B2B_DISCOVERY") || p.includes("B2B_CONVERSION")) value += num(snapshot.B2B?.verifiedRevenueUsd30d);
  if (p.includes("REFERRAL_MONETIZATION")) value += num(snapshot.REFERRAL?.verifiedRevenueUsd30d);
  if (p.includes("TRAVEL_ACQUISITION")) value += num(snapshot.TRAVEL?.verifiedRevenueUsd30d);
  return Number(value.toFixed(2));
}

export function conversionSignalForCandidate(candidate = {}, snapshot = {}) {
  const p = primitives(candidate);
  const parts = [];
  const b = snapshot.B2B || {};
  const n = snapshot.PARTNER || {};
  const v = snapshot.VENTURE || {};
  const r = snapshot.REFERRAL || {};
  const t = snapshot.TRAVEL || {};

  if (p.includes("B2B_DISCOVERY") || p.includes("B2B_CONVERSION")) {
    const denominator = Math.max(1, num(b.activeCandidates) + num(b.inbound7d));
    parts.push(clamp((num(b.quotes7d) * 8 + num(b.negotiating) * 18 + num(b.verifiedSettlements30d) * 55) / denominator, 0, 100));
  }
  if (p.includes("PARTNER_NETWORK")) {
    parts.push(clamp((num(n.matches) * 12 + num(n.councils) * 20) / Math.max(1, num(n.partnerAgents)), 0, 100));
  }
  if (p.includes("VENTURE_INTAKE")) {
    parts.push(clamp((num(v.highPotential) * 28 + num(v.ingestedPass) * 10) / Math.max(1, num(v.highPotential) + num(v.review) + num(v.ingestedPass)), 0, 100));
  }
  if (p.includes("REFERRAL_MONETIZATION")) {
    const funnel = num(r.proposalReady) + num(r.agreedPendingClose) + num(r.paymentDue) + num(r.verifiedSettlements30d);
    parts.push(clamp((num(r.agreedPendingClose) * 12 + num(r.paymentDue) * 24 + num(r.verifiedSettlements30d) * 60) / Math.max(1, funnel), 0, 100));
  }
  if (p.includes("TRAVEL_ACQUISITION")) {
    parts.push(clamp((num(t.confirmations30d) * 70 + num(t.verifiedRewards30d) * 25 + Math.min(20, num(t.clicks7d) * .5)) / Math.max(1, Math.sqrt(num(t.clicks7d) + 1)), 0, 100));
  }
  if (!parts.length) return 0;
  return Number((parts.reduce((a,bv)=>a+bv,0) / parts.length).toFixed(2));
}

export function computeExhaustion(input = {}) {
  const trials = Math.max(0, num(input.trials));
  const positive = Math.max(0, num(input.positiveTrials));
  const noProgress = Math.max(0, num(input.consecutiveNoProgress));
  const lastScore = clamp(input.lastScore, 0, 100);
  const peakScore = Math.max(lastScore, clamp(input.peakScore, 0, 100));
  const verifiedRevenueDeltaUsd = Math.max(0, num(input.verifiedRevenueDeltaUsd));
  const cumulativeDelta = num(input.cumulativeDelta);
  const successRate = trials > 0 ? positive / trials : 0;
  const scoreDrop = Math.max(0, peakScore - lastScore);
  let exhaustionScore = noProgress * 19 + Math.max(0, trials - 3) * 5 + scoreDrop * 1.25;
  if (trials >= 5 && successRate < .25) exhaustionScore += 20;
  if (cumulativeDelta <= 0 && trials >= 4) exhaustionScore += 12;
  if (verifiedRevenueDeltaUsd > 0) exhaustionScore -= 45;
  if (positive > 0 && noProgress === 0) exhaustionScore -= 12;
  exhaustionScore = Number(clamp(exhaustionScore, 0, 100).toFixed(2));
  return {
    exhausted: exhaustionScore >= 70 && verifiedRevenueDeltaUsd <= 0,
    exhaustionScore,
    successRate:Number(successRate.toFixed(3)),
    scoreDrop:Number(scoreDrop.toFixed(2)),
    reason: exhaustionScore >= 70 && verifiedRevenueDeltaUsd <= 0 ? "repeated_stall_or_declining_evidence" : "still_has_learning_or_progress_capacity"
  };
}

export function experimentValue(arm = {}) {
  const runs = Math.max(1, num(arm.runs));
  const proofPerRun = num(arm.proofGain) / runs;
  const conversionPerRun = num(arm.conversionGain) / runs;
  const revenuePerRun = num(arm.revenueGainUsd) / runs;
  return Number((revenuePerRun * 55 + proofPerRun * 4 + conversionPerRun * 3).toFixed(3));
}

export function decideExperimentWinner(input = {}) {
  const champion = input.champion || {};
  const challenger = input.challenger || {};
  const championExhausted = Boolean(input.championExhausted);
  const challengerExhausted = Boolean(input.challengerExhausted);
  if (championExhausted && !challengerExhausted) return { winner:"CHALLENGER", confidence:1, reason:"champion_exhausted" };
  if (challengerExhausted && !championExhausted) return { winner:"CHAMPION", confidence:1, reason:"challenger_exhausted" };
  const championValue = experimentValue(champion);
  const challengerValue = experimentValue(challenger);
  const margin = challengerValue - championValue;
  const revenueMargin = num(challenger.revenueGainUsd) - num(champion.revenueGainUsd);
  if (Math.abs(revenueMargin) > .01) {
    return {
      winner:revenueMargin > 0 ? "CHALLENGER" : "CHAMPION",
      confidence:Number(clamp(0.7 + Math.min(.25, Math.abs(revenueMargin) / 20), 0, 1).toFixed(3)),
      reason:"verified_revenue_breaks_tie",
      championValue,
      challengerValue,
      margin:Number(margin.toFixed(3))
    };
  }
  if (Math.abs(margin) < 2) {
    return { winner:"INCONCLUSIVE", confidence:Number(clamp(Math.abs(margin) / 2, 0, .49).toFixed(3)), reason:"difference_below_directional_threshold", championValue, challengerValue, margin:Number(margin.toFixed(3)) };
  }
  return {
    winner:margin > 0 ? "CHALLENGER" : "CHAMPION",
    confidence:Number(clamp(.55 + Math.min(.35, Math.abs(margin) / 40), 0, .9).toFixed(3)),
    reason:"directional_proof_and_conversion_advantage",
    championValue,
    challengerValue,
    margin:Number(margin.toFixed(3))
  };
}

export function chooseExperimentArm(experiment = {}, health = {}) {
  const championExhausted = Boolean(health.championExhausted);
  const challengerExhausted = Boolean(health.challengerExhausted);
  if (championExhausted && !challengerExhausted) return "CHALLENGER";
  if (challengerExhausted && !championExhausted) return "CHAMPION";
  return num(experiment.cycles_observed ?? experiment.cyclesObserved) % 2 === 0 ? "CHAMPION" : "CHALLENGER";
}

async function upsertBlueprints(env, blueprints) {
  const now = new Date().toISOString();
  for (const b of blueprints) {
    await env.DB.prepare("INSERT INTO lumen_growth_foundry_candidates(id,fingerprint,created_at,updated_at,name,source_key,source_reason,gap_capability,primitives_json,source_strength,status,score,incumbent_score,trials,positive_trials,stalls,cumulative_delta,verified_revenue_delta_usd,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,'DISCOVERED',0,0,0,0,0,0,0,?) ON CONFLICT(fingerprint) DO UPDATE SET updated_at=excluded.updated_at,name=excluded.name,source_reason=excluded.source_reason,gap_capability=excluded.gap_capability,primitives_json=excluded.primitives_json,source_strength=MAX(lumen_growth_foundry_candidates.source_strength,excluded.source_strength),engine_version=excluded.engine_version")
      .bind(b.id,b.fingerprint,now,now,b.name,b.sourceKey,b.sourceReason,b.gapCapability||null,JSON.stringify(b.primitives),b.sourceStrength,VERSION).run();
  }
}

async function incumbent(env) {
  const row = await first(env, "SELECT primary_lane,scores_json FROM lumen_growth_multiplier_state WHERE id='CURRENT' LIMIT 1");
  const scores = parse(row?.scores_json, []);
  const ranked = Array.isArray(scores) ? scores.slice().sort((a,b)=>num(b.score)-num(a.score)) : [];
  const best = ranked[0] || null;
  return { lane:clean(best?.lane || row?.primary_lane || "UNKNOWN",80), score:clamp(best?.score,0,100) };
}

async function candidateById(env, id) {
  return id ? first(env, "SELECT * FROM lumen_growth_foundry_candidates WHERE id=? LIMIT 1", [id]) : null;
}

async function healthById(env, id) {
  return id ? first(env, "SELECT * FROM lumen_growth_foundry_health WHERE candidate_id=? LIMIT 1", [id]) : null;
}

async function updateHealth(env, candidate, evidence) {
  const old = await healthById(env, candidate.id);
  const peakScore = Math.max(num(old?.peak_score), num(evidence.score));
  const consecutiveNoProgress = evidence.positive ? 0 : num(old?.consecutive_no_progress) + 1;
  const exhaustion = computeExhaustion({
    trials:candidate.trials,
    positiveTrials:evidence.positiveTrials,
    consecutiveNoProgress,
    lastScore:evidence.score,
    peakScore,
    verifiedRevenueDeltaUsd:evidence.verifiedRevenueTotal,
    cumulativeDelta:evidence.cumulativeDelta
  });
  const now = new Date().toISOString();
  const cooldownUntil = exhaustion.exhausted ? isoPlusHours(EXHAUSTION_COOLDOWN_HOURS) : null;
  const lastProgressAt = evidence.positive ? now : old?.last_progress_at || null;
  await env.DB.prepare("INSERT INTO lumen_growth_foundry_health(candidate_id,updated_at,peak_score,last_score,consecutive_no_progress,exhaustion_score,exhausted,exhausted_at,cooldown_until,last_progress_at,last_evidence_json,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(candidate_id) DO UPDATE SET updated_at=excluded.updated_at,peak_score=excluded.peak_score,last_score=excluded.last_score,consecutive_no_progress=excluded.consecutive_no_progress,exhaustion_score=excluded.exhaustion_score,exhausted=excluded.exhausted,exhausted_at=CASE WHEN excluded.exhausted=1 THEN COALESCE(lumen_growth_foundry_health.exhausted_at,excluded.exhausted_at) ELSE NULL END,cooldown_until=excluded.cooldown_until,last_progress_at=excluded.last_progress_at,last_evidence_json=excluded.last_evidence_json,engine_version=excluded.engine_version")
    .bind(candidate.id,now,peakScore,evidence.score,consecutiveNoProgress,exhaustion.exhaustionScore,exhaustion.exhausted?1:0,exhaustion.exhausted?now:null,cooldownUntil,lastProgressAt,JSON.stringify({...evidence,exhaustion}),VERSION).run();
  return { ...exhaustion, peakScore, consecutiveNoProgress, cooldownUntil, lastProgressAt };
}

async function updateExperimentEvidence(env, experimentId, arm, evidence) {
  if (!experimentId || !arm || !["CHAMPION","CHALLENGER"].includes(arm)) return null;
  const fieldPrefix = arm === "CHAMPION" ? "champion" : "challenger";
  const now = new Date().toISOString();
  await env.DB.prepare(`UPDATE lumen_growth_foundry_experiments SET updated_at=?,cycles_observed=cycles_observed+1,${fieldPrefix}_runs=${fieldPrefix}_runs+1,${fieldPrefix}_proof_gain=${fieldPrefix}_proof_gain+?,${fieldPrefix}_conversion_gain=${fieldPrefix}_conversion_gain+?,${fieldPrefix}_revenue_gain_usd=${fieldPrefix}_revenue_gain_usd+? WHERE id=? AND status='ACTIVE'`)
    .bind(now,evidence.proofDelta,evidence.conversionDelta,evidence.verifiedRevenueDeltaUsd,experimentId).run();
  return first(env, "SELECT * FROM lumen_growth_foundry_experiments WHERE id=? LIMIT 1", [experimentId]);
}

async function evaluatePrevious(env, state, snapshot, incumbentState) {
  if (!state?.selected_candidate_id || !state?.baseline_json) return { evaluated:false, reason:"no_previous_v2_probe" };
  const candidate = await candidateById(env, state.selected_candidate_id);
  if (!candidate || candidate.status === "REJECTED") return { evaluated:false, reason:"candidate_not_evaluable" };
  const before = parse(state.baseline_json, {});
  const beforeProof = proofForCandidate(candidate, before);
  const afterProof = proofForCandidate(candidate, snapshot);
  const proofDelta = Number((afterProof - beforeProof).toFixed(2));
  const beforeConversion = conversionSignalForCandidate(candidate, before);
  const afterConversion = conversionSignalForCandidate(candidate, snapshot);
  const conversionDelta = Number((afterConversion - beforeConversion).toFixed(2));
  const beforeRevenue = verifiedRevenueForCandidate(candidate, before);
  const afterRevenue = verifiedRevenueForCandidate(candidate, snapshot);
  const verifiedRevenueDeltaUsd = Number(Math.max(0, afterRevenue - beforeRevenue).toFixed(2));
  const positive = verifiedRevenueDeltaUsd > 0 || proofDelta >= 1 || conversionDelta >= .5;
  const positiveTrials = num(candidate.positive_trials) + (positive ? 1 : 0);
  const stalls = positive ? 0 : num(candidate.stalls) + 1;
  const cumulativeDelta = Number((num(candidate.cumulative_delta) + proofDelta).toFixed(2));
  const verifiedRevenueTotal = Number((num(candidate.verified_revenue_delta_usd) + verifiedRevenueDeltaUsd).toFixed(2));
  const score = scoreFoundryCandidate({ ...candidate, positive_trials:positiveTrials, stalls, cumulative_delta:cumulativeDelta, verified_revenue_delta_usd:verifiedRevenueTotal }, incumbentState.score);
  const lifecycle = decideCandidateLifecycle({ ...candidate, score, positive_trials:positiveTrials, stalls, cumulative_delta:cumulativeDelta, verified_revenue_delta_usd:verifiedRevenueTotal }, incumbentState.score);
  const now = new Date().toISOString();
  await env.DB.prepare("UPDATE lumen_growth_foundry_candidates SET updated_at=?,status=?,score=?,incumbent_score=?,positive_trials=?,stalls=?,cumulative_delta=?,verified_revenue_delta_usd=?,last_observation_json=?,promoted_at=CASE WHEN ?='PROMOTED' AND promoted_at IS NULL THEN ? ELSE promoted_at END,rejected_at=CASE WHEN ?='REJECTED' AND rejected_at IS NULL THEN ? ELSE rejected_at END,engine_version=? WHERE id=?")
    .bind(now,lifecycle.status,score,incumbentState.score,positiveTrials,stalls,cumulativeDelta,verifiedRevenueTotal,JSON.stringify({beforeProof,afterProof,proofDelta,beforeConversion,afterConversion,conversionDelta,beforeRevenue,afterRevenue,verifiedRevenueDeltaUsd,positive,attribution:"directional_observational_not_causal"}),lifecycle.status,now,lifecycle.status,now,VERSION,candidate.id).run();
  const health = await updateHealth(env, {...candidate, trials:num(candidate.trials)}, { score, positive, positiveTrials, cumulativeDelta, verifiedRevenueTotal, proofDelta, conversionDelta, verifiedRevenueDeltaUsd });
  const experiment = await updateExperimentEvidence(env,state.experiment_id,state.experiment_arm,{proofDelta,conversionDelta,verifiedRevenueDeltaUsd});
  return {
    evaluated:true,
    candidateId:candidate.id,
    candidateName:candidate.name,
    proof:{before:beforeProof,after:afterProof,delta:proofDelta},
    conversion:{before:beforeConversion,after:afterConversion,delta:conversionDelta},
    verifiedRevenueDeltaUsd,
    positive,
    score,
    lifecycle,
    health,
    experimentId:state.experiment_id || null,
    experimentArm:state.experiment_arm || null,
    experimentCyclesObserved:num(experiment?.cycles_observed),
    attribution:"directional_observational_not_causal"
  };
}

async function releaseExpiredHealth(env) {
  await env.DB.prepare("UPDATE lumen_growth_foundry_health SET exhausted=0,exhausted_at=NULL,cooldown_until=NULL,consecutive_no_progress=MAX(0,consecutive_no_progress-1),updated_at=?,engine_version=? WHERE exhausted=1 AND cooldown_until IS NOT NULL AND datetime(cooldown_until)<=datetime('now')")
    .bind(new Date().toISOString(),VERSION).run();
}

async function rankCandidates(env, incumbentState) {
  await releaseExpiredHealth(env);
  const rows = await all(env, "SELECT c.*,h.exhausted,h.cooldown_until,h.exhaustion_score,h.peak_score,h.consecutive_no_progress FROM lumen_growth_foundry_candidates c LEFT JOIN lumen_growth_foundry_health h ON h.candidate_id=c.id WHERE c.status<>'REJECTED' ORDER BY c.updated_at DESC LIMIT 120");
  const eligible = [];
  for (const row of rows) {
    const score = scoreFoundryCandidate(row, incumbentState.score);
    const cooling = Number(row.exhausted || 0) === 1 && row.cooldown_until && Date.parse(row.cooldown_until) > Date.now();
    const exhaustionPenalty = cooling ? 100 : num(row.exhaustion_score) * .18;
    const adjustedScore = Number(clamp(score - exhaustionPenalty, 0, 100).toFixed(2));
    await env.DB.prepare("UPDATE lumen_growth_foundry_candidates SET score=?,incumbent_score=?,engine_version=? WHERE id=?")
      .bind(score,incumbentState.score,VERSION,row.id).run();
    eligible.push({ ...row, primitives:primitives(row), score, adjustedScore, cooling, exhausted:Boolean(cooling) });
  }
  return eligible.sort((a,b)=>b.adjustedScore-a.adjustedScore || num(b.positive_trials)-num(a.positive_trials) || a.created_at.localeCompare(b.created_at));
}

async function activeExperiment(env) {
  return first(env, "SELECT * FROM lumen_growth_foundry_experiments WHERE status='ACTIVE' ORDER BY created_at ASC LIMIT 1");
}
async function latestCompletedExperiment(env) {
  return first(env, "SELECT * FROM lumen_growth_foundry_experiments WHERE status='COMPLETED' AND winner_id IS NOT NULL ORDER BY completed_at DESC LIMIT 1");
}

async function finishExperimentIfReady(env, experiment) {
  if (!experiment || experiment.status !== "ACTIVE" || num(experiment.cycles_observed) < num(experiment.planned_cycles)) return experiment;
  const championHealth = await healthById(env,experiment.champion_id);
  const challengerHealth = await healthById(env,experiment.challenger_id);
  const result = decideExperimentWinner({
    champion:{ runs:experiment.champion_runs, proofGain:experiment.champion_proof_gain, conversionGain:experiment.champion_conversion_gain, revenueGainUsd:experiment.champion_revenue_gain_usd },
    challenger:{ runs:experiment.challenger_runs, proofGain:experiment.challenger_proof_gain, conversionGain:experiment.challenger_conversion_gain, revenueGainUsd:experiment.challenger_revenue_gain_usd },
    championExhausted:Number(championHealth?.exhausted || 0) === 1,
    challengerExhausted:Number(challengerHealth?.exhausted || 0) === 1
  });
  const winnerId = result.winner === "CHAMPION" ? experiment.champion_id : result.winner === "CHALLENGER" ? experiment.challenger_id : null;
  const loserId = result.winner === "CHAMPION" ? experiment.challenger_id : result.winner === "CHALLENGER" ? experiment.champion_id : null;
  const now = new Date().toISOString();
  await env.DB.prepare("UPDATE lumen_growth_foundry_experiments SET updated_at=?,status='COMPLETED',winner_id=?,loser_id=?,confidence=?,reason=?,completed_at=?,engine_version=? WHERE id=?")
    .bind(now,winnerId,loserId,num(result.confidence),clean(result.reason,300),now,VERSION,experiment.id).run();
  return { ...experiment, status:"COMPLETED", winner_id:winnerId, loser_id:loserId, confidence:num(result.confidence), reason:result.reason, completed_at:now, result };
}

async function startExperiment(env, ranked, latestWinnerId = null) {
  const usable = ranked.filter(x=>!x.cooling && x.adjustedScore >= 35).slice(0,8);
  if (usable.length < 2) return null;
  const champion = (latestWinnerId && usable.find(x=>x.id===latestWinnerId)) || usable.find(x=>x.status==="PROMOTED") || usable[0];
  const challenger = usable.find(x=>x.id!==champion.id && (x.source_key!==champion.source_key || x.primitives.join("+")!==champion.primitives.join("+"))) || usable.find(x=>x.id!==champion.id);
  if (!champion || !challenger) return null;
  const now = new Date().toISOString();
  const id = `GFX-${Date.now()}-${crypto.randomUUID().slice(0,8).toUpperCase()}`;
  await env.DB.prepare("INSERT INTO lumen_growth_foundry_experiments(id,created_at,updated_at,status,champion_id,challenger_id,planned_cycles,engine_version) VALUES(?,?,?,'ACTIVE',?,?,?,?)")
    .bind(id,now,now,champion.id,challenger.id,EXPERIMENT_CYCLES,VERSION).run();
  return first(env,"SELECT * FROM lumen_growth_foundry_experiments WHERE id=? LIMIT 1",[id]);
}

function attentionForExperiment(experiment, selectedId, health = {}) {
  if (!experiment) return { mode:"SINGLE_MOTOR", selectedCandidateId:selectedId || null, allocations:selectedId ? [{candidateId:selectedId,share:1}] : [], rationale:"no_comparable_challenger_available" };
  if (experiment.status === "ACTIVE") {
    if (health.championExhausted && !health.challengerExhausted) return { mode:"EXHAUSTION_REALLOCATION", selectedCandidateId:experiment.challenger_id, allocations:[{candidateId:experiment.challenger_id,share:1}], rationale:"champion_exhausted_reallocate_all_bounded_attention" };
    if (health.challengerExhausted && !health.championExhausted) return { mode:"EXHAUSTION_REALLOCATION", selectedCandidateId:experiment.champion_id, allocations:[{candidateId:experiment.champion_id,share:1}], rationale:"challenger_exhausted_reallocate_all_bounded_attention" };
    return { mode:"CONTROLLED_ALTERNATION", selectedCandidateId:selectedId || null, allocations:[{candidateId:experiment.champion_id,share:.5},{candidateId:experiment.challenger_id,share:.5}], rationale:"deterministic_A_B_A_B_over_four_hourly_cycles_not_simultaneous_traffic_split" };
  }
  if (experiment.winner_id) {
    const loserExhausted = experiment.loser_id && ((experiment.loser_id===experiment.champion_id && health.championExhausted) || (experiment.loser_id===experiment.challenger_id && health.challengerExhausted));
    return loserExhausted
      ? { mode:"WINNER_TAKE_ALL_BOUNDED", selectedCandidateId:experiment.winner_id, allocations:[{candidateId:experiment.winner_id,share:1}], rationale:"winner_has_directional_evidence_and_loser_is_exhausted" }
      : { mode:"WINNER_WITH_EXPLORATION", selectedCandidateId:experiment.winner_id, allocations:[{candidateId:experiment.winner_id,share:.8},{candidateId:experiment.loser_id,share:.2}], rationale:"winner_receives_majority_attention_while_preserving_small_challenger_exploration" };
  }
  return { mode:"INCONCLUSIVE", selectedCandidateId:selectedId || null, allocations:selectedId ? [{candidateId:selectedId,share:1}] : [], rationale:"experiment_did_not_clear_directional_threshold" };
}

async function selectMotor(env, ranked, experiment) {
  if (experiment?.status === "ACTIVE") {
    const championHealth = await healthById(env,experiment.champion_id);
    const challengerHealth = await healthById(env,experiment.challenger_id);
    const health = {
      championExhausted:Number(championHealth?.exhausted || 0) === 1 && (!championHealth.cooldown_until || Date.parse(championHealth.cooldown_until)>Date.now()),
      challengerExhausted:Number(challengerHealth?.exhausted || 0) === 1 && (!challengerHealth.cooldown_until || Date.parse(challengerHealth.cooldown_until)>Date.now())
    };
    const arm = chooseExperimentArm(experiment,health);
    const candidateId = arm === "CHAMPION" ? experiment.champion_id : experiment.challenger_id;
    const candidate = ranked.find(x=>x.id===candidateId) || await candidateById(env,candidateId);
    return { candidate, experiment, arm, health, attention:attentionForExperiment(experiment,candidateId,health) };
  }
  const latest = experiment?.status === "COMPLETED" ? experiment : await latestCompletedExperiment(env);
  if (latest?.winner_id) {
    const candidate = ranked.find(x=>x.id===latest.winner_id && !x.cooling);
    if (candidate) {
      const championHealth = await healthById(env,latest.champion_id);
      const challengerHealth = await healthById(env,latest.challenger_id);
      const health = { championExhausted:Number(championHealth?.exhausted||0)===1, challengerExhausted:Number(challengerHealth?.exhausted||0)===1 };
      return { candidate, experiment:latest, arm:"WINNER", health, attention:attentionForExperiment(latest,candidate.id,health) };
    }
  }
  const candidate = ranked.find(x=>!x.cooling && x.adjustedScore>=35) || null;
  return { candidate, experiment:latest || null, arm:null, health:{}, attention:attentionForExperiment(null,candidate?.id||null,{}) };
}

async function markSelected(env, candidate, incumbentState) {
  if (!candidate) return null;
  const now = new Date().toISOString();
  const status = candidate.status === "PROMOTED" ? "PROMOTED" : "TRIAL";
  await env.DB.prepare("UPDATE lumen_growth_foundry_candidates SET updated_at=?,status=?,trials=trials+1,incumbent_score=?,engine_version=? WHERE id=?")
    .bind(now,status,incumbentState.score,VERSION,candidate.id).run();
  return { ...candidate, status, trials:num(candidate.trials)+1, primitives:primitives(candidate) };
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
    maxConcurrentExperiments:1,
    plannedExperimentCycles:EXPERIMENT_CYCLES,
    oneFoundryMotorExecutionPerCycle:true,
    primitiveExecutionRequiresStaticWhitelist:true,
    deterministicAlternatingExperimentArms:true,
    conversionSignalIsDirectionalNotCausal:true,
    exhaustionCanOnlyReallocateAmongExistingSafeCandidates:true,
    bindingActionsHumanGated:true,
    verifiedRevenueOnly:true,
    learningAttribution:"directional_observational_not_causal"
  };
}

async function trim(env) {
  try {
    await env.DB.prepare(`DELETE FROM lumen_growth_foundry_v2_history WHERE id NOT IN (SELECT id FROM lumen_growth_foundry_v2_history ORDER BY created_at DESC LIMIT ${MAX_HISTORY})`).run();
    await env.DB.prepare(`DELETE FROM lumen_growth_foundry_candidates WHERE id IN (SELECT id FROM lumen_growth_foundry_candidates WHERE status='REJECTED' ORDER BY updated_at DESC LIMIT -1 OFFSET ${MAX_CANDIDATES})`).run();
  } catch {}
}

export async function runGrowthEngineFoundryV2Cycle(env, options = {}) {
  if (!(await ensureSchema(env))) return { ok:false, error:"persistence_unavailable", version:VERSION };
  const gapRefresh = await recomputeCapabilityGaps(env).catch(error=>({ok:false,error:String(error?.message||error).slice(0,220)}));
  const previousState = await first(env,"SELECT * FROM lumen_growth_foundry_v2_state WHERE id='CURRENT' LIMIT 1");
  const incumbentState = await incumbent(env);
  const snapshot = await signalSnapshot(env);
  const evaluation = await evaluatePrevious(env,previousState,snapshot,incumbentState);
  const blueprints = deriveGrowthMotorBlueprints(snapshot);
  await upsertBlueprints(env,blueprints);
  let ranked = await rankCandidates(env,incumbentState);

  let experiment = await activeExperiment(env);
  if (experiment) experiment = await finishExperimentIfReady(env,experiment);
  const latestCompleted = experiment?.status === "COMPLETED" ? experiment : await latestCompletedExperiment(env);
  if (!experiment || experiment.status !== "ACTIVE") {
    experiment = await startExperiment(env,ranked,latestCompleted?.winner_id || null);
  }

  ranked = await rankCandidates(env,incumbentState);
  const selection = await selectMotor(env,ranked,experiment || latestCompleted);
  const selected = await markSelected(env,selection.candidate,incumbentState);
  const action = selected ? (selection.experiment?.status === "ACTIVE" ? "RUN_EXPERIMENT_ARM" : selection.arm === "WINNER" ? "RUN_WINNER" : selected.status === "PROMOTED" ? "RUN_PROMOTED_MOTOR" : "PROBE_CANDIDATE") : "NONE";
  const cycle = Math.max(1,num(previousState?.cycle)+1);
  const now = new Date().toISOString();
  const attention = selection.attention || attentionForExperiment(null,selected?.id||null,{});
  const summary = {
    baseEngineVersion:BASE_ENGINE_VERSION,
    gapRefresh:{ok:gapRefresh?.ok!==false,evaluated:num(gapRefresh?.evaluated),open:num(gapRefresh?.open),weakCoverage:num(gapRefresh?.weakCoverage),covered:num(gapRefresh?.covered)},
    incumbent:incumbentState,
    blueprintsGenerated:blueprints.length,
    evaluation,
    experiment:selection.experiment ? {
      id:selection.experiment.id,
      status:selection.experiment.status,
      championId:selection.experiment.champion_id,
      challengerId:selection.experiment.challenger_id,
      cyclesObserved:num(selection.experiment.cycles_observed),
      plannedCycles:num(selection.experiment.planned_cycles),
      winnerId:selection.experiment.winner_id || null,
      loserId:selection.experiment.loser_id || null,
      confidence:num(selection.experiment.confidence),
      reason:selection.experiment.reason || null
    } : null,
    selected:selected ? {id:selected.id,name:selected.name,status:selected.status,score:num(selected.score),adjustedScore:num(selected.adjustedScore),primitives:selected.primitives,trials:num(selected.trials)} : null,
    attention,
    exhaustedCandidates:ranked.filter(x=>x.cooling).slice(0,10).map(x=>({id:x.id,name:x.name,exhaustionScore:num(x.exhaustion_score),cooldownUntil:x.cooldown_until})),
    rankedCandidates:ranked.slice(0,6).map(x=>({id:x.id,name:x.name,status:x.status,score:num(x.score),adjustedScore:num(x.adjustedScore),cooling:Boolean(x.cooling),primitives:x.primitives}))
  };

  await env.DB.prepare("INSERT OR REPLACE INTO lumen_growth_foundry_v2_state(id,updated_at,cycle,selected_candidate_id,experiment_id,experiment_arm,execution_action,baseline_json,attention_json,summary_json,engine_version) VALUES('CURRENT',?,?,?,?,?,?,?,?,?,?)")
    .bind(now,cycle,selected?.id||null,selection.experiment?.id||null,selection.arm||null,action,selected?JSON.stringify(snapshot):null,JSON.stringify(attention),JSON.stringify(summary),VERSION).run();
  await env.DB.prepare("INSERT INTO lumen_growth_foundry_v2_history(id,created_at,trigger,cycle,selected_candidate_id,experiment_id,experiment_arm,execution_action,evaluation_json,attention_json,summary_json,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)")
    .bind(`GF2-${Date.now()}-${crypto.randomUUID().slice(0,8).toUpperCase()}`,now,clean(options.trigger||"operator",100),cycle,selected?.id||null,selection.experiment?.id||null,selection.arm||null,action,JSON.stringify(evaluation),JSON.stringify(attention),JSON.stringify(summary),VERSION).run();
  await trim(env);

  return {
    ok:true,
    version:VERSION,
    cycle,
    directive:{
      action,
      candidate:selected ? {id:selected.id,name:selected.name,status:selected.status,score:num(selected.score),sourceKey:selected.source_key,sourceReason:selected.source_reason,gapCapability:selected.gap_capability||null,primitives:selected.primitives,trials:num(selected.trials),positiveTrials:num(selected.positive_trials),stalls:num(selected.stalls)} : null,
      experiment:summary.experiment,
      experimentArm:selection.arm||null,
      attention,
      generatedCode:false,
      staticPrimitiveWhitelist:true
    },
    evaluation,
    experiment:summary.experiment,
    attention,
    exhaustedCandidates:summary.exhaustedCandidates,
    topCandidates:summary.rankedCandidates,
    guardrails:guardrails()
  };
}

async function status(env) {
  await ensureSchema(env);
  const state = await first(env,"SELECT * FROM lumen_growth_foundry_v2_state WHERE id='CURRENT' LIMIT 1");
  if (!state) return {ok:true,version:VERSION,initialized:false,guardrails:guardrails()};
  const experiment = state.experiment_id ? await first(env,"SELECT * FROM lumen_growth_foundry_experiments WHERE id=? LIMIT 1",[state.experiment_id]) : await latestCompletedExperiment(env);
  const selected = state.selected_candidate_id ? await candidateById(env,state.selected_candidate_id) : null;
  const health = selected ? await healthById(env,selected.id) : null;
  return {
    ok:true,
    version:VERSION,
    initialized:true,
    updatedAt:state.updated_at,
    cycle:num(state.cycle),
    executionAction:state.execution_action,
    selected:selected ? {id:selected.id,name:selected.name,status:selected.status,score:num(selected.score),primitives:primitives(selected),trials:num(selected.trials),positiveTrials:num(selected.positive_trials),stalls:num(selected.stalls),health:health?{exhausted:Boolean(health.exhausted),exhaustionScore:num(health.exhaustion_score),cooldownUntil:health.cooldown_until,lastProgressAt:health.last_progress_at}:null}:null,
    experiment:experiment ? {id:experiment.id,status:experiment.status,championId:experiment.champion_id,challengerId:experiment.challenger_id,cyclesObserved:num(experiment.cycles_observed),plannedCycles:num(experiment.planned_cycles),winnerId:experiment.winner_id||null,loserId:experiment.loser_id||null,confidence:num(experiment.confidence),reason:experiment.reason||null,completedAt:experiment.completed_at||null}:null,
    attention:parse(state.attention_json,{}),
    summary:parse(state.summary_json,{}),
    guardrails:guardrails()
  };
}

async function experiments(env, limit=20) {
  await ensureSchema(env);
  const n=Math.max(1,Math.min(50,Number(limit)||20));
  return all(env,`SELECT * FROM lumen_growth_foundry_experiments ORDER BY created_at DESC LIMIT ${n}`);
}
async function health(env, limit=40) {
  await ensureSchema(env);
  const n=Math.max(1,Math.min(80,Number(limit)||40));
  return all(env,`SELECT h.*,c.name,c.status,c.score,c.trials,c.positive_trials,c.stalls FROM lumen_growth_foundry_health h LEFT JOIN lumen_growth_foundry_candidates c ON c.id=h.candidate_id ORDER BY h.exhausted DESC,h.exhaustion_score DESC,h.updated_at DESC LIMIT ${n}`);
}

export async function handleGrowthEngineFoundryV2(request,env) {
  const url=new URL(request.url);
  if (request.method==="OPTIONS" && url.pathname.startsWith("/growth-foundry/")) return new Response(null,{status:204,headers:{"access-control-allow-origin":"*","access-control-allow-headers":"content-type,x-lumen-admin","access-control-allow-methods":"GET,POST,OPTIONS"}});
  if (request.method==="GET" && url.pathname==="/growth-foundry/policy") return json({
    ok:true,
    version:VERSION,
    baseEngineVersion:BASE_ENGINE_VERSION,
    name:"LUMEN Growth Engine Foundry v2",
    objective:"create bounded growth motors, run controlled deterministic champion/challenger experiments, measure directional conversion and verified economic evidence, detect exhausted tactics and reallocate bounded execution attention toward the strongest surviving motor",
    experimentDesign:"one motor per cycle; deterministic A/B/A/B alternation across four hourly cycles; no simultaneous paid traffic split",
    winnerRule:"verified revenue first, then normalized directional proof plus conversion signal; inconclusive results do not fabricate a winner",
    exhaustionRule:"repeated stalls, low success rate and score decay can cool a motor for twelve hours; verified revenue resets exhaustion pressure",
    allowedPrimitives:[...ALLOWED_PRIMITIVES],
    lifecycle:["DISCOVERED","TRIAL","PROMOTED","REJECTED"],
    experimentLifecycle:["ACTIVE","COMPLETED"],
    guardrails:guardrails()
  });
  if (request.method==="GET" && url.pathname==="/growth-foundry/status") return json(await status(env));
  if (request.method==="GET" && url.pathname==="/growth-foundry/experiments") {
    if (!authorized(request,env)) return json({ok:false,error:"admin_token_required",version:VERSION},403);
    return json({ok:true,version:VERSION,experiments:await experiments(env,url.searchParams.get("limit")),guardrails:guardrails()});
  }
  if (request.method==="GET" && url.pathname==="/growth-foundry/health") {
    if (!authorized(request,env)) return json({ok:false,error:"admin_token_required",version:VERSION},403);
    return json({ok:true,version:VERSION,health:await health(env,url.searchParams.get("limit")),guardrails:guardrails()});
  }
  if (request.method==="POST" && url.pathname==="/growth-foundry/run") {
    if (!authorized(request,env)) return json({ok:false,error:"admin_token_required",version:VERSION},403);
    return json(await runGrowthEngineFoundryV2Cycle(env,{trigger:"autonomous_operator_or_admin"}),202);
  }
  return null;
}
