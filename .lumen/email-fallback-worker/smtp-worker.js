import { connect } from "cloudflare:sockets";

const VERSION = "1.0-guarded-smtp-corporate-email-fallback";
const MAX_FETCH_BYTES = 220000;
const FETCH_TIMEOUT_MS = 8000;
const SMTP_STEP_TIMEOUT_MS = 12000;
const SMTP_SESSION_TIMEOUT_MS = 30000;

const A2A_FALLBACK_STATUSES = new Set(["CARD_FETCH_FAILED", "INCOMPATIBLE", "AUTH_REQUIRED"]);
const BLOCKED_SOURCES = new Set(["ted_eu_public_procurement", "uk_contracts_finder"]);
const ROLE_LOCALPARTS = new Set([
  "info", "contact", "contacto", "sales", "ventas", "commercial", "comercial",
  "procurement", "purchasing", "compras", "suppliers", "proveedores", "rfq",
  "quotes", "cotizaciones", "business", "partnerships", "partners", "hello"
]);
const FREE_MAIL_DOMAINS = new Set([
  "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "outlook.com", "hotmail.com",
  "live.com", "icloud.com", "proton.me", "protonmail.com", "aol.com"
]);
const PLATFORM_HOST_SUFFIXES = [
  ".workers.dev", ".pages.dev", ".github.io", ".vercel.app", ".netlify.app", ".railway.app", ".up.railway.app"
];
const CONTACT_PATHS = ["/contact", "/contact-us", "/contacto", "/sales", "/commercial", "/about"];
const EMAIL_RE = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi;

function clean(value, limit = 5000) {
  return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit);
}

function json(data, status = 200) {
  return Response.json(data, {
    status,
    headers: {
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "access-control-allow-origin": "*"
    }
  });
}

function bool(value, fallback = false) {
  const text = clean(value, 20).toLowerCase();
  if (!text) return fallback;
  return ["1", "true", "yes", "on"].includes(text);
}

function safeParse(value, fallback = {}) {
  try { return JSON.parse(value || ""); } catch { return fallback; }
}

function authorized(request, env) {
  const configured = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const provided = clean(request.headers.get("x-lumen-admin"), 500);
  return Boolean(configured && provided && configured === provided);
}

function isHttps(value) {
  try { return new URL(value).protocol === "https:"; } catch { return false; }
}

function normalizedHost(value) {
  try { return (new URL(value).hostname || "").toLowerCase().replace(/^www\./, ""); } catch { return ""; }
}

function isPublicCorporateHost(host) {
  const value = clean(host, 260).toLowerCase().replace(/^www\./, "");
  if (!value || value === "localhost" || value.endsWith(".local")) return false;
  if (/^\d{1,3}(\.\d{1,3}){3}$/.test(value) || value.includes(":")) return false;
  if (PLATFORM_HOST_SUFFIXES.some(suffix => value.endsWith(suffix))) return false;
  return value.includes(".");
}

function normalizeLocal(local) {
  return clean(local, 120).toLowerCase().replace(/[._-]/g, "");
}

function isRoleEmail(value) {
  const email = clean(value, 320).toLowerCase().replace(/^[<({\[]+|[>)}\],;:.]+$/g, "");
  const at = email.lastIndexOf("@");
  if (at <= 0) return false;
  const local = email.slice(0, at);
  const domain = email.slice(at + 1).replace(/^www\./, "");
  if (!domain.includes(".") || FREE_MAIL_DOMAINS.has(domain)) return false;
  return ROLE_LOCALPARTS.has(local) || ROLE_LOCALPARTS.has(normalizeLocal(local));
}

function emailDomain(value) {
  const email = clean(value, 320).toLowerCase();
  const at = email.lastIndexOf("@");
  return at > 0 ? email.slice(at + 1).replace(/^www\./, "") : "";
}

function hostMatchesEmail(host, email) {
  const domain = emailDomain(email);
  const h = clean(host, 260).toLowerCase().replace(/^www\./, "");
  return Boolean(domain && h && (domain === h || domain.endsWith(`.${h}`) || h.endsWith(`.${domain}`)));
}

