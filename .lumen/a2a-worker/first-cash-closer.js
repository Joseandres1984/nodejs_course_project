import { buildTrackedCheckoutUrl } from "./commercial-checkout-link.js";
import { classifyCommercialResponse } from "./response-qualification.js";

const VERSION = "1.2-intramodule-first-cash-evolution";
const SEND_TIMEOUT_MS = 15000;
const FAST_LANE_VERSION = "1.1-learning-first-settlement-fast-lane";
const EVOLUTION_VERSION = "1.0-intramodule-first-cash-evolution";
const FAST_LANE_PRIORITY = {
  "MP-QUOTE-SANITY": 100,
  "MP-SUPPLIER-SNAPSHOT": 90,
  "MP-TENDER-SCAN": 80,
  "MP-SOURCING-5": 60,
  "MP-BUYER-SIGNALS": 50,
  "MP-EXPORT-PULSE": 40
};
const CLOSER_VARIANTS = [
  { id: "direct_checkout", description: "Lead with fixed price and exact checkout." },
  { id: "scope_reassurance", description: "Reassure scope and non-binding terms before checkout." },
  { id: "intent_mirror", description: "Mirror the buyer's positive intent before giving the exact checkout." }
];

function json(data, status = 200) {
  return Response.json(data, { status, headers: { "cache-control": "no-store", "x-content-type-options": "nosniff", "access-control-allow-origin": "*" } });
}
function clean(value, limit = 6000) { return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit); }
function boolVar(value, fallback = false) {
  const v = clean(value, 20).toLowerCase();
  if (!v) return fallback;
  return ["1", "true", "yes", "on"].includes(v);
}
function authorized(request, env) {
  const configured = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const provided = clean(request.headers.get("x-lumen-admin"), 500);
  return Boolean(configured && provided && configured === provided);
}
function isHttps(value) { try { return new URL(value).protocol === "https:"; } catch { return false; } }
function withTimeout(ms) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort("timeout"), ms);
  return { signal: controller.signal, clear: () => clearTimeout(timer) };
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_first_cash_closer (proposal_id TEXT PRIMARY KEY,opportunity_id TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,status TEXT NOT NULL,response_class TEXT NOT NULL,checkout_url TEXT,task_id TEXT,context_id TEXT,response_text TEXT,error TEXT,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_first_cash_closer_status ON lumen_first_cash_closer(status,updated_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_first_cash_strategy_assignments (proposal_id TEXT PRIMARY KEY,offer_id TEXT NOT NULL,strategy_id TEXT NOT NULL,response_class TEXT NOT NULL,created_at TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_first_cash_strategy_assignments_strategy ON lumen_first_cash_strategy_assignments(strategy_id,created_at)")
  ]);
  return true;
}

async function candidateRows(env) {
  const primary = `SELECT p.proposal_id,p.opportunity_id,p.offer_id,p.offer_name,p.amount_usd,p.message,p.quality_gate_status,
    o.name AS target,x.agent_url,x.protocol_binding,x.protocol_version,x.context_id,
    COALESCE((SELECT f.response_text FROM lumen_followups f WHERE f.proposal_id=p.proposal_id AND f.response_text IS NOT NULL AND TRIM(f.response_text)<>'' ORDER BY COALESCE(f.sent_at,f.updated_at) DESC LIMIT 1),x.response_text) AS response_text
    FROM lumen_proposal_drafts p
    JOIN lumen_opportunities o ON o.id=p.opportunity_id
    JOIN lumen_outreach_attempts x ON x.proposal_id=p.proposal_id
    LEFT JOIN lumen_first_cash_closer c ON c.proposal_id=p.proposal_id
    WHERE p.quality_gate_status='PASS' AND c.proposal_id IS NULL AND x.agent_url IS NOT NULL
      AND (x.response_text IS NOT NULL OR EXISTS(SELECT 1 FROM lumen_followups f2 WHERE f2.proposal_id=p.proposal_id AND f2.response_text IS NOT NULL AND TRIM(f2.response_text)<>''))
    ORDER BY x.updated_at DESC LIMIT 100`;
  try { const r = await env.DB.prepare(primary).all(); return r.results || []; } catch {}

  const fallback = `SELECT p.proposal_id,p.opportunity_id,p.offer_id,p.offer_name,p.amount_usd,p.message,p.quality_gate_status,
    o.name AS target,x.agent_url,x.protocol_binding,x.protocol_version,x.context_id,x.response_text
    FROM lumen_proposal_drafts p
    JOIN lumen_opportunities o ON o.id=p.opportunity_id
    JOIN lumen_outreach_attempts x ON x.proposal_id=p.proposal_id
    LEFT JOIN lumen_first_cash_closer c ON c.proposal_id=p.proposal_id
    WHERE p.quality_gate_status='PASS' AND c.proposal_id IS NULL AND x.agent_url IS NOT NULL AND x.response_text IS NOT NULL
    ORDER BY x.updated_at DESC LIMIT 100`;
  try { const r = await env.DB.prepare(fallback).all(); return r.results || []; } catch { return []; }
}

