const VERSION = "2.0-economic-operator-control-plane";

function json(data, status = 200) {
  return Response.json(data, { status, headers: { "cache-control": "no-store", "x-content-type-options": "nosniff", "access-control-allow-origin": "*" } });
}
function num(v) { const n = Number(v); return Number.isFinite(n) ? n : 0; }
function boolVar(value, fallback = false) {
  const v = String(value ?? "").trim().toLowerCase();
  if (!v) return fallback;
  return ["1", "true", "yes", "on"].includes(v);
}
function parseObject(value) {
  try {
    const parsed = JSON.parse(String(value || "{}"));
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch { return {}; }
}
async function first(env, sql) { try { return await env.DB.prepare(sql).first(); } catch { return null; } }

async function canonicalRevenueTruth(env) {
  if (!env?.DB) return { verifiedSettlements: 0, verifiedRevenueUsd: 0 };
  const row = await first(env, `SELECT
    COUNT(*) verified_settlements,
    COALESCE(SUM(amount_usd),0) verified_revenue_usd
    FROM lumen_revenue_events
    WHERE event_type='payment_settled' AND status='verified'`);
  return {
    verifiedSettlements: num(row?.verified_settlements),
    verifiedRevenueUsd: num(row?.verified_revenue_usd)
  };
}

export async function computeRevenueFocus(env) {
  if (!env?.DB) return { version: VERSION, mode: "NORMAL_DISCOVERY", backlog: {}, discoveryMultiplier: 1 };
  const [q, revenueTruth] = await Promise.all([
    first(env, `SELECT
      (SELECT COUNT(*) FROM lumen_proposal_drafts WHERE quality_gate_status='PASS') pass_total,
      (SELECT COUNT(*) FROM lumen_proposal_drafts p LEFT JOIN lumen_outreach_attempts x ON x.proposal_id=p.proposal_id WHERE p.quality_gate_status='PASS' AND x.proposal_id IS NULL) pass_waiting_outreach,
      (SELECT COUNT(*) FROM lumen_sales_pipeline WHERE response_class IN ('PURCHASE_INTENT','COMMERCIAL_INTEREST','COMMERCIAL_QUESTION')) qualified_responses,
      (SELECT COUNT(*) FROM lumen_sales_pipeline WHERE response_class IN ('PURCHASE_INTENT','COMMERCIAL_INTEREST')) close_intent,
      (SELECT COUNT(*) FROM lumen_followups WHERE status IN ('PLANNED','READY','PENDING')) followups_ready`),
    canonicalRevenueTruth(env)
  ]);
  const backlog = {
    passTotal: num(q?.pass_total),
    passWaitingOutreach: num(q?.pass_waiting_outreach),
    qualifiedResponses: num(q?.qualified_responses),
    closeIntent: num(q?.close_intent),
    followupsReady: num(q?.followups_ready),
    verifiedSettlements: revenueTruth.verifiedSettlements,
    verifiedRevenueUsd: revenueTruth.verifiedRevenueUsd
  };
  const conversionPressure = backlog.closeIntent * 5 + backlog.qualifiedResponses * 3 + backlog.passWaitingOutreach * 2 + Math.min(3, backlog.followupsReady);
  const mode = conversionPressure >= 5 ? "CONVERSION_FIRST" : conversionPressure >= 2 ? "BALANCED_CONVERSION" : "NORMAL_DISCOVERY";
  const discoveryMultiplier = mode === "CONVERSION_FIRST" ? 0.34 : mode === "BALANCED_CONVERSION" ? 0.67 : 1;
  return {
    version: VERSION,
    mode,
    conversionPressure,
    discoveryMultiplier,
    backlog,
    priority: backlog.closeIntent > 0 ? "CLOSE_INTENT" : backlog.qualifiedResponses > 0 ? "COMMERCIAL_REPLY" : backlog.followupsReady > 0 ? "FOLLOWUP" : backlog.passWaitingOutreach > 0 ? "QUALITY_PASS_OUTREACH" : "DISCOVERY",
    principle: "exploit_verified_commercial_inventory_before_expanding_search",
    revenueTruth: "payment_settled_and_verified_only",
    guardrails: { maxAutonomousExternalCommercialMessagesPerHour: 1, autonomousSpendUsd: 0, verifiedRevenueOnly: true }
  };
}

async function readPortfolioState(env) {
  if (!env?.DB) return null;
  const row = await first(env, "SELECT updated_at,cycle,recommended_lane,recommended_action,recommended_source_type,recommended_source_id,attention_json,metrics_json,top_candidate_json,external_candidate_json,engine_version FROM lumen_portfolio_governor_state WHERE id='GLOBAL' LIMIT 1");
  if (!row) return null;
  return {
    updatedAt: row.updated_at || null,
    cycle: num(row.cycle),
    recommendedLane: row.recommended_lane || null,
    recommendedAction: row.recommended_action || null,
    recommendedSourceType: row.recommended_source_type || null,
    recommendedSourceId: row.recommended_source_id || null,
    attention: parseObject(row.attention_json),
    metrics: parseObject(row.metrics_json),
    topCandidate: parseObject(row.top_candidate_json),
    externalCandidate: parseObject(row.external_candidate_json),
    engineVersion: row.engine_version || null
  };
}

async function readRevenueDirectorState(env) {
  if (!env?.DB) return null;
  const row = await first(env, "SELECT updated_at,cycle,no_progress_cycles,bottleneck,tactic,target_metric,metrics_json,preferred_offers_json,engine_version FROM lumen_revenue_director_state WHERE id='FIRST_CASH' LIMIT 1");
  if (!row) return null;
  let preferredOffers = [];
  try { const parsed = JSON.parse(row.preferred_offers_json || "[]"); preferredOffers = Array.isArray(parsed) ? parsed : []; } catch {}
  return {
    updatedAt: row.updated_at || null,
    cycle: num(row.cycle),
    noProgressCycles: num(row.no_progress_cycles),
    bottleneck: row.bottleneck || null,
    tactic: row.tactic || null,
    targetMetric: row.target_metric || null,
    metrics: parseObject(row.metrics_json),
    preferredOffers,
    engineVersion: row.engine_version || null
  };
}

async function operatorMetrics(env) {
  if (!env?.DB) return {};
  const [revenue, opportunities, pipeline, activity, firstCash, commerce] = await Promise.all([
    canonicalRevenueTruth(env),
    first(env, `SELECT
      (SELECT COUNT(*) FROM lumen_opportunity_factory_candidates WHERE active=1) active_candidates,
      (SELECT COUNT(*) FROM lumen_opportunity_assessments WHERE commercially_actionable=1 AND synthetic_or_test_only=0) actionable_opportunities`),
    first(env, `SELECT
      (SELECT COUNT(*) FROM lumen_proposal_drafts WHERE quality_gate_status='PASS') quality_pass_proposals,
      (SELECT COUNT(*) FROM lumen_proposal_drafts p LEFT JOIN lumen_outreach_attempts x ON x.proposal_id=p.proposal_id WHERE p.quality_gate_status='PASS' AND x.proposal_id IS NULL) approved_unsent,
      (SELECT COUNT(*) FROM lumen_sales_pipeline WHERE response_class IN ('PURCHASE_INTENT','COMMERCIAL_INTEREST','COMMERCIAL_QUESTION')) qualified_responses,
      (SELECT COUNT(*) FROM lumen_sales_pipeline WHERE stage='NEGOTIATING') negotiating`),
    first(env, `SELECT
      COUNT(*) outreach_attempts,
      SUM(CASE WHEN status IN ('SENT','SENT_TASK','WORKING','RESPONDED','TASK_TERMINAL') THEN 1 ELSE 0 END) sent,
      SUM(CASE WHEN status='RESPONDED' THEN 1 ELSE 0 END) responded
      FROM lumen_outreach_attempts`),
    first(env, `SELECT
      COUNT(*) first_cash_attempts,
      SUM(CASE WHEN status IN ('SENT','SENT_TASK','RESPONDED') THEN 1 ELSE 0 END) first_cash_sent,
      SUM(CASE WHEN status='RESPONDED' THEN 1 ELSE 0 END) first_cash_responded,
      SUM(CASE WHEN status='SEND_FAILED' THEN 1 ELSE 0 END) first_cash_failed
      FROM lumen_first_cash_closer`),
    first(env, `SELECT COUNT(*) verified_paid_orders
      FROM lumen_commerce_order_events
      WHERE verified=1 AND event_type IN ('PAID','ORDER_PAID','PAYMENT_CONFIRMED')`)
  ]);
  return {
    verifiedSettlements: revenue.verifiedSettlements,
    verifiedRevenueUsd: revenue.verifiedRevenueUsd,
    activeCandidates: num(opportunities?.active_candidates),
    actionableOpportunities: num(opportunities?.actionable_opportunities),
    qualityPassProposals: num(pipeline?.quality_pass_proposals),
    approvedUnsent: num(pipeline?.approved_unsent),
    qualifiedCommercialResponses: num(pipeline?.qualified_responses),
    negotiating: num(pipeline?.negotiating),
    outreachAttempts: num(activity?.outreach_attempts),
    sent: num(activity?.sent),
    responded: num(activity?.responded),
    firstCashAttempts: num(firstCash?.first_cash_attempts),
    firstCashSent: num(firstCash?.first_cash_sent),
    firstCashResponded: num(firstCash?.first_cash_responded),
    firstCashFailed: num(firstCash?.first_cash_failed),
    verifiedPaidCommerceOrders: num(commerce?.verified_paid_orders)
  };
}

function operatorPhase(metrics, focus) {
  if (num(metrics?.verifiedRevenueUsd) > 0 || num(metrics?.verifiedSettlements) > 0) return "REVENUE_VERIFIED_SCALE";
  if (num(focus?.backlog?.closeIntent) > 0 || num(metrics?.negotiating) > 0) return "CLOSING";
  if (num(metrics?.qualifiedCommercialResponses) > 0) return "CONVERTING";
  if (num(metrics?.approvedUnsent) > 0) return "OUTBOUND_READY";
  if (num(metrics?.actionableOpportunities) > 0 || num(metrics?.activeCandidates) > 0) return "BUILDING_PIPELINE";
  return "DISCOVERING";
}

function nextEconomicAction(metrics, focus, portfolio, director) {
  if (num(metrics?.verifiedRevenueUsd) > 0 && director?.tactic) return director.tactic;
  if (num(focus?.backlog?.closeIntent) > 0) return "CLOSE_VERIFIED_INTENT";
  if (num(metrics?.qualifiedCommercialResponses) > 0) return "QUALIFY_AND_REPLY";
  if (num(focus?.backlog?.followupsReady) > 0) return "FOLLOW_UP";
  if (num(metrics?.approvedUnsent) > 0) return "SEND_QUALITY_PASS_OUTREACH";
  if (portfolio?.recommendedAction) return portfolio.recommendedAction;
  return "DISCOVER_AND_SCORE_NEW_OPPORTUNITIES";
}

export async function computeEconomicOperatorState(env) {
  const [focus, metrics, portfolio, director] = await Promise.all([
    computeRevenueFocus(env),
    operatorMetrics(env),
    readPortfolioState(env),
    readRevenueDirectorState(env)
  ]);
  const phase = operatorPhase(metrics, focus);
  return {
    version: VERSION,
    name: "LUMEN Autonomous Economic Operator",
    objective: "maximize_verified_net_revenue_with_bounded_reversible_autonomy",
    running: Boolean(env?.DB),
    phase,
    revenueFocus: focus,
    metrics,
    portfolio,
    revenueDirector: director,
    nextEconomicAction: nextEconomicAction(metrics, focus, portfolio, director),
    autonomy: {
      marketDiscovery: true,
      opportunityScoring: true,
      strategySelection: true,
      autonomousOutreach: boolVar(env?.A2A_AUTONOMOUS_OUTREACH, false),
      autonomousFollowup: boolVar(env?.A2A_AUTONOMOUS_FOLLOWUP, false),
      autonomousCommercialReply: boolVar(env?.A2A_AUTONOMOUS_COMMERCIAL_REPLY, false),
      autonomousConversionClose: boolVar(env?.A2A_AUTONOMOUS_CONVERSION_CLOSE, false),
      revenueVerification: true,
      profitFeedback: true,
      dynamicTeams: true,
      autonomousSpendUsd: 0,
      autonomousPurchase: false,
      autonomousDebt: false,
      autonomousContract: false,
      bindingActionsHumanGated: true
    },
    operatingCadence: {
      sensingMinutes: 15,
      commercialDecisionMinutes: 60,
      maxAutonomousExternalCommercialMessagesPerHour: 1,
      conversionInventoryBeforeExpansion: true,
      sensingNeverZero: true
    },
    truthRules: {
      revenue: "only_payment_settled_with_status_verified_counts_as_revenue",
      commercialIntent: "raw_or_technical_responses_do_not_count_as_purchase_intent",
      learning: "verified_revenue_and_observed_funnel_progress_outweigh_activity_volume"
    }
  };
}

export async function handleRevenueFocusController(request, env) {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/revenue-focus/state") return json(await computeRevenueFocus(env));
  if (request.method === "GET" && url.pathname === "/revenue-focus/policy") return json({ version: VERSION, objective: "prioritize_close_reply_followup_and_quality_pass_inventory_before_more_discovery", verifiedRevenueOnly: true, revenueTruth: "payment_settled_and_verified_only", autonomousSpendUsd: 0, maxAutonomousExternalCommercialMessagesPerHour: 1 });
  if (request.method === "GET" && url.pathname === "/economic-operator/state") return json(await computeEconomicOperatorState(env));
  if (request.method === "GET" && url.pathname === "/economic-operator/policy") return json({
    version: VERSION,
    name: "LUMEN Autonomous Economic Operator",
    objective: "maximize_verified_net_revenue_with_bounded_reversible_autonomy",
    cycle: "observe_discover_evaluate_choose_act_measure_learn_reallocate",
    preservesExistingLumen: true,
    verifiedRevenueOnly: true,
    revenueTruth: "payment_settled_and_verified_only",
    sensingMinutes: 15,
    commercialDecisionMinutes: 60,
    maxAutonomousExternalCommercialMessagesPerHour: 1,
    autonomousSpendUsd: 0,
    autonomousPurchase: false,
    autonomousDebt: false,
    autonomousContract: false,
    bindingActionsHumanGated: true
  });
  return null;
}
