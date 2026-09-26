const VERSION = "1.0-revenue-focus-controller";

function json(data, status = 200) {
  return Response.json(data, { status, headers: { "cache-control": "no-store", "x-content-type-options": "nosniff", "access-control-allow-origin": "*" } });
}
function num(v) { const n = Number(v); return Number.isFinite(n) ? n : 0; }
async function first(env, sql) { try { return await env.DB.prepare(sql).first(); } catch { return null; } }

export async function computeRevenueFocus(env) {
  if (!env?.DB) return { version: VERSION, mode: "NORMAL_DISCOVERY", backlog: {}, discoveryMultiplier: 1 };
  const q = await first(env, `SELECT
    (SELECT COUNT(*) FROM lumen_proposal_drafts WHERE quality_gate_status='PASS') pass_total,
    (SELECT COUNT(*) FROM lumen_proposal_drafts p LEFT JOIN lumen_outreach_attempts x ON x.proposal_id=p.proposal_id WHERE p.quality_gate_status='PASS' AND x.proposal_id IS NULL) pass_waiting_outreach,
    (SELECT COUNT(*) FROM lumen_sales_pipeline WHERE response_class IN ('PURCHASE_INTENT','COMMERCIAL_INTEREST','COMMERCIAL_QUESTION')) qualified_responses,
    (SELECT COUNT(*) FROM lumen_sales_pipeline WHERE response_class IN ('PURCHASE_INTENT','COMMERCIAL_INTEREST')) close_intent,
    (SELECT COUNT(*) FROM lumen_followups WHERE status IN ('PLANNED','READY','PENDING')) followups_ready,
    (SELECT COUNT(*) FROM lumen_revenue_attributions) verified_settlements`);
  const backlog = {
    passTotal: num(q?.pass_total),
    passWaitingOutreach: num(q?.pass_waiting_outreach),
    qualifiedResponses: num(q?.qualified_responses),
    closeIntent: num(q?.close_intent),
    followupsReady: num(q?.followups_ready),
    verifiedSettlements: num(q?.verified_settlements)
  };
  const conversionPressure = backlog.closeIntent * 5 + backlog.qualifiedResponses * 3 + backlog.passWaitingOutreach * 2 + Math.min(3, backlog.followupsReady);
  const mode = conversionPressure >= 5 ? "CONVERSION_FIRST" : conversionPressure >= 2 ? "BALANCED_CONVERSION" : "NORMAL_DISCOVERY";
  const discoveryMultiplier = mode === "CONVERSION_FIRST" ? 0.34 : mode === "BALANCED_CONVERSION" ? 0.67 : 1;
  return {
    version: VERSION,
    mode,
    conversionPressure,
    discoveryMultiplier,
    backlog,
    priority: backlog.closeIntent > 0 ? "CLOSE_INTENT" : backlog.qualifiedResponses > 0 ? "COMMERCIAL_REPLY" : backlog.followupsReady > 0 ? "FOLLOWUP" : backlog.passWaitingOutreach > 0 ? "QUALITY_PASS_OUTREACH" : "DISCOVERY",
    principle: "exploit_verified_commercial_inventory_before_expanding_search",
    guardrails: { maxAutonomousExternalCommercialMessagesPerHour: 1, autonomousSpendUsd: 0, verifiedRevenueOnly: true }
  };
}

export async function handleRevenueFocusController(request, env) {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/revenue-focus/state") return json(await computeRevenueFocus(env));
  if (request.method === "GET" && url.pathname === "/revenue-focus/policy") return json({ version: VERSION, objective: "prioritize_close_reply_followup_and_quality_pass_inventory_before_more_discovery", verifiedRevenueOnly: true, autonomousSpendUsd: 0, maxAutonomousExternalCommercialMessagesPerHour: 1 });
  return null;
}