async function offerOutcomeMap(env) {
  const map = new Map();
  try {
    const result = await env.DB.prepare("SELECT offer_id,COUNT(DISTINCT receipt_id) AS settlements,COALESCE(SUM(amount_usd),0) AS revenue_usd FROM lumen_x402_revenue_bridge GROUP BY offer_id").all();
    for (const row of result.results || []) map.set(clean(row.offer_id, 100), { settlements: Number(row.settlements || 0), revenueUsd: Number(row.revenue_usd || 0) });
  } catch {}
  return map;
}

async function findEligibleCandidate(env) {
  const rows = await candidateRows(env);
  const outcomes = await offerOutcomeMap(env);
  const eligible = [];
  for (const row of rows) {
    const qualification = classifyCommercialResponse(row.response_text, row.message);
    const closeEligible = ["PURCHASE_INTENT", "COMMERCIAL_INTEREST"].includes(qualification.responseClass);
    if (!closeEligible) continue;
    const checkoutUrl = buildTrackedCheckoutUrl(env, {
      offerId: row.offer_id,
      proposalId: row.proposal_id,
      opportunityId: row.opportunity_id,
      source: "lumen_a2a",
      medium: "first_cash_closer",
      creative: qualification.responseClass.toLowerCase()
    });
    if (!checkoutUrl || !isHttps(row.agent_url)) continue;
    const offerId = clean(row.offer_id, 100);
    const basePriority = FAST_LANE_PRIORITY[offerId] || 0;
    const outcome = outcomes.get(offerId) || { settlements: 0, revenueUsd: 0 };
    const verifiedOutcomeBoost = outcome.settlements * 1000 + outcome.revenueUsd * 20;
    const intentBoost = qualification.responseClass === "PURCHASE_INTENT" ? 120 : 40;
    eligible.push({
      ...row,
      responseClass: qualification.responseClass,
      qualificationReason: qualification.reason,
      checkoutUrl,
      fastLanePriority: basePriority,
      verifiedSettlements: outcome.settlements,
      verifiedRevenueUsd: outcome.revenueUsd,
      learnedPriority: basePriority + verifiedOutcomeBoost + intentBoost
    });
  }
  eligible.sort((a, b) => Number(b.learnedPriority || 0) - Number(a.learnedPriority || 0) || Number(b.fastLanePriority || 0) - Number(a.fastLanePriority || 0));
  return eligible[0] || null;
}

async function closerVariantStats(env) {
  const empty = CLOSER_VARIANTS.map(v => ({ ...v, assignments: 0, responses: 0, settlements: 0, revenueUsd: 0, reward: 0, exploration: 0, score: 0 }));
  try {
    const result = await env.DB.prepare(`SELECT a.strategy_id,
      COUNT(DISTINCT a.proposal_id) AS assignments,
      COUNT(DISTINCT CASE WHEN c.status='RESPONDED' THEN a.proposal_id END) AS responses,
      COUNT(DISTINCT b.receipt_id) AS settlements,
      COALESCE(SUM(b.amount_usd),0) AS revenue_usd
      FROM lumen_first_cash_strategy_assignments a
      LEFT JOIN lumen_first_cash_closer c ON c.proposal_id=a.proposal_id
      LEFT JOIN lumen_x402_revenue_bridge b ON b.proposal_id=a.proposal_id
      GROUP BY a.strategy_id`).all();
    const rows = result.results || [];
    const byId = new Map(rows.map(row => [clean(row.strategy_id, 80), row]));
    const totalAssignments = rows.reduce((sum, row) => sum + Number(row.assignments || 0), 0);
    return CLOSER_VARIANTS.map(variant => {
      const row = byId.get(variant.id) || {};
      const assignments = Number(row.assignments || 0);
      const responses = Number(row.responses || 0);
      const settlements = Number(row.settlements || 0);
      const revenueUsd = Number(row.revenue_usd || 0);
      const reward = settlements * 10000 + revenueUsd * 100 + responses * 10;
      const exploration = 40 * Math.sqrt(Math.log(totalAssignments + 2) / (assignments + 1));
      return { ...variant, assignments, responses, settlements, revenueUsd, reward, exploration, score: reward + exploration };
    });
  } catch {
    return empty;
  }
}

