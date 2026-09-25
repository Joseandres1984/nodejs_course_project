const VERSION = "1.1-microbuyer-commercial-intelligence";

const HARD_TEST_PHRASES = [
  "paper-only",
  "paper only",
  "synthetic purchase",
  "synthetic demand",
  "synthetic transaction",
  "mock purchase",
  "mock transaction",
  "no live commerce",
  "no payment",
  "no wallet",
  "no signing",
  "testnet only",
  "sandbox only",
  "demo only",
  "simulation only"
];

const SOFT_TEST_PHRASES = [
  "trial",
  "prototype",
  "proof of concept",
  "proof-of-concept",
  "demo",
  "sandbox",
  "sample",
  "benchmark",
  "experiment",
  "testing",
  "test agent"
];

const HIGH_INTENT_PHRASES = [
  "request for quote",
  "rfq",
  "request a quote",
  "seeking supplier",
  "looking for supplier",
  "looking to buy",
  "ready to buy",
  "purchase order",
  "procurement request",
  "buyer intent",
  "buying intent",
  "tender",
  "bid deadline",
  "quantity",
  "budget",
  "paid",
  "payment",
  "invoice"
];

const COMMERCIAL_CONTEXT_PHRASES = [
  "buyer",
  "supplier",
  "vendor",
  "procurement",
  "sourcing",
  "purchase",
  "b2b",
  "commerce",
  "importer",
  "distributor",
  "export",
  "quote",
  "pricing"
];

// FIRST CASH does not treat x402 support by itself as purchase intent. A
// microbuyer fit exists only when a machine-payment compatibility signal is
// combined with a concrete information/research need that LUMEN can service.
const MICROBUYER_COMPAT_PHRASES = [
  "x402",
  "http 402",
  "payment-required",
  "payment required",
  "pay per request",
  "per-request",
  "per request",
  "usdc",
  "machine-to-machine",
  "machine to machine",
  "agent marketplace",
  "api marketplace",
  "a2a agent",
  "agent-to-agent",
  "mcp"
];

const MICROBUYER_NEED_PHRASES = [
  "supplier",
  "sourcing",
  "vendor",
  "procurement",
  "company",
  "domain",
  "counterparty",
  "due diligence",
  "research",
  "verification",
  "verify",
  "identity",
  "official channel",
  "market intelligence",
  "quotation",
  "quote",
  "tender"
];

function json(data, status = 200) {
  return Response.json(data, {
    status,
    headers: {
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "access-control-allow-origin": "*"
    }
  });
}

function clean(value, limit = 5000) {
  return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit);
}

function safeParse(value, fallback = {}) {
  try { return JSON.parse(value || ""); } catch { return fallback; }
}

function countHits(text, phrases) {
  return phrases.filter(phrase => text.includes(phrase)).length;
}

function opportunityText(row) {
  const raw = safeParse(row?.raw_json, {});
  return clean([
    row?.name,
    row?.description,
    row?.remote_id,
    row?.evidence,
    raw?.name,
    raw?.description,
    raw?.summary,
    raw?.message,
    raw?.text,
    ...(Array.isArray(raw?.tags) ? raw.tags : [])
  ].filter(Boolean).join(" "), 18000).toLowerCase();
}

