import core from "./worker.js";

const CONVERSION_BASE = "https://lumen-zero-conversion.lumen-b2b.workers.dev";
const X402_BASE = "https://lumen-zero-x402.lumen-b2b.workers.dev";
const CONVERSION_INTERNAL = "https://conversion.internal";
const X402_INTERNAL = "https://x402.internal";

function publicUrl(origin, pathname, search="") {
  return `${origin}${pathname}${search || ""}`;
}

function rewriteLocation(raw, origin) {
  if (!raw) return raw;
  try {
    const u = new URL(raw);
    if (u.origin === CONVERSION_BASE || u.origin === CONVERSION_INTERNAL) {
      const path = u.pathname === "/catalog" ? "/store" : u.pathname;
      return publicUrl(origin, path, u.search);
    }
    if (u.origin === X402_BASE || u.origin === X402_INTERNAL) return publicUrl(origin, u.pathname, u.search);
  } catch (_) {}
  return raw;
}

function rewriteText(text, origin) {
  return String(text)
    .replaceAll(`${CONVERSION_BASE}/catalog`, `${origin}/store`)
    .replaceAll(`${CONVERSION_INTERNAL}/catalog`, `${origin}/store`)
    .replaceAll(CONVERSION_BASE, origin)
    .replaceAll(CONVERSION_INTERNAL, origin)
    .replaceAll(X402_BASE, origin)
    .replaceAll(X402_INTERNAL, origin)
    .replaceAll('href="/catalog"', 'href="/store"')
    .replaceAll('<a href="/services">Servicios</a>', '<a href="/services">Servicios</a><a href="/store">Comprar</a>')
    .replaceAll('<a class="cta" href="/services">Ver servicios</a>', '<a class="cta" href="/services">Ver servicios</a> <a class="cta" href="/store">Comprar intelligence</a>');
}

function base64ToUtf8(raw) {
  let s = String(raw || "").replace(/-/g,"+").replace(/_/g,"/");
  while (s.length % 4) s += "=";
  const binary = atob(s);
  const bytes = Uint8Array.from(binary, c => c.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}
function utf8ToBase64(text, urlSafe=false) {
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  for (let i=0;i<bytes.length;i+=0x8000) binary += String.fromCharCode(...bytes.subarray(i,i+0x8000));
  let out = btoa(binary);
  if (urlSafe) out = out.replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/g,"");
  return out;
}
function rewriteEncodedHeader(raw, origin) {
  if (!raw) return raw;
  try {
    const decoded = base64ToUtf8(raw);
    if (!decoded.trim().startsWith("{")) return raw;
    const rewritten = rewriteText(decoded, origin);
    const urlSafe = raw.includes("-") || raw.includes("_");
    return utf8ToBase64(rewritten, urlSafe);
  } catch (_) {
    return raw;
  }
}

async function normalizeResponse(upstream, origin, {rewriteBody=true}={}) {
  const headers = new Headers(upstream.headers);
  const location = headers.get("location");
  if (location) headers.set("location", rewriteLocation(location, origin));
  for (const name of ["payment-required","x-payment-required","payment-response","x-payment-response"]) {
    const value = headers.get(name);
    if (value) headers.set(name, rewriteEncodedHeader(value, origin));
  }
  headers.set("x-lumen-public-gateway", "unified");

  const type = headers.get("content-type") || "";
  if (rewriteBody && (type.includes("text/html") || type.includes("application/json") || type.includes("text/plain"))) {
    const text = rewriteText(await upstream.text(), origin);
    return new Response(text, {status:upstream.status, headers});
  }
  return new Response(upstream.body, {status:upstream.status, headers});
}

async function proxyBinding(request, binding, requestBase, targetPath, origin, rewriteBody=true) {
  if (!binding || typeof binding.fetch !== "function") {
    return Response.json({ok:false,error:"internal_service_unavailable"},{status:503});
  }
  const incoming = new URL(request.url);
  const target = new URL(targetPath + incoming.search, requestBase);
  const headers = new Headers(request.headers);
  headers.set("x-lumen-public-origin", origin);
  const init = {method:request.method,headers,redirect:"manual"};
  if (!["GET","HEAD"].includes(request.method)) init.body = request.body;
  const upstream = await binding.fetch(new Request(target.toString(), init));
  return normalizeResponse(upstream, origin, {rewriteBody});
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";
    const origin = url.origin;

    if (request.method === "GET" && (path === "/store" || path === "/catalog")) {
      return proxyBinding(request, env.CONVERSION, CONVERSION_INTERNAL, "/catalog", origin, true);
    }
    if (request.method === "GET" && path === "/store.json") {
      return proxyBinding(request, env.CONVERSION, CONVERSION_INTERNAL, "/catalog.json", origin, true);
    }
    if (/^\/offer\/[a-z0-9-]+$/.test(path) && request.method === "GET") {
      return proxyBinding(request, env.CONVERSION, CONVERSION_INTERNAL, path, origin, true);
    }
    if (/^\/go\/[a-z0-9-]+$/.test(path) && request.method === "GET") {
      return proxyBinding(request, env.CONVERSION, CONVERSION_INTERNAL, path, origin, false);
    }
    if (/^\/intent\/[a-z0-9-]+$/.test(path) && request.method === "POST") {
      return proxyBinding(request, env.CONVERSION, CONVERSION_INTERNAL, path, origin, true);
    }

    // Service Binding handles transport, while x402 sees the real public resource URL.
    if (/^\/buy\/[a-z0-9-]+$/.test(path) && ["GET","POST"].includes(request.method)) {
      return proxyBinding(request, env.X402, origin, path, origin, true);
    }

    const response = await core.fetch(request, env, ctx);
    const type = response.headers.get("content-type") || "";
    if (request.method === "GET" && type.includes("text/html")) {
      return normalizeResponse(response, origin, {rewriteBody:true});
    }
    return response;
  }
};
