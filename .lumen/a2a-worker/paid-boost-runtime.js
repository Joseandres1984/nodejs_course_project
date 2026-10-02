import { AI_ROUTER_POLICY } from "./ai-router.js";

export const DEEP_CRON = "12 * * * *";
export const PAID_BOOST_POLICY = Object.freeze({
  version: "1.0-lumen-paid-boost", fastCron: "7,22,37,52 * * * *",
  deepCron: DEEP_CRON, durableDeepCycle: true, maxNewOpportunityWorkflowsPerHour: 2,
  opportunityWorkflow: "observe_existing_proposal_approval_send_response_verified_settlement",
  workflowSendsMessages: false, workflowReleasesDelivery: false,
  autonomousSpendUsd: 0, bindingActionsHumanGated: true,
  extraAiSpendAuthorized: false, ai: AI_ROUTER_POLICY,
});

export async function ensureBoostSchema(env) {
  if (!env.DB) throw new Error("boost_persistence_required");
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_paid_boost_steps (run_id TEXT NOT NULL,step_name TEXT NOT NULL,status TEXT NOT NULL,result_json TEXT,updated_at TEXT NOT NULL,PRIMARY KEY(run_id,step_name))"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_paid_boost_runs (id TEXT PRIMARY KEY,kind TEXT NOT NULL,status TEXT NOT NULL,updated_at TEXT NOT NULL,result_json TEXT)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_paid_boost_opportunities (proposal_id TEXT PRIMARY KEY,instance_id TEXT NOT NULL UNIQUE,stage TEXT NOT NULL,updated_at TEXT NOT NULL,receipt_id TEXT)")
  ]);
}

export async function recordRun(env, id, kind, status, result = null) {
  await env.DB.prepare("INSERT INTO lumen_paid_boost_runs(id,kind,status,updated_at,result_json) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,updated_at=excluded.updated_at,result_json=excluded.result_json")
    .bind(id, kind, status, new Date().toISOString(), result ? JSON.stringify(result) : null).run();
}

// Learning engines mutate counters. A crash after their write must not cause
// blind replay. Ambiguous RUNNING claims are surfaced for review, not retried.
export async function checkpoint(env, runId, name, action) {
  const claim = await env.DB.prepare("INSERT OR IGNORE INTO lumen_paid_boost_steps(run_id,step_name,status,updated_at) VALUES(?,?,'RUNNING',?)")
    .bind(runId, name, new Date().toISOString()).run();
  if (Number(claim?.meta?.changes) !== 1) {
    const previous = await env.DB.prepare("SELECT status,result_json FROM lumen_paid_boost_steps WHERE run_id=? AND step_name=?").bind(runId, name).first();
    if (previous?.status === "DONE") return JSON.parse(previous.result_json);
    return { ok: false, reason: "ambiguous_or_failed_step_requires_review", step: name };
  }
  let result;
  try { result = await action() ?? { ok: true }; }
  catch (error) { result = { ok: false, error: String(error?.message || error).slice(0, 240) }; }
  await env.DB.prepare("UPDATE lumen_paid_boost_steps SET status=?,result_json=?,updated_at=? WHERE run_id=? AND step_name=?")
    .bind(result.ok === false ? "FAILED" : "DONE", JSON.stringify(result), new Date().toISOString(), runId, name).run();
  return result;
}

export async function startDeepCycle(env, scheduledTime) {
  const hour = Math.floor(scheduledTime / 3600000), id = `deep-${hour}`;
  // Atomic createBatch deduplicates redelivered Cron events.
  await env.LUMEN_DEEP_WORKFLOW.createBatch([{ id, params: { scheduledTime } }]);
  return id;
}

export async function startOpportunityObservers(env) {
  const rows = await env.DB.prepare("SELECT p.proposal_id FROM lumen_proposal_drafts p LEFT JOIN lumen_paid_boost_opportunities w ON w.proposal_id=p.proposal_id WHERE w.proposal_id IS NULL AND p.status IN ('DRAFT','APPROVED','SENT','RESPONDED') ORDER BY p.created_at DESC LIMIT 2").all();
  const ids = [];
  for (const row of rows.results || []) {
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(row.proposal_id));
    const id = `opp-${Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, "0")).join("")}`;
    await env.LUMEN_OPPORTUNITY_WORKFLOW.createBatch([{ id, params: { proposalId: row.proposal_id } }]);
    await env.DB.prepare("INSERT OR IGNORE INTO lumen_paid_boost_opportunities(proposal_id,instance_id,stage,updated_at) VALUES(?,?,'TRACKING_PROPOSAL',?)")
      .bind(row.proposal_id, id, new Date().toISOString()).run();
    ids.push(id);
  }
  return { ok: true, started: ids.length, ids };
}

export function observedOpportunityStage(proposal, settlement) {
  if (settlement?.receipt_id && settlement.status === "settled_verified" && settlement.success === true)
    return "PAYMENT_VERIFIED_DELIVERY_PENDING";
  if (!proposal) return "PROPOSAL_MISSING";
  if (proposal.status === "RESPONDED") return "RESPONSE_RECEIVED";
  if (proposal.status === "SENT") return "AWAITING_RESPONSE";
  if (proposal.status === "APPROVED" && proposal.quality_gate_status === "PASS") return "QUALITY_APPROVED_AWAITING_GOVERNOR";
  return "AWAITING_QUALITY_REVIEW";
}

export async function observeOpportunity(env, proposalId, instanceId) {
  const proposal = await env.DB.prepare("SELECT status,quality_gate_status FROM lumen_proposal_drafts WHERE proposal_id=? LIMIT 1").bind(proposalId).first();
  // Payment evidence must join to the provider-verified receipt, not an event
  // supplied by a caller. No arbitrary endpoint can declare a payment.
  const receipt = await env.DB.prepare("SELECT r.id AS receipt_id,r.status,r.request_metadata FROM lumen_x402_revenue_bridge b JOIN lumen_x402_receipts r ON r.id=b.receipt_id WHERE b.proposal_id=? AND r.status='settled_verified' ORDER BY b.created_at DESC LIMIT 1")
    .bind(proposalId).first();
  let success = false;
  try { success = JSON.parse(receipt?.request_metadata || "{}").settlement?.success === true; } catch {}
  const stage = observedOpportunityStage(proposal, receipt ? { ...receipt, success } : null);
  await env.DB.prepare("INSERT INTO lumen_paid_boost_opportunities(proposal_id,instance_id,stage,updated_at,receipt_id) VALUES(?,?,?,?,?) ON CONFLICT(proposal_id) DO UPDATE SET stage=excluded.stage,updated_at=excluded.updated_at,receipt_id=excluded.receipt_id")
    .bind(proposalId, instanceId, stage, new Date().toISOString(), stage === "PAYMENT_VERIFIED_DELIVERY_PENDING" ? receipt.receipt_id : null).run();
  return { stage, proposalId, paymentVerified: stage === "PAYMENT_VERIFIED_DELIVERY_PENDING", releasesDelivery: false };
}
