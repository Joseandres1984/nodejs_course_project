const VERSION = "1.1-viator-affiliate-click-intelligence";
const DEFAULT_PID = "P00322694";
const DEFAULT_MCID = "42383";
const DEFAULT_MEDIUM = "link";
const DEFAULT_MEDIUM_VERSION = "selector";
const ALLOWED_EVENT_TYPES = new Set(["impression", "search", "click"]);

function json(data, status = 200) {
  return Response.json(data, {
    status,
    headers: {
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "access-control-allow-origin": "*",
      "access-control-allow-headers": "content-type,x-lumen-admin",
      "access-control-allow-methods": "GET,POST,OPTIONS"
    }
  });
}

function clean(value, limit = 4000) {
  return String(value ?? "").trim().slice(0, limit);
}

function dimension(value, limit = 160) {
  return clean(value, limit).replace(/[\r\n\t]/g, " ");
}

function isViatorHost(hostname) {
  const host = clean(hostname, 300).toLowerCase().replace(/\.$/, "");
  return host === "viator.com" || host.endsWith(".viator.com");
}

export function buildViatorAffiliateUrl(rawUrl, options = {}) {
  let raw = clean(rawUrl, 4000);
  if (!raw) throw new Error("viator_url_required");
  if (!raw.includes("://")) raw = `https://${raw.replace(/^\/+/, "")}`;

  let url;
  try { url = new URL(raw); }
  catch { throw new Error("invalid_viator_url"); }

  if (!["http:", "https:"].includes(url.protocol)) throw new Error("unsupported_viator_protocol");
  if (!isViatorHost(url.hostname)) throw new Error("only_viator_urls_allowed");
  if (url.username || url.password) throw new Error("credentials_not_allowed");
  if (url.port && !["80", "443"].includes(url.port)) throw new Error("unexpected_viator_port");

  const pid = clean(options.pid || DEFAULT_PID, 100);
  if (!pid) throw new Error("viator_affiliate_pid_missing");
  const mcid = clean(options.mcid || DEFAULT_MCID, 100) || DEFAULT_MCID;
  const medium = clean(options.medium || DEFAULT_MEDIUM, 100) || DEFAULT_MEDIUM;
  const mediumVersion = clean(options.mediumVersion || DEFAULT_MEDIUM_VERSION, 100) || DEFAULT_MEDIUM_VERSION;

  for (const key of ["pid", "mcid", "medium", "medium_version"]) url.searchParams.delete(key);
  url.searchParams.set("pid", pid);
  url.searchParams.set("mcid", mcid);
  url.searchParams.set("medium", medium);
  url.searchParams.set("medium_version", mediumVersion);
  url.protocol = "https:";
  url.port = "";
  return url.toString();
}

function configFromEnv(env) {
  return {
    pid: clean(env?.LUMEN_VIATOR_AFFILIATE_PID || DEFAULT_PID, 100),
    mcid: clean(env?.LUMEN_VIATOR_MCID || DEFAULT_MCID, 100),
    medium: clean(env?.LUMEN_VIATOR_MEDIUM || DEFAULT_MEDIUM, 100),
    mediumVersion: clean(env?.LUMEN_VIATOR_MEDIUM_VERSION || DEFAULT_MEDIUM_VERSION, 100)
  };
}

function authorized(request, env) {
  const configured = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const provided = clean(request.headers.get("x-lumen-admin"), 500);
  return Boolean(configured && provided && configured === provided);
}

async function ensureTravelAnalyticsSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_travel_events (id TEXT PRIMARY KEY,event_type TEXT NOT NULL,provider TEXT NOT NULL DEFAULT 'viator',source TEXT,campaign TEXT,variant TEXT,destination TEXT,product_id TEXT,target_url TEXT,created_at TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_travel_events_type_created ON lumen_travel_events(event_type,created_at DESC)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_travel_events_source_created ON lumen_travel_events(source,created_at DESC)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_travel_events_destination_created ON lumen_travel_events(destination,created_at DESC)")
  ]);
  return true;
}

function eventDimensions(input = {}) {
  return {
    source: dimension(input.source || "direct", 120) || "direct",
    campaign: dimension(input.campaign || "", 160),
    variant: dimension(input.variant || "", 120),
    destination: dimension(input.destination || "", 160),
    productId: dimension(input.product_id || input.productId || "", 180)
  };
}

