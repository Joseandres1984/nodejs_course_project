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
  return `<script id="lumenLiveOwnerSummaryV3">
(()=>{
  const e=id=>document.getElementById(id);
  const set=(id,v)=>{const el=e(id);if(el)el.textContent=v;};
  const usd=v=>'USD '+Number(v||0).toLocaleString('es-AR',{maximumFractionDigits:2});
  const setMany=(ids,v)=>ids.forEach(id=>set(id,v));
  async function refresh(){
    try{
      const r=await fetch('/api/control-tower-v2',{cache:'no-store'});
      if(!r.ok)return;
      const d=await r.json();
      const f=d.funnel||{};
      const totalProposals=Number(f.drafts||0)+Number(f.approved||0)+Number(f.sentProposals||0)+Number(f.respondedProposals||0);
      const strictDemand=Number(f.negotiating||0);
      const actionable=Number(f.actionable||0);
      const replies=Number(f.outreachResponded||0);
      const revenue=Number(f.realizedRevenueUsd||0);
      const focus=revenue>0?'Escalar ingresos verificados':strictDemand>0?'Convertir demanda real en cobro':actionable>0?'Convertir oportunidades en demanda verificable':'Encontrar la primera demanda verificable';
      const detail=revenue>0?'Hay ingresos verificados: el foco es repetir los patrones que ya convirtieron.':strictDemand>0?'Ya existe intención comercial suficiente; prioridad: llevarla a checkout y settlement verificado.':actionable>0?'Hay oportunidades accionables en el motor vivo; falta convertir una en intención de compra verificable.':'First Cash sigue buscando evidencia comercial real sin inflar actividad como resultado.';

      setMany(['lumenRevenue','lfRevenue'],usd(revenue));
      setMany(['lumenDemand','lfDemand'],strictDemand.toLocaleString('es-AR'));
      setMany(['lumenOpps','lfOpps'],actionable.toLocaleString('es-AR'));
      setMany(['lumenProposals','lfProposals'],totalProposals.toLocaleString('es-AR'));
      setMany(['lumenReplies','lfReplies'],replies.toLocaleString('es-AR'));
      set('lfClose',strictDemand.toLocaleString('es-AR'));
      setMany(['lumenFocus','lfFocus'],focus);
      setMany(['lumenFocusDetail','lfDetail'],detail);
      setMany(['lumenAutonomy','lfAutonomy'], 'OPERANDO');
      set('lumenBudgetNow','First Cash: búsqueda cada 15 min · contacto máx. 1 por hora');
      set('lfSearch','Búsqueda: cada 15 min · contacto: máx. 1 por hora');
      set('lumenNeedsYou',strictDemand>0?'Necesita de vos: sólo si aparece una acción vinculante':'Necesita de vos: nada ahora');
      set('lfBlocker',revenue>0?'Bloqueo: ninguno crítico':'Objetivo: primer settlement verificado');
    }catch{}
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',refresh,{once:true});else refresh();
  setTimeout(refresh,1200);
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

  html = html.replace(/<script id="lumenLiveOwnerSummaryV2">[\s\S]*?<\/script>/, "");
  if (!html.includes('id="lumenLiveOwnerSummaryV3"')) {
    html = html.replace("</body>", `${liveOwnerSummaryScript()}</body>`);
  }

  const headers = new Headers(response.headers);
  headers.delete("content-length");
  headers.set("cache-control", "no-store, no-cache, must-revalidate");
  headers.set("pragma", "no-cache");
  headers.set("expires", "0");
  headers.set("x-lumen-tab-normalization", "v3");
  headers.set("x-lumen-owner-summary", "a2a-live-v3");

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