function decodeBasicEntities(text) {
  return String(text || "")
    .replace(/&#64;|&commat;/gi, "@")
    .replace(/&#46;|&period;/gi, ".")
    .replace(/&amp;/gi, "&");
}

function extractRoleEmails(text) {
  const found = decodeBasicEntities(text).match(EMAIL_RE) || [];
  return [...new Set(found.map(x => x.toLowerCase()).filter(isRoleEmail))];
}

function collectPublicStrings(value, depth = 0, out = []) {
  if (depth > 6 || out.length >= 250) return out;
  if (typeof value === "string") {
    out.push(value);
    return out;
  }
  if (Array.isArray(value)) {
    for (const item of value.slice(0, 80)) collectPublicStrings(item, depth + 1, out);
    return out;
  }
  if (value && typeof value === "object") {
    for (const [key, item] of Object.entries(value).slice(0, 100)) {
      if (/token|secret|password|authorization|cookie/i.test(key)) continue;
      collectPublicStrings(item, depth + 1, out);
    }
  }
  return out;
}

function collectWebsiteUrls(raw, endpoint) {
  const urls = [];
  const preferred = [
    raw?.provider?.url, raw?.provider?.website, raw?.organization?.url, raw?.organization?.website,
    raw?.website, raw?.homepage, raw?.homePage, raw?.contactUrl, raw?.contact_url
  ];
  for (const value of preferred) if (isHttps(value)) urls.push(clean(value, 1000));
  if (isHttps(endpoint)) urls.push(clean(endpoint, 1000));
  return [...new Set(urls)];
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_email_outreach_attempts (proposal_id TEXT PRIMARY KEY,opportunity_id TEXT NOT NULL,email TEXT,source_url TEXT,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,provider TEXT,provider_message_id TEXT,error TEXT,metadata_json TEXT)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_email_outreach_status ON lumen_email_outreach_attempts(status,updated_at)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_email_outreach_opportunity ON lumen_email_outreach_attempts(opportunity_id,updated_at)")
  ]);
  return true;
}

async function getCandidate(env) {
  const rows = await env.DB.prepare(
    "SELECT p.proposal_id,p.opportunity_id,p.subject,p.message,p.offer_id,p.offer_name,p.amount_usd,p.updated_at,o.name,o.source,o.endpoint,o.evidence,o.raw_json,x.status AS a2a_status " +
    "FROM lumen_proposal_drafts p " +
    "JOIN lumen_opportunities o ON o.id=p.opportunity_id " +
    "JOIN lumen_outreach_attempts x ON x.proposal_id=p.proposal_id " +
    "LEFT JOIN lumen_email_outreach_attempts e ON e.proposal_id=p.proposal_id " +
    "WHERE p.status='APPROVED' AND p.quality_gate_status='PASS' AND e.proposal_id IS NULL " +
    "ORDER BY p.updated_at ASC LIMIT 12"
  ).all();
  for (const row of rows.results || []) {
    if (BLOCKED_SOURCES.has(String(row.source || ""))) continue;
    if (!A2A_FALLBACK_STATUSES.has(String(row.a2a_status || ""))) continue;
    return row;
  }
  return null;
}

async function fetchTextSameHost(url, officialHost) {
  if (!isHttps(url) || !isPublicCorporateHost(officialHost)) return "";
  const host = normalizedHost(url);
  if (host !== officialHost && !host.endsWith(`.${officialHost}`)) return "";
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort("timeout"), FETCH_TIMEOUT_MS);
  try {
    const response = await fetch(url, {
      method: "GET",
      redirect: "manual",
      signal: controller.signal,
      headers: { "accept": "text/html,application/xhtml+xml,text/plain", "user-agent": `LUMEN-EmailFallback/${VERSION}` }
    });
    if (!response.ok || response.status >= 300) return "";
    const type = String(response.headers.get("content-type") || "").toLowerCase();
    if (!type.includes("text/html") && !type.includes("text/plain") && !type.includes("application/xhtml+xml")) return "";
    return (await response.text()).slice(0, MAX_FETCH_BYTES);
  } catch {
    return "";
  } finally {
    clearTimeout(timer);
  }
}

async function discoverVerifiedRoleEmail(row) {
  const raw = safeParse(row.raw_json, {});
  const declaredEmails = extractRoleEmails(collectPublicStrings(raw).join("\n"));
  if (declaredEmails.length) {
    return { email: declaredEmails[0], sourceUrl: row.evidence || row.endpoint || null, method: "public_declared_metadata" };
  }

  const sites = collectWebsiteUrls(raw, row.endpoint);
  for (const site of sites.slice(0, 4)) {
    const host = normalizedHost(site);
    if (!isPublicCorporateHost(host)) continue;
    const root = `https://${host}`;
    const pages = [site, root, ...CONTACT_PATHS.map(path => `${root}${path}`)];
    for (const page of [...new Set(pages)].slice(0, 5)) {
      const text = await fetchTextSameHost(page, host);
      if (!text) continue;
      const emails = extractRoleEmails(text).filter(email => hostMatchesEmail(host, email));
      if (emails.length) return { email: emails[0], sourceUrl: page, method: "official_domain_public_page" };
    }
  }
  return null;
}

