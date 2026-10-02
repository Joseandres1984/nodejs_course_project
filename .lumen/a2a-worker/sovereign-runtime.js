import { V4_POLICY, V4_VERSION, clean, object, number, iso, rows, optionalRows, ensureSovereignSchema, putState } from "./sovereign-store.js";
import { evaluateEconomics, allocateAttention, benchmark } from "./sovereign-economics.js";
import { verifiedSettlement, operateDeals, decideApproval } from "./sovereign-deals.js";
import { updateEconomicGraph, offerCohort } from "./sovereign-memory.js";
import { marketRadar, createProductDrafts } from "./sovereign-products.js";
import { selfHeal, prepareAutocoderCandidate, latestCodeCandidate } from "./sovereign-operations.js";
import { PROTOCOL_MESH_POLICY, prepareProtocolEnvelope } from "./sovereign-protocol-mesh.js";
import { startDeepCycle } from "./paid-boost-runtime.js";

export async function loadEconomicEvidence(env) {
  const missing = [];
  const opportunities = await optionalRows(env, "SELECT o.*,a.commercially_actionable,a.synthetic_or_test_only,a.commercial_score,a.evidence_strength FROM lumen_opportunities o JOIN lumen_opportunity_assessments a ON a.opportunity_id=o.id WHERE a.synthetic_or_test_only=0 ORDER BY o.updated_at DESC,o.id LIMIT 60", missing);
  const proposals = await optionalRows(env, "SELECT p.*,o.endpoint FROM lumen_proposal_drafts p JOIN lumen_opportunities o ON o.id=p.opportunity_id ORDER BY p.updated_at DESC,p.proposal_id LIMIT 60", missing);
  const responses = await optionalRows(env, "SELECT proposal_id,stage,response_class FROM lumen_sales_pipeline ORDER BY updated_at DESC LIMIT 100", missing);
  for (const proposal of proposals) Object.assign(proposal, responses.find(r => r.proposal_id === proposal.proposal_id) || {});
  const candidates = await optionalRows(env, "SELECT * FROM lumen_opportunity_factory_candidates WHERE active=1 ORDER BY economic_score DESC,id LIMIT 60", missing);
  const cohort = await optionalRows(env, "SELECT offer_id,sent,verified_settlements FROM lumen_offer_performance LIMIT 60", missing);
  const receipts = await optionalRows(env, "SELECT r.id receipt_id,r.status,r.product_id,r.amount_usd,r.created_at,r.currency,r.network,r.pay_to,r.request_metadata,b.proposal_id,b.offer_id FROM lumen_x402_receipts r JOIN lumen_x402_revenue_bridge b ON b.receipt_id=r.id WHERE r.status IN ('settled_verified','redeemed_queued') ORDER BY r.created_at DESC,r.id LIMIT 200", missing);
  const settlements = receipts.filter(r => verifiedSettlement(r));
  const fulfillments = await optionalRows(env, "SELECT order_id,receipt_id,item_id,amount_usd,status,updated_at FROM lumen_paid_fulfillment_jobs ORDER BY updated_at DESC LIMIT 100", missing);
  const deliveries = await optionalRows(env, "SELECT order_id,receipt_id,status,provider_message_id FROM lumen_paid_deliveries ORDER BY updated_at DESC LIMIT 100", missing);
  const byOpportunity = new Map(opportunities.map(o => [o.id, o]));
  const actionable = candidates.filter(c => c.source_type !== "DISCOVERY" || byOpportunity.get(c.source_id)?.commercially_actionable === 1);
  const economics = actionable.map(c => {
    const offerId = c.source_type === "DISCOVERY" ? byOpportunity.get(c.source_id)?.revenue_offer_id : proposals.find(p => p.proposal_id === c.source_id)?.offer_id;
    return evaluateEconomics({ ...c, offer_id: offerId }, cohort.find(o => o.offer_id === offerId));
  });
  return { opportunities, proposals, settlements, fulfillments, deliveries, economics,
    missingCapabilities: [...new Set(missing)], invalidReceiptEvidence: receipts.length - settlements.length,
    evidenceWindow: { opportunities: 60, proposals: 60, receipts: 200, boundedWindowIsNotLifetimeRevenue: true } };
}

