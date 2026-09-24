const VERSION = "1.0-proposal-quality-gate";

const BLOCKED_PHRASES = [
  "guaranteed return",
  "guaranteed results",
  "risk-free",
  "act now",
  "limited time",
  "urgent payment",
  "send password",
  "share password",
  "private key",
  "seed phrase",
  "recovery phrase"
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

function isHttps(value) {
  try { return new URL(value).protocol === "https:"; } catch { return false; }
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_quality_reviews (proposal_id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL, reviewed_at TEXT NOT NULL, status TEXT NOT NULL, quality_score INTEGER NOT NULL, reasons_json TEXT NOT NULL, engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_quality_reviews_status ON lumen_quality_reviews(status,reviewed_at)")
  ]);
  return true;
}

async function getNextDraft(env) {
  const row = await env.DB.prepare("SELECT p.proposal_id,p.opportunity_id,p.created_at,p.updated_at,p.status,p.offer_id,p.offer_name,p.amount_usd,p.subject,p.message,p.quality_gate_status,p.metadata_json,o.name,o.endpoint,o.description,a.commercial_score,a.commercial_fit,a.evidence_strength,a.synthetic_or_test_only FROM lumen_proposal_drafts p JOIN lumen_opportunities o ON o.id=p.opportunity_id LEFT JOIN lumen_opportunity_assessments a ON a.opportunity_id=p.opportunity_id WHERE p.status='DRAFT' AND p.quality_gate_status='PENDING_QUALITY_GATE' ORDER BY COALESCE(a.commercial_score,0) DESC,p.created_at ASC LIMIT 1").first();
  if (!row) return null;
  return { ...row, metadata: safeParse(row.metadata_json, {}) };
}

export function evaluateProposalQuality(row) {
  const reasons = [];
  const blockers = [];
  const message = clean(row?.message, 5000);
  const subject = clean(row?.subject, 500);
  const lower = message.toLowerCase();
  const commercialScore = Number(row?.commercial_score ?? row?.metadata?.commercial_score ?? 0);
  const evidenceStrength = clean(row?.evidence_strength ?? row?.metadata?.evidence_strength, 40).toLowerCase();
  const amountUsd = Number(row?.amount_usd || 0);

  let score = 100;

  if (!isHttps(row?.endpoint)) { blockers.push("endpoint_not_https"); score -= 45; }
  else reasons.push("https_endpoint");

  if (commercialScore < 65) { blockers.push("commercial_score_below_65"); score -= 30; }
  else reasons.push(`commercial_score:${commercialScore}`);

  if (!['medium','strong'].includes(evidenceStrength)) { blockers.push("evidence_too_weak"); score -= 20; }
  else reasons.push(`evidence:${evidenceStrength}`);

  if (Number(row?.synthetic_or_test_only || 0) === 1) { blockers.push("synthetic_or_test_only"); score -= 80; }

  if (subject.length < 12 || subject.length > 180) { blockers.push("subject_length_invalid"); score -= 15; }
  if (message.length < 180 || message.length > 1800) { blockers.push("message_length_invalid"); score -= 20; }

  if (!lower.includes("non-binding")) { blockers.push("missing_nonbinding_disclaimer"); score -= 20; }
  else reasons.push("nonbinding_disclaimer_present");

  if (!lower.includes("no order") || !lower.includes("contract") || !lower.includes("commitment")) {
    blockers.push("missing_commitment_guardrail");
    score -= 20;
  } else reasons.push("commitment_guardrail_present");

  if (!(amountUsd > 0 && amountUsd <= 250)) { blockers.push("amount_outside_safe_catalog_range"); score -= 30; }
  else reasons.push(`catalog_amount_usd:${amountUsd}`);

  const blockedHit = BLOCKED_PHRASES.find(phrase => lower.includes(phrase));
  if (blockedHit) { blockers.push(`blocked_phrase:${blockedHit}`); score -= 50; }

  if (/\b(password|secret|private key|seed phrase|recovery phrase)\b/i.test(message)) {
    blockers.push("credential_or_secret_language");
    score -= 60;
  }

  if (!/[.!?]$/.test(message)) { blockers.push("message_appears_truncated"); score -= 15; }
  else reasons.push("message_has_complete_ending");

  if (!lower.includes("if useful") && !lower.includes("if relevant")) {
    blockers.push("missing_low_pressure_cta");
    score -= 10;
  } else reasons.push("low_pressure_cta_present");

  score = Math.max(0, Math.min(100, Math.round(score)));
  const pass = blockers.length === 0 && score >= 90;
  return { pass, qualityScore: score, blockers, reasons };
}

