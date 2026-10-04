const VERSION = "1.7-intramodule-proposal-evolution";
const PRIORITY_BRIDGE_VERSION = "4.1-sovereign-revenue-priority";
const EVOLUTION_VERSION = "1.0-intramodule-proposal-evolution";

export const OFFERS = {
  "MP-SUPPLIER-SNAPSHOT": { name: "Supplier Snapshot", priceUsd: 1, outcome: "a compact supplier identity and official-channel signal for one named company or domain" },
  "MP-QUOTE-SANITY": { name: "Quote Sanity Check", priceUsd: 7, outcome: "a quick sanity check of pricing and quotation structure" },
  "MP-TENDER-SCAN": { name: "Tender Quick Scan", priceUsd: 9, outcome: "a focused scan of tender fit, deadlines and commercial relevance" },
  "MP-SOURCING-5": { name: "Supplier Shortlist 5", priceUsd: 15, outcome: "a shortlist of five relevant suppliers with evidence" },
  "MP-BUYER-SIGNALS": { name: "Buyer Signal Scan", priceUsd: 19, outcome: "an evidence-backed scan of buyer intent and demand signals" },
  "MP-EXPORT-PULSE": { name: "Export Market Pulse", priceUsd: 25, outcome: "a compact export-market demand and channel pulse" }
};

const PROPOSAL_VARIANTS = [
  { id: "direct_outcome", description: "Lead with the concrete deliverable and fixed price." },
  { id: "evidence_first", description: "Lead with the observed public evidence before the offer." },
  { id: "scope_first", description: "Lead with a low-friction scope question before the commercial detail." },
  { id: "low_friction", description: "Use the shortest path to a reply while preserving the full non-binding disclosure." }
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

function clean(value, limit = 4000) {
  return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit);
}

function boolVar(value, fallback = false) {
  const v = clean(value, 20).toLowerCase();
  if (!v) return fallback;
  return ["1", "true", "yes", "on"].includes(v);
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
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_proposal_drafts_status ON lumen_proposal_drafts(status,updated_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_proposal_variant_assignments (proposal_id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL, offer_id TEXT NOT NULL, variant_id TEXT NOT NULL, created_at TEXT NOT NULL, engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_proposal_variant_assignments_variant ON lumen_proposal_variant_assignments(variant_id,created_at)")
  ]);
  return true;
}