export function validateGoal(body) {
  if (!body || typeof body !== "object" || Array.isArray(body) || Object.keys(body).some(k => !["targetMonthlyRevenueUsd", "objective"].includes(k)))
    throw new Error("goal_fields_invalid_no_authority_overrides");
  const target = body.targetMonthlyRevenueUsd;
  if (!Number.isFinite(target) || target < 1 || target > 1000000) throw new Error("goal_target_invalid");
  return { targetMonthlyRevenueUsd: target, objective: clean(body.objective || "grow_verified_revenue_under_existing_authority", 600),
    autonomousSpendUsd: 0, risk: "low", targetIsCommitment: false };
}
export function planCeo(goal, data, allocation) {
  const paidPending = data.settlements.some(r => !data.fulfillments.some(f => f.receipt_id === r.receipt_id && f.status === "delivered"));
  const bottleneck = data.missingCapabilities.length ? "CAPABILITY_HEALTH" : paidPending ? "PAID_FULFILLMENT" :
    data.proposals.some(p => ["PURCHASE_INTENT", "COMMERCIAL_INTEREST", "COMMERCIAL_QUESTION"].includes(p.response_class)) ? "SCOPE_AND_CLOSE" :
    data.proposals.some(p => p.status === "SENT") ? "BUYER_RESPONSE" : "EVIDENCED_DEMAND";
  return { goal, bottleneck, plan: allocation.allocations.map(a => ({ candidateId: a.candidateId, action: a.nextAction, estimatedMinutes: a.minutes })),
    mandatoryTasks: ["observe_verified_payment_and_delivery", "prepare_scope_bound_packets", "refresh_exact_economic_memory"],
    externalExecution: "existing_governor_and_fulfillment_gates_only", bindingAuthorityChanged: false };
}

export async function sampleMetrics(env, allocation, data, now = Date.now()) {
  const day = new Date(now).toISOString().slice(0,10), yesterday = new Date(now-86400000).toISOString().slice(0,10), missing = [];
  // All global aggregates are read from exact provider receipt truth. The
  // bounded ranking window must not be reported as total economic revenue.
  const amounts = await optionalRows(env, "SELECT COALESCE(SUM(amount_usd),0) revenue,COUNT(*) settlements FROM lumen_x402_receipts WHERE status IN ('settled_verified','redeemed_queued') AND currency='USD' AND network='eip155:8453' AND lower(pay_to)='0x04285de6a083ceb28fb0c254a2ed0f5fdb2eed28' AND json_valid(request_metadata)=1 AND json_extract(request_metadata,'$.settlement.success')=1 AND length(json_extract(request_metadata,'$.settlement.transaction'))=66 AND substr(json_extract(request_metadata,'$.settlement.transaction'),1,2)='0x' AND substr(json_extract(request_metadata,'$.settlement.transaction'),3) NOT GLOB '*[^0-9a-fA-F]*' AND created_at>=? AND created_at<?", missing, [`${day}T00:00:00.000Z`, `${new Date(now+86400000).toISOString().slice(0,10)}T00:00:00.000Z`]);
  const usage = await optionalRows(env, "SELECT reserved_neurons,calls FROM lumen_paid_boost_ai_usage WHERE day=?", missing, [day]);
  const latency = await optionalRows(env, "SELECT AVG((julianday(p.created_at)-julianday(o.discovered_at))*86400000) value FROM lumen_proposal_drafts p JOIN lumen_opportunities o ON o.id=p.opportunity_id WHERE p.created_at>=? AND p.created_at>=o.discovered_at", missing, [`${day}T00:00:00.000Z`]);
  const human = (await rows(env, "SELECT COUNT(*) value FROM lumen_v4_approvals WHERE decided_at>=?", [`${day}T00:00:00.000Z`]))[0];
  const current = { day, sampleTime: iso(), opportunitiesEvaluated: null, usefulExperiments: null,
    humanDecisions: number(human?.value), humanDecisionScope: "v4_only", proposalLatencyMs: latency[0]?.value ?? null,
    verifiedReceiptRevenueUsd: amounts[0]?.revenue ?? null, verifiedSettlements: amounts[0]?.settlements ?? null,
    reservedNeurons: usage[0]?.reserved_neurons ?? null, computeAccounting: "reservation_estimate_not_actual_provider_compute",
    revenuePerReservedNeuron: amounts[0] && usage[0]?.reserved_neurons > 0 ? amounts[0].revenue / usage[0].reserved_neurons : null,
    candidatesEvaluatedThisCycle: data.economics.length, allocatedInternalTasks: allocation.allocations.length,
    missingMetrics: [...new Set(missing)], measurementScope: "UTC_day_to_now_x402_receipts_and_a2a_ai_reservations" };
  const baselineRow = (await rows(env, "SELECT sample_json FROM lumen_v4_metrics WHERE day=?", [yesterday]))[0];
  const baseline = baselineRow ? object(baselineRow.sample_json) : null;
  const comparison = benchmark(baseline, current);
  // A partial current day cannot substantiate a comparison to yesterday's full
  // day. Preserve raw ratios for diagnostics, disable the success claim.
  comparison.status = "INSUFFICIENT_COMPARABLE_DATA";
  comparison.reasons.push("matched_duration_windows_and_actual_compute_not_available");
  comparison.revenueImprovement60PercentVerified = null;
  await env.DB.prepare("INSERT INTO lumen_v4_metrics VALUES(?,?,?) ON CONFLICT(day) DO UPDATE SET updated_at=excluded.updated_at,sample_json=excluded.sample_json")
    .bind(day, iso(), JSON.stringify(current)).run();
  return { current, baseline, comparison, targets: V4_POLICY.targets };
}

