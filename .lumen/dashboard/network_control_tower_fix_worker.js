import base from "./network_control_tower_worker.js";

function n(v) { return Number(v || 0); }

export default {
  async fetch(request, env, ctx) {
    const response = await base.fetch(request, env, ctx);
    const url = new URL(request.url);
    if (request.method !== "GET" || url.pathname !== "/api/network-control-v1" || !response.ok) return response;

    let data;
    try { data = await response.json(); } catch { return response; }

    const redundancy = data?.redundancy || {};
    const module = Array.isArray(data?.modules) ? data.modules.find(x => Number(x?.id) === 13) : null;
    if (module) {
      module.metric = `${n(redundancy.readyAlternates)} fallbacks listos`;
      module.detail = `${n(redundancy.weakAlternates)} débiles`;
    }

    return Response.json(data, {
      status: response.status,
      headers: {
        "cache-control": "no-store",
        "x-content-type-options": "nosniff",
        "x-lumen-network-tower-fix": "redundancy-v1"
      }
    });
  }
};
