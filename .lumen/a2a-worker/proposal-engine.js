const VERSION = "1.3-director-aware-proposal-engine";

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

function safeParse(value, fallback = {}) {
  try { return JSON.parse(value || ""); } catch { return fallback; }
}

function completeExcerpt(value, limit = 420) {
  const text = clean(value, 5000);
  if (!text) return "";
  if (text.length <= limit) return /[.!?]$/.test(text) ? text : `${text}.`;
  const slice = text.slice(0, limit);
  const sentenceEnds = [slice.lastIndexOf(". "), slice.lastIndexOf("! "), slice.lastIndexOf("? ")];
  const bestEnd = Math.max(...sentenceEnds);
  if (bestEnd >= Math.floor(limit * 0.45)) return slice.slice(0, bestEnd + 1).trim();
  const lastSpace = slice.lastIndexOf(" ");
  const fallback = (lastSpace > 80 ? slice.slice(0, lastSpace) : slice).replace(/[,:;\-]+$/, "").trim();
  return /[.!?]$/.test(fallback) ? fallback : `${fallback}.`;
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_proposal_drafts (opportunity_id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, status TEXT NOT NULL, offer_id TEXT NOT NULL, offer_name TEXT NOT NULL, amount_usd REAL NOT NULL, subject TEXT NOT NULL, message TEXT NOT NULL, quality_gate_status TEXT NOT NULL, autonomous_send INTEGER NOT NULL DEFAULT 0, metadata_json TEXT)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_proposal_drafts_status ON lumen_proposal_drafts(status,updated_at)")
  ]);
  return true;
}

async function getBestProposalCandidate(env) {
  const baseFields = "SELECT o.id,o.name,o.description,o.remote_id,o.endpoint,o.evidence,o.score AS discovery_score,o.fit AS discovery_fit,o.demand_signal,o.revenue_offer_id,o.status,a.assessed_at,a.commercial_score,a.commercial_fit,a.evidence_strength,a.commercially_actionable,a.synthetic_or_test_only,a.reasons_json,p.proposal_id AS existing_proposal_id,p.created_at AS existing_created_at,p.status AS existing_proposal_status,p.quality_gate_status AS existing_quality_gate_status";
  const where = " WHERE a.commercially_actionable=1 AND a.synthetic_or_test_only=0 AND (p.opportunity_id IS NULL OR (p.status='DRAFT' AND p.quality_gate_status IN ('PENDING_QUALITY_GATE','NEEDS_REVISION')))";
  let row = null;
  try {
    row = await env.DB.prepare(`${baseFields},COALESCE(f.priority_adjustment,0) AS profit_priority_adjustment,COALESCE(f.evidence_level,'COLD') AS profit_evidence_level,COALESCE(f.verified_settlements,0) AS profit_verified_settlements,COALESCE(f.verified_revenue_usd,0) AS profit_verified_revenue_usd,COALESCE(d.priority_adjustment,0) AS director_priority_adjustment,COALESCE(d.tactic,'NEUTRAL') AS director_tactic,COALESCE(d.evidence_level,'COLD_START') AS director_evidence_level,d.reason AS director_reason FROM lumen_opportunities o JOIN lumen_opportunity_assessments a ON a.opportunity_id=o.id LEFT JOIN lumen_proposal_drafts p ON p.opportunity_id=o.id LEFT JOIN lumen_offer_performance f ON f.offer_id=o.revenue_offer_id LEFT JOIN lumen_revenue_director_offer_focus d ON d.offer_id=o.revenue_offer_id${where} ORDER BY (a.commercial_score + COALESCE(f.priority_adjustment,0) + COALESCE(d.priority_adjustment,0)) DESC,a.commercial_score DESC,o.score DESC,o.updated_at DESC LIMIT 1`).first();
  } catch {
    try {
      row = await env.DB.prepare(`${baseFields},COALESCE(f.priority_adjustment,0) AS profit_priority_adjustment,COALESCE(f.evidence_level,'COLD') AS profit_evidence_level,COALESCE(f.verified_settlements,0) AS profit_verified_settlements,COALESCE(f.verified_revenue_usd,0) AS profit_verified_revenue_usd,0 AS director_priority_adjustment,'NEUTRAL' AS director_tactic,'UNINITIALIZED' AS director_evidence_level,NULL AS director_reason FROM lumen_opportunities o JOIN lumen_opportunity_assessments a ON a.opportunity_id=o.id LEFT JOIN lumen_proposal_drafts p ON p.opportunity_id=o.id LEFT JOIN lumen_offer_performance f ON f.offer_id=o.revenue_offer_id${where} ORDER BY (a.commercial_score + COALESCE(f.priority_adjustment,0)) DESC,a.commercial_score DESC,o.score DESC,o.updated_at DESC LIMIT 1`).first();
    } catch {
      row = await env.DB.prepare(`${baseFields},0 AS profit_priority_adjustment,'COLD' AS profit_evidence_level,0 AS profit_verified_settlements,0 AS profit_verified_revenue_usd,0 AS director_priority_adjustment,'NEUTRAL' AS director_tactic,'UNINITIALIZED' AS director_evidence_level,NULL AS director_reason FROM lumen_opportunities o JOIN lumen_opportunity_assessments a ON a.opportunity_id=o.id LEFT JOIN lumen_proposal_drafts p ON p.opportunity_id=o.id${where} ORDER BY a.commercial_score DESC,o.score DESC,o.updated_at DESC LIMIT 1`).first();
    }
  }
  if (!row) return null;
  return { ...row, reasons: safeParse(row.reasons_json, []) };
}

