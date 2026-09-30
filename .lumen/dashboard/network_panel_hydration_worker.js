import app from "./mobile_layout_fix_worker.js";

function n(v) { return Number(v || 0); }
function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (m) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[m]));
}
function usd(v) {
  return `USD ${n(v).toLocaleString("es-AR", { maximumFractionDigits: 2 })}`;
}
function event(title, sub, more = "") {
  return `<div class="ntEvent"><strong>${esc(title || "—")}</strong><div class="small ntMuted">${esc(sub || "")}</div>${more ? `<div class="small">${esc(more)}</div>` : ""}</div>`;
}
function members(raw) {
  try {
    const x = JSON.parse(raw || "[]");
    return Array.isArray(x) ? x.slice(0, 4).map((m) => `${m.name || "agente"} · ${m.role || "rol"}`).join(" | ") : "";
  } catch { return ""; }
}
function chip(v, kind = "") {
  return `<span class="ntChip ${kind}">${esc(v)}</span>`;
}

async function safeRows(env, sql, binds = []) {
  try {
    let query = env.DB.prepare(sql);
    if (binds.length) query = query.bind(...binds);
    const result = await query.all();
    return result.results || [];
  } catch {
    return [];
  }
}

async function a2aJson(env, path) {
  try {
    if (!env?.A2A?.fetch) return null;
    const response = await env.A2A.fetch(new Request(`https://lumen-a2a.internal${path}`, {
      method: "GET",
      headers: { "accept": "application/json" }
    }));
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  }
}

async function travelSnapshot(env) {
  const [totals, recent, sources, destinations, campaigns, variants, demandRows, matchRows, affiliateHealth, viatorApi] = await Promise.all([
    safeRows(env, "SELECT event_type,COUNT(*) AS total,SUM(CASE WHEN datetime(created_at)>=datetime('now','-1 day') THEN 1 ELSE 0 END) AS last_24h,SUM(CASE WHEN datetime(created_at)>=datetime('now','-7 days') THEN 1 ELSE 0 END) AS last_7d FROM lumen_travel_events GROUP BY event_type"),
    safeRows(env, "SELECT event_type,provider,source,campaign,variant,destination,product_id,created_at FROM lumen_travel_events ORDER BY created_at DESC LIMIT 30"),
    safeRows(env, "SELECT COALESCE(NULLIF(source,''),'direct') AS label,COUNT(*) AS total FROM lumen_travel_events WHERE event_type='click' AND datetime(created_at)>=datetime('now','-7 days') GROUP BY COALESCE(NULLIF(source,''),'direct') ORDER BY total DESC LIMIT 8"),
    safeRows(env, "SELECT COALESCE(NULLIF(destination,''),'sin destino') AS label,COUNT(*) AS total FROM lumen_travel_events WHERE event_type='click' AND datetime(created_at)>=datetime('now','-7 days') GROUP BY COALESCE(NULLIF(destination,''),'sin destino') ORDER BY total DESC LIMIT 8"),
    safeRows(env, "SELECT COALESCE(NULLIF(campaign,''),'sin campaña') AS label,COUNT(*) AS total FROM lumen_travel_events WHERE event_type='click' AND datetime(created_at)>=datetime('now','-7 days') GROUP BY COALESCE(NULLIF(campaign,''),'sin campaña') ORDER BY total DESC LIMIT 8"),
    safeRows(env, "SELECT COALESCE(NULLIF(variant,''),'default') AS label,COUNT(*) AS total FROM lumen_travel_events WHERE event_type='click' AND datetime(created_at)>=datetime('now','-7 days') GROUP BY COALESCE(NULLIF(variant,''),'default') ORDER BY total DESC LIMIT 8"),
    safeRows(env, "SELECT status,COUNT(*) AS total FROM lumen_travel_demands GROUP BY status"),
    safeRows(env, "SELECT status,COUNT(*) AS total FROM lumen_travel_matches GROUP BY status"),
    a2aJson(env, "/health/viator-affiliate"),
    a2aJson(env, "/viator/api/status")
  ]);

  const byType = Object.fromEntries(totals.map((row) => [String(row.event_type || ""), {
    total: n(row.total), last24h: n(row.last_24h), last7d: n(row.last_7d)
  }]));
  const impressions7d = n(byType.impression?.last7d);
  const searches7d = n(byType.search?.last7d);
  const clicks7d = n(byType.click?.last7d);
  const ctr7d = impressions7d > 0 ? Number(((clicks7d / impressions7d) * 100).toFixed(1)) : null;
  const sumRows = (rows) => rows.reduce((acc, row) => acc + n(row.total), 0);

  return {
    provider: "viator",
    analyticsReady: Boolean(affiliateHealth?.analyticsReady || totals.length || recent.length),
    affiliate: {
      live: Boolean(affiliateHealth?.ok),
      version: String(affiliateHealth?.version || "—"),
      mode: String(affiliateHealth?.mode || "—"),
      apiConfigured: Boolean(viatorApi?.configured),
      apiEnvironment: String(viatorApi?.environment || "—"),
      secretExposed: Boolean(viatorApi?.secretExposed)
    },
    funnel: {
      impressions7d,
      searches7d,
      clicks24h: n(byType.click?.last24h),
      clicks7d,
      clicksTotal: n(byType.click?.total),
      ctr7d
    },
    broker: {
      demands: sumRows(demandRows),
      matches: sumRows(matchRows)
    },
    topSources: sources,
    topDestinations: destinations,
    topCampaigns: campaigns,
    topVariants: variants,
    recent
  };
}