async function getBestProposalCandidate(env) {
  const firstCashMode = boolVar(env?.LUMEN_FIRST_CASH_MODE, false);
  const baseFields = "SELECT o.id,o.name,o.description,o.remote_id,o.endpoint,o.evidence,o.score AS discovery_score,o.fit AS discovery_fit,o.demand_signal,o.revenue_offer_id,o.status,a.assessed_at,a.commercial_score,a.commercial_fit,a.evidence_strength,a.commercially_actionable,a.synthetic_or_test_only,a.reasons_json,p.proposal_id AS existing_proposal_id,p.created_at AS existing_created_at,p.status AS existing_proposal_status,p.quality_gate_status AS existing_quality_gate_status";
  const oneTimeMicrobuyerRevision = firstCashMode
    ? " OR (p.status='DRAFT' AND p.quality_gate_status='NEEDS_REVISION' AND a.reasons_json LIKE '%microbuyer_fit%' AND COALESCE(p.metadata_json,'') NOT LIKE '%1.6-first-cash-microbuyer-revision%')"
    : "";
  const where = ` WHERE a.commercially_actionable=1 AND a.synthetic_or_test_only=0 AND (p.opportunity_id IS NULL OR (p.status='DRAFT' AND p.quality_gate_status='PENDING_QUALITY_GATE')${oneTimeMicrobuyerRevision})`;
  const firstCashOrder = firstCashMode ? "CASE WHEN a.reasons_json LIKE '%microbuyer_fit%' THEN 0 ELSE 1 END," : "";
  let row = null;
  try {
    row = await env.DB.prepare(`${baseFields},COALESCE(f.priority_adjustment,0) AS profit_priority_adjustment,COALESCE(f.evidence_level,'COLD') AS profit_evidence_level,COALESCE(f.verified_settlements,0) AS profit_verified_settlements,COALESCE(f.verified_revenue_usd,0) AS profit_verified_revenue_usd,COALESCE(d.priority_adjustment,0) AS director_priority_adjustment,COALESCE(d.tactic,'NEUTRAL') AS director_tactic,COALESCE(d.evidence_level,'COLD_START') AS director_evidence_level,d.reason AS director_reason,COALESCE(pf.economic_score,0) AS portfolio_economic_score,pf.id AS portfolio_candidate_id,pf.lane AS portfolio_lane,pf.rationale AS portfolio_rationale,COALESCE(v4.score,0) AS sovereign_priority_adjustment,v4.run_id AS sovereign_run_id FROM lumen_opportunities o JOIN lumen_opportunity_assessments a ON a.opportunity_id=o.id LEFT JOIN lumen_proposal_drafts p ON p.opportunity_id=o.id LEFT JOIN lumen_offer_performance f ON f.offer_id=o.revenue_offer_id LEFT JOIN lumen_revenue_director_offer_focus d ON d.offer_id=o.revenue_offer_id LEFT JOIN lumen_opportunity_factory_candidates pf ON pf.source_type='DISCOVERY' AND pf.source_id=o.id AND pf.active=1 LEFT JOIN lumen_v4_allocations v4 ON v4.candidate_id=pf.id${where} ORDER BY ${firstCashOrder}(a.commercial_score + COALESCE(f.priority_adjustment,0) + COALESCE(d.priority_adjustment,0) + COALESCE(pf.economic_score,0)*0.20 + COALESCE(v4.score,0)) DESC,a.commercial_score DESC,o.score DESC,o.updated_at DESC LIMIT 1`).first();
  } catch {
    try {
      row = await env.DB.prepare(`${baseFields},COALESCE(f.priority_adjustment,0) AS profit_priority_adjustment,COALESCE(f.evidence_level,'COLD') AS profit_evidence_level,COALESCE(f.verified_settlements,0) AS profit_verified_settlements,COALESCE(f.verified_revenue_usd,0) AS profit_verified_revenue_usd,COALESCE(d.priority_adjustment,0) AS director_priority_adjustment,COALESCE(d.tactic,'NEUTRAL') AS director_tactic,COALESCE(d.evidence_level,'COLD_START') AS director_evidence_level,d.reason AS director_reason,COALESCE(pf.economic_score,0) AS portfolio_economic_score,pf.id AS portfolio_candidate_id,pf.lane AS portfolio_lane,pf.rationale AS portfolio_rationale,0 AS sovereign_priority_adjustment,NULL AS sovereign_run_id FROM lumen_opportunities o JOIN lumen_opportunity_assessments a ON a.opportunity_id=o.id LEFT JOIN lumen_proposal_drafts p ON p.opportunity_id=o.id LEFT JOIN lumen_offer_performance f ON f.offer_id=o.revenue_offer_id LEFT JOIN lumen_revenue_director_offer_focus d ON d.offer_id=o.revenue_offer_id LEFT JOIN lumen_opportunity_factory_candidates pf ON pf.source_type='DISCOVERY' AND pf.source_id=o.id AND pf.active=1${where} ORDER BY ${firstCashOrder}(a.commercial_score + COALESCE(f.priority_adjustment,0) + COALESCE(d.priority_adjustment,0) + COALESCE(pf.economic_score,0)*0.20) DESC,a.commercial_score DESC,o.score DESC,o.updated_at DESC LIMIT 1`).first();
    } catch {
      try {
        row = await env.DB.prepare(`${baseFields},COALESCE(f.priority_adjustment,0) AS profit_priority_adjustment,COALESCE(f.evidence_level,'COLD') AS profit_evidence_level,COALESCE(f.verified_settlements,0) AS profit_verified_settlements,COALESCE(f.verified_revenue_usd,0) AS profit_verified_revenue_usd,0 AS director_priority_adjustment,'NEUTRAL' AS director_tactic,'UNINITIALIZED' AS director_evidence_level,NULL AS director_reason,0 AS portfolio_economic_score,NULL AS portfolio_candidate_id,NULL AS portfolio_lane,NULL AS portfolio_rationale,0 AS sovereign_priority_adjustment,NULL AS sovereign_run_id FROM lumen_opportunities o JOIN lumen_opportunity_assessments a ON a.opportunity_id=o.id LEFT JOIN lumen_proposal_drafts p ON p.opportunity_id=o.id LEFT JOIN lumen_offer_performance f ON f.offer_id=o.revenue_offer_id${where} ORDER BY ${firstCashOrder}(a.commercial_score + COALESCE(f.priority_adjustment,0)) DESC,a.commercial_score DESC,o.score DESC,o.updated_at DESC LIMIT 1`).first();
      } catch {
        row = await env.DB.prepare(`${baseFields},0 AS profit_priority_adjustment,'COLD' AS profit_evidence_level,0 AS profit_verified_settlements,0 AS profit_verified_revenue_usd,0 AS director_priority_adjustment,'NEUTRAL' AS director_tactic,'UNINITIALIZED' AS director_evidence_level,NULL AS director_reason,0 AS portfolio_economic_score,NULL AS portfolio_candidate_id,NULL AS portfolio_lane,NULL AS portfolio_rationale,0 AS sovereign_priority_adjustment,NULL AS sovereign_run_id FROM lumen_opportunities o JOIN lumen_opportunity_assessments a ON a.opportunity_id=o.id LEFT JOIN lumen_proposal_drafts p ON p.opportunity_id=o.id${where} ORDER BY ${firstCashOrder}a.commercial_score DESC,o.score DESC,o.updated_at DESC LIMIT 1`).first();
      }
    }
  }
  if (!row) return null;
  return { ...row, reasons: safeParse(row.reasons_json, []) };
}

