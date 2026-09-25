import app from "./network_control_tower_fix_worker.js";

const LEGACY_RETRYABLE_PATHS = new Set([
  "/api/data",
  "/api/full-state",
  "/api/recovery-state",
  "/api/experiments",
]);

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function unauthorized() {
  return new Response("LUMEN · acceso restringido", {
    status: 401,
    headers: {
      "WWW-Authenticate": 'Basic realm="LUMEN Centro de Comando", charset="UTF-8"',
      "Cache-Control": "no-store",
    },
  });
}

function locked() {
  return new Response("LUMEN dashboard todavía no tiene contraseña configurada.", {
    status: 503,
    headers: { "Cache-Control": "no-store" },
  });
}

function constantTimeEqual(a, b) {
  a = String(a || "");
  b = String(b || "");
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function authOK(request, env) {
  const password = String(env.LUMEN_DASHBOARD_PASSWORD || "");
  if (!password) return null;
  const header = request.headers.get("Authorization") || "";
  if (!header.startsWith("Basic ")) return false;
  try {
    const decoded = atob(header.slice(6));
    const i = decoded.indexOf(":");
    if (i < 0) return false;
    const user = decoded.slice(0, i);
    const pass = decoded.slice(i + 1);
    return constantTimeEqual(user, String(env.LUMEN_DASHBOARD_USER || "socio"))
      && constantTimeEqual(pass, password);
  } catch {
    return false;
  }
}

function protect(request, env) {
  const auth = authOK(request, env);
  if (auth === null) return locked();
  if (!auth) return unauthorized();
  return null;
}

async function scalar(env, sql, binds = []) {
  try {
    let q = env.DB.prepare(sql);
    if (binds.length) q = q.bind(...binds);
    const row = await q.first();
    return Number(row?.n || 0);
  } catch {
    return 0;
  }
}

async function rows(env, sql, binds = []) {
  try {
    let q = env.DB.prepare(sql);
    if (binds.length) q = q.bind(...binds);
    const result = await q.all();
    return result.results || [];
  } catch {
    return [];
  }
}

async function serviceJson(env, path) {
  try {
    if (!env?.A2A) return null;
    const response = await env.A2A.fetch(new Request(`https://lumen-a2a.internal${path}`, {
      method: "GET",
      headers: { accept: "application/json" },
    }));
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

function json(data, extra = {}) {
  return Response.json(data, {
    headers: {
      "cache-control": "no-store, no-cache, must-revalidate",
      "x-content-type-options": "nosniff",
      ...extra,
    },
  });
}

async function liveHealth(request, env) {
  const denied = protect(request, env);
  if (denied) return denied;
  try {
    await env.DB.prepare("SELECT 1 AS ok").first();
    const a2a = await serviceJson(env, "/health");
    return json({
      ok: true,
      service: "lumen-zero-dashboard",
      persistence: "cloudflare_d1",
      dataPlane: "live_d1_a2a",
      legacyStateRequired: false,
      a2aOnline: a2a?.ok === true,
      x402: a2a?.x402 || "UNKNOWN",
      checkedAt: new Date().toISOString(),
    }, { "x-lumen-dashboard-health": "live-v4" });
  } catch (error) {
    return Response.json(
      { ok: false, error: String(error?.message || error) },
      { status: 503, headers: { "cache-control": "no-store" } },
    );
  }
}

async function liveControl(request, env) {
  const denied = protect(request, env);
  if (denied) return denied;
  const now = new Date().toISOString();

  const [
    opportunities, demand, actionable, highScore, testOnly,
    drafts, approved, sentProposals, respondedProposals,
    qualityPass, qualityFail, outreachSent, outreachResponded, outreachFailed,
    negotiating, waiting, noResponse, lost, dueFollowups, followupsSent,
    settlements, realizedRevenueUsd,
  ] = await Promise.all([
    scalar(env, "SELECT COUNT(*) AS n FROM lumen_opportunities"),
    scalar(env, "SELECT COUNT(*) AS n FROM lumen_opportunities WHERE demand_signal=1"),
    scalar(env, "SELECT COUNT(*) AS n FROM lumen_opportunity_assessments WHERE commercially_actionable=1"),
    scalar(env, "SELECT COUNT(*) AS n FROM lumen_opportunity_assessments WHERE commercial_score>=65 AND synthetic_or_test_only=0"),
    scalar(env, "SELECT COUNT(*) AS n FROM lumen_opportunity_assessments WHERE synthetic_or_test_only=1"),
    scalar(env, "SELECT COUNT(*) AS n FROM lumen_proposal_drafts WHERE status='DRAFT'"),
    scalar(env, "SELECT COUNT(*) AS n FROM lumen_proposal_drafts WHERE status='APPROVED'"),
    scalar(env, "SELECT COUNT(*) AS n FROM lumen_proposal_drafts WHERE status='SENT'"),
    scalar(env, "SELECT COUNT(*) AS n FROM lumen_proposal_drafts WHERE status='RESPONDED'"),
    scalar(env, "SELECT COUNT(*) AS n FROM lumen_proposal_drafts WHERE quality_gate_status='PASS'"),
    scalar(env, "SELECT COUNT(*) AS n FROM lumen_proposal_drafts WHERE quality_gate_status='FAIL'"),
    scalar(env, "SELECT COUNT(*) AS n FROM lumen_outreach_attempts WHERE status IN ('SENT','SENT_TASK','WORKING','RESPONDED','TASK_TERMINAL')"),
    scalar(env, "SELECT COUNT(*) AS n FROM lumen_outreach_attempts WHERE status='RESPONDED'"),
    scalar(env, "SELECT COUNT(*) AS n FROM lumen_outreach_attempts WHERE status='SEND_FAILED'"),
    scalar(env, "SELECT COUNT(*) AS n FROM lumen_sales_pipeline WHERE stage='NEGOTIATING'"),
    scalar(env, "SELECT COUNT(*) AS n FROM lumen_sales_pipeline WHERE stage IN ('WAITING','WAITING_TASK')"),
    scalar(env, "SELECT COUNT(*) AS n FROM lumen_sales_pipeline WHERE stage='NO_RESPONSE'"),
    scalar(env, "SELECT COUNT(*) AS n FROM lumen_sales_pipeline WHERE stage='LOST'"),
    scalar(env, "SELECT COUNT(*) AS n FROM lumen_sales_pipeline WHERE stage='WAITING' AND next_action_at IS NOT NULL AND next_action_at<=?", [now]),
    scalar(env, "SELECT COUNT(*) AS n FROM lumen_followups WHERE status IN ('SENT','SENT_TASK','WORKING','RESPONDED')"),
    scalar(env, "SELECT COUNT(*) AS n FROM lumen_revenue_events WHERE event_type='payment_settled' AND status='verified'"),
    scalar(env, "SELECT COALESCE(SUM(amount_usd),0) AS n FROM lumen_revenue_events WHERE event_type='payment_settled' AND status='verified'"),
  ]);

  const [pipeline, top, recent, health, outreachLive, followupLive] = await Promise.all([
    rows(env, "SELECT proposal_id,opportunity_id,target,offer_name,amount_usd,stage,response_class,last_contact_at,next_action,next_action_at,followup_count,updated_at,notes FROM lumen_sales_pipeline ORDER BY CASE stage WHEN 'NEGOTIATING' THEN 1 WHEN 'RESPONDED' THEN 2 WHEN 'WAITING' THEN 3 WHEN 'WAITING_TASK' THEN 4 WHEN 'APPROVED' THEN 5 ELSE 6 END, COALESCE(next_action_at,updated_at) ASC LIMIT 60"),
    rows(env, "SELECT o.id,o.name,o.revenue_offer_id,a.commercial_score,a.commercial_fit,a.evidence_strength FROM lumen_opportunities o JOIN lumen_opportunity_assessments a ON a.opportunity_id=o.id WHERE a.commercially_actionable=1 AND a.synthetic_or_test_only=0 ORDER BY a.commercial_score DESC,o.updated_at DESC LIMIT 8"),
    rows(env, "SELECT proposal_id,opportunity_id,status,updated_at,task_id,error FROM lumen_outreach_attempts ORDER BY updated_at DESC LIMIT 8"),
    serviceJson(env, "/health"),
    serviceJson(env, "/outreach/stats"),
    serviceJson(env, "/followup/stats"),
  ]);

  let bestAction = "Buscar y calificar demanda nueva";
  let actionState = "BUSCANDO";
  if (negotiating > 0) {
    bestAction = "Priorizar respuestas con intención y llevarlas a checkout";
    actionState = "NEGOCIANDO";
  } else if (dueFollowups > 0) {
    bestAction = `Ejecutar ${dueFollowups} seguimiento${dueFollowups === 1 ? "" : "s"} comercial${dueFollowups === 1 ? "" : "es"} vencido${dueFollowups === 1 ? "" : "s"}`;
    actionState = "SIGUIENDO";
  } else if (waiting > 0) {
    bestAction = "Esperar cooldowns y seguir prospectando sin duplicar contactos";
    actionState = "ESPERANDO RESPUESTAS";
  } else if (approved > 0 || qualityPass > outreachSent) {
    bestAction = "Enviar la próxima propuesta aprobada por Quality Gate";
    actionState = "EJECUTANDO";
  } else if (actionable > 0) {
    bestAction = "Convertir la mejor oportunidad comercial en propuesta";
    actionState = "PREPARANDO";
  }

  return json({
    version: "2.1-control-tower-live-d1",
    generatedAt: now,
    objective: settlements > 0 ? "ESCALAR INGRESOS VERIFICADOS" : "GENERAR INGRESOS",
    bestAction,
    actionState,
    system: {
      a2aOnline: health?.ok === true,
      x402: health?.x402 || "UNKNOWN",
      outreachAutonomous: outreachLive?.autonomousOutreachEnabled === true,
      followupAutonomous: followupLive?.autonomousFollowupEnabled === true,
      autonomousOutgoingSpend: false,
      autonomousContract: false,
      cooldownDays: Number(followupLive?.cooldownDays || 4),
      maxFollowups: Number(followupLive?.maxFollowups || 2),
      dataPlane: "live_d1_a2a",
    },
    funnel: {
      opportunities, demand, actionable, highScore, testOnly, drafts, approved,
      qualityPass, qualityFail, outreachSent, outreachResponded, outreachFailed,
      sentProposals, respondedProposals, negotiating, waiting, noResponse, lost,
      dueFollowups, followupsSent, settlements, realizedRevenueUsd,
    },
    revenue: { verifiedSettlements: settlements, realizedRevenueUsd },
    pipeline,
    top,
    recent,
  }, { "x-lumen-control-source": "live-d1-v1" });
}

function moduleRow(id, name, state, metric, detail = "") {
  return { id, name, state, metric, detail };
}

async function liveNetwork(request, env) {
  const denied = protect(request, env);
  if (denied) return denied;

  const [
    partnersLive, recruitment, council, delegation, observed, venture,
    gaps, graph, marketplace, referrals, negotiator, dynamicTeams,
    redundancy, trust, economyLive,
  ] = await Promise.all([
    serviceJson(env, "/partners/stats"),
    serviceJson(env, "/recruitment/stats"),
    serviceJson(env, "/council-runtime/stats"),
    serviceJson(env, "/delegation/stats"),
    serviceJson(env, "/partners/observed-reputation/stats"),
    serviceJson(env, "/venture-council/stats"),
    serviceJson(env, "/capability-gaps/stats"),
    serviceJson(env, "/agent-graph/stats"),
    serviceJson(env, "/partner-marketplace/stats"),
    serviceJson(env, "/referrals/stats"),
    serviceJson(env, "/negotiator/stats"),
    serviceJson(env, "/dynamic-teams/stats"),
    serviceJson(env, "/redundancy/stats"),
    serviceJson(env, "/trust/stats"),
    serviceJson(env, "/agent-economy/stats"),
  ]);

  const [
    partnerCountDb, trustAllowDb, councilDb, delegationDb, ventureDb,
    gapDb, referralDb, negotiationDb, teamDb, realizedDb, potentialDb,
    topPartners,
  ] = await Promise.all([
    scalar(env, "SELECT COUNT(*) AS n FROM lumen_partner_agents"),
    scalar(env, "SELECT COUNT(*) AS n FROM lumen_partner_trust WHERE trust_level='ALLOW'"),
    scalar(env, "SELECT COUNT(*) AS n FROM lumen_council_rooms"),
    scalar(env, "SELECT COUNT(*) AS n FROM lumen_delegation_tasks"),
    scalar(env, "SELECT COUNT(*) AS n FROM lumen_venture_cases WHERE status<>'SOURCE_REJECTED'"),
    scalar(env, "SELECT COUNT(*) AS n FROM lumen_capability_gap_queue WHERE status<>'COVERED'"),
    scalar(env, "SELECT COUNT(*) AS n FROM lumen_referrals"),
    scalar(env, "SELECT COUNT(*) AS n FROM lumen_negotiation_cases"),
    scalar(env, "SELECT COUNT(*) AS n FROM lumen_dynamic_teams WHERE status='DRAFT_TEAM'"),
    scalar(env, "SELECT COALESCE(SUM(amount_usd),0) AS n FROM lumen_revenue_events WHERE event_type='payment_settled' AND status='verified'"),
    scalar(env, "SELECT COALESCE(SUM(amount_usd),0) AS n FROM lumen_proposal_drafts WHERE status IN ('APPROVED','SENT','RESPONDED')"),
    rows(env, `SELECT p.id,p.name,p.capabilities_json,p.reputation_score,p.compatibility_score,p.status,
      t.trust_score,t.trust_level,t.signature_status,
      o.score AS observed_score,o.confidence AS observed_confidence,o.reliability_score,o.responsiveness_score
      FROM lumen_partner_agents p
      LEFT JOIN lumen_partner_trust t ON t.partner_id=p.id
      LEFT JOIN lumen_partner_observed_reputation o ON o.partner_id=p.id
      ORDER BY COALESCE(t.trust_score,0) DESC,p.reputation_score DESC LIMIT 12`),
  ]);

  const partners = partnersLive || { total: partnerCountDb, strongCandidates: 0 };
  if (partners.total == null) partners.total = partnerCountDb;
  const trustState = trust || { allow: trustAllowDb, caution: 0, quarantine: 0 };
  if (trustState.allow == null) trustState.allow = trustAllowDb;
  const councilState = council || { rooms: councilDb, contributions: 0, synthesized: 0 };
  const delegationState = delegation || { total: delegationDb, completed: 0 };
  const ventureState = venture || { total: ventureDb, bestReadiness: 0 };
  const gapState = gaps || { open: gapDb, weakCoverage: 0 };
  const referralState = referrals || { total: referralDb, outboundCandidates: 0, trustedInbound: 0 };
  const negotiatorState = negotiator || { totalCases: negotiationDb, readyForHumanReview: 0, incompleteTerms: 0 };
  const teamState = dynamicTeams || { activeDraftTeams: teamDb, bestTeamScore: 0 };
  const economy = economyLive || {
    potentialIncomeUsd: potentialDb,
    realizedIncomeUsd: realizedDb,
    proposedExpenseUsd: 0,
    outgoingSpendHardBlocked: true,
  };
  if (economy.realizedIncomeUsd == null) economy.realizedIncomeUsd = realizedDb;
  if (economy.potentialIncomeUsd == null) economy.potentialIncomeUsd = potentialDb;
  economy.proposedExpenseUsd = Number(economy.proposedExpenseUsd || 0);

  const modules = [
    moduleRow(1, "Recruitment Engine", partnersLive ? "OPERATIVO" : "LISTO", `${Number(partners.total || 0)} agentes descubiertos`, "lectura viva"),
    moduleRow(2, "Sala de Juntas", council ? "OPERATIVO" : "LISTO", `${Number(councilState.rooms || councilDb)} salas`),
    moduleRow(3, "Delegación de tareas", delegation ? "OPERATIVO" : "LISTO", `${Number(delegationState.total || delegationDb)} tareas`),
    moduleRow(4, "Reputación observada", observed ? "OPERATIVO" : "LISTO", `${Number(observed?.withEvidence || 0)} con evidencia`),
    moduleRow(5, "Venture Council", venture ? "OPERATIVO" : "LISTO", `${Number(ventureState.total || ventureDb)} casos`),
    moduleRow(6, "Capability Gap Engine", gaps ? "OPERATIVO" : "LISTO", `${Number(gapState.open || gapDb)} gaps abiertos`),
    moduleRow(7, "Agent Graph", graph ? "OPERATIVO" : "LISTO", `${Number(graph?.nodes || 0)} nodos / ${Number(graph?.edges || 0)} vínculos`),
    moduleRow(8, "Partner Marketplace", marketplace ? "OPERATIVO" : "LISTO", `${Number(marketplace?.needs?.open || 0)} necesidades abiertas`),
    moduleRow(9, "Referral Network", referrals ? "OPERATIVO" : "LISTO", `${Number(referralState.total || referralDb)} referrals`),
    moduleRow(10, "Economía entre agentes", economyLive ? "OPERATIVO" : "LISTO", `USD ${Number(economy.potentialIncomeUsd || 0)} potencial`, `USD ${Number(economy.realizedIncomeUsd || 0)} realizado`),
    moduleRow(11, "Negotiator", negotiator ? "OPERATIVO" : "LISTO", `${Number(negotiatorState.totalCases || negotiationDb)} casos`),
    moduleRow(12, "Equipos dinámicos", dynamicTeams ? "OPERATIVO" : "LISTO", `${Number(teamState.activeDraftTeams || teamDb)} equipos activos`),
    moduleRow(13, "Redundancia", redundancy ? "OPERATIVO" : "LISTO", `${Number(redundancy?.readyAlternates || redundancy?.readyFallbacks || 0)} fallbacks listos`),
    moduleRow(14, "Trust Layer", trust ? "OPERATIVO" : "LISTO", `${Number(trustState.allow || trustAllowDb)} ALLOW`),
    moduleRow(15, "Torre de Control de la Red", "ONLINE", "lectura viva D1/A2A", "sin dependencia del estado legado"),
  ];

  const safeTopPartners = topPartners.map((p) => ({
    ...p,
    economic_score: null,
    economic_confidence: 0,
    verified_revenue_usd: 0,
    verified_settlements: 0,
    verified_referral_settlements: 0,
  }));

  return json({
    version: "1.1-network-control-live-d1",
    generatedAt: new Date().toISOString(),
    objective: "ORQUESTAR LA RED Y CONVERTIR COLABORACIÓN EN INGRESOS VERIFICADOS",
    bestAction: Number(economy.realizedIncomeUsd || 0) > 0
      ? "Escalar las combinaciones que ya produjeron ingresos verificados."
      : "Priorizar microbuyers y oportunidades con intención comercial hasta lograr el primer settlement.",
    partners,
    recruitment: recruitment || partners,
    council: councilState,
    delegation: delegationState,
    observed: observed || {},
    venture: ventureState,
    gaps: gapState,
    graph: graph || {},
    marketplace: marketplace || { needs: { open: 0 }, interests: { matchCandidates: 0 } },
    referrals: referralState,
    negotiator: negotiatorState,
    dynamicTeams: teamState,
    redundancy: redundancy || { readyAlternates: 0, weakAlternates: 0 },
    trust: trustState,
    economy,
    modules,
    topPartners: safeTopPartners,
    rooms: [],
    tasks: [],
    ventures: [],
    negotiations: [],
    referralRows: [],
    gapRows: [],
    economyIntents: [],
    teams: [],
    graphEdges: [],
    partnerEconomic: {
      total: Number(partners.total || partnerCountDb),
      revenueProducingPartners: 0,
      meaningfulEconomicConfidence: 0,
      totalPartnerAttributedRevenueUsd: Number(economy.realizedIncomeUsd || 0),
    },
    guardrails: {
      outgoingBudgetUsd: 0,
      outgoingSpendHardBlocked: true,
      autonomousOutgoingSpend: false,
      autonomousPurchase: false,
      autonomousContract: false,
      bindingActionsHumanGated: true,
      verifiedSettlementRequiredForIncome: true,
    },
  }, { "x-lumen-network-source": "live-d1-a2a-v1" });
}

function isLegacyRetryable(request) {
  if (request.method !== "GET") return false;
  return LEGACY_RETRYABLE_PATHS.has(new URL(request.url).pathname);
}

function liveOwnerSummaryScript() {
  return `<script id="lumenLiveOwnerSummaryV4">
(()=>{
  const e=id=>document.getElementById(id);
  const set=(id,v)=>{const el=e(id);if(el)el.textContent=v;};
  const usd=v=>'USD '+Number(v||0).toLocaleString('es-AR',{maximumFractionDigits:2});
  const setMany=(ids,v)=>ids.forEach(id=>set(id,v));
  async function refresh(){
    try{
      const r=await fetch('/api/control-tower-v2',{cache:'no-store'});
      if(!r.ok)return;
      const d=await r.json(),f=d.funnel||{};
      const totalProposals=Number(f.drafts||0)+Number(f.approved||0)+Number(f.sentProposals||0)+Number(f.respondedProposals||0);
      const strictDemand=Number(f.negotiating||0),actionable=Number(f.actionable||0),replies=Number(f.outreachResponded||0),revenue=Number(f.realizedRevenueUsd||0);
      const focus=revenue>0?'Escalar ingresos verificados':strictDemand>0?'Convertir demanda real en cobro':actionable>0?'Convertir oportunidades en demanda verificable':'Encontrar la primera demanda verificable';
      const detail=revenue>0?'Hay ingresos verificados: el foco es repetir los patrones que ya convirtieron.':strictDemand>0?'Ya existe intención comercial suficiente; prioridad: checkout y settlement verificado.':actionable>0?'Hay oportunidades accionables en el motor vivo; falta convertir una en intención de compra verificable.':'First Cash sigue buscando evidencia comercial real sin inflar actividad como resultado.';
      setMany(['lumenRevenue','lfRevenue'],usd(revenue));
      setMany(['lumenDemand','lfDemand'],strictDemand.toLocaleString('es-AR'));
      setMany(['lumenOpps','lfOpps'],actionable.toLocaleString('es-AR'));
      setMany(['lumenProposals','lfProposals'],totalProposals.toLocaleString('es-AR'));
      setMany(['lumenReplies','lfReplies'],replies.toLocaleString('es-AR'));
      set('lfClose',strictDemand.toLocaleString('es-AR'));
      setMany(['lumenFocus','lfFocus'],focus);
      setMany(['lumenFocusDetail','lfDetail'],detail);
      setMany(['lumenAutonomy','lfAutonomy'],'OPERANDO');
      set('lumenBudgetNow','First Cash: búsqueda cada 15 min · contacto máx. 1 por hora');
      set('lfSearch','Búsqueda: cada 15 min · contacto: máx. 1 por hora');
      set('lumenNeedsYou',strictDemand>0?'Necesita de vos: sólo si aparece una acción vinculante':'Necesita de vos: nada ahora');
      set('lfBlocker',revenue>0?'Bloqueo: ninguno crítico':'Objetivo: primer settlement verificado');
    }catch{}
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',refresh,{once:true});else refresh();
  setTimeout(refresh,800);setInterval(refresh,20000);
})();
</script>`;
}

function liveRefreshScript() {
  return `<script id="lumenLiveRefreshV1">
(()=>{
  const install=()=>{
    const old=document.getElementById('lumenRefreshBtn');
    if(!old||old.dataset.liveRefresh==='1')return;
    const btn=old.cloneNode(true);btn.dataset.liveRefresh='1';old.replaceWith(btn);
    const status=document.getElementById('lumenRefreshStatus');
    btn.addEventListener('click',async()=>{
      btn.disabled=true;btn.textContent='Actualizando…';
      if(status){status.textContent='';status.style.color='#8fa7b3';}
      try{
        const rs=await Promise.all([
          fetch('/health',{cache:'no-store'}),
          fetch('/api/control-tower-v2',{cache:'no-store'}),
          fetch('/api/network-control-v1',{cache:'no-store'})
        ]);
        if(rs.some(r=>!r.ok))throw new Error('alguna fuente viva no respondió');
        btn.textContent='Datos actualizados';
        if(status){status.textContent='D1 + A2A en vivo';status.style.color='#9de8c5';}
        setTimeout(()=>{btn.textContent='Actualizar datos';btn.disabled=false;},1200);
      }catch(err){
        btn.textContent='Reintentar';
        if(status){status.textContent='No pude leer las fuentes vivas';status.style.color='#ff9a9a';}
        btn.disabled=false;
      }
    });
  };
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>setTimeout(install,0),{once:true});else setTimeout(install,0);
  setTimeout(install,1000);
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

  html = html
    .replace(/<script id="lumenLiveOwnerSummaryV2">[\s\S]*?<\/script>/, "")
    .replace(/<script id="lumenLiveOwnerSummaryV3">[\s\S]*?<\/script>/, "");

  if (!html.includes('id="lumenLiveOwnerSummaryV4"')) {
    html = html.replace("</body>", `${liveOwnerSummaryScript()}</body>`);
  }
  if (!html.includes('id="lumenLiveRefreshV1"')) {
    html = html.replace("</body>", `${liveRefreshScript()}</body>`);
  }

  const headers = new Headers(response.headers);
  headers.delete("content-length");
  headers.set("cache-control", "no-store, no-cache, must-revalidate");
  headers.set("pragma", "no-cache");
  headers.set("expires", "0");
  headers.set("x-lumen-tab-normalization", "v4");
  headers.set("x-lumen-owner-summary", "a2a-live-v4");

  return new Response(html, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === "/health") {
      return liveHealth(request, env);
    }
    if (request.method === "GET" && url.pathname === "/api/control-tower-v2") {
      return liveControl(request, env);
    }
    if (request.method === "GET" && url.pathname === "/api/network-control-v1") {
      return liveNetwork(request, env);
    }

    if (!isLegacyRetryable(request)) {
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
    headers.set("x-lumen-dashboard-read-status", "legacy_state_unavailable");
    return new Response(lastResponse?.body || "Legacy state temporarily unavailable", {
      status: lastResponse?.status || 503,
      statusText: lastResponse?.statusText || "Service Unavailable",
      headers,
    });
  },
};