function normalizeEmailBody(row) {
  let body = String(row.message || "").trim();
  body = body.replace(/^Hi\s+[^\n]{1,220},\s*/i, "Hello,\n\n");
  const disclosure = [
    "—",
    "LUMEN B2B",
    "Automated commercial outreach using a public corporate role address.",
    "If you prefer no further messages from LUMEN, reply with 'unsubscribe'."
  ].join("\n");
  return `${body}\n\n${disclosure}`.slice(0, 5000);
}

function mailbox(value) {
  const match = String(value ?? "").match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i);
  return match ? match[0].toLowerCase() : "";
}

function smtpConfig(env) {
  const host = clean(env?.LUMEN_SMTP_HOST, 260).toLowerCase();
  const rawPort = Number(env?.LUMEN_SMTP_PORT || 587);
  const port = Number.isFinite(rawPort) ? Math.trunc(rawPort) : 587;
  const user = clean(env?.LUMEN_SMTP_USER, 320);
  const password = String(env?.LUMEN_SMTP_PASSWORD || "");
  const from = mailbox(env?.LUMEN_SMTP_FROM || user);
  const ssl = bool(env?.LUMEN_SMTP_SSL, port === 465);
  const validPort = port === 465 || port === 587;
  const configured = Boolean(host && user && password && from && validPort && host !== "localhost" && !host.endsWith(".local"));
  return { configured, host, port, user, password, from, ssl: port === 465 ? true : ssl };
}

function bytesToBase64(bytes) {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(binary);
}

function utf8Base64(value) {
  return bytesToBase64(new TextEncoder().encode(String(value ?? "")));
}

function plainAuthBase64(user, password) {
  return utf8Base64(`\u0000${user}\u0000${password}`);
}

function sanitizeHeader(value, limit = 180) {
  return String(value ?? "").replace(/[\r\n]+/g, " ").trim().slice(0, limit);
}

function normalizeCrlf(value) {
  return String(value ?? "").replace(/\r?\n/g, "\r\n");
}

function dotStuff(value) {
  return normalizeCrlf(value).replace(/^\./gm, "..");
}

function messageIdDomain(from) {
  const domain = emailDomain(from);
  return domain || "lumen.local";
}

function renderMessage(from, target, subject, body) {
  const safeFrom = sanitizeHeader(from, 320);
  const safeTarget = sanitizeHeader(target, 320);
  const encodedSubject = `=?UTF-8?B?${utf8Base64(sanitizeHeader(subject || "LUMEN B2B commercial introduction", 180))}?=`;
  const messageId = `<lumen-${crypto.randomUUID()}@${messageIdDomain(safeFrom)}>`;
  return [
    `From: LUMEN B2B <${safeFrom}>`,
    `To: ${safeTarget}`,
    `Subject: ${encodedSubject}`,
    `Date: ${new Date().toUTCString()}`,
    `Message-ID: ${messageId}`,
    "MIME-Version: 1.0",
    "Content-Type: text/plain; charset=UTF-8",
    "Content-Transfer-Encoding: 8bit",
    "X-LUMEN-Automated: true",
    "",
    dotStuff(body)
  ].join("\r\n");
}

async function withTimeout(promise, ms, label) {
  let timer;
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`${label}_timeout`)), ms); })
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

function createSmtpChannel(socket) {
  let reader = socket.readable.getReader();
  let writer = socket.writable.getWriter();
  const decoder = new TextDecoder();
  const encoder = new TextEncoder();
  let buffer = "";

  async function writeRaw(text) {
    await withTimeout(writer.write(encoder.encode(text)), SMTP_STEP_TIMEOUT_MS, "smtp_write");
  }

  async function command(line) {
    await writeRaw(`${line}\r\n`);
  }

  async function response(allowedCodes) {
    const allowed = new Set(Array.isArray(allowedCodes) ? allowedCodes.map(Number) : [Number(allowedCodes)]);
    const lines = [];
    while (true) {
      const newline = buffer.indexOf("\n");
      if (newline < 0) {
        const chunk = await withTimeout(reader.read(), SMTP_STEP_TIMEOUT_MS, "smtp_read");
        if (chunk.done) throw new Error("smtp_connection_closed");
        buffer += decoder.decode(chunk.value, { stream: true });
        continue;
      }
      let line = buffer.slice(0, newline + 1);
      buffer = buffer.slice(newline + 1);
      line = line.replace(/\r?\n$/, "");
      lines.push(line);
      const match = /^(\d{3})([ -])(.*)$/.exec(line);
      if (!match) continue;
      const code = Number(match[1]);
      const separator = match[2];
      if (separator === "-") continue;
      if (!allowed.has(code)) throw new Error(`smtp_${code}:${clean(lines.join(" | "), 700)}`);
      return { code, lines, text: lines.join("\n") };
    }
  }

  function release() {
    try { reader.releaseLock(); } catch {}
    try { writer.releaseLock(); } catch {}
  }

  return { command, response, writeRaw, release };
}