async function networkSnapshot(request, env, ctx) {
  try {
    const url = new URL(request.url);
    url.pathname = "/api/network-control-v1";
    url.search = "";
    const response = await app.fetch(new Request(url.toString(), {
      method: "GET",
      headers: request.headers,
    }), env, ctx);
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  }
}

function setPanel(html, id, content) {
  const empty = `<div id="${id}"></div>`;
  return html.includes(empty) ? html.replace(empty, `<div id="${id}">${content}</div>`) : html;
}
function setClassPanel(html, cls, id, content) {
  const empty = `<div class="${cls}" id="${id}"></div>`;
  return html.includes(empty) ? html.replace(empty, `<div class="${cls}" id="${id}">${content}</div>`) : html;
}

function hydratePanels(html, data) {
  if (!data) {
    const unavailable = '<div class="empty">Datos de red no disponibles en este momento.</div>';
    for (const id of ["ntRoomsList", "ntTasksList", "ntNegotiatorList", "ntReferralList", "ntVentureList", "ntGapList", "ntTeamList", "ntGraphList"]) {
      html = setPanel(html, id, unavailable);
    }
    html = setClassPanel(html, "ntTable", "ntEconomyList", unavailable);
    html = setClassPanel(html, "ntGuard", "ntGuardrails", '<div><strong>Guardrails</strong><div class="small">No se pudo leer el estado vivo. Las restricciones de seguridad no se relajan por este error visual.</div></div>');
    return html;
  }

  const rooms = Array.isArray(data.rooms) ? data.rooms : [];
  html = setPanel(html, "ntRoomsList", rooms.length
    ? rooms.map((x) => event(`${x.id} · ${x.status}`, `Ronda ${n(x.round_no)} · ${n(x.contributions)}/${n(x.members)} contribuciones`, `Alineación ${x.alignment_score == null ? "—" : n(x.alignment_score)} · mensajes externos ${n(x.external_messages)}`)).join("")
    : '<div class="empty">Sin salas creadas.</div>');

  const tasks = Array.isArray(data.tasks) ? data.tasks : [];
  html = setPanel(html, "ntTasksList", tasks.length
    ? tasks.map((x) => event(`${x.partner_name || "Agente"} · ${x.role || "rol"}`, `${x.status || "—"} · ${x.title || ""}`, `${x.quality_score == null ? "" : `Quality ${n(x.quality_score)}`}${x.error ? ` · ${x.error}` : ""}`)).join("")
    : '<div class="empty">Sin tareas de delegación todavía.</div>');

  const negotiations = Array.isArray(data.negotiations) ? data.negotiations : [];
  html = setPanel(html, "ntNegotiatorList", negotiations.length
    ? negotiations.map((x) => event(x.title, `${x.status || "—"} · ${n(x.candidate_count)} candidatos · ${n(x.priced_candidate_count)} precios`, `Recomendado: ${x.recommended_partner_name || "aún no"} · confidence ${n(x.recommendation_confidence)}`)).join("")
    : '<div class="empty">Sin casos de negociación.</div>');

  const referrals = Array.isArray(data.referralRows) ? data.referralRows : [];
  html = setPanel(html, "ntReferralList", referrals.length
    ? referrals.map((x) => event(x.title, `${x.direction || ""} · ${x.status || ""}`, `${x.target_partner_name || x.origin_partner_name ? `Agente: ${x.target_partner_name || x.origin_partner_name} · ` : ""}match ${n(x.match_score)} · settled ${usd(x.settled_revenue_usd)}`)).join("")
    : '<div class="empty">Sin referrals.</div>');

  const ventures = Array.isArray(data.ventures) ? data.ventures : [];
  html = setPanel(html, "ntVentureList", ventures.length
    ? ventures.map((x) => event(x.title, `${x.status || "—"} · readiness ${n(x.readiness_score)} · coverage ${n(x.coverage_score)}`, `gaps ${n(x.gap_count)} · ${x.next_experiment || ""}`)).join("")
    : '<div class="empty">Todavía no hay Venture Cases maduros.</div>');

  const gaps = Array.isArray(data.gapRows) ? data.gapRows : [];
  html = setPanel(html, "ntGapList", gaps.length
    ? gaps.map((x) => event(x.capability, `Prioridad ${n(x.priority)} · ${x.status || "—"}`, `Candidatos ${n(x.current_candidates)} · fuertes ${n(x.strong_candidates)} · mejor ${x.best_partner_name || "ninguno"}`)).join("")
    : '<div class="empty">No hay gaps abiertos.</div>');

  const teams = Array.isArray(data.teams) ? data.teams : [];
  html = setPanel(html, "ntTeamList", teams.length
    ? teams.map((x) => event(x.id, `Score ${n(x.team_score)} · coverage ${n(x.coverage_score)} · affinity ${n(x.graph_affinity_score)}`, members(x.members_json))).join("")
    : '<div class="empty">Sin equipos dinámicos activos.</div>');

  const edges = Array.isArray(data.graphEdges) ? data.graphEdges : [];
  html = setPanel(html, "ntGraphList", edges.length
    ? edges.map((x) => event(`${x.source_name || "Agente"} + ${x.target_name || "Agente"}`, `${x.relation_type || "—"} · affinity ${n(x.affinity_score)}`, `contextos ${n(x.contexts)} · éxitos ${n(x.successes)} · fallas ${n(x.failures)}`)).join("")
    : '<div class="empty">Sin historial conjunto suficiente.</div>');

  const intents = Array.isArray(data.economyIntents) ? data.economyIntents : [];
  const economy = intents.length
    ? `<table><thead><tr><th>Dirección</th><th>Servicio</th><th>Contraparte</th><th>USD</th><th>Estado</th><th>Aprobación</th><th>Settlement</th></tr></thead><tbody>${intents.map((x) => `<tr><td>${chip(x.direction, x.direction === "INCOME" ? "ntGood" : "ntWarn")}</td><td>${esc(x.service_name || x.kind || "—")}</td><td>${esc(x.counterparty_name || "—")}</td><td>${usd(x.amount_usd)}</td><td>${esc(x.status || "—")}</td><td>${esc(x.approval_status || "—")}</td><td>${esc(x.settlement_status || "—")}${n(x.settled_amount_usd) > 0 ? ` · ${usd(x.settled_amount_usd)}` : ""}</td></tr>`).join("")}</tbody></table>`
    : '<div class="empty">Sin intenciones económicas registradas.</div>';
  html = setClassPanel(html, "ntTable", "ntEconomyList", economy);

  const guardrails = '<div><strong>Gasto autónomo</strong><div class="ntKpi">USD 0</div><div class="small">hard-blocked</div></div><div><strong>Contratos automáticos</strong><div class="ntKpi">NO</div><div class="small">human-gated</div></div><div><strong>Compras autónomas</strong><div class="ntKpi">NO</div><div class="small">human-gated</div></div><div><strong>Ingreso realizado</strong><div class="ntKpi">SETTLED</div><div class="small">sólo pago verificado</div></div><div><strong>Trust</strong><div class="ntKpi">OBLIGATORIO</div><div class="small">antes de acciones externas sensibles</div></div><div><strong>Calidad</strong><div class="ntKpi">GATES</div><div class="small">juntas, tareas, resultados y propuestas</div></div>';
  html = setClassPanel(html, "ntGuard", "ntGuardrails", guardrails);
  return html;
}