async function selectCloserVariant(env, proposalId) {
  try {
    const prior = await env.DB.prepare("SELECT strategy_id FROM lumen_first_cash_strategy_assignments WHERE proposal_id=? LIMIT 1").bind(proposalId).first();
    if (prior?.strategy_id && CLOSER_VARIANTS.some(v => v.id === prior.strategy_id)) {
      const stats = await closerVariantStats(env);
      return { variantId: prior.strategy_id, reason: "stable_existing_assignment", stats };
    }
  } catch {}
  const stats = await closerVariantStats(env);
  const minimumAssignments = Math.min(...stats.map(s => s.assignments));
  const selected = [...stats].sort((a,b) => {
    if (minimumAssignments < 2 && a.assignments !== b.assignments) return a.assignments - b.assignments;
    return b.score - a.score || a.assignments - b.assignments || a.id.localeCompare(b.id);
  })[0] || { id: "direct_checkout" };
  return { variantId: selected.id, reason: selected.assignments < 2 ? "bounded_exploration" : "verified_outcome_exploitation", stats };
}

function closerMessage(row, variantId = "direct_checkout") {
  const offer = clean(row.offer_name, 140) || "this LUMEN service";
  const amount = Number(row.amount_usd || 0);
  const checkout = `Direct x402 checkout for this exact offer: ${row.checkoutUrl}`;
  const price = `The exact price is USD ${amount.toFixed(2)} per request.`;
  const disclosure = "No subscription, contract or additional commitment is created by this message. A purchase only occurs if the buyer signs the x402 payment authorization and settlement succeeds.";
  const scope = "If you want the scope clarified before paying, reply with the requirement and LUMEN can confirm the deliverable.";
  if (variantId === "scope_reassurance") {
    return clean([`Thanks for the interest in ${offer}.`, scope, price, disclosure, checkout].join("\n\n"), 2400);
  }
  if (variantId === "intent_mirror") {
    const mirrored = row.responseClass === "PURCHASE_INTENT"
      ? `Your reply indicates purchase intent for ${offer}.`
      : `Your reply indicates commercial interest in ${offer}.`;
    return clean([mirrored, price, checkout, disclosure, scope].join("\n\n"), 2400);
  }
  return clean([
    `Thanks for the interest in ${offer}.`,
    price,
    checkout,
    disclosure,
    scope
  ].join("\n\n"), 2400);
}

function envelope(row, text) {
  const id = `lumen-close-${crypto.randomUUID()}`;
  const version = clean(row.protocol_version, 20) || "0.3.0";
  const isV1 = version.startsWith("1.");
  const message = { messageId: id, role: isV1 ? "ROLE_USER" : "user", parts: [{ text }] };
  const metadata = {
    lumen: {
      proposalId: row.proposal_id,
      opportunityId: row.opportunity_id,
      offerId: row.offer_id,
      amountUsd: Number(row.amount_usd || 0),
      stage: "first_cash_close",
      checkoutUrl: row.checkoutUrl,
      intramoduleEvolution: { version: EVOLUTION_VERSION, strategyId: row.closerVariant || "direct_checkout" }
    }
  };
  if (clean(row.protocol_binding, 40).toUpperCase() === "HTTP+JSON") {
    return {
      url: `${clean(row.agent_url, 1000).replace(/\/$/, "")}/message:send`,
      headers: { "content-type": "application/a2a+json", "accept": "application/a2a+json, application/json", "a2a-version": version },
      payload: { message, metadata }
    };
  }
  return {
    url: row.agent_url,
    headers: { "content-type": "application/json", "accept": "application/json", "a2a-version": version },
    payload: { jsonrpc: "2.0", id, method: isV1 ? "SendMessage" : "message/send", params: { message, metadata } }
  };
}

