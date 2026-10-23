import { page } from "./page.mjs";
import { client } from "./client.mjs";
import { validateLead, qualifyLead } from "./qualification.mjs";

const json = (data, status = 200) => new Response(JSON.stringify(data), {
  status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store",
    "x-content-type-options": "nosniff", "referrer-policy": "no-referrer" }
});
const securePageHeaders = {
  "content-type": "text/html; charset=utf-8",
  "content-security-policy": "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
  "x-content-type-options": "nosniff", "referrer-policy": "no-referrer",
  "x-frame-options": "DENY", "cache-control": "no-store"
};
function enabled(env) {
  return env.SUBMISSIONS_ENABLED === "true" && Boolean(env.LEADFLOW_DB &&
    env.LEADFLOW_ADMIN_TOKEN && env.LEADFLOW_RATE_SALT && env.PRIVACY_EMAIL);
}
function validToken(expected, supplied) {
  if (!expected || !supplied || typeof supplied !== "string") return false;
  let mismatch = expected.length ^ supplied.length;
  const length = Math.max(expected.length, supplied.length);
  for (let i = 0; i < length; i++) mismatch |= (expected.charCodeAt(i) || 0) ^ (supplied.charCodeAt(i) || 0);
  return mismatch === 0;
}
async function enforceRateLimit(request, env) {
  const ip = request.headers.get("CF-Connecting-IP") || "unknown";
  const input = new TextEncoder().encode(env.LEADFLOW_RATE_SALT + ":" + ip);
  const digest = await crypto.subtle.digest("SHA-256", input);
  const key = [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, "0")).join("");
  const now = Math.floor(Date.now() / 1000);
  const resetAt = now + 3600;
  await env.LEADFLOW_DB.prepare(
    "INSERT INTO rate_limit (key, hits, reset_at) VALUES (?, 1, ?) " +
    "ON CONFLICT(key) DO UPDATE SET hits=CASE WHEN reset_at <= ? THEN 1 ELSE hits + 1 END, " +
    "reset_at=CASE WHEN reset_at <= ? THEN ? ELSE reset_at END"
  ).bind(key, resetAt, now, now, resetAt).run();
  const count = await env.LEADFLOW_DB.prepare("SELECT hits FROM rate_limit WHERE key=?").bind(key).first();
  return Number(count?.hits || 0) <= 10;
}
async function notify(env, lead) {
  if (!env.NOTIFY_WEBHOOK_URL && !env.NOTIFY_WEBHOOK_TOKEN) return "not_configured";
  if (!env.NOTIFY_WEBHOOK_URL || !env.NOTIFY_WEBHOOK_TOKEN) return "failed";
  try {
    const url = new URL(env.NOTIFY_WEBHOOK_URL);
    if (url.protocol !== "https:" || url.username || url.password) return "failed";
    const response = await fetch(url.toString(), {
      method: "POST",
      headers: { "content-type": "application/json", "authorization": "Bearer " + env.NOTIFY_WEBHOOK_TOKEN },
      body: JSON.stringify({ event: "lead.created", service: "lumen-leadflow", lead }),
      signal: AbortSignal.timeout(5000)
    });
    return response.ok ? "sent" : "failed";
  } catch { return "failed"; }
}
async function handleSubmission(request, env) {
  if (!enabled(env)) return json({ ok: false, error: "Captación deshabilitada. Solo se permite la simulación." }, 503);
  const origin = request.headers.get("origin");
  if (origin && origin !== new URL(request.url).origin) return json({ ok: false, error: "Origen no autorizado." }, 403);
  if (!(request.headers.get("content-type") || "").toLowerCase().startsWith("application/json")) {
    return json({ ok: false, error: "Se requiere JSON." }, 415);
  }
  const advertised = Number(request.headers.get("content-length") || 0);
  if (advertised > 4096) return json({ ok: false, error: "Solicitud demasiado extensa." }, 413);
  let raw;
  try { raw = await request.text(); } catch { return json({ ok: false, error: "Solicitud inválida." }, 400); }
  if (raw.length > 4096) return json({ ok: false, error: "Solicitud demasiado extensa." }, 413);
  let payload;
  try { payload = JSON.parse(raw); } catch { return json({ ok: false, error: "JSON inválido." }, 400); }
  const { lead, error } = validateLead(payload);
  if (error) return json({ ok: false, error }, 422);
  if (lead.website) return json({ ok: true, saved: false }, 202);
  if (!(await enforceRateLimit(request, env))) return json({ ok: false, error: "Demasiadas solicitudes. Probá más tarde." }, 429);
  const id = crypto.randomUUID();
  const qualification = qualifyLead(lead);
  const createdAt = new Date().toISOString();
  await env.LEADFLOW_DB.prepare(
    "INSERT INTO leads (id, created_at, name, email, area, budget_ars, operation, property_type, timeframe, priority, consent_version, notification_status) " +
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'v1', 'not_configured')"
  ).bind(id, createdAt, lead.name, lead.email, lead.area, lead.budget, lead.operation,
    lead.propertyType, lead.timeframe, qualification.priority).run();
  const notice = await notify(env, { id, createdAt, ...lead, website: undefined, consent: undefined,
    priority: qualification.priority });
  if (notice !== "not_configured") {
    await env.LEADFLOW_DB.prepare("UPDATE leads SET notification_status=? WHERE id=?").bind(notice, id).run();
  }
  return json({ ok: true, saved: true, id, priority: qualification.priority, notification: notice }, 201);
}
async function admin(request, env, path) {
  if (!env.LEADFLOW_DB || !env.LEADFLOW_ADMIN_TOKEN) return json({ ok: false }, 503);
  const supplied = (request.headers.get("authorization") || "").replace(/^Bearer /i, "");
  if (!validToken(env.LEADFLOW_ADMIN_TOKEN, supplied)) return json({ ok: false, error: "No autorizado." }, 401);
  if (path === "/api/admin/leads" && request.method === "GET") {
    const result = await env.LEADFLOW_DB.prepare(
      "SELECT id, created_at, name, email, area, budget_ars, operation, property_type, timeframe, priority, notification_status FROM leads ORDER BY created_at DESC LIMIT 100"
    ).all();
    return json({ ok: true, leads: result.results || [] });
  }
  const match = path.match(/^\/api\/admin\/leads\/([0-9a-f-]{36})$/);
  if (match && request.method === "DELETE") {
    await env.LEADFLOW_DB.prepare("DELETE FROM leads WHERE id=?").bind(match[1]).run();
    return json({ ok: true });
  }
  return json({ ok: false, error: "No encontrado." }, 404);
}
export default {
  async fetch(request, env = {}) {
    const path = new URL(request.url).pathname;
    try {
      if (path === "/" && request.method === "GET") return new Response(page, { headers: securePageHeaders });
      if (path === "/client.js" && request.method === "GET") return new Response(client, {
        headers: { "content-type": "text/javascript; charset=utf-8", "x-content-type-options": "nosniff", "cache-control": "public, max-age=600" }
      });
      if (path === "/health" && request.method === "GET") return json({ ok: true, service: "lumen-leadflow" });
      if (path === "/api/status" && request.method === "GET") return json({
        ok: true, submissionsEnabled: enabled(env), privacyEmail: env.PRIVACY_EMAIL || null,
        mode: enabled(env) ? "captacion_habilitada" : "demo_sin_guardado"
      });
      if (path === "/api/leads" && request.method === "POST") return await handleSubmission(request, env);
      if (path.startsWith("/api/admin/")) return await admin(request, env, path);
      return json({ ok: false, error: "No encontrado." }, 404);
    } catch {
      return json({ ok: false, error: "Error interno. No reintentes sin verificar el resultado." }, 500);
    }
  },
  async scheduled(_event, env = {}) {
    if (!env.LEADFLOW_DB) return;
    const now = Math.floor(Date.now() / 1000);
    await env.LEADFLOW_DB.prepare("DELETE FROM rate_limit WHERE reset_at < ?").bind(now).run();
    const retention = Math.max(1, Math.min(365, Number(env.RETENTION_DAYS) || 90));
    const cutoff = new Date(Date.now() - retention * 86400000).toISOString();
    await env.LEADFLOW_DB.prepare("DELETE FROM leads WHERE created_at < ?").bind(cutoff).run();
  }
};
