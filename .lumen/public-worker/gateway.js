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

function humanCheckout(text, origin) {
  let out = String(text)
    .replaceAll("<title>Payment Required</title>", "<title>LUMEN Checkout</title>")
    .replaceAll(">Payment Required<", ">LUMEN Checkout<")
    .replaceAll("Select a wallet", "Elegir billetera")
    .replaceAll("Connect wallet", "Conectar y pagar")
    .replaceAll("USD Coin", "USDC")
    .replace(/LUMEN ([^.<]{1,120}) machine-intelligence purchase\. To access this content, please pay \$([0-9.]+) USDC\./g,
      '<strong>$1</strong><br><span style="display:inline-block;margin-top:.55rem;color:#4b5563">Pago seguro de USD $2 en USDC sobre Base.</span>');

  if (out.includes("LUMEN Checkout") && !out.includes("Volver a LUMEN")) {
    const footer = `<div style="max-width:620px;margin:18px auto 40px;padding:0 18px;text-align:center;font-family:system-ui,-apple-system,sans-serif"><a href="${origin}/store" style="display:inline-block;padding:11px 16px;border-radius:12px;text-decoration:none;color:#111827;background:#fff;border:1px solid #d1d5db;font-weight:650">← Volver a LUMEN</a><div style="margin-top:12px;font-size:13px;color:#6b7280">Pago protegido por x402 · USDC · Base</div></div>`;
    out = out.includes("</body>") ? out.replace("</body>", `${footer}</body>`) : `${out}${footer}`;
  }
  return out;
}

function rewriteText(text, origin) {
  const rewritten = String(text)
    .replaceAll(`${CONVERSION_BASE}/catalog`, `${origin}/store`)
    .replaceAll(`${CONVERSION_INTERNAL}/catalog`, `${origin}/store`)
    .replaceAll(CONVERSION_BASE, origin)
    .replaceAll(CONVERSION_INTERNAL, origin)
    .replaceAll(X402_BASE, origin)
    .replaceAll(X402_INTERNAL, origin)
    .replaceAll('href="/catalog"', 'href="/store"')
    .replaceAll('<a href="/services">Servicios</a>', '<a href="/services">Servicios</a><a href="/store">Comprar</a>')
    .replaceAll('<a class="cta" href="/services">Ver servicios</a>', '<a class="cta" href="/services">Ver servicios</a> <a class="cta" href="/store">Comprar intelligence</a>');
  return humanCheckout(rewritten, origin);
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

async function warmX402(binding, origin) {
  if (!binding || typeof binding.fetch !== "function") return false;
  try {
    const response = await binding.fetch(new Request(`${origin}/health`, {
      method:"GET",
      headers:{"x-lumen-public-origin":origin,"user-agent":"LUMEN-Public-Gateway/1.0"},
    }));
    return response.ok;
  } catch (_) {
    return false;
  }
}

async function proxyX402(request, binding, origin, targetPath) {
  if (!binding || typeof binding.fetch !== "function") {
    return Response.json({ok:false,error:"internal_service_unavailable"},{status:503});
  }
  // x402 paid resources are GET-based. Hide transient cold-start 500s from buyers.
  if (request.method !== "GET") return proxyBinding(request,binding,origin,targetPath,origin,true);

  const incoming = new URL(request.url);
  const target = new URL(targetPath + incoming.search, origin);
  const headers = new Headers(request.headers);
  headers.set("x-lumen-public-origin", origin);
  let last = null;

  for (let attempt=1; attempt<=4; attempt++) {
    try {
      const upstream = await binding.fetch(new Request(target.toString(), {method:"GET",headers,redirect:"manual"}));
      if (upstream.status !== 500) return normalizeResponse(upstream, origin, {rewriteBody:true});
      last = {
        status:upstream.status,
        headers:new Headers(upstream.headers),
        body:await upstream.text(),
      };
    } catch (error) {
      last = {
        status:503,
        headers:new Headers({"content-type":"application/json"}),
        body:JSON.stringify({ok:false,error:"x402_internal_retry",detail:String(error?.message||error).slice(0,180)}),
      };
    }
    if (attempt < 4) await new Promise(resolve => setTimeout(resolve, 350 * attempt));
  }

  return normalizeResponse(new Response(last?.body || '{"error":"Internal Server Error"}', {
    status:last?.status || 503,
    headers:last?.headers || {"content-type":"application/json"},
  }), origin, {rewriteBody:true});
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";
    const origin = url.origin;

    if (request.method === "GET" && (path === "/store" || path === "/catalog")) {
      if (ctx?.waitUntil) ctx.waitUntil(warmX402(env.X402, origin));
      return proxyBinding(request, env.CONVERSION, CONVERSION_INTERNAL, "/catalog", origin, true);
    }
    if (request.method === "GET" && path === "/store.json") {
      return proxyBinding(request, env.CONVERSION, CONVERSION_INTERNAL, "/catalog.json", origin, true);
    }
    if (/^\/offer\/[a-z0-9-]+$/.test(path) && request.method === "GET") {
      if (ctx?.waitUntil) ctx.waitUntil(warmX402(env.X402, origin));
      return proxyBinding(request, env.CONVERSION, CONVERSION_INTERNAL, path, origin, true);
    }
    if (/^\/go\/[a-z0-9-]+$/.test(path) && request.method === "GET") {
      return proxyBinding(request, env.CONVERSION, CONVERSION_INTERNAL, path, origin, false);
    }
    if (/^\/intent\/[a-z0-9-]+$/.test(path) && request.method === "POST") {
      return proxyBinding(request, env.CONVERSION, CONVERSION_INTERNAL, path, origin, true);
    }

    // Service Binding handles transport; the buyer sees only the public LUMEN URL.
    if (/^\/buy\/[a-z0-9-]+$/.test(path) && ["GET","POST"].includes(request.method)) {
      return proxyX402(request, env.X402, origin, path);
    }

    const response = await core.fetch(request, env, ctx);
    const type = response.headers.get("content-type") || "";
    if (request.method === "GET" && type.includes("text/html")) {
      return normalizeResponse(response, origin, {rewriteBody:true});
    }
    return response;
  }
};