async function proposalVariantStats(env) {
  const empty = PROPOSAL_VARIANTS.map(v => ({ ...v, assignments: 0, responses: 0, settlements: 0, revenueUsd: 0, reward: 0, exploration: 0, score: 0 }));
  try {
    const result = await env.DB.prepare(`SELECT a.variant_id,
      COUNT(DISTINCT a.proposal_id) AS assignments,
      COUNT(DISTINCT CASE WHEN c.status='RESPONDED' THEN a.proposal_id END) AS responses,
      COUNT(DISTINCT b.receipt_id) AS settlements,
      COALESCE(SUM(b.amount_usd),0) AS revenue_usd
      FROM lumen_proposal_variant_assignments a
      LEFT JOIN lumen_first_cash_closer c ON c.proposal_id=a.proposal_id
      LEFT JOIN lumen_x402_revenue_bridge b ON b.proposal_id=a.proposal_id
      GROUP BY a.variant_id`).all();
    const byId = new Map((result.results || []).map(row => [clean(row.variant_id, 80), row]));
    const totalAssignments = (result.results || []).reduce((sum, row) => sum + Number(row.assignments || 0), 0);
    return PROPOSAL_VARIANTS.map(variant => {
      const row = byId.get(variant.id) || {};
      const assignments = Number(row.assignments || 0);
      const responses = Number(row.responses || 0);
      const settlements = Number(row.settlements || 0);
      const revenueUsd = Number(row.revenue_usd || 0);
      const reward = settlements * 10000 + revenueUsd * 100 + responses * 12;
      const exploration = 45 * Math.sqrt(Math.log(totalAssignments + 2) / (assignments + 1));
      return { ...variant, assignments, responses, settlements, revenueUsd, reward, exploration, score: reward + exploration };
    });
  } catch {
    return empty;
  }
}

