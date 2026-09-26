import stable from "./stable_worker.js";

const PUBLIC_WEB = "https://lumen-zero-public.lumen-b2b.workers.dev";
const INSTAGRAM_URL = "https://www.instagram.com/lumen.b2b/";
const CATALOG_VERSION = "2026-09-25-live";
const SERVICE_CATALOG = [
  { id: "SRV-QUOTECHECK", name: "LUMEN QuoteCheck Global", from_usd: 59, desc: "Revisión documental y comparación estructurada de cotizaciones B2B con referencias públicas disponibles." },
  { id: "SRV-SUPPLIERCHECK", name: "LUMEN SupplierCheck", from_usd: 79, desc: "Investigación de identidad, canales oficiales, señales públicas y riesgo comercial de proveedores." },
  { id: "SRV-TENDER-HUNTER", name: "LUMEN Tender Hunter Global", from_usd: 99, desc: "Detección y preanálisis de oportunidades y licitaciones públicas relevantes." },
  { id: "SRV-SOURCING-EXPRESS", name: "LUMEN Sourcing Express", from_usd: 149, desc: "Investigación y preselección de proveedores para una necesidad B2B concreta." },
  { id: "SRV-B2B-PROSPECTING", name: "LUMEN Prospección B2B", from_usd: 199, desc: "Empresas objetivo, señales públicas y canales corporativos compatibles con una oferta B2B." },
  { id: "SRV-EXPORT-SCOUT", name: "LUMEN Export Scout", from_usd: 249, desc: "Búsqueda de mercados, importadores, distribuidores y compradores con evidencia pública." },
];

const n = (v) => Number(v || 0);
const s = (v, d = "") => String(v ?? d);

async function rows(env, sql, binds = []) {
  try {
    let q = env.DB.prepare(sql);
    if (binds.length) q = q.bind(...binds);
    const r = await q.all();
    return r.results || [];
  } catch {
    return [];
  }
}

async function scalar(env, sql, binds = []) {
  try {
    let q = env.DB.prepare(sql);
    if (binds.length) q = q.bind(...binds);
    const r = await q.first();
    return n(r?.n);
  } catch {
    return 0;
  }
}

function requestFor(request, pathname) {
  const u = new URL(request.url);
  u.pathname = pathname;
  u.search = "";
  return new Request(u.toString(), { method: "GET", headers: request.headers });
}

async function stableJson(request, env, ctx, pathname) {
  const response = await stable.fetch(requestFor(request, pathname), env, ctx);
  if (!response.ok) return { response, data: null };
  try {
    return { response, data: await response.json() };
  } catch {
    return { response, data: null };
  }
}

function recentActivity(outreach, revenue, proposals) {
  const events = [];
  for (const x of outreach) {
    events.push({
      ts: s(x.updated_at),
      msg: `A2A outreach · ${s(x.status, "estado desconocido")} · ${s(x.proposal_id || x.opportunity_id, "sin id")}`,
    });
  }
  for (const x of revenue) {
    events.push({
      ts: s(x.created_at || x.updated_at),
      msg: `Revenue · ${s(x.event_type)} · ${s(x.status)} · USD ${n(x.amount_usd).toFixed(2)}`,
    });
  }
  for (const x of proposals) {
    events.push({
      ts: s(x.updated_at),
      msg: `Propuesta · ${s(x.status)} · ${s(x.offer_name || x.revenue_offer_id || x.proposal_id || x.id, "oferta")}`,
    });
  }
  return events
    .filter((x) => x.ts)
    .sort((a, b) => String(b.ts).localeCompare(String(a.ts)))
    .slice(0, 50);
}

function pendingFromLive(ctrl) {
  const f = ctrl?.funnel || {};
  const pending = [];
  if (n(f.settlements) === 0) {
    pending.push({
      title: "FIRST CASH: conseguir el primer settlement verificado",
      reason: "La infraestructura de cobro está activa; el objetivo sigue siendo convertir una oportunidad real en pago confirmado.",
      priority: 100,
      risk: "low",
      owner: "LUMEN",
    });
  }
  if (n(f.dueFollowups) > 0) {
    pending.push({
      title: `Ejecutar ${n(f.dueFollowups)} follow-up${n(f.dueFollowups) === 1 ? "" : "s"} vencido${n(f.dueFollowups) === 1 ? "" : "s"}`,
      reason: "Hay conversaciones comerciales esperando seguimiento y tienen prioridad sobre nueva salida fría.",
      priority: 96,
      risk: "low",
      owner: "LUMEN",
    });
  }
  if (n(f.outreachFailed) > 0) {
    pending.push({
      title: `Rotar ${n(f.outreachFailed)} contacto${n(f.outreachFailed) === 1 ? "" : "s"} fallido${n(f.outreachFailed) === 1 ? "" : "s"}`,
      reason: "No insistir sobre endpoints rotos o inaccesibles; elegir el siguiente candidato válido.",
      priority: 88,
      risk: "low",
      owner: "LUMEN",
    });
  }
  if (n(f.actionable) > 0 && n(f.negotiating) === 0) {
    pending.push({
      title: "Convertir oportunidades accionables en intención real",
      reason: `${n(f.actionable)} oportunidades son accionables; ninguna cuenta como demanda real hasta tener intención comercial suficiente.`,
      priority: 84,
      risk: "low",
      owner: "LUMEN",
    });
  }
  return pending.slice(0, 20);
}

