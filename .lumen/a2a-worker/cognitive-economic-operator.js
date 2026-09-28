import { computeEconomicOperatorState } from "./revenue-focus-controller.js";

export const COGNITIVE_ECONOMIC_OPERATOR_VERSION = "1.0-cognitive-economic-supervisor";

const SAFE_PRODUCTS = new Set([
  "supplier-snapshot",
  "quote-sanity",
  "tender-scan",
  "sourcing-5",
  "buyer-signals",
  "export-pulse",
]);
const SAFE_DECISIONS = new Set(["contact", "research", "hold", "prioritize"]);
const SAFE_PRIORITIES = new Set(["low", "medium", "high"]);
const CONVERSION_LOCKED_PHASES = new Set(["CLOSING", "CONVERTING", "OUTBOUND_READY"]);
const MAX_HISTORY_DAYS = 30;

function json(data, status = 200) {
  return Response.json(data, {
    status,
    headers: {
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "access-control-allow-origin": "*",
    },
  });
}

function clean(value, limit = 240) {
  return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit);
}

function clamp(value, min = 0, max = 1) {
  const n = Number(value);
  return Math.max(min, Math.min(max, Number.isFinite(n) ? n : min));
}

function num(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function safeProduct(value) {
  const product = clean(value, 80);
  return SAFE_PRODUCTS.has(product) ? product : null;
}

function compactEconomicContext(economic) {
  const metrics = economic?.metrics || {};
  const portfolio = economic?.portfolio || {};
  const director = economic?.revenueDirector || {};
  return {
    phase: clean(economic?.phase, 80) || "UNKNOWN",
    next_economic_action: clean(economic?.nextEconomicAction, 160) || "OBSERVE",
    revenue_focus: {
      mode: clean(economic?.revenueFocus?.mode, 80),
      priority: clean(economic?.revenueFocus?.priority, 80),
      conversion_pressure: num(economic?.revenueFocus?.conversionPressure),
    },
    metrics: {
      verified_revenue_usd: num(metrics?.verifiedRevenueUsd),
      verified_settlements: num(metrics?.verifiedSettlements),
      active_candidates: num(metrics?.activeCandidates),
      actionable_opportunities: num(metrics?.actionableOpportunities),
      quality_pass_proposals: num(metrics?.qualityPassProposals),
      approved_unsent: num(metrics?.approvedUnsent),
      qualified_commercial_responses: num(metrics?.qualifiedCommercialResponses),
      negotiating: num(metrics?.negotiating),
      outreach_attempts: num(metrics?.outreachAttempts),
      sent: num(metrics?.sent),
      responded: num(metrics?.responded),
      first_cash_attempts: num(metrics?.firstCashAttempts),
      first_cash_sent: num(metrics?.firstCashSent),
      first_cash_responded: num(metrics?.firstCashResponded),
      verified_paid_commerce_orders: num(metrics?.verifiedPaidCommerceOrders),
    },
    portfolio: {
      recommended_lane: clean(portfolio?.recommendedLane, 100),
      recommended_action: clean(portfolio?.recommendedAction, 140),
      recommended_source_type: clean(portfolio?.recommendedSourceType, 100),
      recommended_source_id: clean(portfolio?.recommendedSourceId, 140),
      top_candidate: portfolio?.topCandidate && typeof portfolio.topCandidate === "object"
        ? {
            product_slug: safeProduct(portfolio.topCandidate.product_slug || portfolio.topCandidate.product),
            lane: clean(portfolio.topCandidate.lane, 80),
            source_type: clean(portfolio.topCandidate.source_type, 80),
          }
        : null,
    },
    revenue_director: {
      bottleneck: clean(director?.bottleneck, 100),
      tactic: clean(director?.tactic, 140),
      target_metric: clean(director?.targetMetric, 100),
      no_progress_cycles: num(director?.noProgressCycles),
      preferred_offers: Array.isArray(director?.preferredOffers)
        ? director.preferredOffers.slice(0, 4).map((offer) => typeof offer === "string" ? clean(offer, 100) : {
            product_slug: safeProduct(offer?.product_slug || offer?.product),
            offer: clean(offer?.offer || offer?.name || offer?.id, 100),
          })
        : [],
    },
  };
}

export function cognitiveEconomicOperatorPolicy() {
  return {
    version: COGNITIVE_ECONOMIC_OPERATOR_VERSION,
    mode: "bounded_advisory_supervisor",
    purpose: "use_cognitive_reasoning_to_improve_reversible_attention_without_overriding_revenue_conversion_or_authority",
    cognitiveWorker: {
      transport: "cloudflare_service_binding",
      task: "director",
      directPublicDependency: false,
      fallback: "deterministic_economic_guardrail",
    },
    authority: {
      mayReadEconomicState: true,
      maySelectProductFocus: true,
      mayAdjustDiscoveryAttention: true,
      mayChangeExternalCommercialAction: false,
      hardConversionPriorityOverride: false,
      externalMessagesCreated: false,
      autonomousSpendUsd: 0,
      autonomousPurchase: false,
      autonomousDebt: false,
      autonomousContract: false,
      bindingActionsHumanGated: true,
    },
    truthRules: {
      verifiedRevenueOnly: true,
      cognitiveOutputIsAdvisory: true,
      existingEconomicOperatorRemainsAuthoritative: true,
      conversionInventoryBeforeExploration: true,
    },
  };
}

export function deriveCognitivePlan(economic = {}, cognitive = {}) {
  const phase = clean(economic?.phase, 80) || "UNKNOWN";
  const revenueMode = clean(economic?.revenueFocus?.mode, 80) || "NORMAL_DISCOVERY";
  const hardAction = clean(economic?.nextEconomicAction, 160) || "OBSERVE";
  const conversionLocked = revenueMode === "CONVERSION_FIRST" || CONVERSION_LOCKED_PHASES.has(phase);

  const decisionRaw = clean(cognitive?.decision, 40);
  const decision = SAFE_DECISIONS.has(decisionRaw) ? decisionRaw : "hold";
  const productFocus = safeProduct(cognitive?.product);
  const priorityRaw = clean(cognitive?.priority, 30);
  const priority = SAFE_PRIORITIES.has(priorityRaw) ? priorityRaw : "medium";
  const confidence = Number(clamp(cognitive?.confidence, 0, 1).toFixed(4));

  const cognitiveSupportsExploration = Boolean(productFocus)
    && ["contact", "research", "prioritize"].includes(decision)
    && confidence >= 0.45;
  const b2bDiscoveryBoost = !conversionLocked && cognitiveSupportsExploration;

  return {
    version: COGNITIVE_ECONOMIC_OPERATOR_VERSION,
    mode: conversionLocked ? "CONVERSION_GUARD" : "COGNITIVE_ADVISORY",
    phase,
    revenueMode,
    hardEconomicAction: hardAction,
    hardEconomicActionPreserved: true,
    cognitiveDecision: decision,
    productFocus,
    priority,
    confidence,
    b2bDiscoveryBoost,
    externalCommercialAction: hardAction,
    rationale: conversionLocked
      ? "Qualified conversion inventory remains authoritative; cognition is observation-only for discovery allocation."
      : b2bDiscoveryBoost
        ? "Cognitive evidence may increase reversible B2B sensing for the selected product family."
        : "No sufficiently strong safe cognitive signal; preserve the existing economic cadence.",
    authority: cognitiveEconomicOperatorPolicy().authority,
  };
}

function inferCurrentProduct(economic) {
  const direct = safeProduct(economic?.portfolio?.topCandidate?.product_slug || economic?.portfolio?.topCandidate?.product);
  if (direct) return direct;
  for (const offer of Array.isArray(economic?.revenueDirector?.preferredOffers) ? economic.revenueDirector.preferredOffers : []) {
    const candidate = safeProduct(typeof offer === "string" ? offer : offer?.product_slug || offer?.product);
    if (candidate) return candidate;
  }
  return null;
}

async function askCognitiveWorker(env, economic) {
  if (!env?.COGNITIVE || typeof env.COGNITIVE.fetch !== "function") {
    throw new Error("cognitive_service_binding_unavailable");
  }
  const body = {
    task: "director",
    subject: {
      current_product: inferCurrentProduct(economic),
      economic_phase: clean(economic?.phase, 80),
      next_economic_action: clean(economic?.nextEconomicAction, 160),
    },
    context: compactEconomicContext(economic),
    technical_canary: false,
  };
  const response = await env.COGNITIVE.fetch(new Request("https://lumen.internal/decide", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  }));
  if (!response?.ok) throw new Error(`cognitive_http_${response?.status || 0}`);
  const result = await response.json();
  if (!result || typeof result !== "object") throw new Error("cognitive_invalid_response");
  return result;
}

