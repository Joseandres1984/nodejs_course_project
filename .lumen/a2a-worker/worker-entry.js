import a2aWorker from "./worker.js";
import { handleRevenue } from "./revenue-expansion.js";
import { DISCOVERY_VERSION, handleDiscovery } from "./discovery.js";

function landingPage(origin) {
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
  const base = esc(origin);
  const structured = JSON.stringify({
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    name: "LUMEN B2B Agent",
    applicationCategory: "BusinessApplication",
    operatingSystem: "Web / A2A v1.0",
    description: "Global B2B sourcing, procurement intelligence, supplier verification, tender discovery, buyer signals, export intelligence and machine-paid x402 services for AI agents and business systems.",
    url: origin,
    offers: {
      "@type": "AggregateOffer",
      priceCurrency: "USD",
      lowPrice: "5",
      offerCount: "10"
    }
  }).replace(/</g, "\\u003c");
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>LUMEN B2B Agent · Global A2A sourcing & intelligence</title>
  <meta name="description" content="Global A2A v1.0 B2B sourcing, procurement intelligence, supplier verification, tender discovery, buyer signals, export research and x402 machine services." />
  <meta name="keywords" content="A2A, B2B procurement, supplier sourcing, supplier verification, RFQ, tenders, buyer intent, export research, market intelligence, x402, machine commerce" />
  <meta name="robots" content="index,follow,max-snippet:-1" />
  <link rel="canonical" href="${base}/" />
  <link rel="alternate" type="application/json" href="${base}/.well-known/agent-card.json" title="A2A Agent Card" />
  <link rel="alternate" type="application/json" href="${base}/openapi.json" title="OpenAPI" />
  <link rel="alternate" type="text/plain" href="${base}/llms.txt" title="LLM discovery guide" />
  <script type="application/ld+json">${structured}</script>
  <style>
    :root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#080b12;color:#f4f7fb;min-height:100vh;display:grid;place-items:center;padding:24px}.card{width:min(860px,100%);background:#111722;border:1px solid #243044;border-radius:24px;padding:28px;box-shadow:0 24px 80px #0008}.eyebrow{font-size:13px;letter-spacing:.18em;text-transform:uppercase;color:#8ba8d8}.status{display:inline-flex;align-items:center;gap:8px;margin:14px 0 8px;padding:7px 11px;border:1px solid #315d47;border-radius:999px;color:#a8efc5;background:#10241a;font-size:13px}.dot{width:8px;height:8px;border-radius:50%;background:#68dc98}h1{font-size:clamp(30px,7vw,54px);line-height:1;margin:12px 0 14px}p{color:#bdc8d8;line-height:1.55}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin-top:22px}a{display:block;text-decoration:none;color:#eef5ff;background:#172235;border:1px solid #2a3c58;border-radius:16px;padding:15px}a:hover{background:#1d2b43}.k{font-size:12px;color:#8fa4c2;margin-bottom:5px}.v{font-weight:700}.foot{margin-top:22px;font-size:12px;color:#7e8ca2;word-break:break-all}
  </style>
</head>
<body>
  <main class="card">
    <div class="eyebrow">LUMEN B2B · GLOBAL AGENT COMMERCE</div>
    <div class="status"><span class="dot"></span>A2A v1.0 gateway online worldwide</div>
    <h1>Procurement intelligence built for agents.</h1>
    <p>LUMEN is a public seller-side A2A agent for supplier sourcing, supplier verification, quotation review, public tenders, buyer signals, B2B prospect intelligence and export research. AI agents can discover services, request non-binding quotes and use eligible x402 machine checkout. LUMEN receives revenue but never performs autonomous outgoing spend or binding acceptance.</p>
    <div class="grid">
      <a href="${base}/.well-known/agent-card.json"><div class="k">A2A standard</div><div class="v">Agent Card</div></a>
      <a href="${base}/discovery.json"><div class="k">Agent discovery</div><div class="v">Discovery Index</div></a>
      <a href="${base}/openapi.json"><div class="k">Machine interface</div><div class="v">OpenAPI</div></a>
      <a href="${base}/llms.txt"><div class="k">LLM crawlers</div><div class="v">llms.txt</div></a>
      <a href="${base}/machine/catalog"><div class="k">From USD 5</div><div class="v">Machine Store</div></a>
      <a href="${base}/seller/catalog"><div class="k">Full services</div><div class="v">Seller Catalog</div></a>
      <a href="${base}/revenue/catalog"><div class="k">Subscriptions & success fee</div><div class="v">Revenue Catalog</div></a>
      <a href="${base}/payments/status"><div class="k">Collection readiness</div><div class="v">x402 Status</div></a>
      <a href="${base}/health"><div class="k">Operational</div><div class="v">Health</div></a>
    </div>
    <div class="foot">Discovery ${esc(DISCOVERY_VERSION)} · ${base}</div>
  </main>
</body>
</html>`;
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    const discoveryResponse = await handleDiscovery(request, env, ctx, a2aWorker);
    if (discoveryResponse) return discoveryResponse;

    if (request.method === "GET" && (url.pathname === "/" || url.pathname === "")) {
      return new Response(landingPage(url.origin), {
        status: 200,
        headers: {
          "content-type": "text/html; charset=utf-8",
          "cache-control": "public, max-age=300",
          "x-content-type-options": "nosniff"
        }
      });
    }
    const revenueResponse = await handleRevenue(request, env);
    if (revenueResponse) return revenueResponse;
    return a2aWorker.fetch(request, env, ctx);
  }
};