export function assessCommercialOpportunity(row) {
  const text = opportunityText(row);
  const reasons = [];
  const hardTestHits = countHits(text, HARD_TEST_PHRASES);
  const softTestHits = countHits(text, SOFT_TEST_PHRASES);
  const intentHits = countHits(text, HIGH_INTENT_PHRASES);
  const contextHits = countHits(text, COMMERCIAL_CONTEXT_PHRASES);
  const microbuyerCompatHits = countHits(text, MICROBUYER_COMPAT_PHRASES);
  const microbuyerNeedHits = countHits(text, MICROBUYER_NEED_PHRASES);
  const microbuyerFit = microbuyerCompatHits > 0 && microbuyerNeedHits > 0;

  let score = Math.min(70, Math.max(0, Number(row?.score || 0)));

  if (Number(row?.demand_signal || 0) === 1) {
    score += 10;
    reasons.push("base_demand_signal");
  }
  if (row?.endpoint) {
    score += 4;
    reasons.push("reachable_endpoint");
  }
  if (intentHits) {
    score += Math.min(28, intentHits * 7);
    reasons.push(`high_intent:${intentHits}`);
  }
  if (contextHits) {
    score += Math.min(12, contextHits * 2);
    reasons.push(`commercial_context:${contextHits}`);
  }
  if (microbuyerCompatHits) reasons.push(`microbuyer_compat:${microbuyerCompatHits}`);
  if (microbuyerNeedHits) reasons.push(`microbuyer_need:${microbuyerNeedHits}`);
  if (microbuyerFit) {
    score += 20;
    reasons.push("microbuyer_fit");
  }
  if (hardTestHits) {
    score -= Math.min(70, hardTestHits * 24);
    reasons.push(`hard_test_only:${hardTestHits}`);
  }
  if (softTestHits) {
    score -= Math.min(30, softTestHits * 8);
    reasons.push(`soft_test_signal:${softTestHits}`);
  }

  const explicitNoCommerce = hardTestHits > 0;
  if (explicitNoCommerce) score = Math.min(score, 24);

  score = Math.max(0, Math.min(100, Math.round(score)));
  const fit = score >= 80 ? "A" : score >= 65 ? "B" : score >= 45 ? "C" : "D";
  const evidenceStrength = intentHits >= 3
    ? "strong"
    : (intentHits >= 1 || microbuyerFit)
      ? "medium"
      : Number(row?.demand_signal || 0) === 1
        ? "weak"
        : "none";
  const commerciallyActionable = !explicitNoCommerce && score >= 45 && Number(row?.demand_signal || 0) === 1;

  return {
    commercialScore: score,
    commercialFit: fit,
    evidenceStrength,
    commerciallyActionable,
    syntheticOrTestOnly: explicitNoCommerce,
    reasons,
    intentHits,
    contextHits,
    microbuyerCompatHits,
    microbuyerNeedHits,
    microbuyerFit,
    hardTestHits,
    softTestHits
  };
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_opportunity_assessments (opportunity_id TEXT PRIMARY KEY, assessed_at TEXT NOT NULL, commercial_score INTEGER NOT NULL, commercial_fit TEXT NOT NULL, evidence_strength TEXT NOT NULL, commercially_actionable INTEGER NOT NULL DEFAULT 0, synthetic_or_test_only INTEGER NOT NULL DEFAULT 0, reasons_json TEXT NOT NULL, engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_opportunity_assessments_rank ON lumen_opportunity_assessments(commercially_actionable,commercial_score,assessed_at)")
  ]);
  return true;
}

export async function runCommercialReassessment(env) {
  if (!(await ensureSchema(env))) return { ok: false, error: "persistence_unavailable" };
  const rows = await env.DB.prepare("SELECT id,name,description,remote_id,endpoint,evidence,score,fit,demand_signal,revenue_offer_id,status,raw_json FROM lumen_opportunities ORDER BY score DESC, updated_at DESC LIMIT 250").all();
  let assessed = 0;
  let actionable = 0;
  let testOnly = 0;
  let microbuyerFits = 0;
  const now = new Date().toISOString();

  for (const row of rows.results || []) {
    const a = assessCommercialOpportunity(row);
    await env.DB.prepare("INSERT INTO lumen_opportunity_assessments(opportunity_id,assessed_at,commercial_score,commercial_fit,evidence_strength,commercially_actionable,synthetic_or_test_only,reasons_json,engine_version) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(opportunity_id) DO UPDATE SET assessed_at=excluded.assessed_at,commercial_score=excluded.commercial_score,commercial_fit=excluded.commercial_fit,evidence_strength=excluded.evidence_strength,commercially_actionable=excluded.commercially_actionable,synthetic_or_test_only=excluded.synthetic_or_test_only,reasons_json=excluded.reasons_json,engine_version=excluded.engine_version")
      .bind(row.id, now, a.commercialScore, a.commercialFit, a.evidenceStrength, a.commerciallyActionable ? 1 : 0, a.syntheticOrTestOnly ? 1 : 0, JSON.stringify(a.reasons), VERSION).run();
    assessed += 1;
    if (a.commerciallyActionable) actionable += 1;
    if (a.syntheticOrTestOnly) testOnly += 1;
    if (a.microbuyerFit) microbuyerFits += 1;
  }

  return {
    ok: true,
    version: VERSION,
    assessed,
    actionable,
    testOnly,
    microbuyerFits,
    guardrails: {
      autonomousOutgoingSpend: false,
      autonomousPurchase: false,
      autonomousContract: false,
      autonomousOutreach: false,
      microbuyerCompatibilityAloneIsNotIntent: true,
      bindingActionsHumanGated: true
    }
  };
}