async function selectProposalVariant(env, proposalId) {
  if (proposalId) {
    try {
      const prior = await env.DB.prepare("SELECT variant_id FROM lumen_proposal_variant_assignments WHERE proposal_id=? LIMIT 1").bind(proposalId).first();
      if (prior?.variant_id && PROPOSAL_VARIANTS.some(v => v.id === prior.variant_id)) {
        const stats = await proposalVariantStats(env);
        return { variantId: prior.variant_id, reason: "stable_existing_assignment", stats };
      }
    } catch {}
  }
  const stats = await proposalVariantStats(env);
  const selected = [...stats].sort((a, b) => {
    if (a.assignments !== b.assignments && Math.min(...stats.map(s => s.assignments)) < 2) return a.assignments - b.assignments;
    return b.score - a.score || a.assignments - b.assignments || a.id.localeCompare(b.id);
  })[0] || { id: "direct_outcome" };
  return { variantId: selected.id, reason: selected.assignments < 2 ? "bounded_exploration" : "verified_outcome_exploitation", stats };
}

function buildProposalMessage({ variantId, target, offer, evidence, firstCashMode, microbuyerFit }) {
  const disclosure = "This is a non-binding commercial introduction. No order, payment, contract or commitment is created by this message.";
  const checkoutHint = firstCashMode && microbuyerFit
    ? "If useful, reply with one company or domain you want checked. LUMEN can confirm the exact deliverable and provide the x402 checkout. If this is not relevant, no action is needed."
    : "If useful, reply with the requirement or scope you want checked. LUMEN can then confirm the exact deliverable and provide the x402 checkout. If this is not relevant, no action is needed.";
  const observed = evidence || (microbuyerFit
    ? "the public signal combines machine-payment compatibility with an information-verification need."
    : "the public signal appears related to an active B2B requirement.");
  const price = firstCashMode && microbuyerFit
    ? `FIRST CASH offer: ${offer.name} — ${offer.outcome} — USD ${offer.priceUsd.toFixed(2)} per request via x402 USDC on Base.`
    : `We can provide ${offer.outcome} for USD ${offer.priceUsd}.`;

  if (variantId === "evidence_first") {
    return [`Hi ${target},`, `Observed context: ${observed}`, `That signal appears relevant to ${offer.name}.`, price, disclosure, checkoutHint].join("\n\n");
  }
  if (variantId === "scope_first") {
    const question = microbuyerFit
      ? "Would a one-company or one-domain verification be useful for your current workflow?"
      : `Is ${offer.name} relevant to a requirement you are working on now?`;
    return [`Hi ${target},`, question, `Observed context: ${observed}`, price, disclosure, checkoutHint].join("\n\n");
  }
  if (variantId === "low_friction") {
    return [`Hi ${target},`, `${offer.name}: ${offer.outcome}.`, `Observed context: ${observed}`, price, checkoutHint, disclosure].join("\n\n");
  }
  return firstCashMode && microbuyerFit
    ? [
        `Hi ${target},`,
        "LUMEN found a public signal that suggests your agent/API may use machine-to-machine payments together with research or verification workflows.",
        `Observed context: ${observed}`,
        price,
        disclosure,
        checkoutHint
      ].join("\n\n")
    : [
        `Hi ${target},`,
        `LUMEN found a public commercial signal that appears relevant to ${offer.name}.`,
        `Observed context: ${observed}`,
        price,
        disclosure,
        checkoutHint
      ].join("\n\n");
}

