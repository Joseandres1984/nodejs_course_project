import app from "./live_data_worker.js";

// Redeploy marker: keep the tokenized Instagram command flow and verified Gmail health active together.
async function hmacHex(secret, value) {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(String(secret || "")),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(value));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function withCommandTokens(rows, env) {
  const secret = String(env.LUMEN_DASHBOARD_PASSWORD || "");
  const out = [];
  for (const row of Array.isArray(rows) ? rows : []) {
    const approve = await hmacHex(secret, `${row.job_id}|${row.fingerprint}|approve`);
    const reject = await hmacHex(secret, `${row.job_id}|${row.fingerprint}|reject`);
    out.push({ ...row, approve_token: approve, reject_token: reject });
  }
  return out;
}

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

function argentinaReleasedSearchCap(now = new Date()) {
  const hourText = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Argentina/Buenos_Aires",
    hour: "2-digit",
    hourCycle: "h23",
  }).format(now);
  const hour = Number(hourText);
  if (hour < 6) return 4;
  if (hour < 12) return 10;
  if (hour < 18) return 17;
  return 24;
}

function withSearchBudgetTruth(scout) {
  const current = scout && typeof scout === "object" ? scout : {};
  const reportedHardCap = Math.max(0, Number(current.hard_cap || 0));

  // Once the A2A backend publishes a real quota meter, trust it and stop adapting it here.
  if (reportedHardCap > 0) return current;

  const releasedCap = argentinaReleasedSearchCap();
  const used = Math.max(0, Number(current.used ?? current.demand_used ?? 0));
  const demandUsed = Math.max(0, Number(current.demand_used ?? used));
  const effectiveUsed = Math.max(used, demandUsed);
  const remaining = Math.max(0, releasedCap - effectiveUsed);

  return {
    ...current,
    provider: current.provider || "A2A + TED + UK Contracts Finder",
    used: effectiveUsed,
    remaining,
    hard_cap: 24,
    released_cap: releasedCap,
    general_used: Math.max(0, Number(current.general_used || 0)),
    demand_used: demandUsed,
    budget_exhausted: remaining <= 0,
    budget_source: "argentina_staged_internal_cap",
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
      data.instagram_posts = await withCommandTokens(data.instagram_posts, env);
      data.scout = withSearchBudgetTruth(data.scout);
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
        owner_email_fallback: gmail.live,
        owner_email_fallback_status: gmail.live ? "available_via_gmail" : "unavailable",
        owner_email_fallback_source: gmail.source,
      };
      return jsonResponse(data, response, {
        "x-lumen-public-health-source": "service-binding",
        "x-lumen-gmail-status-source": "a2a-channel-health",
        "x-lumen-search-budget-source": data.scout?.budget_source || "a2a-backend",
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