async function openAuthenticatedSmtp(env) {
  const config = smtpConfig(env);
  if (!config.configured) throw new Error("smtp_not_configured");
  const secureTransport = config.port === 465 ? "on" : "starttls";
  let socket = connect({ hostname: config.host, port: config.port }, { secureTransport, allowHalfOpen: true });
  await withTimeout(socket.opened, SMTP_STEP_TIMEOUT_MS, "smtp_connect");
  let channel = createSmtpChannel(socket);
  await channel.response(220);
  await channel.command("EHLO lumen-b2b");
  let ehlo = await channel.response(250);

  if (config.port === 587) {
    if (!/STARTTLS/i.test(ehlo.text)) throw new Error("smtp_starttls_not_offered");
    await channel.command("STARTTLS");
    await channel.response(220);
    channel.release();
    socket = socket.startTls();
    await withTimeout(socket.opened, SMTP_STEP_TIMEOUT_MS, "smtp_tls_connect");
    channel = createSmtpChannel(socket);
    await channel.command("EHLO lumen-b2b");
    ehlo = await channel.response(250);
  }

  if (/AUTH[^\n]*(?:^|\s)PLAIN(?:\s|$)/im.test(ehlo.text)) {
    await channel.command(`AUTH PLAIN ${plainAuthBase64(config.user, config.password)}`);
    await channel.response(235);
  } else {
    await channel.command("AUTH LOGIN");
    await channel.response(334);
    await channel.command(utf8Base64(config.user));
    await channel.response(334);
    await channel.command(utf8Base64(config.password));
    await channel.response(235);
  }

  return { socket, channel, config };
}

async function closeSmtp(session) {
  try {
    await session.channel.command("QUIT");
    await session.channel.response([221, 250]);
  } catch {}
  try { session.channel.release(); } catch {}
  try { await session.socket.close(); } catch {}
}

async function smtpProbe(env) {
  const config = smtpConfig(env);
  if (!config.configured) return { ok: false, configured: false, authenticated: false, reason: "smtp_not_configured" };
  let session;
  try {
    session = await withTimeout(openAuthenticatedSmtp(env), SMTP_SESSION_TIMEOUT_MS, "smtp_session");
    return { ok: true, configured: true, authenticated: true, route: config.port === 465 ? "implicit_tls" : "starttls", port: config.port };
  } catch (error) {
    return { ok: false, configured: true, authenticated: false, reason: clean(error?.message || error, 400), port: config.port };
  } finally {
    if (session) await closeSmtp(session);
  }
}

async function sendSmtp(env, target, subject, body) {
  let session;
  try {
    session = await withTimeout(openAuthenticatedSmtp(env), SMTP_SESSION_TIMEOUT_MS, "smtp_session");
    const { channel, config } = session;
    await channel.command(`MAIL FROM:<${config.from}>`);
    await channel.response(250);
    await channel.command(`RCPT TO:<${target}>`);
    await channel.response([250, 251]);
    await channel.command("DATA");
    await channel.response(354);
    const message = renderMessage(config.from, target, subject, body);
    await channel.writeRaw(`${message}\r\n.\r\n`);
    const accepted = await channel.response(250);
    return {
      provider: "smtp_tls",
      messageId: clean(accepted.text, 300) || null,
      route: config.port === 465 ? "implicit_tls" : "starttls"
    };
  } finally {
    if (session) await closeSmtp(session);
  }
}