export async function runSovereignCycle(env, { runId = `v4-${Math.floor(Date.now()/3600000)}` } = {}) {
  const startedMs = Date.now();
  await ensureSovereignSchema(env);
  const claim = await env.DB.prepare("INSERT OR IGNORE INTO lumen_v4_runs VALUES(?,? ,NULL,'RUNNING',NULL)").bind(runId, iso()).run();
  if (Number(claim.meta?.changes) !== 1) {
    const previous = (await rows(env, "SELECT status,result_json FROM lumen_v4_runs WHERE id=?", [runId]))[0];
    return previous?.status === "COMPLETED" || previous?.status === "DEGRADED" ? object(previous.result_json) : { ok: false, reason: "ambiguous_v4_cycle_no_replay", runId };
  }
  try {
    const data = await loadEconomicEvidence(env);
    const goalRow = (await rows(env, "SELECT goal_json FROM lumen_v4_goals WHERE id='GLOBAL'"))[0];
    const goal = goalRow ? object(goalRow.goal_json) : validateGoal({ targetMonthlyRevenueUsd: 1000 });
    const allocation = allocateAttention(data.economics);
    // Replace this small derived cache in a transaction; stale priorities must
    // not survive when a candidate disappears or a cycle has no evidence.
    await env.DB.batch([env.DB.prepare("DELETE FROM lumen_v4_allocations"), ...allocation.allocations.map(a =>
      env.DB.prepare("INSERT INTO lumen_v4_allocations VALUES(?,?,?,?,?)").bind(a.candidateId, runId, iso(), Math.min(8, Math.log1p(a.utility)*4), JSON.stringify(a)))]);
    const graph = await updateEconomicGraph(env, data.proposals, data.settlements, data.opportunities);
    const radar = marketRadar(data.opportunities, data.settlements);
    const products = await createProductDrafts(env, radar);
    const deals = await operateDeals(env, data, allocation.allocations);
    await env.DB.prepare("UPDATE lumen_v4_approvals SET status='EXPIRED' WHERE status IN ('PENDING','APPROVED') AND expires_at<=?").bind(iso()).run();
    const health = await selfHeal(env, data.missingCapabilities);
    const autocoder = await prepareAutocoderCandidate(env, health);
    const ceo = planCeo(goal, data, allocation);
    const metrics = await sampleMetrics(env, allocation, data);
    const result = { ok: data.missingCapabilities.length === 0, version: V4_VERSION, runId,
      elapsedWallMs: Date.now() - startedMs, elapsedIsCpuTime: false,
      allocation, graph, radar, products, deals, health, autocoder, ceo, metrics,
      missingCapabilities: [...new Set(data.missingCapabilities)], invalidReceiptEvidence: data.invalidReceiptEvidence,
      evidenceWindow: data.evidenceWindow, autonomy: { internalArtifactsPrepared: true, sendsMessages: false, releasesDelivery: false, autonomousSpendUsd: 0 } };
    await putState(env, "GLOBAL", result);
    await env.DB.prepare("UPDATE lumen_v4_runs SET finished_at=?,status=?,result_json=? WHERE id=?")
      .bind(iso(), result.ok ? "COMPLETED" : "DEGRADED", JSON.stringify(result), runId).run();
    return result;
  } catch (error) {
    await env.DB.prepare("UPDATE lumen_v4_runs SET finished_at=?,status='FAILED',result_json=? WHERE id=?")
      .bind(iso(), JSON.stringify({ ok: false, error: clean(error.message,240) }), runId).run();
    throw error;
  }
}

