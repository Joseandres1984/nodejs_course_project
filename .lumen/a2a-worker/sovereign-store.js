import deliverySchema from "./paid-delivery-schema.json" with { type: "json" };

export const V4_VERSION = "4.0-sovereign-revenue";
export const V4_POLICY = Object.freeze({
  version: V4_VERSION, mode: "SUPERVISED_INTERNAL_EXECUTION", hourlyWorkflow: true,
  autonomousSpendUsd: 0, sendsMessages: false, releasesDelivery: false,
  changesCatalogPrices: false, publishesProducts: false, deploysCode: false,
  bindingActionsHumanGated: true, maxCandidates: 60, maxDealsPerCycle: 3,
  maxProductDraftsPerCycle: 2, maxShadowWorlds: 4, planningMinutes: 10,
  approvalTtlHours: 24, additionalAiCalls: 0,
  graphWindow: { opportunities: 30, proposals: 20, receipts: 50 },
  targets: { humanInterventionReduction: 0.70, opportunityMultiplier: 3,
    usefulExperimentMultiplier: 4, proposalTimeReduction: 0.60, revenuePerComputeIncrease: 0.60 },
  targetsAreMeasuredResults: false,
  modules: {
    revenueBrain: "bounded_economic_ranking_and_internal_budget_allocation",
    dealOperator: "research_drafts_scope_bound_approval_packets_existing_fulfillment_observation",
    protocolMesh: "A2A_0.3_and_MCP_envelope_preparation_x402_checkout_reference_AP2_blocked",
    productFactory: "evidence_backed_packaging_drafts_existing_capabilities_only",
    shadowWorlds: "four_deterministic_scenarios_independent_constraint_judge",
    economicMemory: "exact_entity_graph_and_offer_cohorts",
    autocoderLab: "bounded_playbook_patch_candidates_isolated_PR_workflow_no_automerge",
    selfHealing: "local_schema_repair_recompute_diagnostics_no_external_replay",
    marketRadar: "deduplicated_host_demand_existing_discovery_sources",
    ceoMode: "persisted_goal_bottleneck_plan_internal_execution"
  }
});

export const clean = (value, size = 500) => String(value ?? "").trim().replace(/\s+/g, " ").slice(0, size);
export const number = (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;
export const clamp = (value, low, high) => Math.max(low, Math.min(high, number(value)));
export function object(value) {
  try { const parsed = typeof value === "string" ? JSON.parse(value) : value;
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {}; } catch { return {}; }
}
export async function digest(value) {
  const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(typeof value === "string" ? value : JSON.stringify(value)));
  return [...new Uint8Array(hash)].map(b => b.toString(16).padStart(2, "0")).join("");
}
export function host(value) {
  try { const url = new URL(value); return url.protocol === "https:" ? url.hostname.toLowerCase() : null; } catch { return null; }
}
export const iso = () => new Date().toISOString();
export async function rows(env, sql, args = []) {
  return (await env.DB.prepare(sql).bind(...args).all()).results || [];
}
// Missing optional legacy capabilities are visible. Syntax, transport and DB
// failures must propagate; treating those as zero activity would mislead CEO.
export async function optionalRows(env, sql, missing, args = []) {
  try { return await rows(env, sql, args); }
  catch (error) {
    if (!/no such table:/i.test(String(error?.message || error))) throw error;
    missing.push(clean(String(error?.message || error), 180)); return [];
  }
}

export async function ensureSovereignSchema(env) {
  if (!env.DB) throw new Error("v4_persistence_required");
  // The legacy delivery observer needs its canonical empty table even before
  // the first paid report. These CREATEs never queue or send a delivery.
  await env.DB.batch([
    ...deliverySchema.map(sql => env.DB.prepare(sql)),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_v4_runs (id TEXT PRIMARY KEY,started_at TEXT NOT NULL,finished_at TEXT,status TEXT NOT NULL,result_json TEXT)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_v4_state (id TEXT PRIMARY KEY,updated_at TEXT NOT NULL,state_json TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_v4_goals (id TEXT PRIMARY KEY,updated_at TEXT NOT NULL,goal_json TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_v4_allocations (candidate_id TEXT PRIMARY KEY,run_id TEXT NOT NULL,updated_at TEXT NOT NULL,score REAL NOT NULL,allocation_json TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_v4_deals (proposal_id TEXT PRIMARY KEY,opportunity_id TEXT NOT NULL,updated_at TEXT NOT NULL,stage TEXT NOT NULL,packet_id TEXT,deal_json TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_v4_approvals (id TEXT PRIMARY KEY,proposal_id TEXT NOT NULL,kind TEXT NOT NULL,scope_hash TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,expires_at TEXT NOT NULL,decided_at TEXT,packet_json TEXT NOT NULL,UNIQUE(proposal_id,kind,scope_hash))"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_v4_products (id TEXT PRIMARY KEY,offer_id TEXT NOT NULL,updated_at TEXT NOT NULL,status TEXT NOT NULL,spec_json TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_v4_nodes (id TEXT PRIMARY KEY,kind TEXT NOT NULL,updated_at TEXT NOT NULL,data_json TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_v4_edges (source TEXT NOT NULL,relation TEXT NOT NULL,target TEXT NOT NULL,updated_at TEXT NOT NULL,evidence_json TEXT NOT NULL,PRIMARY KEY(source,relation,target))"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_v4_incidents (id TEXT PRIMARY KEY,updated_at TEXT NOT NULL,status TEXT NOT NULL,details_json TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_v4_code_candidates (id TEXT PRIMARY KEY,updated_at TEXT NOT NULL,status TEXT NOT NULL,patch_json TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_v4_metrics (day TEXT PRIMARY KEY,updated_at TEXT NOT NULL,sample_json TEXT NOT NULL)")
  ]);
  await env.DB.batch([
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_v4_approvals_pending ON lumen_v4_approvals(status,expires_at)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_v4_edges_target ON lumen_v4_edges(target,relation)")
  ]);
}
export async function putState(env, id, value) {
  await env.DB.prepare("INSERT INTO lumen_v4_state VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,state_json=excluded.state_json")
    .bind(id, iso(), JSON.stringify(value)).run();
}