async function commercialStats(env) {
  await ensureSchema(env);
  const total = await env.DB.prepare("SELECT COUNT(*) AS n FROM lumen_opportunity_assessments").first();
  const actionable = await env.DB.prepare("SELECT COUNT(*) AS n FROM lumen_opportunity_assessments WHERE commercially_actionable=1").first();
  const testOnly = await env.DB.prepare("SELECT COUNT(*) AS n FROM lumen_opportunity_assessments WHERE synthetic_or_test_only=1").first();
  const high = await env.DB.prepare("SELECT COUNT(*) AS n FROM lumen_opportunity_assessments WHERE commercial_score>=65 AND synthetic_or_test_only=0").first();
  const microbuyers = await env.DB.prepare("SELECT COUNT(*) AS n FROM lumen_opportunity_assessments WHERE reasons_json LIKE '%microbuyer_fit%' AND synthetic_or_test_only=0").first();
  return json({
    version: VERSION,
    totalAssessed: Number(total?.n || 0),
    actionable: Number(actionable?.n || 0),
    filteredTestOnly: Number(testOnly?.n || 0),
    commercialScore65Plus: Number(high?.n || 0),
    microbuyerFits: Number(microbuyers?.n || 0),
    autonomousOutreach: false,
    autonomousOutgoingSpend: false
  });
}

export async function getBestCommercialOpportunity(env) {
  await ensureSchema(env);
  const row = await env.DB.prepare("SELECT o.id,o.name,o.description,o.remote_id,o.endpoint,o.evidence,o.score AS discovery_score,o.fit AS discovery_fit,o.demand_signal,o.revenue_offer_id,o.status,a.assessed_at,a.commercial_score,a.commercial_fit,a.evidence_strength,a.commercially_actionable,a.synthetic_or_test_only,a.reasons_json FROM lumen_opportunities o JOIN lumen_opportunity_assessments a ON a.opportunity_id=o.id WHERE a.commercially_actionable=1 AND a.synthetic_or_test_only=0 ORDER BY a.commercial_score DESC,o.score DESC,o.updated_at DESC LIMIT 1").first();
  if (!row) return null;
  return {
    ...row,
    reasons: safeParse(row.reasons_json, []),
    commercially_actionable: Boolean(row.commercially_actionable),
    synthetic_or_test_only: Boolean(row.synthetic_or_test_only)
  };
}

async function commercialNext(env) {
  const opportunity = await getBestCommercialOpportunity(env);
  return json({
    version: VERSION,
    opportunity,
    nextAction: opportunity ? "prepare_nonbinding_proposal_draft" : "wait_for_stronger_verified_demand",
    autonomousSend: false,
    guardrails: { autonomousOutgoingSpend: false, autonomousOutreach: false, bindingActionsHumanGated: true }
  });
}

async function manualReassess(request, env) {
  const configured = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const provided = clean(request.headers.get("x-lumen-admin"), 500);
  if (!configured || !provided || configured !== provided) return json({ ok: false, error: "admin_token_required" }, 403);
  return json(await runCommercialReassessment(env), 202);
}

export async function handleCommercialIntelligence(request, env) {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/commercial/stats") return commercialStats(env);
  if (request.method === "GET" && url.pathname === "/commercial/next") return commercialNext(env);
  if (request.method === "POST" && url.pathname === "/commercial/reassess") return manualReassess(request, env);
  return null;
}
