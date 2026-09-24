import { getBestCommercialOpportunity } from "./commercial-intelligence.js";

const VERSION = "1.0-nonbinding-proposal-engine";

const OFFERS = {
  "MP-SUPPLIER-SNAPSHOT": { name: "Supplier Snapshot", priceUsd: 5, outcome: "a compact supplier verification snapshot" },
  "MP-QUOTE-SANITY": { name: "Quote Sanity Check", priceUsd: 7, outcome: "a quick sanity check of pricing and quotation structure" },
  "MP-TENDER-SCAN": { name: "Tender Quick Scan", priceUsd: 9, outcome: "a focused scan of tender fit, deadlines and commercial relevance" },
  "MP-SOURCING-5": { name: "Supplier Shortlist 5", priceUsd: 15, outcome: "a shortlist of five relevant suppliers with evidence" },
  "MP-BUYER-SIGNALS": { name: "Buyer Signal Scan", priceUsd: 19, outcome: "an evidence-backed scan of buyer intent and demand signals" },
  "MP-EXPORT-PULSE": { name: "Export Market Pulse", priceUsd: 25, outcome: "a compact export-market demand and channel pulse" }
};

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

function clean(value, limit = 4000) {
  return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit);
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_proposal_drafts (opportunity_id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, status TEXT NOT NULL, offer_id TEXT NOT NULL, offer_name TEXT NOT NULL, amount_usd REAL NOT NULL, subject TEXT NOT NULL, message TEXT NOT NULL, quality_gate_status TEXT NOT NULL, autonomous_send INTEGER NOT NULL DEFAULT 0, metadata_json TEXT)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_proposal_drafts_status ON lumen_proposal_drafts(status,updated_at)")
  ]);
  return true;
}

function makeDraft(opportunity) {
  const offer = OFFERS[opportunity.revenue_offer_id] || OFFERS["MP-BUYER-SIGNALS"];
  const target = clean(opportunity.name || opportunity.remote_id, 180);
  const evidence = clean(opportunity.description, 360);
  const subject = `Possible fit: ${offer.name} for ${target}`;
  const message = clean([
    `Hi ${target},`,
    `LUMEN detected a public commercial signal that may fit ${offer.name}.`,
    evidence ? `Observed context: ${evidence}` : "The signal appears related to an active B2B requirement.",
    `We can provide ${offer.outcome} for USD ${offer.priceUsd}.`,
    "This is a non-binding draft only. No order, payment, contract or commitment is created by this message.",
    "If useful, the next step would be to confirm the requirement and receive the exact scope before checkout."
  ].join("\n\n"), 3500);

  return {
    offerId: opportunity.revenue_offer_id || "MP-BUYER-SIGNALS",
    offerName: offer.name,
    amountUsd: offer.priceUsd,
    subject,
    message
  };
}

export async function prepareTopProposal(env) {
  if (!(await ensureSchema(env))) return { ok: false, error: "persistence_unavailable" };
  const opportunity = await getBestCommercialOpportunity(env);
  if (!opportunity) {
    return { ok: true, prepared: false, reason: "no_commercially_actionable_opportunity", version: VERSION };
  }

  const draft = makeDraft(opportunity);
  const existing = await env.DB.prepare("SELECT proposal_id,created_at FROM lumen_proposal_drafts WHERE opportunity_id=? LIMIT 1").bind(opportunity.id).first();
  const now = new Date().toISOString();
  const proposalId = existing?.proposal_id || `PROP-${crypto.randomUUID().replaceAll("-", "").slice(0, 12).toUpperCase()}`;
  const createdAt = existing?.created_at || now;
  const metadata = {
    commercial_score: opportunity.commercial_score,
    commercial_fit: opportunity.commercial_fit,
    evidence_strength: opportunity.evidence_strength,
    discovery_score: opportunity.discovery_score,
    endpoint: opportunity.endpoint || null,
    reasons: opportunity.reasons || [],
    source_status: opportunity.status || null,
    engine_version: VERSION
  };

  await env.DB.prepare("INSERT INTO lumen_proposal_drafts(opportunity_id,proposal_id,created_at,updated_at,status,offer_id,offer_name,amount_usd,subject,message,quality_gate_status,autonomous_send,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(opportunity_id) DO UPDATE SET updated_at=excluded.updated_at,status=excluded.status,offer_id=excluded.offer_id,offer_name=excluded.offer_name,amount_usd=excluded.amount_usd,subject=excluded.subject,message=excluded.message,quality_gate_status=excluded.quality_gate_status,autonomous_send=excluded.autonomous_send,metadata_json=excluded.metadata_json")
    .bind(opportunity.id, proposalId, createdAt, now, "DRAFT", draft.offerId, draft.offerName, draft.amountUsd, draft.subject, draft.message, "PENDING_QUALITY_GATE", 0, JSON.stringify(metadata)).run();

  return {
    ok: true,
    prepared: true,
    version: VERSION,
    proposal: {
      proposalId,
      opportunityId: opportunity.id,
      target: opportunity.name,
      offerId: draft.offerId,
      offerName: draft.offerName,
      amountUsd: draft.amountUsd,
      subject: draft.subject,
      message: draft.message,
      status: "DRAFT",
      qualityGateStatus: "PENDING_QUALITY_GATE",
      autonomousSend: false
    },
    guardrails: {
      chargeCreated: false,
      contractCreated: false,
      autonomousOutgoingSpend: false,
      autonomousOutreach: false,
      bindingActionsHumanGated: true
    }
  };
}

async function getNextProposal(env) {
  await ensureSchema(env);
  const row = await env.DB.prepare("SELECT p.opportunity_id,p.proposal_id,p.created_at,p.updated_at,p.status,p.offer_id,p.offer_name,p.amount_usd,p.subject,p.message,p.quality_gate_status,p.autonomous_send,p.metadata_json,o.name,o.endpoint,o.description FROM lumen_proposal_drafts p JOIN lumen_opportunities o ON o.id=p.opportunity_id WHERE p.status='DRAFT' ORDER BY p.updated_at DESC LIMIT 1").first();
  if (!row) return json({ version: VERSION, proposal: null, nextAction: "prepare_top_proposal" });
  let metadata = {};
  try { metadata = JSON.parse(row.metadata_json || "{}"); } catch {}
  return json({
    version: VERSION,
    proposal: {
      proposalId: row.proposal_id,
      opportunityId: row.opportunity_id,
      target: row.name,
      endpoint: row.endpoint || null,
      offerId: row.offer_id,
      offerName: row.offer_name,
      amountUsd: Number(row.amount_usd || 0),
      subject: row.subject,
      message: row.message,
      qualityGateStatus: row.quality_gate_status,
      autonomousSend: Boolean(row.autonomous_send),
      metadata
    },
    nextAction: "quality_gate_review_before_any_external_send",
    guardrails: { autonomousOutgoingSpend: false, autonomousOutreach: false, bindingActionsHumanGated: true }
  });
}

async function manualPrepare(request, env) {
  const configured = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const provided = clean(request.headers.get("x-lumen-admin"), 500);
  if (!configured || !provided || configured !== provided) return json({ ok: false, error: "admin_token_required" }, 403);
  return json(await prepareTopProposal(env), 202);
}

export async function handleProposalEngine(request, env) {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/proposals/next") return getNextProposal(env);
  if (request.method === "POST" && url.pathname === "/proposals/prepare-top") return manualPrepare(request, env);
  return null;
}
