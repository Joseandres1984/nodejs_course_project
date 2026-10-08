const VERSION = "2.0-growth-multiplier-compounding";
const LANES = ["B2B", "TRAVEL", "REFERRAL", "PARTNER", "VENTURE"];
const MAX_MEMORY_WEIGHT = 12;
const MIN_MEMORY_WEIGHT = -6;
const MAX_HISTORY = 120;

function clean(value, limit = 4000) {
  return String(value ?? "").trim().replace(/[\r\n\t]+/g, " ").slice(0, limit);
}
function num(value) {
  const n = Number(value || 0);
  return Number.isFinite(n) ? n : 0;
}
function clamp(value, min, max) {
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
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_growth_multiplier_state (id TEXT PRIMARY KEY,updated_at TEXT NOT NULL,cycle INTEGER NOT NULL,primary_lane TEXT NOT NULL,exploration_lane TEXT,confidence TEXT NOT NULL,reason TEXT NOT NULL,snapshot_json TEXT NOT NULL,scores_json TEXT NOT NULL,activation_plan_json TEXT NOT NULL,learning_json TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_growth_multiplier_memory (lane TEXT PRIMARY KEY,updated_at TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,evaluated_cycles INTEGER NOT NULL DEFAULT 0,positive_outcomes INTEGER NOT NULL DEFAULT 0,stalls INTEGER NOT NULL DEFAULT 0,cumulative_reward REAL NOT NULL DEFAULT 0,learned_weight REAL NOT NULL DEFAULT 0,last_outcome TEXT,last_proof_value REAL NOT NULL DEFAULT 0,last_selected_at TEXT,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_growth_multiplier_memory_weight ON lumen_growth_multiplier_memory(learned_weight DESC,updated_at DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_growth_multiplier_cycles (id TEXT PRIMARY KEY,created_at TEXT NOT NULL,trigger TEXT NOT NULL,primary_lane TEXT NOT NULL,exploration_lane TEXT,confidence TEXT NOT NULL,reason TEXT NOT NULL,snapshot_json TEXT NOT NULL,scores_json TEXT NOT NULL,activation_plan_json TEXT NOT NULL,learning_json TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_growth_multiplier_cycles_created ON lumen_growth_multiplier_cycles(created_at DESC)")
  ]);
  return true;
}

async function snapshot(env) {
  const [
    x402Revenue30d, x402Settlements30d,
    referralRevenue30d, referralSettlements30d, referralPaymentDue, referralAgreed, referralProposalReady,
    negotiating, quotes7d, inbound7d, machineRequests7d, activeCandidates,
    travelAffiliateRevenue30d, travelAffiliateRewards30d, travelConfirmations30d, travelClicks7d, travelResults7d, travelRecommended,
    partnerAgents, partnerMatches, partnerCouncils,
    ventureHighPotential, ventureReview, ventureBestScore, ventureIngestedPass
  ] = await Promise.all([
    scalar(env, "SELECT COALESCE(SUM(amount_usd),0) n FROM lumen_revenue_events WHERE event_type='payment_settled' AND source='x402' AND status='verified' AND datetime(created_at)>=datetime('now','-30 days')"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_revenue_events WHERE event_type='payment_settled' AND source='x402' AND status='verified' AND datetime(created_at)>=datetime('now','-30 days')"),
    scalar(env, "SELECT COALESCE(SUM(settled_amount_usd),0) n FROM lumen_referral_commissions WHERE status='SETTLED' AND datetime(updated_at)>=datetime('now','-30 days')"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_referral_commissions WHERE status='SETTLED' AND datetime(updated_at)>=datetime('now','-30 days')"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_referral_commissions WHERE status='PAYMENT_DUE'"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_referral_commissions WHERE status='AGREED_PENDING_CLOSE'"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_referral_commissions WHERE status='PROPOSAL_READY'"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_sales_pipeline WHERE stage='NEGOTIATING'"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_a2a_quotes WHERE datetime(created_at)>=datetime('now','-7 days')"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_a2a_inbound WHERE binding_intent=0 AND datetime(received_at)>=datetime('now','-7 days')"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_machine_orders WHERE status='received_unverified' AND datetime(created_at)>=datetime('now','-7 days')"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_opportunity_factory_candidates WHERE active=1"),
    scalar(env, "SELECT COALESCE(SUM(amount_usd),0) n FROM lumen_revenue_events WHERE event_type='affiliate_reward_confirmed' AND source='travelpayouts' AND status='verified' AND datetime(created_at)>=datetime('now','-30 days')"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_revenue_events WHERE event_type='affiliate_reward_confirmed' AND source='travelpayouts' AND status='verified' AND datetime(created_at)>=datetime('now','-30 days')"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_viator_booking_events WHERE event_type='CONFIRMATION' AND datetime(last_updated)>=datetime('now','-30 days')"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_travel_events WHERE event_type='click' AND datetime(created_at)>=datetime('now','-7 days')"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_travel_events WHERE event_type='result_shown' AND datetime(created_at)>=datetime('now','-7 days')"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_travel_acquisition_campaigns WHERE status IN ('RECOMMENDED','APPROVED')"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_partner_agents"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_partner_matches"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_partner_councils"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_partner_ideas WHERE status='HIGH_POTENTIAL'"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_partner_ideas WHERE status='REVIEW'"),
    scalar(env, "SELECT COALESCE(MAX(total_score),0) n FROM lumen_partner_ideas"),
    scalar(env, "SELECT COUNT(*) n FROM lumen_venture_suggestion_intake WHERE status='INGESTED_PASS'")
  ]);

  const b2bVerifiedRevenueUsd30d = Math.max(0, x402Revenue30d - referralRevenue30d);
  const b2bVerifiedSettlements30d = Math.max(0, x402Settlements30d - referralSettlements30d);

  return {
    capturedAt: new Date().toISOString(),
    B2B: {
      verifiedRevenueUsd30d: b2bVerifiedRevenueUsd30d,
      verifiedSettlements30d: b2bVerifiedSettlements30d,
      negotiating,
      quotes7d,
      inbound7d,
      machineRequests7d,
      activeCandidates
    },
    TRAVEL: {
      verifiedRevenueUsd30d: travelAffiliateRevenue30d,
      verifiedRewards30d: travelAffiliateRewards30d,
      confirmations30d: travelConfirmations30d,
      clicks7d: travelClicks7d,
      results7d: travelResults7d,
      recommendedCampaigns: travelRecommended
    },
    REFERRAL: {
      verifiedRevenueUsd30d: referralRevenue30d,
      verifiedSettlements30d: referralSettlements30d,
      paymentDue: referralPaymentDue,
      agreedPendingClose: referralAgreed,
      proposalReady: referralProposalReady
    },
    PARTNER: {
      partnerAgents,
      matches: partnerMatches,
      councils: partnerCouncils
    },
    VENTURE: {
      highPotential: ventureHighPotential,
      review: ventureReview,
      bestScore: ventureBestScore,
      ingestedPass: ventureIngestedPass
    },
    truth: {
      verifiedRevenueOnly: true,
      nonbindingDemandIsNotRevenue: true,
      clicksAreNotRevenue: true,
      partnerMatchesAreNotRevenue: true,
      ventureScoresAreNotRevenue: true,
      referralRevenueRequiresSettledCommission: true
    }
  };
}

function revenueStrength(usd, events) {
  const revenue = Math.max(0, num(usd));
  const count = Math.max(0, num(events));
  return Math.min(72, Math.log1p(revenue) * 17) + Math.min(30, count * 15);
}

export function growthProof(lane, snapshotValue = {}) {
  const s = snapshotValue || {};
  if (lane === "B2B") {
    return num(s.verifiedRevenueUsd30d) * 100 + num(s.verifiedSettlements30d) * 50 + num(s.negotiating) * 6 + num(s.quotes7d) * 2 + num(s.inbound7d) + num(s.machineRequests7d) * .4 + num(s.activeCandidates) * .15;
  }
  if (lane === "TRAVEL") {
    return num(s.verifiedRevenueUsd30d) * 100 + num(s.verifiedRewards30d) * 50 + num(s.confirmations30d) * 22 + num(s.clicks7d) * 1.5 + num(s.results7d) * .12 + num(s.recommendedCampaigns) * .2;
  }
  if (lane === "REFERRAL") {
    return num(s.verifiedRevenueUsd30d) * 100 + num(s.verifiedSettlements30d) * 50 + num(s.paymentDue) * 10 + num(s.agreedPendingClose) * 5 + num(s.proposalReady);
  }
  if (lane === "PARTNER") {
    return num(s.councils) * 8 + num(s.matches) * 4 + num(s.partnerAgents);
  }
  if (lane === "VENTURE") {
    return num(s.highPotential) * 10 + num(s.review) * 4 + num(s.ingestedPass) * 5 + num(s.bestScore) / 10;
  }
  return 0;
}

function learnedWeight(memory, lane) {
  const row = memory?.[lane] || {};
  return clamp(row.learnedWeight ?? row.learned_weight ?? 0, MIN_MEMORY_WEIGHT, MAX_MEMORY_WEIGHT);
}

export function scoreGrowthLanes(snapshotValue = {}, memory = {}) {
  const b = snapshotValue.B2B || {};
  const t = snapshotValue.TRAVEL || {};
  const r = snapshotValue.REFERRAL || {};
  const p = snapshotValue.PARTNER || {};
  const v = snapshotValue.VENTURE || {};

  // First-cash routing: a large stock of partner matches or speculative ideas
  // is not proof of a buyer. When B2B has real downstream conversations but
  // no lane has a verified payment, cap research-only signals as primary drivers.
  // Verified revenue immediately lifts this cap for economic winner selection.
  const anyVerifiedPayment = [
    b.verifiedRevenueUsd30d, b.verifiedSettlements30d,
    t.verifiedRevenueUsd30d, t.verifiedRewards30d,
    r.verifiedRevenueUsd30d, r.verifiedSettlements30d
  ].some(x => num(x) > 0);
  const b2bDownstreamIntent = [b.negotiating, b.quotes7d, b.inbound7d].some(x => num(x) > 0);
  const researchOnlyCeiling = !anyVerifiedPayment && b2bDownstreamIntent ? 18 : Infinity;

  const scores = [
    {
      lane: "B2B",
      score: 12 + revenueStrength(b.verifiedRevenueUsd30d, b.verifiedSettlements30d) + Math.min(24, num(b.negotiating) * 8) + Math.min(12, num(b.quotes7d) * 1.5) + Math.min(10, num(b.inbound7d) * 2) + Math.min(8, num(b.machineRequests7d)) + Math.min(7, num(b.activeCandidates) * .35) + learnedWeight(memory, "B2B"),
      verifiedRevenueUsd: num(b.verifiedRevenueUsd30d),
      verifiedEvents: num(b.verifiedSettlements30d),
      proof: growthProof("B2B", b),
      evidence: `verified_settlements=${num(b.verifiedSettlements30d)}; negotiating=${num(b.negotiating)}; quotes7d=${num(b.quotes7d)}`
    },
    {
      lane: "TRAVEL",
      score: 10 + revenueStrength(t.verifiedRevenueUsd30d, t.verifiedRewards30d) + Math.min(28, num(t.confirmations30d) * 9) + Math.min(12, num(t.clicks7d) * .6) + Math.min(6, num(t.results7d) * .08) + Math.min(5, num(t.recommendedCampaigns) * .5) + learnedWeight(memory, "TRAVEL"),
      verifiedRevenueUsd: num(t.verifiedRevenueUsd30d),
      verifiedEvents: num(t.verifiedRewards30d),
      proof: growthProof("TRAVEL", t),
      evidence: `verified_affiliate_rewards=${num(t.verifiedRewards30d)}; confirmations=${num(t.confirmations30d)}; clicks7d=${num(t.clicks7d)}`
    },
    {
      lane: "REFERRAL",
      score: 8 + revenueStrength(r.verifiedRevenueUsd30d, r.verifiedSettlements30d) + Math.min(20, num(r.paymentDue) * 8) + Math.min(15, num(r.agreedPendingClose) * 5) + Math.min(10, num(r.proposalReady) * 2) + learnedWeight(memory, "REFERRAL"),
      verifiedRevenueUsd: num(r.verifiedRevenueUsd30d),
      verifiedEvents: num(r.verifiedSettlements30d),
      proof: growthProof("REFERRAL", r),
      evidence: `verified_referral_settlements=${num(r.verifiedSettlements30d)}; payment_due=${num(r.paymentDue)}; agreed=${num(r.agreedPendingClose)}`
    },
    {
      lane: "PARTNER",
      score: Math.min(researchOnlyCeiling, 6 + Math.min(11, num(p.partnerAgents) * .7) + Math.min(16, num(p.matches) * 2) + Math.min(18, num(p.councils) * 3) + learnedWeight(memory, "PARTNER")),
      verifiedRevenueUsd: 0,
      verifiedEvents: 0,
      proof: growthProof("PARTNER", p),
      evidence: `partners=${num(p.partnerAgents)}; matches=${num(p.matches)}; councils=${num(p.councils)}`
    },
    {
      lane: "VENTURE",
      score: Math.min(researchOnlyCeiling, 6 + Math.min(24, num(v.highPotential) * 8) + Math.min(12, num(v.review) * 3) + Math.min(18, num(v.bestScore) * .2) + Math.min(10, num(v.ingestedPass) * 2) + learnedWeight(memory, "VENTURE")),
      verifiedRevenueUsd: 0,
      verifiedEvents: 0,
      proof: growthProof("VENTURE", v),
      evidence: `high_potential=${num(v.highPotential)}; review=${num(v.review)}; best_score=${num(v.bestScore)}; ingested_pass=${num(v.ingestedPass)}`
    }
  ];

  return scores
    .map(x => ({ ...x, score: Number(Math.max(0, x.score).toFixed(2)), proof: Number(x.proof.toFixed(2)), learnedWeight: learnedWeight(memory, x.lane) }))
    .sort((a, b) => b.score - a.score || b.verifiedRevenueUsd - a.verifiedRevenueUsd || a.lane.localeCompare(b.lane));
}

function laneStalls(memory, lane) {
  return Math.max(0, num(memory?.[lane]?.stalls));
}

export function chooseGrowthAllocation(scores = [], memory = {}, cycle = 1) {
  const ranked = [...scores].sort((a, b) => num(b.score) - num(a.score));
  const primary = ranked[0] || { lane:"B2B", score:0, verifiedRevenueUsd:0, verifiedEvents:0, evidence:"no_signal" };
  const runner = ranked.find(x => x.lane !== primary.lane) || null;
  const gap = runner ? num(primary.score) - num(runner.score) : num(primary.score);
  const primaryVerified = num(primary.verifiedRevenueUsd) > 0 || num(primary.verifiedEvents) > 0;
  const anyVerified = ranked.some(x => num(x.verifiedRevenueUsd) > 0 || num(x.verifiedEvents) > 0);
  const stalls = laneStalls(memory, primary.lane);
  const periodicExplore = Number(cycle || 1) % 4 === 0;
  const shouldExplore = Boolean(runner && (!anyVerified || !primaryVerified || gap < 10 || stalls >= 2 || periodicExplore));
  const exploration = shouldExplore ? runner : null;
  const confidence = gap >= 24 && primaryVerified ? "HIGH" : gap >= 10 ? "MEDIUM" : "LOW";
  const allocation = exploration ? { primary:0.8, exploration:0.2 } : { primary:1, exploration:0 };
  const reason = primaryVerified
    ? `${primary.lane} leads with verified economic evidence; ${exploration ? `a bounded ${exploration.lane} exploration is retained to avoid local maxima` : "focus remains concentrated on the verified winner"}.`
    : `${primary.lane} leads on current non-revenue evidence; ${exploration ? `${exploration.lane} remains a bounded challenger until verified revenue appears` : "no alternate lane currently justifies activation"}.`;
  return {
    primaryLane: primary.lane,
    explorationLane: exploration?.lane || null,
    confidence,
    scoreGap: Number(gap.toFixed(2)),
    primaryVerified,
    anyVerified,
    primaryStalls: stalls,
    allocation,
    reason,
    primary,
    runnerUp: runner
  };
}

function laneActivation(lane) {
  const map = {
    B2B: {
      mode: "SAFE_INTERNAL_PREPARATION",
      objective: "find, qualify and prepare the shortest non-binding path to verified B2B revenue",
      endpoints: ["/source-intelligence/cycle", "/market-hunter/run", "/commercial/reassess", "/proposals/prepare-top", "/quality/review-next"]
    },
    TRAVEL: {
      mode: "SAFE_INTERNAL_ACQUISITION_REFRESH",
      objective: "refresh conversion-aware Travel recommendations from confirmed bookings and measured buyer intent",
      endpoints: ["/travel/acquisition/run"]
    },
    REFERRAL: {
      mode: "INTERNAL_COMMISSION_PLANNING_ONLY",
      objective: "prepare non-binding success-fee cases while leaving counterparty contact to the existing guarded autopilot",
      endpoints: ["/referrals/commissions/plan"]
    },
    PARTNER: {
      mode: "NONBINDING_NETWORK_BUILD",
      objective: "discover and match useful partners and assemble a non-binding council without spend or contract authority",
      endpoints: ["/partners/discover", "/partners/match", "/partners/council"]
    },
    VENTURE: {
      mode: "EVIDENCE_GATED_IDEA_INGESTION",
      objective: "ingest only explicit PASS-quality partner business suggestions and rank them without inventing demand",
      endpoints: ["/venture-intake/run"]
    }
  };
  return { lane, ...(map[lane] || map.B2B), createsExternalMessages:false, autonomousSpendUsd:0, bindingActionsHumanGated:true };
}

export function buildActivationPlan(allocation) {
  return {
    primary: laneActivation(allocation.primaryLane),
    exploration: allocation.explorationLane ? laneActivation(allocation.explorationLane) : null,
    allocation: allocation.allocation,
    sequencing: "primary_then_at_most_one_bounded_exploration_lane",
    externalCommercialSlot: "not_consumed_by_growth_multiplier",
    downstreamRule: "existing_guarded_modules_keep_their_own_message_and_authority_limits"
  };
}

async function memoryMap(env) {
  const rows = await all(env, "SELECT lane,updated_at,attempts,evaluated_cycles,positive_outcomes,stalls,cumulative_reward,learned_weight,last_outcome,last_proof_value,last_selected_at,engine_version FROM lumen_growth_multiplier_memory");
  return Object.fromEntries(rows.map(row => [row.lane, {
    ...row,
    attempts:num(row.attempts),
    evaluatedCycles:num(row.evaluated_cycles),
    positiveOutcomes:num(row.positive_outcomes),
    stalls:num(row.stalls),
    cumulativeReward:num(row.cumulative_reward),
    learnedWeight:num(row.learned_weight),
    lastProofValue:num(row.last_proof_value)
  }]));
}

async function ensureMemoryLane(env, lane) {
  const now = new Date().toISOString();
  await env.DB.prepare("INSERT OR IGNORE INTO lumen_growth_multiplier_memory(lane,updated_at,attempts,evaluated_cycles,positive_outcomes,stalls,cumulative_reward,learned_weight,last_outcome,last_proof_value,last_selected_at,engine_version) VALUES(?,?,0,0,0,0,0,0,'UNTESTED',0,NULL,?)")
    .bind(lane, now, VERSION).run();
}

async function learnFromPrevious(env, previous, currentSnapshot) {
  if (!previous) return { evaluated:false, attribution:"observational_not_causal", lanes:[] };
  const previousSnapshot = parse(previous.snapshot_json, {});
  const previousPlan = parse(previous.activation_plan_json, {});
  const previousLanes = [previous.primary_lane, previous.exploration_lane].filter((x, i, a) => x && a.indexOf(x) === i && LANES.includes(x));
  const results = [];
  for (const lane of previousLanes) {
    await ensureMemoryLane(env, lane);
    const before = growthProof(lane, previousSnapshot[lane] || {});
    const after = growthProof(lane, currentSnapshot[lane] || {});
    const delta = after - before;
    const isPrimary = lane === previous.primary_lane;
    const gain = delta > 0;
    const current = await first(env, "SELECT stalls,learned_weight,cumulative_reward FROM lumen_growth_multiplier_memory WHERE lane=? LIMIT 1", [lane]);
    const oldStalls = Math.max(0, num(current?.stalls));
    const oldWeight = clamp(current?.learned_weight, MIN_MEMORY_WEIGHT, MAX_MEMORY_WEIGHT);
    const reward = gain ? Math.min(12, Math.log1p(delta) * (isPrimary ? 2.4 : 1.4)) : 0;
    const newWeight = gain
      ? clamp(oldWeight + (isPrimary ? 1.25 : .65), MIN_MEMORY_WEIGHT, MAX_MEMORY_WEIGHT)
      : clamp(oldWeight - Math.min(.65, .12 * (oldStalls + 1)), MIN_MEMORY_WEIGHT, MAX_MEMORY_WEIGHT);
    const outcome = gain ? "OBSERVED_PROGRESS" : "NO_OBSERVED_PROGRESS";
    await env.DB.prepare("UPDATE lumen_growth_multiplier_memory SET updated_at=?,evaluated_cycles=evaluated_cycles+1,positive_outcomes=positive_outcomes+?,stalls=?,cumulative_reward=cumulative_reward+?,learned_weight=?,last_outcome=?,last_proof_value=?,engine_version=? WHERE lane=?")
      .bind(new Date().toISOString(), gain ? 1 : 0, gain ? 0 : oldStalls + 1, reward, newWeight, outcome, after, VERSION, lane).run();
    results.push({ lane, role:isPrimary?"PRIMARY":"EXPLORATION", before:Number(before.toFixed(2)), after:Number(after.toFixed(2)), delta:Number(delta.toFixed(2)), outcome, reward:Number(reward.toFixed(2)), attribution:"observational_not_causal" });
  }
  return { evaluated:true, previousAllocation:{ primary:previous.primary_lane, exploration:previous.exploration_lane || null, plan:previousPlan?.allocation || null }, attribution:"observational_not_causal", lanes:results };
}

async function markSelected(env, lane, proofValue) {
  if (!lane) return;
  await ensureMemoryLane(env, lane);
  const now = new Date().toISOString();
  await env.DB.prepare("UPDATE lumen_growth_multiplier_memory SET updated_at=?,attempts=attempts+1,last_selected_at=?,last_proof_value=?,engine_version=? WHERE lane=?")
    .bind(now, now, num(proofValue), VERSION, lane).run();
}

async function trimHistory(env) {
  try {
    await env.DB.prepare(`DELETE FROM lumen_growth_multiplier_cycles WHERE id NOT IN (SELECT id FROM lumen_growth_multiplier_cycles ORDER BY created_at DESC LIMIT ${MAX_HISTORY})`).run();
  } catch {}
}

export async function runGrowthMultiplierV2Cycle(env, options = {}) {
  if (!(await ensureSchema(env))) return { ok:false, error:"persistence_unavailable", version:VERSION };
  for (const lane of LANES) await ensureMemoryLane(env, lane);

  const previous = await first(env, "SELECT * FROM lumen_growth_multiplier_state WHERE id='CURRENT' LIMIT 1");
  const currentSnapshot = await snapshot(env);
  const learning = await learnFromPrevious(env, previous, currentSnapshot);
  const memory = await memoryMap(env);
  const cycle = Math.max(1, num(previous?.cycle) + 1);
  const scores = scoreGrowthLanes(currentSnapshot, memory);
  const allocation = chooseGrowthAllocation(scores, memory, cycle);
  const activationPlan = buildActivationPlan(allocation);

  await markSelected(env, allocation.primaryLane, allocation.primary?.proof);
  if (allocation.explorationLane) await markSelected(env, allocation.explorationLane, allocation.runnerUp?.proof);

  const now = new Date().toISOString();
  const cycleId = `GM2-${Date.now()}-${crypto.randomUUID().slice(0, 8).toUpperCase()}`;
  const trigger = clean(options.trigger || "scheduled", 100);
  const guardrails = {
    autonomousSpendUsd:0,
    autonomousPurchase:false,
    autonomousContract:false,
    paidMedia:false,
    createsExternalMessages:false,
    maxExternalCommercialMessagesDelegatedPerCycle:1,
    bindingActionsHumanGated:true,
    verifiedRevenueOnly:true,
    selfModifyingCode:false,
    learningAttribution:"observational_not_causal"
  };

  await env.DB.prepare("INSERT OR REPLACE INTO lumen_growth_multiplier_state(id,updated_at,cycle,primary_lane,exploration_lane,confidence,reason,snapshot_json,scores_json,activation_plan_json,learning_json,engine_version) VALUES('CURRENT',?,?,?,?,?,?,?,?,?,?,?)")
    .bind(now, cycle, allocation.primaryLane, allocation.explorationLane, allocation.confidence, allocation.reason, JSON.stringify(currentSnapshot), JSON.stringify(scores), JSON.stringify(activationPlan), JSON.stringify(learning), VERSION).run();
  await env.DB.prepare("INSERT INTO lumen_growth_multiplier_cycles(id,created_at,trigger,primary_lane,exploration_lane,confidence,reason,snapshot_json,scores_json,activation_plan_json,learning_json,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)")
    .bind(cycleId, now, trigger, allocation.primaryLane, allocation.explorationLane, allocation.confidence, allocation.reason, JSON.stringify(currentSnapshot), JSON.stringify(scores), JSON.stringify(activationPlan), JSON.stringify(learning), VERSION).run();
  await trimHistory(env);

  return {
    ok:true,
    version:VERSION,
    cycleId,
    cycle,
    primaryLane:allocation.primaryLane,
    explorationLane:allocation.explorationLane,
    confidence:allocation.confidence,
    allocation:allocation.allocation,
    reason:allocation.reason,
    scores,
    activationPlan,
    learning,
    narrative:`I am concentrating ${Math.round(allocation.allocation.primary*100)}% of Growth Multiplier attention on ${allocation.primaryLane}${allocation.explorationLane?` and keeping ${Math.round(allocation.allocation.exploration*100)}% as a bounded ${allocation.explorationLane} challenger`:""}. I will promote lanes only from observed evidence and verified revenue truth, not activity volume alone.`,
    guardrails
  };
}

async function status(env) {
  await ensureSchema(env);
  const row = await first(env, "SELECT * FROM lumen_growth_multiplier_state WHERE id='CURRENT' LIMIT 1");
  const memory = await memoryMap(env);
  if (!row) return { ok:true, version:VERSION, initialized:false, memory, guardrails:policyGuardrails() };
  return {
    ok:true,
    version:VERSION,
    initialized:true,
    updatedAt:row.updated_at,
    cycle:num(row.cycle),
    primaryLane:row.primary_lane,
    explorationLane:row.exploration_lane || null,
    confidence:row.confidence,
    reason:row.reason,
    snapshot:parse(row.snapshot_json, {}),
    scores:parse(row.scores_json, []),
    activationPlan:parse(row.activation_plan_json, {}),
    learning:parse(row.learning_json, {}),
    memory,
    guardrails:policyGuardrails()
  };
}

async function history(env, limit = 10) {
  await ensureSchema(env);
  const n = Math.max(1, Math.min(30, Number(limit) || 10));
  const rows = await all(env, `SELECT id,created_at,trigger,primary_lane,exploration_lane,confidence,reason,scores_json,activation_plan_json,learning_json,engine_version FROM lumen_growth_multiplier_cycles ORDER BY created_at DESC LIMIT ${n}`);
  return rows.map(row => ({ ...row, scores:parse(row.scores_json, []), activationPlan:parse(row.activation_plan_json, {}), learning:parse(row.learning_json, {}) }));
}

function policyGuardrails() {
  return {
    autonomousSpendUsd:0,
    autonomousPurchase:false,
    autonomousContract:false,
    paidMedia:false,
    createsExternalMessages:false,
    maxExternalCommercialMessagesDelegatedPerCycle:1,
    bindingActionsHumanGated:true,
    verifiedRevenueOnly:true,
    selfModifyingCode:false
  };
}

export async function handleGrowthMultiplierV2(request, env) {
  const url = new URL(request.url);
  if (request.method === "OPTIONS" && url.pathname.startsWith("/growth-multiplier/")) {
    return new Response(null, { status:204, headers:{ "access-control-allow-origin":"*", "access-control-allow-headers":"content-type,x-lumen-admin", "access-control-allow-methods":"GET,POST,OPTIONS" } });
  }
  if (request.method === "GET" && url.pathname === "/growth-multiplier/policy") {
    return json({
      ok:true,
      version:VERSION,
      name:"LUMEN Growth Multiplier v2",
      objective:"compound verified economic learning across B2B, Travel, Referral, Partner and Venture lanes",
      principle:"verified outcomes outrank activity; exploit winners while preserving bounded exploration",
      lanes:LANES,
      learning:"persistent_lane_memory_with_observational_attribution",
      allocation:"winner_focus_plus_at_most_one_bounded_challenger",
      guardrails:policyGuardrails()
    });
  }
  if (request.method === "GET" && url.pathname === "/growth-multiplier/status") return json(await status(env));
  if (request.method === "GET" && url.pathname === "/growth-multiplier/history") return json({ ok:true, version:VERSION, cycles:await history(env, url.searchParams.get("limit")) });
  if (request.method === "POST" && url.pathname === "/growth-multiplier/run") {
    if (!authorized(request, env)) return json({ ok:false, error:"admin_token_required", version:VERSION }, 403);
    return json(await runGrowthMultiplierV2Cycle(env, { trigger:"admin_or_operator" }), 202);
  }
  return null;
}
