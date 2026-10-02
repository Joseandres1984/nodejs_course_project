import playbooks from "./sovereign-playbooks.json" with { type: "json" };
import { digest, iso, optionalRows, rows, ensureSovereignSchema, clean } from "./sovereign-store.js";

export function validatePlaybooks(value) {
  const bounds = { maxInternalDeals: [1,3], minimumProductHostSignals: [2,5], diagnosticLookbackHours: [1,24] };
  if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).length !== 3)
    throw new Error("playbook_keys_invalid");
  for (const [key, limits] of Object.entries(bounds))
    if (!Number.isInteger(value[key]) || value[key] < limits[0] || value[key] > limits[1]) throw new Error(`playbook_bound:${key}`);
  if (Object.keys(value).some(key => !bounds[key])) throw new Error("playbook_unknown_key");
  return value;
}
export const ACTIVE_PLAYBOOKS = Object.freeze(validatePlaybooks(playbooks));

export async function selfHeal(env, missing = []) {
  // The only automatically applied repair is local idempotent schema creation.
  // Failed/ambiguous sends, Workflow steps and delivery jobs are never replayed.
  await ensureSovereignSchema(env);
  const failures = await optionalRows(env, "SELECT run_id,step_name,status,updated_at FROM lumen_paid_boost_steps WHERE (status='FAILED' OR (status='RUNNING' AND julianday(updated_at)<julianday('now','-3 hours'))) AND julianday(updated_at)>julianday('now',?) ORDER BY updated_at DESC LIMIT 15", missing, [`-${ACTIVE_PLAYBOOKS.diagnosticLookbackHours} hours`]);
  const current = new Set();
  for (const failure of failures) {
    const id = `INC-${await digest([failure.run_id, failure.step_name])}`; current.add(id);
    const details = { ...failure, playbook: "NO_REPLAY_ESCALATE_FOR_REVIEW", repaired: false,
      reason: "legacy_step_may_have_committed_external_or_learning_side_effects" };
    await env.DB.prepare("INSERT INTO lumen_v4_incidents VALUES(?,?,'REVIEW_REQUIRED',?) ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,status=excluded.status,details_json=excluded.details_json")
      .bind(id, iso(), JSON.stringify(details)).run();
  }
  // No incident is auto-closed merely because it falls outside a read window.
  return { schemaReady: true, localRepair: "idempotent_v4_schema", reviewRequired: current.size,
    incidents: [...current], replaysExternalActions: false, autoDeployment: false };
}

export async function prepareAutocoderCandidate(env, health) {
  if (!health.reviewRequired || ACTIVE_PLAYBOOKS.maxInternalDeals === 1)
    return { prepared: false, reason: "no_evidenced_bounded_playbook_change" };
  const content = JSON.stringify({ ...ACTIVE_PLAYBOOKS, maxInternalDeals: 1 }, null, 2) + "\n";
  const patch = { path: ".lumen/a2a-worker/sovereign-playbooks.json", encoding: "utf-8", content,
    baseContentSha256: await digest(JSON.stringify(ACTIVE_PLAYBOOKS, null, 2) + "\n"),
    reason: "reduce_internal_deal_work_while_legacy_workflow_incidents_require_review",
    evidence: health.incidents, tests: ["test-sovereign-revenue.mjs", "test-paid-boost.mjs"],
    touchesFinancialAuthority: false, autoMerge: false, autoDeploy: false };
  validatePlaybooks(JSON.parse(content));
  const id = `CODE-${await digest(patch)}`;
  await env.DB.prepare("INSERT OR IGNORE INTO lumen_v4_code_candidates VALUES(?,?,'ISOLATED_PR_REQUIRED',?)")
    .bind(id, iso(), JSON.stringify(patch)).run();
  return { prepared: true, id, patch };
}

export async function latestCodeCandidate(env) {
  const result = await rows(env, "SELECT id,status,patch_json FROM lumen_v4_code_candidates ORDER BY updated_at DESC LIMIT 1");
  return result[0] || null;
}
