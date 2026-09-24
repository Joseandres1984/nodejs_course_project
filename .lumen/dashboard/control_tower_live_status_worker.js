import base from "./sales_followup_worker.js";

async function serviceJson(env, path) {
  try {
    if (!env?.A2A) return null;
    const response = await env.A2A.fetch(new Request(`https://lumen-a2a.internal${path}`, { method: "GET", headers: { accept: "application/json" } }));
    return response.ok ? await response.json() : null;
  } catch { return null; }
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/api/control-tower-v2") {
      const response = await base.fetch(request, env, ctx);
      if (!response.ok || !String(response.headers.get("content-type") || "").includes("application/json")) return response;
      const data = await response.json();
      const [health, outreach, followup] = await Promise.all([
        serviceJson(env, "/health"),
        serviceJson(env, "/outreach/stats"),
        serviceJson(env, "/followup/stats"),
      ]);
      data.system = {
        ...(data.system || {}),
        a2aOnline: health?.ok === true,
        x402: health?.x402 || data.system?.x402 || "UNKNOWN",
        outreachAutonomous: outreach?.autonomousOutreachEnabled === true,
        followupAutonomous: followup?.autonomousFollowupEnabled === true,
        cooldownDays: Number(followup?.cooldownDays || data.system?.cooldownDays || 4),
        maxFollowups: Number(followup?.maxFollowups || data.system?.maxFollowups || 2),
      };
      return Response.json(data, { headers: { "cache-control": "no-store", "x-content-type-options": "nosniff" } });
    }
    return base.fetch(request, env, ctx);
  }
};