function makeDraft(opportunity, env, variantId = "direct_outcome") {
  const reasons = Array.isArray(opportunity.reasons) ? opportunity.reasons : [];
  const firstCashMode = boolVar(env?.LUMEN_FIRST_CASH_MODE, false);
  const microbuyerFit = reasons.includes("microbuyer_fit");
  const selectedOfferId = firstCashMode && microbuyerFit ? "MP-SUPPLIER-SNAPSHOT" : (opportunity.revenue_offer_id || "MP-BUYER-SIGNALS");
  const offer = OFFERS[selectedOfferId] || OFFERS["MP-BUYER-SIGNALS"];
  const target = clean(opportunity.name || opportunity.remote_id, 180);
  const evidence = completeExcerpt(opportunity.description, 420);
  const subjectPrefix = variantId === "scope_first" ? "Quick scope check" : variantId === "evidence_first" ? "Observed fit" : (firstCashMode && microbuyerFit ? "USD 1 machine-service fit" : "Possible fit");
  const subject = clean(`${subjectPrefix}: ${offer.name} for ${target}`, 180);
  const message = buildProposalMessage({ variantId, target, offer, evidence, firstCashMode, microbuyerFit });

  return {
    offerId: selectedOfferId,
    offerName: offer.name,
    amountUsd: offer.priceUsd,
    subject,
    message: clean(message, 1800),
    firstCashMode,
    microbuyerFit,
    variantId
  };
}

