const VERSION = "1.0-channel-health";
const MAX_BODY_BYTES = 4096;
const FRESH_SECONDS = 2 * 60 * 60;
const ALLOWED_CHANNELS = new Set(["gmail"]);
const ALLOWED_STATUS = new Set(["online", "degraded", "offline"]);

function json(data, status = 200) {
  return Response.json(data, {
    status,
    headers: {
      "cache-control": "no-store, no-cache, must-revalidate",
      "x-content-type-options": "nosniff",
    },
  });
}

function clean(value, limit = 200) {
  return String(value ?? "").trim().slice(0, limit);
}

function bool(value) {
  return value === true;
}

async function ensureSchema(env) {
  if (!env?.DB) throw new Error("d1_binding_missing");
  await env.DB.prepare(
    "CREATE TABLE IF NOT EXISTS lumen_channel_health (channel TEXT PRIMARY KEY, status TEXT NOT NULL, provider TEXT, checked_at TEXT NOT NULL, details_json TEXT)"
  ).run();
}

function authorized(request, env) {
  const configured = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const provided = clean(request.headers.get("x-lumen-admin"), 500);
  return Boolean(configured && provided && configured === provided);
}

function safeDetails(input) {
  return {
    gmail_live: bool(input?.gmail_live),
    smtp_live: bool(input?.smtp_live),
    brevo_live: bool(input?.brevo_live),
    outbound_live: bool(input?.outbound_live),
    mail_live: bool(input?.mail_live),
    probe_message_sent: false,
  };
}

async function writeHealth(request, env) {
  if (!authorized(request, env)) return json({ ok: false, error: "admin_token_required" }, 403);
  const length = Number(request.headers.get("content-length") || 0);
  if (length > MAX_BODY_BYTES) return json({ ok: false, error: "payload_too_large" }, 413);

  let body;
  try {
    body = await request.json();
  } catch {
    return json({ ok: false, error: "invalid_json" }, 400);
  }

  const channel = clean(body?.channel, 40).toLowerCase();
  const status = clean(body?.status, 40).toLowerCase();
  const provider = clean(body?.provider, 80) || null;
  if (!ALLOWED_CHANNELS.has(channel)) return json({ ok: false, error: "unsupported_channel" }, 400);
  if (!ALLOWED_STATUS.has(status)) return json({ ok: false, error: "invalid_status" }, 400);

  const details = safeDetails(body?.details || {});
  if (details.probe_message_sent) return json({ ok: false, error: "probe_must_not_send" }, 400);
  const checkedAt = new Date().toISOString();

  await ensureSchema(env);
  await env.DB.prepare(
    "INSERT INTO lumen_channel_health(channel,status,provider,checked_at,details_json) VALUES(?,?,?,?,?) ON CONFLICT(channel) DO UPDATE SET status=excluded.status,provider=excluded.provider,checked_at=excluded.checked_at,details_json=excluded.details_json"
  ).bind(channel, status, provider, checkedAt, JSON.stringify(details)).run();

  return json({
    ok: true,
    version: VERSION,
    channel,
    status,
    provider,
    checkedAt,
    details,
  }, 202);
}

async function readHealth(env, channel) {
  if (!ALLOWED_CHANNELS.has(channel)) return json({ ok: false, error: "unsupported_channel" }, 404);
  await ensureSchema(env);
  const row = await env.DB.prepare(
    "SELECT channel,status,provider,checked_at,details_json FROM lumen_channel_health WHERE channel=? LIMIT 1"
  ).bind(channel).first();

  if (!row) {
    return json({
      ok: true,
      version: VERSION,
      channel,
      status: "unknown",
      provider: null,
      checkedAt: null,
      fresh: false,
      details: {},
    });
  }

  let details = {};
  try { details = JSON.parse(row.details_json || "{}"); } catch {}
  const ageSeconds = Math.max(0, Math.round((Date.now() - Date.parse(row.checked_at)) / 1000));
  const fresh = Number.isFinite(ageSeconds) && ageSeconds <= FRESH_SECONDS;

  return json({
    ok: true,
    version: VERSION,
    channel: row.channel,
    status: fresh ? row.status : "stale",
    recordedStatus: row.status,
    provider: row.provider || null,
    checkedAt: row.checked_at,
    ageSeconds,
    fresh,
    details: safeDetails(details),
  });
}

export async function handleChannelHealth(request, env) {
  const url = new URL(request.url);
  if (request.method === "POST" && url.pathname === "/channel-health") return writeHealth(request, env);
  if (request.method === "GET" && url.pathname.startsWith("/channel-health/")) {
    const channel = clean(url.pathname.split("/").filter(Boolean)[1], 40).toLowerCase();
    return readHealth(env, channel);
  }
  return null;
}
