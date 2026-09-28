import app from "./live_data_worker.js";

async function serviceJson(binding, path) {
  try {
    if (!binding || typeof binding.fetch !== "function") return null;
    const response = await binding.fetch(new Request(`https://lumen-internal${path}`, {
      method: "GET",
      headers: { accept: "application/json" },
    }));
    if (!response.ok) return { ok: false, httpStatus: response.status };
    try {
      return await response.json();
    } catch {
      return { ok: false, error: "invalid_json" };
    }
  } catch (error) {
    return { ok: false, error: String(error?.message || error || "service_binding_failed").slice(0, 180) };
  }
}

async function publicWebStatus(env) {
  const health = await serviceJson(env?.PUBLIC, "/health");
  return health?.ok === true ? "online" : health?.httpStatus ? `http_${health.httpStatus}` : "unreachable";
}

async function x402DashboardStatus(env) {
  const health = await serviceJson(env?.X402, "/health");
  if (health?.ok === true && health?.x402 === "LIVE" && health?.recipientConfigured === true && health?.resourceServerInitialized === true) {
    return { status: "READY", live: true, source: "x402_service_binding" };
  }
  return {
    status: health?.x402 || (health?.httpStatus ? `HTTP_${health.httpStatus}` : "UNAVAILABLE"),
    live: false,
    source: "x402_service_binding",
  };
}

function jsonResponse(data, sourceResponse, extraHeaders = {}) {
  const headers = new Headers(sourceResponse.headers);
  headers.set("cache-control", "no-store, no-cache, must-revalidate");
  headers.set("x-content-type-options", "nosniff");
  for (const [key, value] of Object.entries(extraHeaders)) headers.set(key, value);
  return Response.json(data, { status: sourceResponse.status, headers });
}

export default {
  async fetch(request, env, ctx) {
    const response = await app.fetch(request, env, ctx);
    if (request.method !== "GET" || !response.ok) return response;

    const url = new URL(request.url);
    const type = String(response.headers.get("content-type") || "");
    if (!type.includes("application/json")) return response;

    if (url.pathname === "/api/data") {
      let data;
      try { data = await response.json(); } catch { return response; }
      data.services = data.services || {};
      data.services.public_web = {
        ...(data.services.public_web || {}),
        url: "https://lumen-zero-public.lumen-b2b.workers.dev",
        status: await publicWebStatus(env),
        probe: "service_binding",
      };
      return jsonResponse(data, response, { "x-lumen-public-health-source": "service-binding" });
    }

    if (url.pathname === "/api/control-tower-v2") {
      let data;
      try { data = await response.json(); } catch { return response; }
      const x402 = await x402DashboardStatus(env);
      data.system = {
        ...(data.system || {}),
        x402: x402.status,
        x402Live: x402.live,
        x402StatusSource: x402.source,
      };
      return jsonResponse(data, response, { "x-lumen-x402-status-source": "service-binding" });
    }

    return response;
  },
};
