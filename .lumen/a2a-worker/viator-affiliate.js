const VERSION = "1.0-viator-affiliate-cloudflare";
const DEFAULT_PID = "P00322694";
const DEFAULT_MCID = "42383";
const DEFAULT_MEDIUM = "link";
const DEFAULT_MEDIUM_VERSION = "selector";

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

function clean(value, limit = 4000) {
  return String(value ?? "").trim().slice(0, limit);
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

export async function handleViatorAffiliate(request, env) {
  const url = new URL(request.url);
  if (!["/health/viator-affiliate", "/go/viator", "/viator/affiliate-link", "/viator/affiliate-batch"].includes(url.pathname)) return null;

  const config = configFromEnv(env);

  if (url.pathname === "/health/viator-affiliate" && request.method === "GET") {
    return json({ ok: Boolean(config.pid), provider: "viator", version: VERSION, mode: "affiliate-link-generation", networkCalls: 0, pidConfigured: Boolean(config.pid) });
  }

  if (url.pathname === "/go/viator" && request.method === "GET") {
    try {
      const target = buildViatorAffiliateUrl(url.searchParams.get("url") || "", config);
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
      return json({ ok: true, provider: "viator", originalUrl: clean(payload?.url, 4000), affiliateUrl: target, monetized: true, version: VERSION });
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