async function recordTravelEvent(env, eventType, input = {}, targetUrl = "") {
  if (!ALLOWED_EVENT_TYPES.has(eventType) || !env?.DB) return false;
  await ensureTravelAnalyticsSchema(env);
  const d = eventDimensions(input);
  await env.DB.prepare("INSERT INTO lumen_travel_events(id,event_type,provider,source,campaign,variant,destination,product_id,target_url,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)")
    .bind(
      crypto.randomUUID(),
      eventType,
      "viator",
      d.source,
      d.campaign,
      d.variant,
      d.destination,
      d.productId,
      clean(targetUrl, 4000),
      new Date().toISOString()
    ).run();
  return true;
}

export async function handleViatorAffiliate(request, env) {
  const url = new URL(request.url);
  if (!["/health/viator-affiliate", "/go/viator", "/travel/event", "/viator/affiliate-link", "/viator/affiliate-batch"].includes(url.pathname)) return null;

  if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: {
    "access-control-allow-origin": "*",
    "access-control-allow-headers": "content-type,x-lumen-admin",
    "access-control-allow-methods": "GET,POST,OPTIONS",
    "access-control-max-age": "86400"
  }});

  const config = configFromEnv(env);

  if (url.pathname === "/health/viator-affiliate" && request.method === "GET") {
    let analyticsReady = false;
    try { analyticsReady = await ensureTravelAnalyticsSchema(env); } catch {}
    return json({ ok: Boolean(config.pid), provider: "viator", version: VERSION, mode: "affiliate-link-generation+click-intelligence", networkCalls: 0, pidConfigured: Boolean(config.pid), analyticsReady });
  }

  if (url.pathname === "/travel/event" && request.method === "POST") {
    let payload = {};
    try { payload = await request.json(); } catch {}
    const eventType = dimension(payload?.eventType || payload?.event_type || "", 40).toLowerCase();
    if (!ALLOWED_EVENT_TYPES.has(eventType) || eventType === "click") return json({ ok: false, error: "event_type_not_allowed" }, 400);
    try {
      await recordTravelEvent(env, eventType, payload, "");
      return json({ ok: true, eventType, provider: "viator", version: VERSION });
    } catch {
      return json({ ok: false, error: "analytics_unavailable" }, 503);
    }
  }

  if (url.pathname === "/go/viator" && request.method === "GET") {
    try {
      const target = buildViatorAffiliateUrl(url.searchParams.get("url") || "", config);
      try {
        await recordTravelEvent(env, "click", Object.fromEntries(url.searchParams.entries()), target);
      } catch {
        // Analytics must never block a monetized redirect.
      }
      return Response.redirect(target, 307);
    } catch (error) {
      return json({ ok: false, error: clean(error?.message || error, 180) }, 400);
    }
  }

  if (!authorized(request, env)) return json({ ok: false, error: "unauthorized" }, 401);

  if (url.pathname === "/viator/affiliate-link" && request.method === "POST") {
    let payload = {};
    try { payload = await request.json(); } catch {}
    try {
      const target = buildViatorAffiliateUrl(payload?.url || "", config);
      return json({ ok: true, provider: "viator", originalUrl: clean(payload?.url, 4000), affiliateUrl: target, monetized: true, trackingEndpoint: "/go/viator", version: VERSION });
    } catch (error) {
      return json({ ok: false, error: clean(error?.message || error, 180) }, 400);
    }
  }

  if (url.pathname === "/viator/affiliate-batch" && request.method === "POST") {
    let payload = {};
    try { payload = await request.json(); } catch {}
    const urls = Array.isArray(payload?.urls) ? payload.urls.slice(0, 20) : [];
    if (!urls.length) return json({ ok: false, error: "urls_required" }, 400);
    const results = urls.map(raw => {
      try { return { originalUrl: clean(raw, 4000), affiliateUrl: buildViatorAffiliateUrl(raw, config), monetized: true }; }
      catch (error) { return { originalUrl: clean(raw, 4000), affiliateUrl: null, monetized: false, error: clean(error?.message || error, 180) }; }
    });
    return json({ ok: true, provider: "viator", results, version: VERSION });
  }

  return json({ ok: false, error: "method_not_allowed" }, 405);
}
