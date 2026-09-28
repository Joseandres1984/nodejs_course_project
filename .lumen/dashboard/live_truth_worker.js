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

async function gmailDashboardStatus(env) {
  const health = await serviceJson(env?.A2A, "/channel-health/gmail");
  const inboundLive = health?.details?.gmail_live === true;
  const outboundLive = health?.details?.outbound_live === true;
  const live = health?.ok === true && health?.fresh === true && health?.status === "online" && inboundLive && outboundLive;
  return {
    live,
    status: health?.status || (health?.httpStatus ? `http_${health.httpStatus}` : "unknown"),
    provider: health?.provider || "—",
    checkedAt: health?.checkedAt || null,
    fresh: health?.fresh === true,
    source: "a2a_channel_health",
    inboundLive,
    outboundLive,
    probeMessageSent: false,
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
      const [publicStatus, gmail] = await Promise.all([
        publicWebStatus(env),
        gmailDashboardStatus(env),
      ]);

      data.services = data.services || {};
      data.services.public_web = {
        ...(data.services.public_web || {}),
        url: "https://lumen-zero-public.lumen-b2b.workers.dev",
        status: publicStatus,
        probe: "service_binding",
      };
      data.services.gmail = {
        ...(data.services.gmail || {}),
        status: gmail.status,
        live: gmail.live,
        provider: gmail.provider,
        checked_at: gmail.checkedAt,
        fresh: gmail.fresh,
        imap_live: gmail.inboundLive,
        outbound_live: gmail.outboundLive,
        probe_message_sent: gmail.probeMessageSent,
        source: gmail.source,
      };
      data.outbound = {
        ...(data.outbound || {}),
        mail_ready: gmail.live,
        mail_provider: gmail.provider,
        mail_status: gmail.status,
        mail_checked_at: gmail.checkedAt,
        mail_status_source: gmail.source,
      };
      return jsonResponse(data, response, {
        "x-lumen-public-health-source": "service-binding",
        "x-lumen-gmail-status-source": "a2a-channel-health",
      });
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