function extractResponse(body, binding) {
  const value = clean(binding, 40).toUpperCase() === "JSONRPC" ? (body?.result || body || {}) : (body || {});
  const task = value?.task || (value?.id && value?.status ? value : null);
  const message = value?.message || null;
  const parts = message?.parts || task?.status?.message?.parts || task?.artifacts?.flatMap?.(a => a?.parts || []) || [];
  return {
    taskId: clean(task?.id, 300) || null,
    contextId: clean(task?.contextId, 300) || clean(message?.contextId, 300) || null,
    responseText: clean((Array.isArray(parts) ? parts : []).map(p => p?.text || "").filter(Boolean).join(" "), 5000) || null
  };
}

async function record(env, row, values) {
  const now = new Date().toISOString();
  await env.DB.prepare("INSERT INTO lumen_first_cash_closer(proposal_id,opportunity_id,created_at,updated_at,status,response_class,checkout_url,task_id,context_id,response_text,error,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(proposal_id) DO UPDATE SET updated_at=excluded.updated_at,status=excluded.status,response_class=excluded.response_class,checkout_url=excluded.checkout_url,task_id=excluded.task_id,context_id=excluded.context_id,response_text=excluded.response_text,error=excluded.error,engine_version=excluded.engine_version")
    .bind(row.proposal_id,row.opportunity_id,now,now,values.status,row.responseClass,row.checkoutUrl,values.taskId||null,values.contextId||null,values.responseText||null,values.error||null,VERSION).run();
}

async function assignCloserVariant(env, row, variantId) {
  const now = new Date().toISOString();
  await env.DB.prepare("INSERT INTO lumen_first_cash_strategy_assignments(proposal_id,offer_id,strategy_id,response_class,created_at,engine_version) VALUES(?,?,?,?,?,?) ON CONFLICT(proposal_id) DO UPDATE SET engine_version=excluded.engine_version")
    .bind(row.proposal_id, clean(row.offer_id, 100), variantId, row.responseClass, now, EVOLUTION_VERSION).run();
}

export async function runFirstCashCloser(env, { force = false } = {}) {
  if (!(await ensureSchema(env))) return { ok: false, sent: false, error: "persistence_unavailable", version: VERSION };
  const candidate = await findEligibleCandidate(env);
  if (!candidate) return { ok: true, sent: false, reason: "no_verified_commercial_intent", version: VERSION };

  const evolution = await selectCloserVariant(env, candidate.proposal_id);
  candidate.closerVariant = evolution.variantId;
  await assignCloserVariant(env, candidate, evolution.variantId);

  const enabled = boolVar(env?.A2A_AUTONOMOUS_OUTREACH, false) && boolVar(env?.A2A_AUTONOMOUS_CONVERSION_CLOSE, false);
  if (!force && !enabled) {
    return {
      ok: true,
      sent: false,
      ready: true,
      proposalId: candidate.proposal_id,
      responseClass: candidate.responseClass,
      reason: "autonomous_conversion_close_disabled",
      version: VERSION,
      evolution: { version: EVOLUTION_VERSION, strategyId: evolution.variantId, selectionReason: evolution.reason }
    };
  }

  const text = closerMessage(candidate, evolution.variantId);
  const req = envelope(candidate, text);
  const timeout = withTimeout(SEND_TIMEOUT_MS);
  let raw = "";
  try {
    const response = await fetch(req.url, { method: "POST", headers: req.headers, body: JSON.stringify(req.payload), signal: timeout.signal });
    raw = await response.text();
    if (!response.ok) throw new Error(`first_cash_close_http_${response.status}`);
    let body = {}; try { body = JSON.parse(raw); } catch {}
    const info = extractResponse(body, candidate.protocol_binding);
    const status = info.responseText ? "RESPONDED" : info.taskId ? "SENT_TASK" : "SENT";
    await record(env, candidate, { status, ...info });
    const selectedStats = evolution.stats.find(s => s.id === evolution.variantId) || null;
    return {
      ok: true,
      sent: true,
      version: VERSION,
      proposalId: candidate.proposal_id,
      opportunityId: candidate.opportunity_id,
      offerId: candidate.offer_id,
      amountUsd: Number(candidate.amount_usd || 0),
      responseClass: candidate.responseClass,
      qualificationReason: candidate.qualificationReason,
      status,
      taskId: info.taskId,
      checkoutUrl: candidate.checkoutUrl,
      fastLane: {
        version: FAST_LANE_VERSION,
        basePriority: candidate.fastLanePriority,
        learnedPriority: candidate.learnedPriority,
        verifiedSettlements: candidate.verifiedSettlements,
        verifiedRevenueUsd: candidate.verifiedRevenueUsd,
        objective: "first_verified_settlement_then_repeat_verified_winners"
      },
      evolution: {
        version: EVOLUTION_VERSION,
        strategyId: evolution.variantId,
        selectionReason: evolution.reason,
        strategySettlements: Number(selectedStats?.settlements || 0),
        strategyRevenueUsd: Number(selectedStats?.revenueUsd || 0),
        selfModifyingCode: false,
        priceMutation: false
      },
      guardrails: { positiveIntentRequired: true, sharedResponseQualification: true, exactOfferCheckout: true, autonomousDiscounting: false, autonomousSpend: false, autonomousContract: false, maxExternalMessagesPerRun: 1, bindingActionsHumanGated: true }
    };
  } catch (error) {
    const err = clean(error?.message || error, 500);
    await record(env, candidate, { status: "SEND_FAILED", error: err });
    return { ok: false, sent: false, version: VERSION, proposalId: candidate.proposal_id, status: "SEND_FAILED", error: err, evolution: { version: EVOLUTION_VERSION, strategyId: evolution.variantId } };
  } finally { timeout.clear(); }
}