export async function reviewNextProposal(env) {
  if (!(await ensureSchema(env))) return { ok: false, error: "persistence_unavailable" };
  const row = await getNextDraft(env);
  if (!row) return { ok: true, reviewed: false, reason: "no_pending_proposal", version: VERSION };

  const result = evaluateProposalQuality(row);
  const now = new Date().toISOString();
  const status = result.pass ? "PASS" : "FAIL";

  await env.DB.prepare("INSERT INTO lumen_quality_reviews(proposal_id,opportunity_id,reviewed_at,status,quality_score,reasons_json,engine_version) VALUES(?,?,?,?,?,?,?) ON CONFLICT(proposal_id) DO UPDATE SET reviewed_at=excluded.reviewed_at,status=excluded.status,quality_score=excluded.quality_score,reasons_json=excluded.reasons_json,engine_version=excluded.engine_version")
    .bind(row.proposal_id, row.opportunity_id, now, status, result.qualityScore, JSON.stringify({ blockers: result.blockers, reasons: result.reasons }), VERSION).run();

  if (result.pass) {
    await env.DB.prepare("UPDATE lumen_proposal_drafts SET status='APPROVED',quality_gate_status='PASS',updated_at=? WHERE proposal_id=?")
      .bind(now, row.proposal_id).run();
  } else {
    await env.DB.prepare("UPDATE lumen_proposal_drafts SET status='DRAFT',quality_gate_status='NEEDS_REVISION',updated_at=? WHERE proposal_id=?")
      .bind(now, row.proposal_id).run();
  }

  return {
    ok: true,
    reviewed: true,
    version: VERSION,
    proposalId: row.proposal_id,
    opportunityId: row.opportunity_id,
    status,
    qualityScore: result.qualityScore,
    blockers: result.blockers,
    reasons: result.reasons,
    nextAction: result.pass ? "probe_a2a_endpoint_before_contact" : "revise_proposal_copy",
    guardrails: {
      autonomousOutgoingSpend: false,
      autonomousPurchase: false,
      autonomousContract: false,
      bindingActionsHumanGated: true
    }
  };
}

async function qualityStats(env) {
  await ensureSchema(env);
  const total = await env.DB.prepare("SELECT COUNT(*) AS n FROM lumen_quality_reviews").first();
  const passed = await env.DB.prepare("SELECT COUNT(*) AS n FROM lumen_quality_reviews WHERE status='PASS'").first();
  const failed = await env.DB.prepare("SELECT COUNT(*) AS n FROM lumen_quality_reviews WHERE status='FAIL'").first();
  const approved = await env.DB.prepare("SELECT COUNT(*) AS n FROM lumen_proposal_drafts WHERE status='APPROVED' AND quality_gate_status='PASS'").first();
  return json({
    version: VERSION,
    reviewed: Number(total?.n || 0),
    passed: Number(passed?.n || 0),
    failed: Number(failed?.n || 0),
    approvedAwaitingOutreach: Number(approved?.n || 0)
  });
}

async function qualityNext(env) {
  await ensureSchema(env);
  const proposal = await getNextDraft(env);
  if (!proposal) return json({ version: VERSION, proposal: null, nextAction: "wait_for_pending_proposal" });
  const evaluation = evaluateProposalQuality(proposal);
  return json({
    version: VERSION,
    proposal: {
      proposalId: proposal.proposal_id,
      opportunityId: proposal.opportunity_id,
      target: proposal.name,
      commercialScore: Number(proposal.commercial_score || 0),
      evidenceStrength: proposal.evidence_strength,
      evaluation
    },
    nextAction: evaluation.pass ? "approve_for_a2a_probe" : "revise_before_contact"
  });
}

function authorized(request, env) {
  const configured = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const provided = clean(request.headers.get("x-lumen-admin"), 500);
  return Boolean(configured && provided && configured === provided);
}

export async function handleQualityGate(request, env) {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/quality/stats") return qualityStats(env);
  if (request.method === "GET" && url.pathname === "/quality/next") return qualityNext(env);
  if (request.method === "POST" && url.pathname === "/quality/review-next") {
    if (!authorized(request, env)) return json({ ok: false, error: "admin_token_required" }, 403);
    return json(await reviewNextProposal(env), 202);
  }
  return null;
}