function makeDraft(opportunity) {
  const offer = OFFERS[opportunity.revenue_offer_id] || OFFERS["MP-BUYER-SIGNALS"];
  const target = clean(opportunity.name || opportunity.remote_id, 180);
  const evidence = completeExcerpt(opportunity.description, 420);
  const subject = clean(`Possible fit: ${offer.name} for ${target}`, 180);
  const message = [
    `Hi ${target},`,
    `LUMEN found a public commercial signal that appears relevant to ${offer.name}.`,
    evidence ? `Observed context: ${evidence}` : "Observed context: the public signal appears related to an active B2B requirement.",
    `We can provide ${offer.outcome} for USD ${offer.priceUsd}.`,
    "This is a non-binding commercial introduction. No order, payment, contract or commitment is created by this message.",
    "If useful, reply with the requirement or scope you want checked. LUMEN can then confirm the exact deliverable and provide the x402 checkout. If this is not relevant, no action is needed."
  ].join("\n\n");
  return { offerId: opportunity.revenue_offer_id || "MP-BUYER-SIGNALS", offerName: offer.name, amountUsd: offer.priceUsd, subject, message: clean(message, 1800) };
}

export async function prepareTopProposal(env) {
  if (!(await ensureSchema(env))) return { ok: false, error: "persistence_unavailable" };
  const opportunity = await getBestProposalCandidate(env);
  if (!opportunity) return { ok: true, prepared: false, reason: "no_unprocessed_commercial_candidate", version: VERSION };

  const draft = makeDraft(opportunity);
  const now = new Date().toISOString();
  const proposalId = opportunity.existing_proposal_id || `PROP-${crypto.randomUUID().replaceAll("-", "").slice(0, 12).toUpperCase()}`;
  const createdAt = opportunity.existing_created_at || now;
  const metadata = {
    commercial_score: opportunity.commercial_score,
    commercial_fit: opportunity.commercial_fit,
    evidence_strength: opportunity.evidence_strength,
    discovery_score: opportunity.discovery_score,
    endpoint: opportunity.endpoint || null,
    reasons: opportunity.reasons || [],
    source_status: opportunity.status || null,
    profit_feedback: {
      priority_adjustment: Number(opportunity.profit_priority_adjustment || 0),
      evidence_level: opportunity.profit_evidence_level || "COLD",
      verified_settlements: Number(opportunity.profit_verified_settlements || 0),
      verified_revenue_usd: Number(opportunity.profit_verified_revenue_usd || 0),
      changes_price: false,
      changes_only_selection_priority: true
    },
    revenue_director: {
      priority_adjustment: Number(opportunity.director_priority_adjustment || 0),
      tactic: opportunity.director_tactic || "NEUTRAL",
      evidence_level: opportunity.director_evidence_level || "COLD_START",
      reason: opportunity.director_reason || null,
      changes_price: false,
      changes_only_selection_priority: true
    },
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
      autonomousSend: false,
      profitPriorityAdjustment: Number(opportunity.profit_priority_adjustment || 0),
      profitEvidenceLevel: opportunity.profit_evidence_level || "COLD",
      directorPriorityAdjustment: Number(opportunity.director_priority_adjustment || 0),
      directorTactic: opportunity.director_tactic || "NEUTRAL"
    },
    guardrails: {
      chargeCreated: false,
      contractCreated: false,
      autonomousPriceChange: false,
      autonomousOutgoingSpend: false,
      autonomousContract: false,
      bindingActionsHumanGated: true
    }
  };
}

async function getNextProposal(env) {
  await ensureSchema(env);
  const row = await env.DB.prepare("SELECT p.opportunity_id,p.proposal_id,p.created_at,p.updated_at,p.status,p.offer_id,p.offer_name,p.amount_usd,p.subject,p.message,p.quality_gate_status,p.autonomous_send,p.metadata_json,o.name,o.endpoint,o.description FROM lumen_proposal_drafts p JOIN lumen_opportunities o ON o.id=p.opportunity_id WHERE p.status IN ('DRAFT','APPROVED') ORDER BY CASE WHEN p.status='APPROVED' THEN 0 ELSE 1 END,p.updated_at DESC LIMIT 1").first();
  if (!row) return json({ version: VERSION, proposal: null, nextAction: "prepare_top_proposal" });
  const metadata = safeParse(row.metadata_json, {});
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
      status: row.status,
      qualityGateStatus: row.quality_gate_status,
      autonomousSend: Boolean(row.autonomous_send),
      metadata
    },
    nextAction: row.status === "APPROVED" ? "probe_a2a_endpoint_before_contact" : "quality_gate_review_before_any_external_send",
    guardrails: { autonomousPriceChange:false, autonomousOutgoingSpend: false, autonomousContract: false, bindingActionsHumanGated: true }
  });
}

function authorized(request, env) {
  const configured = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const provided = clean(request.headers.get("x-lumen-admin"), 500);
  return Boolean(configured && provided && configured === provided);
}

export async function handleProposalEngine(request, env) {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/proposals/next") return getNextProposal(env);
  if (request.method === "POST" && url.pathname === "/proposals/prepare-top") {
    if (!authorized(request, env)) return json({ ok: false, error: "admin_token_required" }, 403);
    return json(await prepareTopProposal(env), 202);
  }
  return null;
}