async function statsData(env) {
  await ensureSchema(env);
  let row = null;
  try { row = await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN status IN ('SENT','SENT_TASK','RESPONDED') THEN 1 ELSE 0 END) sent,SUM(CASE WHEN status='RESPONDED' THEN 1 ELSE 0 END) responded,SUM(CASE WHEN status='SEND_FAILED' THEN 1 ELSE 0 END) failed FROM lumen_first_cash_closer").first(); } catch {}
  const candidate = await findEligibleCandidate(env);
  const variants = await closerVariantStats(env);
  const ranked = [...variants].sort((a,b) => b.settlements - a.settlements || b.revenueUsd - a.revenueUsd || b.responses - a.responses || b.score - a.score);
  return {
    total: Number(row?.total || 0),
    sent: Number(row?.sent || 0),
    responded: Number(row?.responded || 0),
    failed: Number(row?.failed || 0),
    readyToClose: Boolean(candidate),
    readyProposalId: candidate?.proposal_id || null,
    readyResponseClass: candidate?.responseClass || null,
    readyLearnedPriority: Number(candidate?.learnedPriority || 0),
    championStrategy: ranked[0]?.id || null,
    strategyStats: ranked.map(({ id, assignments, responses, settlements, revenueUsd, score }) => ({ id, assignments, responses, settlements, revenueUsd, score })),
    autonomousEnabled: boolVar(env?.A2A_AUTONOMOUS_OUTREACH, false) && boolVar(env?.A2A_AUTONOMOUS_CONVERSION_CLOSE, false)
  };
}

export async function handleFirstCashCloser(request, env) {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/first-cash/policy") {
    return json({
      version: VERSION,
      fastLaneVersion: FAST_LANE_VERSION,
      evolutionVersion: EVOLUTION_VERSION,
      name: "LUMEN First Cash Closer",
      positiveIntentRequired: true,
      sharedResponseQualification: true,
      checkoutEligibleClasses:["PURCHASE_INTENT","COMMERCIAL_INTEREST"],
      technicalAckIsNotIntent: true,
      echoIsNotIntent:true,
      genericResponseIsNotIntent:true,
      exactOfferCheckout: true,
      trackedAttribution: true,
      intramoduleEvolution: {
        enabled: true,
        boundedVariants: CLOSER_VARIANTS.map(v => v.id),
        rewardOrder: ["verified_settlement", "verified_revenue", "qualified_response", "bounded_exploration"],
        offerPriorityLearnsFromVerifiedSettlements: true,
        championChallenger: true,
        selfModifyingCode: false,
        mutatesPrice: false,
        mutatesAuthority: false
      },
      fastLane: { enabled: true, objective: "first_verified_settlement_then_repeat_verified_winners", priorityOrder: Object.keys(FAST_LANE_PRIORITY), learnedOutcomeBoost: true, maxExternalMessagesPerRun: 1 },
      maxExternalMessagesPerRun: 1,
      autonomousDiscounting: false,
      autonomousSpend: false,
      autonomousContract: false,
      bindingActionsHumanGated: true
    });
  }
  if (request.method === "GET" && url.pathname === "/first-cash/stats") return json({ version: VERSION, ...await statsData(env) });
  if (request.method === "POST" && url.pathname === "/first-cash/run") {
    if (!authorized(request, env)) return json({ ok: false, error: "admin_token_required" }, 403);
    return json(await runFirstCashCloser(env, { force: false }), 202);
  }
  return null;
}
