import adaptive from "./adaptive-entry.js";
import { withBudgetedAi } from "./ai-router.js";
import { DEEP_CRON, PAID_BOOST_POLICY, ensureBoostSchema, startDeepCycle } from "./paid-boost-runtime.js";
import { handleSovereign } from "./sovereign-runtime.js";
import { handleRevenueLoopV5 } from "./revenue-loop-v5.js";
import { FIRST_SETTLEMENT_MISSION_POLICY, getFirstSettlementMissionStatus } from "./first-settlement-mission-v1.js";
import { RESPONSE_CLOSER_POLICY, getResponseCloserStatus } from "./response-closer-v1.js";
import { handleFirstCashCloser } from "./first-cash-closer.js";
import { runSupplierMarketLaunchEvolution } from "./supplier-market-launch.js";
export { LumenDeepWorkflow, LumenOpportunityWorkflow } from "./paid-boost-workflows.js";

function adminAuthorized(request, env) {
  const expected = env.OPPORTUNITY_ADMIN_TOKEN;
  return Boolean(expected && request.headers.get("x-lumen-admin") === expected);
}

export async function handleResponseCloser(request, env) {
  const url = new URL(request.url), path = url.pathname;
  if (!path.startsWith("/response-closer/")) return null;
  if (request.method === "GET" && path === "/response-closer/policy") return Response.json(RESPONSE_CLOSER_POLICY);
  if (!adminAuthorized(request, env)) return Response.json({ ok:false, error:"admin_token_required" }, { status:403 });
  if (request.method === "GET" && path === "/response-closer/status") {
    return Response.json(await getResponseCloserStatus(env, url.searchParams.get("opportunity_id")), { headers:{ "cache-control":"no-store" } });
  }
  return Response.json({ ok:false, error:"not_found" }, { status:404 });
}

export async function handleFirstSettlementMission(request, env) {
  const path = new URL(request.url).pathname;
  if (!path.startsWith("/first-settlement/")) return null;
  if (request.method === "GET" && path === "/first-settlement/policy") return Response.json(FIRST_SETTLEMENT_MISSION_POLICY);
  if (!adminAuthorized(request, env)) return Response.json({ ok: false, error: "admin_token_required" }, { status: 403 });
  if (request.method === "GET" && path === "/first-settlement/status") {
    const status = await getFirstSettlementMissionStatus(env);
    return Response.json(status, { headers: { "cache-control": "no-store" } });
  }
  return Response.json({ ok: false, error: "not_found" }, { status: 404 });
}

export async function handlePaidBoost(request, env) {
  const path = new URL(request.url).pathname;
  if (!path.startsWith("/paid-boost/")) return null;
  if (request.method === "GET" && path === "/paid-boost/policy") return Response.json(PAID_BOOST_POLICY);
  if (!adminAuthorized(request, env)) return Response.json({ ok: false, error: "admin_token_required" }, { status: 403 });
  if (request.method === "GET" && path === "/paid-boost/status") {
    await ensureBoostSchema(env);
    const runs = await env.DB.prepare("SELECT * FROM lumen_paid_boost_runs ORDER BY updated_at DESC LIMIT 15").all();
    const opportunities = await env.DB.prepare("SELECT stage,COUNT(*) count FROM lumen_paid_boost_opportunities GROUP BY stage").all();
    const ai = await env.DB.prepare("SELECT calls,reserved_neurons,updated_at FROM lumen_paid_boost_ai_usage WHERE day=?").bind(new Date().toISOString().slice(0,10)).first().catch(() => null);
    return Response.json({ ok: true, version: PAID_BOOST_POLICY.version, workflowBindingsReady: Boolean(env.LUMEN_DEEP_WORKFLOW && env.LUMEN_OPPORTUNITY_WORKFLOW), runs: runs.results, opportunities: opportunities.results, ai }, { headers: { "cache-control":"no-store" } });
  }
  if (request.method === "POST" && path === "/paid-boost/deep/run") {
    if (!env.LUMEN_DEEP_WORKFLOW) return Response.json({ ok: false, error: "workflow_binding_missing" }, { status: 503 });
    const id = await startDeepCycle(env, Date.now());
    return Response.json({ ok: true, instanceId: id, hourlyDeduplication: true }, { status: 202 });
  }
  return Response.json({ ok: false, error: "not_found" }, { status: 404 });
}

export default {
  async fetch(request, env, ctx) {
    const responseCloser = await handleResponseCloser(request, env);
    if (responseCloser) return responseCloser;
    const firstSettlementResponse = await handleFirstSettlementMission(request, env);
    if (firstSettlementResponse) return firstSettlementResponse;
    const firstCashResponse = await handleFirstCashCloser(request, env);
    if (firstCashResponse) return firstCashResponse;
    const v5Response = await handleRevenueLoopV5(request, env);
    if (v5Response) return v5Response;
    const sovereignResponse = await handleSovereign(request, env);
    if (sovereignResponse) return sovereignResponse;
    const response = await handlePaidBoost(request, env);
    return response || adaptive.fetch(request, withBudgetedAi(env), ctx);
  },
  async scheduled(controller, env, ctx) {
    if (!env.LUMEN_DEEP_WORKFLOW || !env.LUMEN_OPPORTUNITY_WORKFLOW) throw new Error("paid_boost_workflow_bindings_required");
    if (controller.cron === DEEP_CRON) { ctx.waitUntil(startDeepCycle(env, controller.scheduledTime)); return; }
    const minute = new Date(Number(controller?.scheduledTime || Date.now())).getUTCMinutes();
    if (minute === 7) ctx.waitUntil(runSupplierMarketLaunchEvolution(env));
    return adaptive.scheduled(controller, { ...withBudgetedAi(env), LUMEN_DEEP_WORKFLOW_MANAGED: true }, ctx);
  }
};