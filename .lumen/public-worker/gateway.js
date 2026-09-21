import core from "./worker.js";

const CONVERSION_BASE = "https://lumen-zero-conversion.lumen-b2b.workers.dev";
const X402_BASE = "https://lumen-zero-x402.lumen-b2b.workers.dev";

function publicUrl(origin, pathname, search="") {
  return `${origin}${pathname}${search || ""}`;
}

function rewriteLocation(raw, origin) {
  if (!raw) return raw;
  try {
    const u = new URL(raw);
    if (u.origin === CONVERSION_BASE) {
      const path = u.pathname === "/catalog" ? "/store" : u.pathname;
      return publicUrl(origin, path, u.search);
    }
    if (u.origin === X402_BASE) return publicUrl(origin, u.pathname, u.search);
  } catch (_) {}
  return raw;
}

function rewriteHtml(text, origin) {
  return String(text)
    .replaceAll(`${CONVERSION_BASE}/catalog`, `${origin}/store`)
    .replaceAll(CONVERSION_BASE, origin)
    .replaceAll(X402_BASE, origin)
    .replaceAll('href="/catalog"', 'href="/store"')
    .replaceAll('<a href="/services">Servicios</a>', '<a href="/services">Servicios</a><a href="/store">Comprar</a>');
}

async function normalizeResponse(upstream, origin, {rewriteBody=true}={}) {
  const headers = new Headers(upstream.headers);
  const location = headers.get("location");
  if (location) headers.set("location", rewriteLocation(location, origin));
  headers.set("x-lumen-public-gateway", "unified");

  const type = headers.get("content-type") || "";
  if (rewriteBody && type.includes("text/html")) {
    const text = rewriteHtml(await upstream.text(), origin);
    return new Response(text, {status:upstream.status, headers});
  }
  if (rewriteBody && type.includes("application/json")) {
    const text = rewriteHtml(await upstream.text(), origin);
    return new Response(text, {status:upstream.status, headers});
  }
  return new Response(upstream.body, {status:upstream.status, headers});
}

async function proxy(request, base, targetPath, origin, rewriteBody=true) {
  const incoming = new URL(request.url);
  const target = new URL(targetPath + incoming.search, base);
  const init = {
    method: request.method,
    headers: new Headers(request.headers),
    redirect: "manual",
  };
  if (!["GET","HEAD"].includes(request.method)) init.body = request.body;
  init.headers.set("x-lumen-public-origin", origin);
  const upstream = await fetch(new Request(target.toString(), init));
  return normalizeResponse(upstream, origin, {rewriteBody});
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";
    const origin = url.origin;

    // One human-facing storefront. Conversion remains an internal service.
    if (request.method === "GET" && (path === "/store" || path === "/catalog")) {
      return proxy(request, CONVERSION_BASE, "/catalog", origin, true);
    }
    if (request.method === "GET" && path === "/store.json") {
      return proxy(request, CONVERSION_BASE, "/catalog.json", origin, true);
    }
    if (/^\/offer\/[a-z0-9-]+$/.test(path) && request.method === "GET") {
      return proxy(request, CONVERSION_BASE, path, origin, true);
    }
    if (/^\/go\/[a-z0-9-]+$/.test(path) && request.method === "GET") {
      return proxy(request, CONVERSION_BASE, path, origin, false);
    }
    if (/^\/intent\/[a-z0-9-]+$/.test(path) && request.method === "POST") {
      return proxy(request, CONVERSION_BASE, path, origin, true);
    }

    // x402 stays behind the same visible public hostname.
    if (/^\/buy\/[a-z0-9-]+$/.test(path) && ["GET","POST"].includes(request.method)) {
      return proxy(request, X402_BASE, path, origin, false);
    }

    const response = await core.fetch(request, env, ctx);
    const type = response.headers.get("content-type") || "";
    if (request.method === "GET" && type.includes("text/html")) {
      return normalizeResponse(response, origin, {rewriteBody:true});
    }
    return response;
  }
};
