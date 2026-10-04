import app from "./unified_decision_center_worker.js";

async function commercialDecisionCommands(env) {
  try {
    const result = await env.DB.prepare(
      "SELECT decision_key,object_id,action,processed,processed_at,result FROM lumen_owner_decision_commands WHERE decision_type='commercial_close' ORDER BY created_at DESC"
    ).all();
    return result.results || [];
  } catch {
    return [];
  }
}

function syncCommercialDecisionTruth(data, commands) {
  const rows = Array.isArray(commands) ? commands : [];
  const decidedIds = new Set(rows.map((row) => String(row?.object_id || "")).filter(Boolean));
  const sourceApprovals = Array.isArray(data?.approvals) ? data.approvals : [];
  const pendingApprovals = sourceApprovals.filter((approval) => !decidedIds.has(String(approval?.id || "")));
  const processing = rows.filter((row) => Number(row?.processed || 0) === 0).length;
  const processed = rows.filter((row) => Number(row?.processed || 0) === 1).length;

  data.money = data.money && typeof data.money === "object" ? data.money : {};
  data.money.pending_closures = pendingApprovals.length;
  data.money.decision_commands_processing = processing;
  data.money.decision_commands_processed = processed;
  data.approvals = pendingApprovals;
  data.decision_truth = {
    source: "lumen_owner_decision_commands",
    pending_human_decisions: pendingApprovals.length,
    commands_processing: processing,
    commands_processed: processed,
    synchronized: true,
  };
  return data;
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const upstream = await app.fetch(request, env, ctx);

    if (upstream.status === 401 || upstream.status === 503) return upstream;

    if (request.method === "GET" && url.pathname === "/api/data" && String(upstream.headers.get("content-type") || "").includes("application/json")) {
      try {
        const data = await upstream.json();
        const commands = await commercialDecisionCommands(env);
        const synced = syncCommercialDecisionTruth(data, commands);
        const headers = new Headers(upstream.headers);
        headers.delete("content-length");
        headers.set("cache-control", "no-store");
        headers.set("x-lumen-decision-truth-sync", "v1");
        return new Response(JSON.stringify(synced), { status: upstream.status, headers });
      } catch (error) {
        return new Response(JSON.stringify({ ok: false, error: "decision_truth_sync_failed", detail: String(error?.message || error).slice(0, 240) }), {
          status: 500,
          headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
        });
      }
    }

    return upstream;
  },
};