async function bodyJson(request) {
  if (!request.body) throw new Error("json_body_required");
  const reader = request.body.getReader(); let size = 0; const chunks = [];
  for (;;) {
    const part = await reader.read(); if (part.done) break;
    size += part.value.byteLength;
    if (size > 16384) { await reader.cancel(); throw new Error("json_body_too_large"); }
    chunks.push(part.value);
  }
  const bytes = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  const value = JSON.parse(new TextDecoder().decode(bytes));
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("json_object_required");
  return value;
}
const json = (body, status = 200) => Response.json(body, { status, headers: { "cache-control": "no-store", "x-content-type-options": "nosniff" } });
export async function handleSovereign(request, env) {
  const url = new URL(request.url), path = url.pathname;
  if (!path.startsWith("/sovereign/")) return null;
  if (request.method === "GET" && path === "/sovereign/policy") return json({ ...V4_POLICY, protocolMesh: PROTOCOL_MESH_POLICY });
  if (!env.OPPORTUNITY_ADMIN_TOKEN || request.headers.get("x-lumen-admin") !== env.OPPORTUNITY_ADMIN_TOKEN)
    return json({ ok: false, error: "admin_token_required" }, 403);
  await ensureSovereignSchema(env);
  if (request.method === "GET" && path === "/sovereign/status") {
    const state = (await rows(env, "SELECT state_json,updated_at FROM lumen_v4_state WHERE id='GLOBAL'"))[0];
    const runs = await rows(env, "SELECT id,status,started_at,finished_at,json_extract(result_json,'$.error') error FROM lumen_v4_runs ORDER BY started_at DESC LIMIT 5");
    return json({ ok: true, version: V4_VERSION, initialized: Boolean(state), updatedAt: state?.updated_at, runs,
      state: state ? object(state.state_json) : null, approvals: await rows(env, "SELECT id,proposal_id,kind,status,scope_hash,expires_at,packet_json FROM lumen_v4_approvals ORDER BY created_at DESC LIMIT 30") });
  }
  if (request.method === "GET" && path === "/sovereign/memory") return json({ ok: true, cohort: await offerCohort(env, url.searchParams.get("offerId")) });
  if (request.method === "GET" && path === "/sovereign/autocoder/candidate") return json({ ok: true, candidate: await latestCodeCandidate(env) });
  if (request.method === "POST" && path === "/sovereign/run") {
    if (!env.LUMEN_DEEP_WORKFLOW) return json({ ok: false, error: "workflow_binding_missing" }, 503);
    return json({ ok: true, instanceId: await startDeepCycle(env, Date.now()), hourlyDeduplication: true }, 202);
  }
  if (request.method === "POST" && path === "/sovereign/verify") {
    if (!env.LUMEN_DEEP_WORKFLOW) return json({ ok: false, error: "workflow_binding_missing" }, 503);
    const releaseId = clean(env.LUMEN_V4_RELEASE_ID || "v4-scope2", 40).replace(/[^a-zA-Z0-9_-]/g, "-");
    const instanceId = `sovereign-verify-${releaseId}-${Math.floor(Date.now()/3600000)}`;
    await env.LUMEN_DEEP_WORKFLOW.createBatch([{ id: instanceId, params: { sovereignOnly: true, scheduledTime: Date.now() } }]);
    return json({ ok: true, instanceId, runId: `v4-${instanceId}`, hourlyDeduplication: true, sendsMessages: false }, 202);
  }
  if ((request.method === "POST" && ["/sovereign/goal", "/sovereign/protocol/prepare"].includes(path)) ||
      request.method === "POST" && /^\/sovereign\/approvals\/V4-AP-[a-f0-9]{64}\/decision$/.test(path)) {
    let body; try { body = await bodyJson(request); } catch { return json({ ok: false, error: "invalid_or_oversized_json" }, 400); }
    if (path === "/sovereign/goal") {
      let goal; try { goal = validateGoal(body); } catch (error) { return json({ ok: false, error: error.message }, 400); }
      await env.DB.prepare("INSERT INTO lumen_v4_goals VALUES('GLOBAL',?,?) ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,goal_json=excluded.goal_json").bind(iso(), JSON.stringify(goal)).run();
      return json({ ok: true, goal });
    }
    if (path === "/sovereign/protocol/prepare") {
      try { return json({ ok: true, envelope: prepareProtocolEnvelope(body.protocol, body.task) }); }
      catch (error) { return json({ ok: false, error: error.message }, 400); }
    }
    const decision = await decideApproval(env, path.split("/")[3], body); return json(decision.result, decision.status);
  }
  return json({ ok: false, error: "not_found" }, 404);
}
