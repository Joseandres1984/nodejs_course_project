const VERSION = "1.0-viator-partner-api";
const API_VERSION = "2.0";
const DEFAULT_LANGUAGE = "es-AR";
const DEFAULT_ENVIRONMENT = "sandbox";
const MAX_REQUEST_BODY_BYTES = 50000;

function clean(value, limit = 4000) {
  return String(value ?? "").trim().slice(0, limit);
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

function authorized(request, env) {
  const configured = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const provided = clean(request.headers.get("x-lumen-admin"), 500);
  return Boolean(configured && provided && configured === provided);
}

function apiEnvironment(env) {
  return clean(env?.VIATOR_API_ENV, 40).toLowerCase() === "production" ? "production" : DEFAULT_ENVIRONMENT;
}

function apiBase(env) {
  return apiEnvironment(env) === "production"
    ? "https://api.viator.com/partner"
    : "https://api.sandbox.viator.com/partner";
}

function apiLanguage(env) {
  return clean(env?.VIATOR_API_LANGUAGE, 40) || DEFAULT_LANGUAGE;
}

function apiKey(env) {
  return clean(env?.VIATOR_API_KEY, 500);
}

function campaignValue(env) {
  return clean(env?.VIATOR_API_CAMPAIGN_VALUE, 200) || "lumen-api";
}

function safeUpstreamError(payload, status) {
  const code = clean(payload?.code || payload?.error || `upstream_${status}`, 120);
  const message = clean(payload?.message || "Viator Partner API request failed", 300);
  const trackingId = clean(payload?.trackingId, 200) || null;
  return { code, message, trackingId };
}

export function getViatorApiStatus(env = {}) {
  const environment = apiEnvironment(env);
  return {
    ok: true,
    version: VERSION,
    provider: "viator",
    apiVersion: API_VERSION,
    configured: Boolean(apiKey(env)),
    environment,
    baseHost: environment === "production" ? "api.viator.com" : "api.sandbox.viator.com",
    language: apiLanguage(env),
    authentication: "exp-api-key",
    secretExposed: false,
    bookingAuthority: false,
    paymentAuthority: false,
    autonomousSpendUsd: 0,
    fallbackAvailable: true
  };
}

export async function viatorApiRequest(env, path, options = {}) {
  const key = apiKey(env);
  if (!key) {
    const error = new Error("viator_api_key_not_configured");
    error.status = 503;
    throw error;
  }

  const method = clean(options.method || "GET", 12).toUpperCase();
  const target = new URL(`${apiBase(env)}${path.startsWith("/") ? path : `/${path}`}`);
  const query = options.query && typeof options.query === "object" ? options.query : {};
  for (const [keyName, raw] of Object.entries(query)) {
    if (raw === undefined || raw === null || raw === "") continue;
    target.searchParams.set(keyName, clean(raw, 500));
  }

  const headers = {
    "exp-api-key": key,
    "Accept-Language": apiLanguage(env),
    "Accept": `application/json;version=${API_VERSION}`
  };

  const init = { method, headers };
  if (options.body !== undefined) {
    const encoded = JSON.stringify(options.body);
    if (encoded.length > MAX_REQUEST_BODY_BYTES) {
      const error = new Error("viator_api_request_body_too_large");
      error.status = 413;
      throw error;
    }
    headers["Content-Type"] = `application/json;version=${API_VERSION}`;
    init.body = encoded;
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);
  init.signal = controller.signal;

  let response;
  try {
    response = await fetch(target.toString(), init);
  } catch (error) {
    clearTimeout(timeout);
    const wrapped = new Error(error?.name === "AbortError" ? "viator_api_timeout" : "viator_api_network_error");
    wrapped.status = 502;
    throw wrapped;
  }
  clearTimeout(timeout);

  let payload = null;
  const text = await response.text();
  if (text) {
    try { payload = JSON.parse(text); }
    catch { payload = { message: clean(text, 500) }; }
  }

  if (!response.ok) {
    const details = safeUpstreamError(payload, response.status);
    const error = new Error(details.code);
    error.status = response.status;
    error.details = details;
    throw error;
  }

  return {
    ok: true,
    status: response.status,
    trackingId: clean(response.headers.get("x-unique-id"), 200) || null,
    rateLimitRemaining: clean(response.headers.get("ratelimit-remaining"), 100) || null,
    data: payload
  };
}

export async function getViatorDestinations(env) {
  return viatorApiRequest(env, "/destinations");
}

export async function searchViatorProducts(env, payload, options = {}) {
  const query = {};
  const campaign = clean(options.campaignValue || campaignValue(env), 200);
  if (campaign) query["campaign-value"] = campaign;
  return viatorApiRequest(env, "/products/search", { method: "POST", query, body: payload });
}

function summarizeDestinations(data, nameFilter = "") {
  const rows = Array.isArray(data) ? data : Array.isArray(data?.destinations) ? data.destinations : [];
  const needle = clean(nameFilter, 120).toLocaleLowerCase();
  const selected = needle
    ? rows.filter(item => clean(item?.name, 200).toLocaleLowerCase().includes(needle)).slice(0, 25)
    : rows.slice(0, 5);
  return {
    total: rows.length,
    matches: selected.map(item => ({
      destinationId: item?.destinationId ?? null,
      name: clean(item?.name, 200) || null,
      type: clean(item?.type, 80) || null,
      parentDestinationId: item?.parentDestinationId ?? null,
      defaultCurrencyCode: clean(item?.defaultCurrencyCode, 20) || null,
      timeZone: clean(item?.timeZone, 100) || null
    }))
  };
}

export async function handleViatorApi(request, env) {
  const url = new URL(request.url);
  const paths = [
    "/viator/api/status",
    "/viator/api/test",
    "/viator/api/destinations",
    "/viator/api/products/search"
  ];
  if (!paths.includes(url.pathname)) return null;

  if (request.method === "GET" && url.pathname === "/viator/api/status") {
    return json(getViatorApiStatus(env));
  }

  if (!authorized(request, env)) {
    return json({ ok: false, error: "unauthorized", version: VERSION }, 401);
  }

  if (request.method === "GET" && ["/viator/api/test", "/viator/api/destinations"].includes(url.pathname)) {
    try {
      const result = await getViatorDestinations(env);
      const summary = summarizeDestinations(result.data, url.searchParams.get("name") || "");
      return json({
        ok: true,
        version: VERSION,
        provider: "viator",
        environment: apiEnvironment(env),
        apiVersion: API_VERSION,
        configured: true,
        trackingId: result.trackingId,
        rateLimitRemaining: result.rateLimitRemaining,
        destinations: summary,
        secretExposed: false
      });
    } catch (error) {
      return json({
        ok: false,
        version: VERSION,
        provider: "viator",
        environment: apiEnvironment(env),
        configured: Boolean(apiKey(env)),
        error: clean(error?.message || error, 180),
        upstream: error?.details || null,
        secretExposed: false
      }, Number(error?.status || 502));
    }
  }

  if (request.method === "POST" && url.pathname === "/viator/api/products/search") {
    let payload = null;
    try { payload = await request.json(); } catch {}
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      return json({ ok: false, error: "valid_json_object_required", version: VERSION }, 400);
    }
    try {
      const result = await searchViatorProducts(env, payload, { campaignValue: url.searchParams.get("campaign") || undefined });
      return json({
        ok: true,
        version: VERSION,
        provider: "viator",
        environment: apiEnvironment(env),
        apiVersion: API_VERSION,
        trackingId: result.trackingId,
        rateLimitRemaining: result.rateLimitRemaining,
        data: result.data,
        affiliateAttributionSource: "viator_productUrl",
        secretExposed: false
      });
    } catch (error) {
      return json({
        ok: false,
        version: VERSION,
        provider: "viator",
        environment: apiEnvironment(env),
        configured: Boolean(apiKey(env)),
        error: clean(error?.message || error, 180),
        upstream: error?.details || null,
        secretExposed: false
      }, Number(error?.status || 502));
    }
  }

  return json({ ok: false, error: "method_not_allowed", version: VERSION }, 405);
}