const TRAVEL_SECTION = `<section class="page" id="travel"><div class="grid g6"><div class="card"><div class="klabel">Clics 24 h</div><div class="kpi good" id="travelClicks24">–</div></div><div class="card"><div class="klabel">Clics 7 días</div><div class="kpi" id="travelClicks7">–</div></div><div class="card"><div class="klabel">CTR 7 días</div><div class="kpi blue" id="travelCtr7">–</div></div><div class="card"><div class="klabel">Impresiones 7 días</div><div class="kpi" id="travelImpressions7">–</div></div><div class="card"><div class="klabel">Búsquedas 7 días</div><div class="kpi" id="travelSearches7">–</div></div><div class="card"><div class="klabel">Viator</div><div class="kpi" id="travelViator">–</div></div></div><div class="grid g2 section"><div class="card"><h2>Embudo Travel</h2><div id="travelFunnel"></div></div><div class="card"><h2>Estado y monetización</h2><div id="travelStatus"></div></div></div><div class="grid g2 section"><div class="card"><h2>Top destinos</h2><div id="travelDestinations"></div></div><div class="card"><h2>Top fuentes</h2><div id="travelSources"></div></div></div><div class="grid g2 section"><div class="card"><h2>Campañas</h2><div id="travelCampaigns"></div></div><div class="card"><h2>Variantes CTA</h2><div id="travelVariants"></div></div></div><div class="card section"><h2>Eventos recientes</h2><div id="travelRecent"></div></div></section>`;

