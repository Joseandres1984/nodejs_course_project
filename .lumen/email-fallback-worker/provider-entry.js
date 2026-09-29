import baseWorker from "./worker.js";

const VERSION = "1.1-provider-health-gate";
const PROBE_TIMEOUT_MS = 10000;

function clean(value, limit = 500) {
  return String(value ?? "").trim().slice(0, limit);
}

function safeParse(value, fallback = {}) {
  try { return JSON.parse(value || ""); } catch { return fallback; }
}

async function fetchJson(url, apiKey) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort("timeout"), PROBE_TIMEOUT_MS);
  try {
    const response = await fetch(url, {
      method: "GET",
      headers: { "accept": "application/json", "api-key": apiKey },
      signal: controller.signal
    });
    const text = await response.text();
    if (!response.ok) return { ok: false, status: response.status, body: safeParse(text, {}) };
    return { ok: true, status: response.status, body: safeParse(text, {}) };
  } catch (error) {
    return { ok: false, status: 0, error: clean(error?.message || error, 300) };
  } finally {
    clearTimeout(timer);
  }
}

async function probeBrevo(env) {
  const apiKey = clean(env?.LUMEN_BREVO_API_KEY, 500);
  const fromEmail = clean(env?.LUMEN_BREVO_FROM_EMAIL, 320).toLowerCase();
  const senderFlag = clean(env?.LUMEN_BREVO_SENDER_VERIFIED, 20).toLowerCase() === "true";
  if (!apiKey || !fromEmail || !senderFlag) {
    return { ok: false, provider: "brevo", reason: "brevo_configuration_incomplete", senderVerified: false };
  }

  const account = await fetchJson("https://api.brevo.com/v3/account", apiKey);
  if (!account.ok) {
    return { ok: false, provider: "brevo", reason: `brevo_account_probe_${account.status || "failed"}`, senderVerified: false };
  }

  const senders = await fetchJson("https://api.brevo.com/v3/senders", apiKey);
  if (!senders.ok) {
    return { ok: false, provider: "brevo", reason: `brevo_sender_probe_${senders.status || "failed"}`, senderVerified: false };
  }

  const rows = Array.isArray(senders.body?.senders) ? senders.body.senders : [];
  const match = rows.find(row => clean(row?.email, 320).toLowerCase() === fromEmail);
  const active = Boolean(match?.active);
  return {
    ok: active,
    provider: "brevo",
    reason: active ? null : "brevo_sender_not_active",
    senderVerified: active,
    senderId: active ? (match?.id ?? null) : null
  };
}

async function ensureHealthSchema(env) {
  await env.DB.prepare(
    "CREATE TABLE IF NOT EXISTS lumen_channel_health (channel TEXT PRIMARY KEY, status TEXT NOT NULL, provider TEXT, checked_at TEXT NOT NULL, details_json TEXT)"
  ).run();
}

async function refreshOutboundHealth(env) {
  if (!env?.DB) return { ok: false, reason: "d1_binding_missing" };
  await ensureHealthSchema(env);

  const previous = await env.DB.prepare(
    "SELECT status,provider,checked_at,details_json FROM lumen_channel_health WHERE channel='gmail' LIMIT 1"
  ).first();
  const previousDetails = safeParse(previous?.details_json, {});
  const gmailLive = previousDetails?.gmail_live === true;

  const probe = await probeBrevo(env);
  const details = {
    gmail_live: gmailLive,
    smtp_live: false,
    brevo_live: probe.ok,
    outbound_live: probe.ok,
    mail_live: gmailLive && probe.ok,
    probe_message_sent: false,
    provider_health_version: VERSION,
    provider_reason: probe.reason || null
  };
  const status = probe.ok ? (gmailLive ? "online" : "degraded") : "offline";
  const now = new Date().toISOString();

  await env.DB.prepare(
    "INSERT INTO lumen_channel_health(channel,status,provider,checked_at,details_json) VALUES('gmail',?,?,?,?) " +
    "ON CONFLICT(channel) DO UPDATE SET status=excluded.status,provider=excluded.provider,checked_at=excluded.checked_at,details_json=excluded.details_json"
  ).bind(status, "brevo", now, JSON.stringify(details)).run();

  return { ok: probe.ok, status, provider: "brevo", checkedAt: now, senderVerified: probe.senderVerified, reason: probe.reason || null };
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if ((request.method === "GET" && url.pathname === "/health") || (request.method === "POST" && url.pathname === "/run")) {
      await refreshOutboundHealth(env);
    }
    return baseWorker.fetch(request, env, ctx);
  },

  async scheduled(controller, env, ctx) {
    await refreshOutboundHealth(env);
    return baseWorker.scheduled(controller, env, ctx);
  }
};
