const WEBHOOK_PATH = "/instagram-webhook";
const MAX_BODY_BYTES = 256000;

function text(body, status = 200) {
  return new Response(body, {
    status,
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "no-referrer",
    },
  });
}

function hex(bytes) {
  return [...new Uint8Array(bytes)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function constantTimeEqual(a, b) {
  a = String(a || "");
  b = String(b || "");
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

async function verifySignature(raw, signatureHeader, appSecret) {
  if (!appSecret || !signatureHeader || !signatureHeader.startsWith("sha256=")) return false;
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(appSecret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const digest = await crypto.subtle.sign("HMAC", key, raw);
  return constantTimeEqual(`sha256=${hex(digest)}`, signatureHeader.toLowerCase());
}

async function ensureSchema(env) {
  await env.DB.prepare(
    "CREATE TABLE IF NOT EXISTS lumen_instagram_webhook_events (id TEXT PRIMARY KEY, received_at TEXT NOT NULL, event_object TEXT, entry_id TEXT, event_types TEXT, payload TEXT NOT NULL, processed INTEGER NOT NULL DEFAULT 0, processed_at TEXT)"
  ).run();
  await env.DB.prepare(
    "CREATE INDEX IF NOT EXISTS idx_lumen_instagram_webhook_pending ON lumen_instagram_webhook_events(processed, received_at)"
  ).run();
}

function summarizeEvent(payload) {
  const entries = Array.isArray(payload?.entry) ? payload.entry : [];
  const entryIds = entries.map((e) => String(e?.id || "")).filter(Boolean);
  const types = new Set();
  for (const entry of entries) {
    for (const change of Array.isArray(entry?.changes) ? entry.changes : []) {
      if (change?.field) types.add(String(change.field));
    }
    if (Array.isArray(entry?.messaging) && entry.messaging.length) types.add("messages");
  }
  return {
    object: String(payload?.object || ""),
    entryId: entryIds.join(",").slice(0, 500),
    eventTypes: [...types].join(",").slice(0, 500),
  };
}

async function handleVerification(request, env) {
  const url = new URL(request.url);
  const mode = url.searchParams.get("hub.mode") || "";
  const token = url.searchParams.get("hub.verify_token") || "";
  const challenge = url.searchParams.get("hub.challenge") || "";
  const expected = String(env.LUMEN_INSTAGRAM_WEBHOOK_VERIFY_TOKEN || "");
  if (!expected) return text("webhook_not_configured", 503);
  if (mode === "subscribe" && constantTimeEqual(token, expected) && challenge) return text(challenge, 200);
  return text("forbidden", 403);
}

async function handleEvent(request, env) {
  const appSecret = String(env.LUMEN_INSTAGRAM_APP_SECRET || "");
  if (!appSecret) return text("webhook_signature_not_configured", 503);

  const length = Number(request.headers.get("Content-Length") || 0);
  if (length > MAX_BODY_BYTES) return text("payload_too_large", 413);

  const raw = await request.arrayBuffer();
  if (raw.byteLength > MAX_BODY_BYTES) return text("payload_too_large", 413);

  const signature = request.headers.get("X-Hub-Signature-256") || "";
  if (!(await verifySignature(raw, signature, appSecret))) return text("invalid_signature", 401);

  let payload;
  try {
    payload = JSON.parse(new TextDecoder().decode(raw));
  } catch {
    return text("invalid_json", 400);
  }

  if (String(payload?.object || "") !== "instagram") return text("ignored", 200);

  await ensureSchema(env);
  const summary = summarizeEvent(payload);
  const now = new Date().toISOString();
  await env.DB.prepare(
    "INSERT INTO lumen_instagram_webhook_events(id, received_at, event_object, entry_id, event_types, payload, processed) VALUES (?, ?, ?, ?, ?, ?, 0)"
  ).bind(
    crypto.randomUUID(),
    now,
    summary.object,
    summary.entryId,
    summary.eventTypes,
    JSON.stringify(payload)
  ).run();

  return text("EVENT_RECEIVED", 200);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/health" && request.method === "GET") {
      return Response.json(
        { ok: true, service: "lumen-instagram-webhook", storage: "cloudflare-d1", signature_validation: true },
        { headers: { "Cache-Control": "no-store" } }
      );
    }
    if (url.pathname !== WEBHOOK_PATH) return text("not_found", 404);
    if (request.method === "GET") return handleVerification(request, env);
    if (request.method === "POST") return handleEvent(request, env);
    return text("method_not_allowed", 405);
  },
};