const TRAVEL_RENDER_JS = `function renderTravel(t){
  if(!t)return;
  const f=t.funnel||{};
  $('travelClicks24').textContent=num(f.clicks24h);$('travelClicks7').textContent=num(f.clicks7d);$('travelImpressions7').textContent=num(f.impressions7d);$('travelSearches7').textContent=num(f.searches7d);$('travelCtr7').textContent=f.ctr7d==null?'—':num(f.ctr7d).toLocaleString('es-AR',{maximumFractionDigits:1})+'%';
  $('travelViator').innerHTML=t.affiliate?.live?'<span class="good">ACTIVO</span>':'<span class="warn">VERIFICAR</span>';
  $('travelFunnel').innerHTML=line('Impresiones · 7 días',num(f.impressions7d))+line('Búsquedas · 7 días',num(f.searches7d))+line('Clics · 7 días',num(f.clicks7d))+line('CTR',f.ctr7d==null?'sin impresiones todavía':num(f.ctr7d).toLocaleString('es-AR',{maximumFractionDigits:1})+'%')+line('Clics históricos',num(f.clicksTotal));
  $('travelStatus').innerHTML=line('Tracking',t.analyticsReady?'<span class="chip ok">ACTIVO</span>':'<span class="chip">sin eventos</span>')+line('Afiliado Viator',t.affiliate?.live?'<span class="chip ok">ONLINE</span>':'<span class="chip no">NO CONFIRMADO</span>')+line('Viator API',t.affiliate?.apiConfigured?'<span class="chip ok">CONFIGURADA</span>':'<span class="chip">NO CONFIGURADA</span>')+line('Entorno API',esc(t.affiliate?.apiEnvironment||'—'))+line('Demandas Travel',num(t.broker?.demands))+line('Matches Travel',num(t.broker?.matches))+'<p class="note">Los ingresos sólo deben mostrarse cuando exista atribución confirmada del partner. No se estiman comisiones.</p>';
  const ranked=(rows)=>table([['Nombre',r=>esc(r.label)],['Clics',r=>num(r.total)]],rows||[]);
  $('travelDestinations').innerHTML=ranked(t.topDestinations);$('travelSources').innerHTML=ranked(t.topSources);$('travelCampaigns').innerHTML=ranked(t.topCampaigns);$('travelVariants').innerHTML=ranked(t.topVariants);
  $('travelRecent').innerHTML=table([['Fecha',r=>'<span class="small">'+esc(r.created_at)+'</span>'],['Evento',r=>esc(r.event_type)],['Destino',r=>esc(r.destination||'—')],['Fuente',r=>esc(r.source||'direct')],['Campaña',r=>esc(r.campaign||'—')],['Variante',r=>esc(r.variant||'—')]],t.recent||[]);
}`;

