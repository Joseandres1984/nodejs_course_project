import a2aWorker from "./worker.js";

function landingPage(origin) {
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
  const base = esc(origin);
  return `<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>LUMEN B2B · A2A Gateway</title>
  <style>
    :root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#080b12;color:#f4f7fb;min-height:100vh;display:grid;place-items:center;padding:24px}.card{width:min(760px,100%);background:#111722;border:1px solid #243044;border-radius:24px;padding:28px;box-shadow:0 24px 80px #0008}.eyebrow{font-size:13px;letter-spacing:.18em;text-transform:uppercase;color:#8ba8d8}.status{display:inline-flex;align-items:center;gap:8px;margin:14px 0 8px;padding:7px 11px;border:1px solid #315d47;border-radius:999px;color:#a8efc5;background:#10241a;font-size:13px}.dot{width:8px;height:8px;border-radius:50%;background:#68dc98}h1{font-size:clamp(30px,7vw,54px);line-height:1;margin:12px 0 14px}p{color:#bdc8d8;line-height:1.55}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin-top:22px}a{display:block;text-decoration:none;color:#eef5ff;background:#172235;border:1px solid #2a3c58;border-radius:16px;padding:15px}a:hover{background:#1d2b43}.k{font-size:12px;color:#8fa4c2;margin-bottom:5px}.v{font-weight:700}.foot{margin-top:22px;font-size:12px;color:#7e8ca2;word-break:break-all}
  </style>
</head>
<body>
  <main class="card">
    <div class="eyebrow">LUMEN B2B</div>
    <div class="status"><span class="dot"></span>A2A Gateway operativo</div>
    <h1>Machine commerce, sourcing e inteligencia B2B</h1>
    <p>Este es el gateway público A2A de LUMEN. Los agentes pueden descubrir servicios, consultar el catálogo, pedir cotizaciones y usar el checkout x402. LUMEN vende y cobra; no realiza gasto autónomo.</p>
    <div class="grid">
      <a href="${base}/health"><div class="k">Estado</div><div class="v">Health</div></a>
      <a href="${base}/machine/catalog"><div class="k">Productos</div><div class="v">Machine Store</div></a>
      <a href="${base}/seller/catalog"><div class="k">Servicios</div><div class="v">Seller Catalog</div></a>
      <a href="${base}/payments/status"><div class="k">Cobros</div><div class="v">x402 Status</div></a>
      <a href="${base}/.well-known/agent-card.json"><div class="k">A2A</div><div class="v">Agent Card</div></a>
    </div>
    <div class="foot">${base}</div>
  </main>
</body>
</html>`;
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (request.method === "GET" && (url.pathname === "/" || url.pathname === "")) {
      return new Response(landingPage(url.origin), {
        status: 200,
        headers: {
          "content-type": "text/html; charset=utf-8",
          "cache-control": "public, max-age=60",
          "x-content-type-options": "nosniff"
        }
      });
    }
    return a2aWorker.fetch(request, env, ctx);
  }
};
