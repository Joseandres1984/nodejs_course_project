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

function liveOwnerSummaryScript() {
  return `<script id="lumenLiveOwnerSummaryV2">
(()=>{
  const e=id=>document.getElementById(id);
  const set=(id,v)=>{const el=e(id);if(el)el.textContent=v;};
  const usd=v=>'USD '+Number(v||0).toLocaleString('es-AR',{maximumFractionDigits:2});
  async function refresh(){
    try{
      const r=await fetch('/api/control-tower-v2',{cache:'no-store'});
      if(!r.ok)return;
      const d=await r.json();
      const f=d.funnel||{};
      const totalProposals=Number(f.drafts||0)+Number(f.approved||0)+Number(f.sentProposals||0)+Number(f.respondedProposals||0);
      const strictDemand=Number(f.negotiating||0);
      set('lfRevenue',usd(f.realizedRevenueUsd));
      set('lfDemand',strictDemand.toLocaleString('es-AR'));
      set('lfOpps',Number(f.actionable||0).toLocaleString('es-AR'));
      set('lfProposals',totalProposals.toLocaleString('es-AR'));
      set('lfClose',Number(f.negotiating||0).toLocaleString('es-AR'));
      set('lfReplies',Number(f.outreachResponded||0).toLocaleString('es-AR'));
      set('lfFocus',Number(f.realizedRevenueUsd||0)>0?'Escalar ingresos verificados':'Conseguir el primer cobro verificado');
      set('lfDetail','First Cash activo · oportunidades accionables y actividad A2A leídas desde el motor vivo. Sólo un settlement verificado cuenta como ingreso.');
      set('lfAutonomy','Autonomía: OPERANDO · First Cash');
      set('lfSearch','Búsqueda: cada 15 min · contacto: máx. 1 por hora');
      set('lfBlocker',Number(f.realizedRevenueUsd||0)>0?'Bloqueo: ninguno crítico':'Objetivo: primer settlement x402 verificado');
    }catch{}
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',refresh,{once:true});else refresh();
  setInterval(refresh,20000);
})();
</script>`;
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

  if (!html.includes('id="lumenLiveOwnerSummaryV2"')) {
    html = html.replace("</body>", `${liveOwnerSummaryScript()}</body>`);
  }

  const headers = new Headers(response.headers);
  headers.delete("content-length");
  headers.set("cache-control", "no-store");
  headers.set("x-lumen-tab-normalization", "v2");
  headers.set("x-lumen-owner-summary", "a2a-live-v2");

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