function injectTravelUI(html) {
  if (!html.includes('data-tab="travel"')) {
    const navMarker = '</nav><div id="result">';
    if (html.includes(navMarker)) html = html.replace(navMarker, '<button class="tab" data-tab="travel">Travel</button></nav><div id="result">');
  }
  if (!html.includes('id="travel"')) {
    const infraMarker = '<section class="page" id="infra">';
    if (html.includes(infraMarker)) html = html.replace(infraMarker, `${TRAVEL_SECTION}${infraMarker}`);
  }
  if (!html.includes('function renderTravel(t)')) {
    const renderMarker = 'function render(d){';
    if (html.includes(renderMarker)) html = html.replace(renderMarker, `${TRAVEL_RENDER_JS}\nfunction render(d){\n  renderTravel(d.travel);`);
  }
  return html;
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    let downstreamRequest = request;
    if (request.method === "GET" && ["/secretaria", "/secretaria/"].includes(url.pathname)) {
      const rootUrl = new URL(request.url);
      rootUrl.pathname = "/";
      rootUrl.search = "";
      downstreamRequest = new Request(rootUrl.toString(), { method: "GET", headers: request.headers });
    }
    const response = await app.fetch(downstreamRequest, env, ctx);

    if (request.method === "GET" && url.pathname === "/api/data" && response.ok && String(response.headers.get("content-type") || "").includes("application/json")) {
      try {
        const data = await response.json();
        data.travel = await travelSnapshot(env);
        const headers = new Headers(response.headers);
        headers.delete("content-length");
        headers.set("cache-control", "no-store");
        headers.set("x-lumen-travel-intelligence", "v1");
        return Response.json(data, { status: response.status, headers });
      } catch {
        return response;
      }
    }

    const isDashboardPage = request.method === "GET"
      && response.ok
      && ["/", "/index.html", "/full", "/secretaria", "/secretaria/"].includes(url.pathname)
      && String(response.headers.get("content-type") || "").includes("text/html");
    if (!isDashboardPage) return response;

    let html = await response.text();
    const snapshot = await networkSnapshot(request, env, ctx);
    html = hydratePanels(html, snapshot);
    html = injectTravelUI(html);

    const headers = new Headers(response.headers);
    headers.delete("content-length");
    headers.set("cache-control", "no-store, no-cache, must-revalidate");
    headers.set("x-lumen-network-panel-hydration", snapshot ? "live" : "fallback");
    headers.set("x-lumen-travel-panel", "v1");
    return new Response(html, { status: response.status, statusText: response.statusText, headers });
  },
};
