const VERSION = "1.0-guarded-corporate-email-fallback";
const MAX_FETCH_BYTES = 220000;
const FETCH_TIMEOUT_MS = 8000;
const SEND_TIMEOUT_MS = 15000;
const MAIL_HEALTH_FRESH_MS = 6 * 60 * 60 * 1000;

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

async function readMailHealth(env) {
  try {
    const row = await env.DB.prepare("SELECT status,provider,checked_at,details_json FROM lumen_channel_health WHERE channel='gmail' LIMIT 1").first();
    if (!row) return { ok: false, reason: "mail_health_missing" };
    const checked = Date.parse(String(row.checked_at || ""));
    const fresh = Number.isFinite(checked) && Date.now() - checked <= MAIL_HEALTH_FRESH_MS;
    const details = safeParse(row.details_json, {});
    const outboundLive = details?.outbound_live === true || details?.mail_live === true;
    return {
      ok: fresh && outboundLive && ["online", "degraded"].includes(String(row.status || "").toLowerCase()),
      fresh,
      outboundLive,
      status: row.status || null,
      provider: row.provider || null,
      checkedAt: row.checked_at || null,
      reason: fresh ? (outboundLive ? null : "outbound_mail_not_live") : "mail_health_stale"
    };
  } catch {
    return { ok: false, reason: "mail_health_unavailable" };
  }
}

function brevoReady(env) {
  return Boolean(
    bool(env?.EMAIL_FALLBACK_ENABLED, false) &&
    clean(env?.LUMEN_BREVO_API_KEY, 500) &&
    clean(env?.LUMEN_BREVO_FROM_EMAIL, 320) &&
    bool(env?.LUMEN_BREVO_SENDER_VERIFIED, false)
  );
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
  if (normalizedHost(url) !== officialHost && !normalizedHost(url).endsWith(`.${officialHost}`)) return "";
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
    const text = await response.text();
    return text.slice(0, MAX_FETCH_BYTES);
  } catch {
    return "";
  } finally {
    clearTimeout(timer);
  }
}

async function discoverVerifiedRoleEmail(row) {
  const raw = safeParse(row.raw_json, {});
  const declaredStrings = collectPublicStrings(raw);
  const declaredEmails = extractRoleEmails(declaredStrings.join("\n"));
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

async function sendBrevo(env, target, subject, body) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort("timeout"), SEND_TIMEOUT_MS);
  try {
    const response = await fetch("https://api.brevo.com/v3/smtp/email", {
      method: "POST",
      signal: controller.signal,
      headers: {
        "content-type": "application/json",
        "accept": "application/json",
        "api-key": clean(env.LUMEN_BREVO_API_KEY, 500)
      },
      body: JSON.stringify({
        sender: {
          email: clean(env.LUMEN_BREVO_FROM_EMAIL, 320),
          name: clean(env?.LUMEN_BREVO_FROM_NAME || "LUMEN B2B", 120)
        },
        to: [{ email: target }],
        subject: clean(subject || "LUMEN B2B commercial introduction", 180),
        textContent: body
      })
    });
    const text = await response.text();
    if (!response.ok) throw new Error(`brevo_http_${response.status}:${clean(text, 400)}`);
    const parsed = safeParse(text, {});
    return { provider: "brevo", messageId: clean(parsed?.messageId || parsed?.message_id, 300) || null };
  } finally {
    clearTimeout(timer);
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
    JSON.stringify({ version: VERSION, a2aStatus: row.a2a_status || null, contactMethod: contact?.method || null, source: row.source || null })
  ).run();
}

async function runFallback(env, meta = {}) {
  if (!(await ensureSchema(env))) return { ok: false, sent: false, reason: "persistence_unavailable" };
  if (!bool(env?.EMAIL_FALLBACK_ENABLED, false)) return { ok: true, sent: false, reason: "email_fallback_disabled", version: VERSION };
  if (!brevoReady(env)) return { ok: true, sent: false, reason: "brevo_not_ready", version: VERSION };

  const health = await readMailHealth(env);
  if (!health.ok) return { ok: true, sent: false, reason: health.reason || "mail_health_not_ready", mailHealth: health, version: VERSION };

  const maxPerRun = Math.max(1, Math.min(1, Number(env?.EMAIL_FALLBACK_MAX_PER_RUN || 1) || 1));
  let sent = 0;
  const results = [];
  while (sent < maxPerRun) {
    const row = await getCandidate(env);
    if (!row) break;
    const contact = await discoverVerifiedRoleEmail(row);
    if (!contact) {
      await recordAttempt(env, row, null, "NO_VERIFIED_ROLE_EMAIL", { error: "no_public_corporate_role_email_found" });
      results.push({ proposalId: row.proposal_id, sent: false, reason: "no_verified_role_email" });
      continue;
    }

    try {
      const delivery = await sendBrevo(env, contact.email, row.subject, normalizeEmailBody(row));
      await recordAttempt(env, row, contact, "SENT", delivery);
      await env.DB.prepare("UPDATE lumen_proposal_drafts SET status='SENT',updated_at=? WHERE proposal_id=?")
        .bind(new Date().toISOString(), row.proposal_id).run();
      sent += 1;
      results.push({ proposalId: row.proposal_id, opportunityId: row.opportunity_id, sent: true, provider: delivery.provider, contactMethod: contact.method });
    } catch (error) {
      const message = clean(error?.message || error, 700);
      await recordAttempt(env, row, contact, "SEND_FAILED", { provider: "brevo", error: message });
      results.push({ proposalId: row.proposal_id, sent: false, reason: "send_failed", error: message });
      break;
    }
  }

  return {
    ok: true,
    sent: sent > 0,
    sentCount: sent,
    version: VERSION,
    trigger: clean(meta?.trigger || "manual", 80),
    results,
    guardrails: {
      a2aFailureRequired: true,
      allowedA2aFailureStatuses: [...A2A_FALLBACK_STATUSES],
      publicCorporateRoleEmailsOnly: true,
      personalEmailInference: false,
      freeMailDomainsAllowed: false,
      publicProcurementSolicitation: false,
      maxMessagesPerRun: 1,
      autonomousSpendUsd: 0,
      bindingActionsHumanGated: true
    }
  };
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
    schedule: "hourly_after_primary_a2a_slot",
    a2aFailureRequired: true,
    allowedA2aFailureStatuses: [...A2A_FALLBACK_STATUSES],
    verifiedCorporateRoleEmailOnly: true,
    declaredMetadataOrOfficialDomainEvidenceOnly: true,
    personalEmailInference: false,
    generatedEmailGuessing: false,
    publicProcurementSourcesExcluded: [...BLOCKED_SOURCES],
    freeMailDomainsAllowed: false,
    provider: "brevo_https_api",
    maxExternalMessagesPerRun: 1,
    autonomousSpendUsd: 0,
    autonomousPurchase: false,
    autonomousContract: false,
    bindingActionsHumanGated: true
  };
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") {
      const mailHealth = env?.DB ? await readMailHealth(env) : { ok: false, reason: "db_missing" };
      return json({ ok: true, service: "lumen-zero-email-fallback", version: VERSION, configured: brevoReady(env), mailHealth });
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