export async function prepareTopProposal(env) {
  if (!(await ensureSchema(env))) return { ok: false, error: "persistence_unavailable" };
  const opportunity = await getBestProposalCandidate(env);
  if (!opportunity) return { ok: true, prepared: false, reason: "no_unprocessed_commercial_candidate", version: VERSION };

  const now = new Date().toISOString();
  const proposalId = opportunity.existing_proposal_id || `PROP-${crypto.randomUUID().replaceAll("-", "").slice(0, 12).toUpperCase()}`;
  const createdAt = opportunity.existing_created_at || now;
  const evolution = await selectProposalVariant(env, proposalId);
  const draft = makeDraft(opportunity, env, evolution.variantId);
  const selectedStats = evolution.stats.find(s => s.id === draft.variantId) || null;
  const metadata = {
    commercial_score: opportunity.commercial_score,
    commercial_fit: opportunity.commercial_fit,
    evidence_strength: opportunity.evidence_strength,
    discovery_score: opportunity.discovery_score,
    endpoint: opportunity.endpoint || null,
    reasons: opportunity.reasons || [],
    source_status: opportunity.status || null,
    intramodule_evolution: {
      version: EVOLUTION_VERSION,
      variant_id: draft.variantId,
      selection_reason: evolution.reason,
      verified_settlements: Number(selectedStats?.settlements || 0),
      verified_revenue_usd: Number(selectedStats?.revenueUsd || 0),
      responses: Number(selectedStats?.responses || 0),
      assignments: Number(selectedStats?.assignments || 0),
      self_modifying_code: false,
      mutates_price: false,
      reward_order: ["verified_settlement", "verified_revenue", "qualified_response", "bounded_exploration"]
    },
    first_cash: {
      enabled: draft.firstCashMode,
      microbuyer_fit: draft.microbuyerFit,
      selected_offer_id: draft.offerId,
      autonomous_discounting: false,
      one_time_revision: opportunity.existing_quality_gate_status === "NEEDS_REVISION"
    },
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
    opportunity_factory: {
      candidate_id: opportunity.portfolio_candidate_id || null,
      economic_score: Number(opportunity.portfolio_economic_score || 0),
      lane: opportunity.portfolio_lane || "NEW_BUSINESS",
      rationale: opportunity.portfolio_rationale || null,
      changes_price: false,
      changes_only_selection_priority: true
    },
    sovereign_v4: {
      bridge_version: PRIORITY_BRIDGE_VERSION,
      priority_adjustment: Number(opportunity.sovereign_priority_adjustment || 0),
      run_id: opportunity.sovereign_run_id || null,
      source_candidate_id: opportunity.portfolio_candidate_id || null,
      changes_price: false,
      changes_only_selection_priority: true
    },
    engine_version: VERSION
  };

  await env.DB.prepare("INSERT INTO lumen_proposal_drafts(opportunity_id,proposal_id,created_at,updated_at,status,offer_id,offer_name,amount_usd,subject,message,quality_gate_status,autonomous_send,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(opportunity_id) DO UPDATE SET updated_at=excluded.updated_at,status=excluded.status,offer_id=excluded.offer_id,offer_name=excluded.offer_name,amount_usd=excluded.amount_usd,subject=excluded.subject,message=excluded.message,quality_gate_status=excluded.quality_gate_status,autonomous_send=excluded.autonomous_send,metadata_json=excluded.metadata_json")
    .bind(opportunity.id, proposalId, createdAt, now, "DRAFT", draft.offerId, draft.offerName, draft.amountUsd, draft.subject, draft.message, "PENDING_QUALITY_GATE", 0, JSON.stringify(metadata)).run();
  await env.DB.prepare("INSERT INTO lumen_proposal_variant_assignments(proposal_id,opportunity_id,offer_id,variant_id,created_at,engine_version) VALUES(?,?,?,?,?,?) ON CONFLICT(proposal_id) DO UPDATE SET offer_id=excluded.offer_id,engine_version=excluded.engine_version")
    .bind(proposalId, opportunity.id, draft.offerId, draft.variantId, now, EVOLUTION_VERSION).run();

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
      firstCashMode: draft.firstCashMode,
      microbuyerFit: draft.microbuyerFit,
      revisedFrom: opportunity.existing_quality_gate_status || null,
      proposalVariant: draft.variantId,
      evolutionSelectionReason: evolution.reason,
      profitPriorityAdjustment: Number(opportunity.profit_priority_adjustment || 0),
      profitEvidenceLevel: opportunity.profit_evidence_level || "COLD",
      directorPriorityAdjustment: Number(opportunity.director_priority_adjustment || 0),
      directorTactic: opportunity.director_tactic || "NEUTRAL",
      portfolioEconomicScore: Number(opportunity.portfolio_economic_score || 0),
      portfolioLane: opportunity.portfolio_lane || "NEW_BUSINESS",
      sovereignPriorityAdjustment: Number(opportunity.sovereign_priority_adjustment || 0),
      sovereignRunId: opportunity.sovereign_run_id || null
    },
    evolution: {
      version: EVOLUTION_VERSION,
      variant: draft.variantId,
      selectionReason: evolution.reason,
      variants: evolution.stats.map(({ id, assignments, responses, settlements, revenueUsd, score }) => ({ id, assignments, responses, settlements, revenueUsd, score })),
      selfModifyingCode: false,
      priceMutation: false
    },
    guardrails: {
      chargeCreated: false,
      contractCreated: false,
      autonomousPriceChange: false,
      autonomousDiscounting: false,
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

async function getEvolutionStats(env) {
  await ensureSchema(env);
  const variants = await proposalVariantStats(env);
  const ranked = [...variants].sort((a,b) => b.settlements - a.settlements || b.revenueUsd - a.revenueUsd || b.responses - a.responses || b.score - a.score);
  return {
    version: EVOLUTION_VERSION,
    objective: "verified_settlement_first_then_verified_revenue_then_qualified_response",
    champion: ranked[0]?.id || null,
    variants: ranked.map(({ id, description, assignments, responses, settlements, revenueUsd, score }) => ({ id, description, assignments, responses, settlements, revenueUsd, score })),
    boundedExploration: true,
    selfModifyingCode: false,
    mutatesPrice: false,
    mutatesAuthority: false
  };
}

function authorized(request, env) {
  const configured = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const provided = clean(request.headers.get("x-lumen-admin"), 500);
  return Boolean(configured && provided && configured === provided);
}

export async function handleProposalEngine(request, env) {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/proposals/next") return getNextProposal(env);
  if (request.method === "GET" && url.pathname === "/proposals/evolution") return json(await getEvolutionStats(env));
  if (request.method === "POST" && url.pathname === "/proposals/prepare-top") {
    if (!authorized(request, env)) return json({ ok: false, error: "admin_token_required" }, 403);
    return json(await prepareTopProposal(env), 202);
  }
  return null;
}