function deterministicFallback(economic, error = null) {
  return {
    id: null,
    provider: "economic_guardrail",
    model: null,
    decision: "hold",
    product: inferCurrentProduct(economic),
    priority: economic?.revenueFocus?.mode === "CONVERSION_FIRST" ? "high" : "medium",
    confidence: 0.5,
    reasons: [error ? `Cognitive worker unavailable: ${clean(error, 120)}` : "Deterministic economic guardrail fallback."],
    next_action: clean(economic?.nextEconomicAction, 220) || "Preserve current economic cadence.",
    actions_executed: false,
    outgoing_spend_enabled: false,
    governor_required: true,
  };
}

async function ensureSchema(env) {
  if (!env?.DB) return;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_cognitive_operator_state (id TEXT PRIMARY KEY, updated_at TEXT NOT NULL, version TEXT NOT NULL, phase TEXT NOT NULL, hard_action TEXT NOT NULL, provider TEXT NOT NULL, cognitive_decision TEXT NOT NULL, product_focus TEXT, priority TEXT NOT NULL, confidence REAL NOT NULL DEFAULT 0, mode TEXT NOT NULL, plan_json TEXT NOT NULL, economic_snapshot_json TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_cognitive_operator_history (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, version TEXT NOT NULL, phase TEXT NOT NULL, hard_action TEXT NOT NULL, provider TEXT NOT NULL, cognitive_decision TEXT NOT NULL, product_focus TEXT, priority TEXT NOT NULL, confidence REAL NOT NULL DEFAULT 0, mode TEXT NOT NULL, plan_json TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_cognitive_operator_history_created ON lumen_cognitive_operator_history(created_at)"),
  ]);
}