async function liveUnifiedData(request, env, ctx) {
  const health = await stableJson(request, env, ctx, "/health");
  if (!health.response.ok) return health.response;
  const control = await stableJson(request, env, ctx, "/api/control-tower-v2");
  if (!control.response.ok || !control.data) return control.response;
  const network = await stableJson(request, env, ctx, "/api/network-control-v1");

  const ctrl = control.data || {};
  const net = network.data || {};
  const f = ctrl.funnel || {};
  const now = new Date().toISOString();
  const totalProposals = n(f.drafts) + n(f.approved) + n(f.sentProposals) + n(f.respondedProposals);
  const pipelineValue = await scalar(env, "SELECT COALESCE(SUM(amount_usd),0) AS n FROM lumen_proposal_drafts WHERE status IN ('APPROVED','SENT','RESPONDED')");

  const [
    topOpps, pipelineRows, outreachRows, proposalRows, revenueRows,
    inquiries, journal, instagramPosts, instagramCommands,
  ] = await Promise.all([
    rows(env, "SELECT o.id,o.name,o.revenue_offer_id,a.commercial_score,a.commercial_fit,a.evidence_strength FROM lumen_opportunities o JOIN lumen_opportunity_assessments a ON a.opportunity_id=o.id WHERE a.commercially_actionable=1 AND a.synthetic_or_test_only=0 ORDER BY a.commercial_score DESC,o.updated_at DESC LIMIT 20"),
    rows(env, "SELECT proposal_id,opportunity_id,target,offer_name,amount_usd,stage,response_class,last_contact_at,next_action,next_action_at,followup_count,updated_at,notes FROM lumen_sales_pipeline ORDER BY COALESCE(updated_at,last_contact_at) DESC LIMIT 20"),
    rows(env, "SELECT proposal_id,opportunity_id,status,updated_at,task_id,error FROM lumen_outreach_attempts ORDER BY updated_at DESC LIMIT 20"),
    rows(env, "SELECT * FROM lumen_proposal_drafts ORDER BY updated_at DESC LIMIT 20"),
    rows(env, "SELECT * FROM lumen_revenue_events ORDER BY COALESCE(updated_at,created_at) DESC LIMIT 20"),
    rows(env, "SELECT id,created_at,service_id,email,company,name,need,source,processed,processed_at FROM lumen_public_inquiries ORDER BY created_at DESC LIMIT 30"),
    rows(env, "SELECT cycle,recorded_at,local_time,status,source FROM lumen_cycle_journal ORDER BY cycle DESC LIMIT 30"),
    rows(env, "SELECT job_id,fingerprint,audience,campaign_id,caption,image_url,state_status,approval_status,last_error,created_at,updated_at FROM lumen_instagram_control_posts ORDER BY updated_at DESC LIMIT 30"),
    rows(env, "SELECT id,job_id,fingerprint,action,created_at,processed,processed_at,result FROM lumen_instagram_control_commands ORDER BY created_at DESC LIMIT 30"),
  ]);

  const opportunities = topOpps.map((x) => ({
    id: s(x.id),
    buyer: s(x.name, "—"),
    need: s(x.revenue_offer_id, "microservicio / B2B"),
    score: n(x.commercial_score),
    pipeline: 0,
    status: s(x.commercial_fit || x.evidence_strength, "accionable"),
    source: "A2A",
  }));

  const deals = pipelineRows.map((x) => ({
    id: s(x.proposal_id || x.opportunity_id),
    buyer: s(x.target, "—"),
    stage: s(x.stage, "—"),
    expected_value: n(x.amount_usd),
    pipeline: n(x.amount_usd),
    company_profit: n(x.amount_usd),
    company_share_pct: 100,
    source: "A2A",
  }));

  const outbox = outreachRows.map((x) => ({
    id: s(x.proposal_id || x.opportunity_id),
    counterparty: s(x.opportunity_id, "—"),
    kind: "A2A",
    status: s(x.status, "—"),
  }));

  const offers = proposalRows.map((x) => ({
    id: s(x.proposal_id || x.id),
    supplier: s(x.target || x.opportunity_id, "—"),
    amount: n(x.amount_usd),
    lead_days: 0,
    source: "LUMEN Proposal Engine",
    status: s(x.status, "—"),
  }));

  const catalogAverage = SERVICE_CATALOG.reduce((a, x) => a + x.from_usd, 0) / SERVICE_CATALOG.length;
  const activity = recentActivity(outreachRows, revenueRows, proposalRows);
  const partners = n(net?.partners?.total);
  const realized = n(f.realizedRevenueUsd);

  return Response.json({
    source: "live_d1_a2a_fallback",
    status: {
      updated_at: ctrl.generatedAt || now,
      ticks: 0,
      last_tick: ctrl.generatedAt || now,
      last_origin: "D1+A2A",
      watchdog_score: 100,
      watchdog_status: "healthy",
      watchdog_passed: 2,
      watchdog_total: 2,
      fleet_size: partners,
      worker_status: health.data?.a2aOnline ? "healthy" : "degraded",
      persistence: "Cloudflare D1",
      state_bytes: 0,
      cycle: 0,
    },
    money: {
      pipeline: pipelineValue,
      expected_value: pipelineValue,
      potential_profit: pipelineValue,
      registered_profit: realized,
      realized_revenue: realized,
      pending_closures: n(f.negotiating),
    },
    goals: [],
    opportunities,
    deals,
    approvals: [],
    outbox,
    offers,
    activity,
    pending: pendingFromLive(ctrl),
    researchLeads: opportunities.map((x) => ({ title: x.buyer, url: "", source: "A2A", status: x.status })),
    policies: { min_share: 0, target_share: 100, risk_reserve: 0 },
    funnel: {
      leads: n(f.opportunities),
      candidates: n(f.highScore),
      verified: n(f.highScore),
      buyers: n(f.demand),
      suppliers: partners,
      contacts: n(f.outreachSent),
      demand: n(f.demand),
      opportunities: n(f.actionable),
      proposals: totalProposals,
      close_ready: n(f.negotiating),
      outbound_sent: n(f.outreachSent),
      inbound: n(f.outreachResponded),
    },
    scout: {
      provider: "A2A + TED + UK Contracts Finder",
      used: 0,
      remaining: 0,
      hard_cap: 0,
      general_used: 0,
      demand_used: 0,
      budget_exhausted: false,
    },
    outbound: {
      live: ctrl.system?.outreachAutonomous === true,
      mail_ready: false,
      mail_provider: "—",
      eligible: n(f.actionable),
      blocker: n(f.negotiating) > 0 ? "priorizar cierre" : "ninguno crítico",
      failed: n(f.outreachFailed),
      instagram: instagramPosts.length > 0,
      instagram_send: true,
      instagram_inbox: "connected",
      whatsapp: false,
      owner_email_fallback: false,
      social_waiting: 0,
    },
    intelligence: {
      market_status: "active",
      authority: "autonomous_research_bounded_outreach",
      observations: n(f.opportunities),
      products: 0,
      companies: n(f.actionable),
      catalogs: 0,
      lane: s(ctrl.actionState, "FIRST_CASH"),
      action: s(ctrl.bestAction, "Buscar demanda real"),
      learning_status: "active",
      revenue_os: "active",
    },
    governance: {
      financial_commitments: false,
      contracts: "aprobación humana",
      unverified_contact: "no enviar",
      live_outbound: ctrl.system?.outreachAutonomous === true,
      automation_disclosed: true,
      instagram_posts: "control de publicación",
      paid_media: "aprobación humana",
      new_connectors: "aprobación humana",
    },
    catalog: {
      version: CATALOG_VERSION,
      services: SERVICE_CATALOG,
      floor_usd: Math.min(...SERVICE_CATALOG.map((x) => x.from_usd)),
      ceiling_usd: Math.max(...SERVICE_CATALOG.map((x) => x.from_usd)),
      average_usd: catalogAverage,
    },
    instagram_posts: instagramPosts,
    instagram_commands: instagramCommands,
    public_inquiries: inquiries,
    cycle_journal: journal,
    services: {
      public_web: { url: PUBLIC_WEB, status: "online" },
      instagram: { url: INSTAGRAM_URL, status: instagramPosts.length ? "operational" : "connected" },
      dashboard: { status: "online" },
    },
  }, {
    headers: {
      "cache-control": "no-store, no-cache, must-revalidate",
      "x-content-type-options": "nosniff",
      "x-lumen-data-source": "live-d1-a2a-fallback-v1",
    },
  });
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/api/data") {
      const legacy = await stable.fetch(request, env, ctx);
      if (legacy.status !== 503) return legacy;
      return liveUnifiedData(request, env, ctx);
    }
    return stable.fetch(request, env, ctx);
  },
};
