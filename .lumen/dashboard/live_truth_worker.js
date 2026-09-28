import base from "./live_data_worker.js";
import stable from "./stable_worker.js";

const SOURCE = "legacy-verification+live-d1-commercial";

function n(value) {
  const parsed = Number(value || 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function requestFor(request, pathname) {
  const url = new URL(request.url);
  url.pathname = pathname;
  url.search = "";
  return new Request(url.toString(), { method: "GET", headers: request.headers });
}

async function asJson(response) {
  if (!response?.ok) return null;
  try {
    return await response.json();
  } catch {
    return null;
  }
}

async function mergedData(request, env, ctx) {
  const legacyResponse = await stable.fetch(requestFor(request, "/api/data"), env, ctx);
  const legacy = await asJson(legacyResponse);

  const controlResponse = await stable.fetch(requestFor(request, "/api/control-tower-v2"), env, ctx);
  const control = await asJson(controlResponse);

  if (!legacy && !control) return base.fetch(request, env, ctx);
  if (!legacy) return base.fetch(request, env, ctx);
  if (!control) return legacyResponse;

  const live = control.funnel || {};
  const oldFunnel = legacy.funnel || {};
  const proposals = n(live.drafts) + n(live.approved) + n(live.sentProposals) + n(live.respondedProposals);

  const merged = {
    ...legacy,
    source: SOURCE,
    status: {
      ...(legacy.status || {}),
      updated_at: control.generatedAt || legacy.status?.updated_at || null,
      last_tick: control.generatedAt || legacy.status?.last_tick || null,
      last_origin: "D1+A2A live commercial truth",
    },
    funnel: {
      ...oldFunnel,
      // Keep historically verified company/contact inventory from the canonical snapshot.
      verified: n(oldFunnel.verified),
      buyers: n(oldFunnel.buyers),
      suppliers: n(oldFunnel.suppliers),
      contacts: n(oldFunnel.contacts),
      // Overlay downstream commercial truth from the live D1 pipeline.
      demand: n(live.demand),
      opportunities: n(live.actionable),
      proposals,
      close_ready: n(live.negotiating),
      outbound_sent: n(live.outreachSent),
      inbound: n(live.outreachResponded),
    },
    live_commercial: {
      generated_at: control.generatedAt || null,
      action_state: control.actionState || null,
      best_action: control.bestAction || null,
      waiting: n(live.waiting),
      due_followups: n(live.dueFollowups),
      negotiating: n(live.negotiating),
      followups_sent: n(live.followupsSent),
      settlements: n(live.settlements),
      realized_revenue_usd: n(live.realizedRevenueUsd),
    },
  };

  return Response.json(merged, {
    headers: {
      "cache-control": "no-store, no-cache, must-revalidate",
      "x-content-type-options": "nosniff",
      "x-lumen-data-source": "merged-live-commercial-v1",
    },
  });
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/api/data") {
      return mergedData(request, env, ctx);
    }
    return base.fetch(request, env, ctx);
  },
};