async function persistSupervisorState(env, economic, cognitive, plan) {
  if (!env?.DB) return { persisted: false, reason: "db_unavailable" };
  await ensureSchema(env);
  const now = new Date().toISOString();
  const historyId = `COGOP-${crypto.randomUUID().replaceAll("-", "").slice(0, 20).toUpperCase()}`;
  const provider = clean(cognitive?.provider, 80) || "unknown";
  const planJson = JSON.stringify(plan).slice(0, 12000);
  const economicJson = JSON.stringify(compactEconomicContext(economic)).slice(0, 16000);

  await env.DB.prepare(`INSERT INTO lumen_cognitive_operator_state
    (id,updated_at,version,phase,hard_action,provider,cognitive_decision,product_focus,priority,confidence,mode,plan_json,economic_snapshot_json)
    VALUES('GLOBAL',?,?,?,?,?,?,?,?,?,?,?,?)
    ON CONFLICT(id) DO UPDATE SET
      updated_at=excluded.updated_at, version=excluded.version, phase=excluded.phase,
      hard_action=excluded.hard_action, provider=excluded.provider, cognitive_decision=excluded.cognitive_decision,
      product_focus=excluded.product_focus, priority=excluded.priority, confidence=excluded.confidence,
      mode=excluded.mode, plan_json=excluded.plan_json, economic_snapshot_json=excluded.economic_snapshot_json`)
    .bind(
      now,
      COGNITIVE_ECONOMIC_OPERATOR_VERSION,
      plan.phase,
      plan.hardEconomicAction,
      provider,
      plan.cognitiveDecision,
      plan.productFocus,
      plan.priority,
      plan.confidence,
      plan.mode,
      planJson,
      economicJson,
    ).run();

  await env.DB.prepare(`INSERT INTO lumen_cognitive_operator_history
    (id,created_at,version,phase,hard_action,provider,cognitive_decision,product_focus,priority,confidence,mode,plan_json)
    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)`)
    .bind(
      historyId,
      now,
      COGNITIVE_ECONOMIC_OPERATOR_VERSION,
      plan.phase,
      plan.hardEconomicAction,
      provider,
      plan.cognitiveDecision,
      plan.productFocus,
      plan.priority,
      plan.confidence,
      plan.mode,
      planJson,
    ).run();

  try {
    await env.DB.prepare(`DELETE FROM lumen_cognitive_operator_history WHERE created_at < datetime('now','-${MAX_HISTORY_DAYS} days')`).run();
  } catch {}
  return { persisted: true, historyId, updatedAt: now };
}