async function recordAttempt(env, row, contact, status, extra = {}) {
  const now = new Date().toISOString();
  await env.DB.prepare(
    "INSERT INTO lumen_email_outreach_attempts(proposal_id,opportunity_id,email,source_url,status,created_at,updated_at,provider,provider_message_id,error,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?) " +
    "ON CONFLICT(proposal_id) DO UPDATE SET email=excluded.email,source_url=excluded.source_url,status=excluded.status,updated_at=excluded.updated_at,provider=excluded.provider,provider_message_id=excluded.provider_message_id,error=excluded.error,metadata_json=excluded.metadata_json"
  ).bind(
    row.proposal_id, row.opportunity_id, contact?.email || null, contact?.sourceUrl || null, status, now, now,
    extra.provider || null, extra.messageId || null, extra.error || null,
    JSON.stringify({ version: VERSION, a2aStatus: row.a2a_status || null, contactMethod: contact?.method || null, source: row.source || null, route: extra.route || null })
  ).run();
}

function guardrails() {
  return {
    a2aFailureRequired: true,
    allowedA2aFailureStatuses: [...A2A_FALLBACK_STATUSES],
    publicCorporateRoleEmailsOnly: true,
    personalEmailInference: false,
    generatedEmailGuessing: false,
    freeMailDomainsAllowed: false,
    publicProcurementSolicitation: false,
    maxMessagesPerRun: 1,
    maxMessagesPerHour: 1,
    autonomousSpendUsd: 0,
    bindingActionsHumanGated: true,
    optOutDisclosure: true
  };
}

async function runFallback(env, meta = {}) {
  if (!(await ensureSchema(env))) return { ok: false, sent: false, reason: "persistence_unavailable", version: VERSION };
  if (!bool(env?.EMAIL_FALLBACK_ENABLED, false)) return { ok: true, sent: false, reason: "email_fallback_disabled", version: VERSION };
  if (!smtpConfig(env).configured) return { ok: true, sent: false, reason: "smtp_not_configured", version: VERSION };

  const row = await getCandidate(env);
  if (!row) return { ok: true, sent: false, sentCount: 0, reason: "no_eligible_a2a_failed_proposal", version: VERSION };

  const contact = await discoverVerifiedRoleEmail(row);
  if (!contact) {
    await recordAttempt(env, row, null, "NO_VERIFIED_ROLE_EMAIL", { error: "no_public_corporate_role_email_found" });
    return { ok: true, sent: false, sentCount: 0, reason: "no_verified_role_email", proposalId: row.proposal_id, version: VERSION };
  }

  try {
    const delivery = await sendSmtp(env, contact.email, row.subject, normalizeEmailBody(row));
    await recordAttempt(env, row, contact, "SENT", delivery);
    await env.DB.prepare("UPDATE lumen_proposal_drafts SET status='SENT',updated_at=? WHERE proposal_id=?")
      .bind(new Date().toISOString(), row.proposal_id).run();
    return {
      ok: true,
      sent: true,
      sentCount: 1,
      version: VERSION,
      trigger: clean(meta?.trigger || "manual", 80),
      proposalId: row.proposal_id,
      opportunityId: row.opportunity_id,
      provider: delivery.provider,
      contactMethod: contact.method,
      guardrails: guardrails()
    };
  } catch (error) {
    const message = clean(error?.message || error, 700);
    await recordAttempt(env, row, contact, "SEND_FAILED", { provider: "smtp_tls", error: message });
    return { ok: false, sent: false, sentCount: 0, reason: "send_failed", error: message, proposalId: row.proposal_id, version: VERSION };
  }
}

async function stats(env) {
  await ensureSchema(env);
  const rows = await env.DB.prepare("SELECT status,COUNT(*) AS n,MAX(updated_at) AS last_at FROM lumen_email_outreach_attempts GROUP BY status ORDER BY status").all();
  return rows.results || [];
}

function policy(env) {
  return {
    version: VERSION,
    enabled: bool(env?.EMAIL_FALLBACK_ENABLED, false),
    provider: "smtp_tls",
    schedule: "hourly_after_primary_a2a_slot",
    configured: smtpConfig(env).configured,
    ...guardrails()
  };
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") {
      return json({ ok: true, service: "lumen-zero-email-fallback", version: VERSION, ...(await smtpProbe(env)) });
    }
    if (request.method === "GET" && url.pathname === "/policy") return json(policy(env));
    if (request.method === "GET" && url.pathname === "/stats") return json({ version: VERSION, rows: await stats(env) });
    if (request.method === "POST" && url.pathname === "/run") {
      if (!authorized(request, env)) return json({ ok: false, error: "admin_token_required" }, 403);
      return json(await runFallback(env, { trigger: "admin" }), 202);
    }
    return json({ ok: false, error: "not_found" }, 404);
  },

  async scheduled(controller, env, ctx) {
    ctx.waitUntil(runFallback(env, { trigger: "cloudflare_cron", scheduledTime: controller?.scheduledTime || null }));
  }
};
