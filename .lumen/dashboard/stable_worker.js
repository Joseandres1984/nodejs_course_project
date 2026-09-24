import app from "./network_control_tower_fix_worker.js";

const RETRYABLE_PATHS = new Set([
  "/health",
  "/api/data",
  "/api/full-state",
  "/api/recovery-state",
  "/api/experiments",
  "/api/control-tower-v2",
  "/api/network-control-v1",
]);

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isRetryable(request) {
  if (request.method !== "GET") return false;
  const url = new URL(request.url);
  return RETRYABLE_PATHS.has(url.pathname);
}

async function normalizeInjectedTabs(request, response) {
  if (request.method !== "GET" || response.status !== 200) return response;
  const url = new URL(request.url);
  if (!["/", "/index.html", "/full"].includes(url.pathname)) return response;
  if (!String(response.headers.get("content-type") || "").includes("text/html")) return response;

  let html = await response.text();
  html = html
    .replace(/data-p=(['"])experiments\1/g, 'data-tab="experiments"')
    .replace(/data-p=(['"])controlv2\1/g, 'data-tab="controlv2"')
    .replace(/data-p=(['"])networktower\1/g, 'data-tab="networktower"');

  const headers = new Headers(response.headers);
  headers.delete("content-length");
  headers.set("cache-control", "no-store");
  headers.set("x-lumen-tab-normalization", "v2");

  return new Response(html, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

export default {
  async fetch(request, env, ctx) {
    if (!isRetryable(request)) {
      return normalizeInjectedTabs(request, await app.fetch(request, env, ctx));
    }

    const delays = [0, 80, 180, 350, 700];
    let lastResponse = null;

    for (let attempt = 0; attempt < delays.length; attempt++) {
      if (delays[attempt]) await sleep(delays[attempt]);
      const response = await app.fetch(request, env, ctx);
      lastResponse = response;

      if (response.status !== 503) {
        const headers = new Headers(response.headers);
        headers.set("x-lumen-dashboard-read-attempts", String(attempt + 1));
        headers.set("x-lumen-dashboard-read-status", attempt === 0 ? "direct" : "recovered");
        return normalizeInjectedTabs(request, new Response(response.body, {
          status: response.status,
          statusText: response.statusText,
          headers,
        }));
      }
    }

    const headers = new Headers(lastResponse?.headers || {});
    headers.set("x-lumen-dashboard-read-attempts", String(delays.length));
    headers.set("x-lumen-dashboard-read-status", "persistent_503");
    return new Response(lastResponse?.body || "LUMEN state temporarily unavailable", {
      status: lastResponse?.status || 503,
      statusText: lastResponse?.statusText || "Service Unavailable",
      headers,
    });
  },
};