async function readSupervisorState(env) {
  if (!env?.DB) return null;
  await ensureSchema(env);
  const row = await env.DB.prepare("SELECT updated_at,version,phase,hard_action,provider,cognitive_decision,product_focus,priority,confidence,mode,plan_json,economic_snapshot_json FROM lumen_cognitive_operator_state WHERE id='GLOBAL' LIMIT 1").first();
  if (!row) return null;
  let plan = null;
  let economicSnapshot = null;
  try { plan = JSON.parse(row.plan_json || "null"); } catch {}
  try { economicSnapshot = JSON.parse(row.economic_snapshot_json || "null"); } catch {}
  return {
    updatedAt: row.updated_at || null,
    version: row.version || COGNITIVE_ECONOMIC_OPERATOR_VERSION,
    phase: row.phase || null,
    hardEconomicAction: row.hard_action || null,
    provider: row.provider || null,
    cognitiveDecision: row.cognitive_decision || null,
    productFocus: row.product_focus || null,
    priority: row.priority || null,
    confidence: num(row.confidence),
    mode: row.mode || null,
    plan,
    economicSnapshot,
  };
}

export async function runCognitiveEconomicSupervisor(env) {
  const economic = await computeEconomicOperatorState(env);
  let cognitive;
  let cognitiveError = null;
  try {
    cognitive = await askCognitiveWorker(env, economic);
  } catch (error) {
    cognitiveError = clean(error?.message || error, 160) || "cognitive_unavailable";
    cognitive = deterministicFallback(economic, cognitiveError);
  }

  const plan = deriveCognitivePlan(economic, cognitive);
  let persistence;
  try {
    persistence = await persistSupervisorState(env, economic, cognitive, plan);
  } catch (error) {
    persistence = { persisted: false, reason: clean(error?.message || error, 180) || "persistence_failed" };
  }

  return {
    ok: true,
    version: COGNITIVE_ECONOMIC_OPERATOR_VERSION,
    status: cognitiveError ? "degraded_deterministic_fallback" : "active",
    cognitiveProvider: clean(cognitive?.provider, 80) || "unknown",
    cognitiveDecisionId: clean(cognitive?.id, 120) || null,
    cognitiveError,
    plan,
    persistence,
    actionsExecutedBySupervisor: false,
    externalMessagesCreated: false,
    outgoingSpendEnabled: false,
    bindingAuthorityChanged: false,
  };
}

function adminAuthorized(request, env) {
  const expected = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const supplied = clean(request.headers.get("x-lumen-admin"), 500);
  return Boolean(expected) && supplied === expected;
}

export async function handleCognitiveEconomicOperator(request, env) {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/cognitive-operator/policy") {
    return json(cognitiveEconomicOperatorPolicy());
  }
  if (request.method === "GET" && url.pathname === "/cognitive-operator/state") {
    try {
      const state = await readSupervisorState(env);
      return json({
        ok: true,
        version: COGNITIVE_ECONOMIC_OPERATOR_VERSION,
        initialized: Boolean(state),
        state,
        policy: cognitiveEconomicOperatorPolicy(),
      });
    } catch (error) {
      return json({ ok: false, error: clean(error?.message || error, 180) || "state_read_failed" }, 500);
    }
  }
  if (request.method === "POST" && url.pathname === "/cognitive-operator/run") {
    if (!clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500)) return json({ ok: false, error: "admin_not_configured" }, 503);
    if (!adminAuthorized(request, env)) return json({ ok: false, error: "unauthorized" }, 401);
    try {
      return json(await runCognitiveEconomicSupervisor(env));
    } catch (error) {
      return json({ ok: false, error: clean(error?.message || error, 180) || "cognitive_supervisor_failed" }, 500);
    }
  }
  return null;
}
