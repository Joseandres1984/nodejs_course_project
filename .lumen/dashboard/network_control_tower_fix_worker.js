import base from "./network_control_tower_worker.js";

function n(v) { return Number(v || 0); }

async function economicRows(env) {
  try {
    const r = await env.DB.prepare(`SELECT partner_id,economic_score,economic_confidence,verified_revenue_usd,verified_settlements,verified_referral_settlements
      FROM lumen_partner_economic_performance`).all();
    return r.results || [];
  } catch { return []; }
}

async function economicSummary(env) {
  try {
    const r = await env.DB.prepare(`SELECT COUNT(*) total,
      SUM(CASE WHEN verified_settlements>0 THEN 1 ELSE 0 END) producing,
      SUM(CASE WHEN economic_confidence>=30 THEN 1 ELSE 0 END) meaningful,
      COALESCE(SUM(verified_revenue_usd),0) revenue
      FROM lumen_partner_economic_performance`).first();
    return {
      total: n(r?.total),
      revenueProducingPartners: n(r?.producing),
      meaningfulEconomicConfidence: n(r?.meaningful),
      totalPartnerAttributedRevenueUsd: n(r?.revenue)
    };
  } catch {
    return { total: 0, revenueProducingPartners: 0, meaningfulEconomicConfidence: 0, totalPartnerAttributedRevenueUsd: 0 };
  }
}

function economicScript() {
  return `<script id="lumenEconomicPartnerColumns">
(()=>{
  const money=v=>'USD '+Number(v||0).toFixed(2);
  async function enrich(){
    let data;try{const r=await fetch('/api/network-control-v1',{cache:'no-store'});if(!r.ok)return;data=await r.json();}catch{return;}
    const root=document.getElementById('ntPartnersTable');if(!root)return;
    const table=root.querySelector('table');if(!table)return;
    const head=table.querySelector('thead tr');if(!head||head.querySelector('[data-economic-col]'))return;
    const h1=document.createElement('th');h1.textContent='Valor económico';h1.setAttribute('data-economic-col','1');
    const h2=document.createElement('th');h2.textContent='Revenue atribuible';h2.setAttribute('data-economic-col','1');
    head.appendChild(h1);head.appendChild(h2);
    const partners=Array.isArray(data.topPartners)?data.topPartners:[];
    table.querySelectorAll('tbody tr').forEach((tr,i)=>{
      const p=partners[i]||{};const settlements=Number(p.verified_settlements||0);const conf=Number(p.economic_confidence||0);
      const a=document.createElement('td');a.setAttribute('data-economic-col','1');a.textContent=settlements>0?(Number(p.economic_score||50)+' / c'+conf):'—';
      const b=document.createElement('td');b.setAttribute('data-economic-col','1');b.textContent=money(p.verified_revenue_usd)+' · '+settlements+' settlement'+(settlements===1?'':'s');
      tr.appendChild(a);tr.appendChild(b);
    });
  }
  const obs=new MutationObserver(()=>enrich());
  const start=()=>{const root=document.getElementById('ntPartnersTable');if(root)obs.observe(root,{childList:true,subtree:true});enrich();};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
</script>`;
}

export default {
  async fetch(request, env, ctx) {
    const response = await base.fetch(request, env, ctx);
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === "/api/network-control-v1" && response.ok) {
      let data;
      try { data = await response.json(); } catch { return response; }

      const redundancy = data?.redundancy || {};
      const module13 = Array.isArray(data?.modules) ? data.modules.find(x => Number(x?.id) === 13) : null;
      if (module13) {
        module13.metric = `${n(redundancy.readyAlternates)} fallbacks listos`;
        module13.detail = `${n(redundancy.weakAlternates)} débiles`;
      }

      const econRows = await economicRows(env);
      const econByPartner = new Map(econRows.map(x => [x.partner_id, x]));
      if (Array.isArray(data?.topPartners)) {
        data.topPartners = data.topPartners.map(p => ({
          ...p,
          economic_score: econByPartner.get(p.id)?.economic_score ?? null,
          economic_confidence: econByPartner.get(p.id)?.economic_confidence ?? 0,
          verified_revenue_usd: econByPartner.get(p.id)?.verified_revenue_usd ?? 0,
          verified_settlements: econByPartner.get(p.id)?.verified_settlements ?? 0,
          verified_referral_settlements: econByPartner.get(p.id)?.verified_referral_settlements ?? 0
        }));
      }
      data.partnerEconomic = await economicSummary(env);
      const module4 = Array.isArray(data?.modules) ? data.modules.find(x => Number(x?.id) === 4) : null;
      if (module4) {
        module4.metric = `${n(data?.observed?.withEvidence)} con evidencia operativa`;
        module4.detail = `${n(data.partnerEconomic.revenueProducingPartners)} con revenue verificado · USD ${n(data.partnerEconomic.totalPartnerAttributedRevenueUsd).toFixed(2)} atribuible`;
      }

      return Response.json(data, {
        status: response.status,
        headers: {
          "cache-control": "no-store",
          "x-content-type-options": "nosniff",
          "x-lumen-network-tower-fix": "redundancy-v1+partner-economics-v1"
        }
      });
    }

    if (request.method === "GET" && response.ok && ["/", "/index.html", "/full"].includes(url.pathname) && String(response.headers.get("content-type") || "").includes("text/html")) {
      let html = await response.text();
      if (!html.includes('id="lumenEconomicPartnerColumns"')) html = html.replace("</body>", `${economicScript()}</body>`);
      const headers = new Headers(response.headers);
      headers.delete("content-length");
      headers.set("cache-control", "no-store");
      headers.set("x-lumen-network-economic-columns", "v1");
      return new Response(html, { status: response.status, statusText: response.statusText, headers });
    }

    return response;
  }
};
