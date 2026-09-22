import app from "./experiment_worker.js";

const RETRYABLE_PATHS = new Set([
  "/health",
  "/api/data",
  "/api/full-state",
  "/api/recovery-state",
  "/api/experiments",
]);

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isRetryable(request) {
  if (request.method !== "GET") return false;
  const url = new URL(request.url);
  return RETRYABLE_PATHS.has(url.pathname);
}

export default {
  async fetch(request, env, ctx) {
    if (!isRetryable(request)) return app.fetch(request, env, ctx);

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
        return new Response(response.body, {
          status: response.status,
          statusText: response.statusText,
          headers,
        });
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
