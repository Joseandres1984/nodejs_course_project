import base from "./network_control_tower_worker.js";

function n(v) { return Number(v || 0); }
function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (m) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[m]));
}

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

async function fetchNetworkSnapshot(request, env, ctx) {
  try {
    const url = new URL(request.url);
    url.pathname = "/api/network-control-v1";
    url.search = "";
    const r = await base.fetch(new Request(url.toString(), {
      method: "GET",
      headers: request.headers
    }), env, ctx);
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}

function replaceSimple(html, id, oldValue, newValue, tag = "div") {
  const from = `id="${id}">${oldValue}</${tag}>`;
  const to = `id="${id}">${newValue}</${tag}>`;
  return html.replace(from, to);
}

function hydrateNetworkHtml(html, data) {
  if (!data) return html;
  const p = data.partners || {};
  const t = data.trust || {};
  const c = data.council || {};
  const dg = data.delegation || {};
  const m = data.marketplace || {};
  const rf = data.referrals || {};
  const ng = data.negotiator || {};
  const vt = data.venture || {};
  const gp = data.gaps || {};
  const dt = data.dynamicTeams || {};
  const eco = data.economy || {};
  const g = data.guardrails || {};

  html = replaceSimple(html, "ntObjective", "ORQUESTANDO RED MULTIAGENTE", esc(data.objective || "ORQUESTANDO RED MULTIAGENTE"));
  html = replaceSimple(html, "ntState", "CARGANDO RED", `RED ${n(p.total)} AGENTES · ${n(t.allow)} TRUST ALLOW`);
  html = replaceSimple(html, "ntBestAction", "Calculando la mejor acción segura para la red…", `Mejor acción segura ahora: ${esc(data.bestAction || "—")}`, "p");
  html = replaceSimple(html, "ntPartners", "0", n(p.total));
  html = replaceSimple(html, "ntAllow", "0", n(t.allow));
  html = replaceSimple(html, "ntRooms", "0", n(c.rooms));
  html = replaceSimple(html, "ntTasks", "0", n(dg.total));
  html = replaceSimple(html, "ntTeams", "0", n(dt.activeDraftTeams));
  html = replaceSimple(html, "ntNeeds", "0", n(m?.needs?.open));
  html = replaceSimple(html, "ntReferrals", "0", n(rf.total));
  html = replaceSimple(html, "ntNegotiations", "0", n(ng.totalCases));
  html = replaceSimple(html, "ntVentures", "0", n(vt.total));
  html = replaceSimple(html, "ntGaps", "0", n(gp.open) + n(gp.weakCoverage));
  html = replaceSimple(html, "ntPotential", "USD 0", `USD ${n(eco.potentialIncomeUsd).toLocaleString("es-AR", { maximumFractionDigits: 2 })}`);
  html = replaceSimple(html, "ntRealized", "USD 0", `USD ${n(eco.realizedIncomeUsd).toLocaleString("es-AR", { maximumFractionDigits: 2 })}`);
  html = replaceSimple(html, "ntExpense", "USD 0", `USD ${n(eco.proposedExpenseUsd).toLocaleString("es-AR", { maximumFractionDigits: 2 })}`);
  html = replaceSimple(html, "ntSpendBlock", "HARD BLOCK", g.outgoingSpendHardBlocked === false ? "REVISAR" : "HARD BLOCK ACTIVO");

  const modules = Array.isArray(data.modules) ? data.modules : [];
  if (modules.length) {
    const moduleHtml = modules.map((x) => `<div class="ntModule"><div class="ntModuleTop"><div style="display:flex;gap:8px;align-items:center"><span class="ntModuleNo">${n(x.id)}</span><strong>${esc(x.name)}</strong></div><span class="ntModuleState ${esc(String(x.state || "").toLowerCase().replace(/[^a-z0-9]+/g, "-"))}">${esc(x.state)}</span></div><div class="small" style="margin-top:8px">${esc(x.metric || "")}</div><div class="small ntMuted">${esc(x.detail || "")}</div></div>`).join("");
    html = html.replace('<div class="ntModules" id="ntModules"></div>', `<div class="ntModules" id="ntModules">${moduleHtml}</div>`);
  }

  const partners = Array.isArray(data.topPartners) ? data.topPartners : [];
  if (partners.length) {
    const rows = partners.map((x) => `<tr><td><strong>${esc(x.name || "—")}</strong></td><td>${esc(x.trust_level || "UNASSESSED")} ${n(x.trust_score)}</td><td>${n(x.reputation_score)}</td><td>${x.observed_score == null ? "—" : n(x.observed_score)}</td><td>${n(x.observed_confidence)}</td><td>${x.reliability_score == null ? "—" : n(x.reliability_score)}</td></tr>`).join("");
    const table = `<table><thead><tr><th>Agente</th><th>Trust</th><th>Reputación</th><th>Observada</th><th>Confidence</th><th>Reliability</th></tr></thead><tbody>${rows}</tbody></table>`;
    html = html.replace('<div class="ntTable" id="ntPartnersTable"><div class="empty">Cargando agentes…</div></div>', `<div class="ntTable" id="ntPartnersTable">${table}</div>`);
  }

  return html;
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
      const snapshot = await fetchNetworkSnapshot(request, env, ctx);
      html = hydrateNetworkHtml(html, snapshot);
      if (!html.includes('id="lumenEconomicPartnerColumns"')) html = html.replace("</body>", `${economicScript()}</body>`);
      const headers = new Headers(response.headers);
      headers.delete("content-length");
      headers.set("cache-control", "no-store");
      headers.set("x-lumen-network-economic-columns", "v1");
      headers.set("x-lumen-network-server-hydration", snapshot ? "live" : "unavailable");
      return new Response(html, { status: response.status, statusText: response.statusText, headers });
    }

    return response;
  }
};
