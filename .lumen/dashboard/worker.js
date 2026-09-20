const STATE_KEY = "global";

function unauthorized() {
  return new Response("LUMEN · acceso restringido", {
    status: 401,
    headers: { "WWW-Authenticate": 'Basic realm="LUMEN"', "Cache-Control": "no-store" },
  });
}

function locked() {
  return new Response("LUMEN dashboard todavía no tiene contraseña configurada.", {
    status: 503,
    headers: { "Cache-Control": "no-store" },
  });
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
    return user === String(env.LUMEN_DASHBOARD_USER || "socio") && pass === password;
  } catch {
    return false;
  }
}

async function sha256Hex(bytes) {
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(hash)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function loadState(env) {
  const manifest = await env.DB.prepare(
    "SELECT encoding, chunk_count, payload_sha256, uncompressed_bytes, updated_at FROM lumen_state_manifest WHERE state_key = ? LIMIT 1"
  ).bind(STATE_KEY).first();
  if (!manifest) throw new Error("state_not_initialized");
  if (manifest.encoding !== "zlib+base64+json") throw new Error("unsupported_state_encoding");

  const rows = await env.DB.prepare(
    "SELECT chunk_no, payload FROM lumen_state_chunks WHERE state_key = ? ORDER BY chunk_no ASC"
  ).bind(STATE_KEY).all();
  const chunks = rows.results || [];
  if (chunks.length !== Number(manifest.chunk_count || 0)) throw new Error("incomplete_state_chunks");

  const encoded = chunks.map((r) => String(r.payload || "")).join("");
  const binary = atob(encoded);
  const compressed = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) compressed[i] = binary.charCodeAt(i);

  const stream = new Blob([compressed]).stream().pipeThrough(new DecompressionStream("deflate"));
  const raw = new Uint8Array(await new Response(stream).arrayBuffer());
  const digest = await sha256Hex(raw);
  if (manifest.payload_sha256 && digest !== manifest.payload_sha256) throw new Error("state_checksum_mismatch");

  const state = JSON.parse(new TextDecoder().decode(raw));
  return { state, manifest };
}

function n(v) { return Number(v || 0); }
function arr(v) { return Array.isArray(v) ? v : []; }
function obj(v) { return v && typeof v === "object" && !Array.isArray(v) ? v : {}; }
function s(v, fallback = "") { const out = String(v ?? "").trim(); return out || fallback; }
function firstObj(...values) { for (const value of values) { if (value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).length) return value; } return {}; }

function summarize(state, manifest) {
  const funnel = obj(state.business_funnel);
  const readiness = obj(state.external_market_readiness);
  const scoutStatus = obj(state.scout_status);
  const scoutBudget = obj(state.scout_budget);
  const demandBudget = obj(state.demand_search_budget);
  const adaptiveBudget = obj(state.adaptive_search_budget);
  const workforceRoot = obj(state.agent_workforce);
  const workforce = firstObj(workforceRoot.last_cycle, state.agent_workforce_last, state.workforce_last_cycle);
  const watchdog = obj(state.system_watchdog);
  const revenue = obj(state.revenue_execution_v2);
  const revenueFunnel = obj(revenue.revenue_funnel);
  const revCounts = obj(revenueFunnel.counts);
  const secretary = obj(state.executive_secretary_private_bridge || state.executive_secretary);
  const crd = obj(state.continuous_revenue_drive);
  const money = obj(state.money_engine);
  const service = firstObj(state.service_growth_pipeline, state.service_revenue_runtime);
  const intelligence = firstObj(state.intelligence_revenue_engine, obj(state.intelligence_cycle_bridge).intelligence_revenue);
  const partner = obj(state.partner_network);
  const distribution = obj(state.distribution_operator);
  const acquisition = obj(state.acquisition_campaigns);
  const instagram = obj(state.instagram_publish_control);
  const notification = obj(state.notification_router);
  const meta = obj(state.meta_autonomy);
  const canonical = obj(state.canonical_priority_cleanup);

  const generalDaily = n(adaptiveBudget.general_pool_daily || scoutBudget.daily_budget || scoutStatus.general_retail_pool_daily);
  const demandDaily = n(adaptiveBudget.demand_reserved_daily || demandBudget.daily_budget || scoutStatus.demand_reserved_daily);
  const hardCap = n(adaptiveBudget.total_daily_cap || scoutStatus.daily_query_budget || scoutBudget.total_daily_cap || (generalDaily + demandDaily));
  const generalUsed = n(scoutBudget.queries_used);
  const demandUsed = n(demandBudget.queries_used);
  const totalUsed = Math.min(hardCap || (generalUsed + demandUsed), generalUsed + demandUsed);
  const totalRemaining = Math.max(0, (hardCap || 0) - generalUsed - demandUsed);
  const generalRemaining = scoutBudget.queries_remaining !== undefined ? n(scoutBudget.queries_remaining) : Math.max(0, generalDaily - generalUsed);
  const demandRemaining = demandBudget.queries_remaining !== undefined ? n(demandBudget.queries_remaining) : Math.max(0, demandDaily - demandUsed);

  const fleetSize = n(workforce.fleet_size || workforceRoot.roster_count || arr(workforceRoot.roster).length);
  const companyCycle = n(workforce.company_cycle || state.ticks);
  const workerStatus = s(workforce.status, fleetSize ? "healthy" : "unknown");
  const byRoleRaw = obj(workforce.by_role);
  const byRole = Object.entries(byRoleRaw).map(([key, value]) => ({
    key,
    recruited: n(obj(value).recruited),
    assignments: n(obj(value).assignments),
    web_searches: n(obj(value).web_searches),
    errors: n(obj(value).errors),
  })).filter((x) => x.recruited || x.assignments || x.web_searches || x.errors);

  const activities = arr(state.activity).slice(0, 36).map((x) => ({ ts: x.ts || "", msg: x.msg || "" }));
  const pending = arr(secretary.pending).slice(0, 12).map((x) => ({
    title: x.title || "Pendiente", reason: x.reason || "", priority: n(x.priority), risk: x.risk || "",
  }));
  const news = arr(secretary.news).slice(0, 8).map((x) => ({
    title: x.title || "Novedad", summary: x.summary || "", category: x.category || "", created_at: x.created_at || "",
  }));

  const realizedRevenue = n(
    money.realized_revenue_truth_usd ||
    service.realized_service_revenue_usd ||
    obj(state.expansion_revenue_runtime).revenue_generated_usd
  );

  return {
    status: {
      runtime: "LUMEN Zero",
      persistence: "Cloudflare D1",
      state_updated_at: manifest.updated_at || state.last_tick || null,
      state_bytes: n(manifest.uncompressed_bytes),
      ticks: n(state.ticks),
      watchdog_status: watchdog.status || "unknown",
      watchdog_score: n(watchdog.score_pct),
      company_cycle: companyCycle,
      fleet_size: fleetSize,
      worker_status: workerStatus,
      master_mode: s(meta.company_mode || state.master_company_mode, "REVENUE_EXECUTION"),
      management_department: s(meta.management_department, "Market Intelligence"),
      management_priority: s(meta.management_priority, "repair_weakest_department"),
    },
    funnel: {
      research_leads: n(funnel.research_leads ?? arr(state.research_leads).length),
      candidate_accounts: n(funnel.candidate_accounts ?? arr(state.candidate_accounts).length),
      verified_companies: n(funnel.verified_companies),
      verified_buyers: n(funnel.verified_buyers),
      verified_suppliers: n(funnel.verified_suppliers),
      verified_contacts: n(funnel.verified_commercial_channels || funnel.verified_corporate_emails),
      buyers_with_demand: n(funnel.buyers_with_public_demand),
      requirements_ready: n(funnel.requirements_ready_for_rfq),
      opportunities: n(funnel.evidence_backed_opportunities ?? revCounts.market_opportunities),
      outbound_sent: n(funnel.outbound_sent),
      inbound_received: n(funnel.inbound_received),
      real_offers: n(funnel.real_offers),
      proposals: n(funnel.proposals),
      viable_deals: n(funnel.viable_deals),
      close_ready: n(funnel.close_ready),
    },
    scout: {
      provider: scoutStatus.provider || "bing_rss_public",
      paid_search: Boolean(scoutStatus.paid_search),
      used: totalUsed,
      remaining: totalRemaining,
      general_used: generalUsed,
      general_remaining: generalRemaining,
      demand_used: demandUsed,
      demand_remaining: demandRemaining,
      hard_cap: hardCap,
      general_daily: generalDaily,
      demand_daily: demandDaily,
      strategy: s(obj(state.scout).strategy || crd.primary_lane, "demand_discovery"),
      budget_reason: s(adaptiveBudget.reason),
    },
    outbound: {
      live: Boolean(readiness.outbound_live),
      mail_ready: Boolean(readiness.mail_transport_ready),
      mail_provider: readiness.mail_provider || null,
      eligible_prospects: n(readiness.eligible_external_prospects),
      blocker: readiness.primary_blocker || null,
      outbox_ready: n(readiness.outbox_ready),
      sent_or_delivered: n(readiness.outbox_sent_or_delivered),
      failed: n(readiness.outbox_failed),
      social_waiting: n(readiness.social_jobs_awaiting_authorized_connector),
      instagram_configured: Boolean(instagram.connector_configured),
      instagram_approval_required: instagram.approval_required_per_post !== false,
      whatsapp_ready: Boolean(notification.delivery_ready),
    },
    revenue: {
      realized_usd: realizedRevenue,
      opportunities: n(revCounts.market_opportunities),
      proposals: n(revCounts.proposals),
      active_deals: n(revCounts.active_deals),
      close_ready: n(revCounts.close_ready),
      primary_lane: s(crd.primary_lane, "distribution"),
      primary_action: s(crd.primary_action),
      objective: s(crd.objective, "maximizar progreso comercial verificado hacia ingresos rentables"),
      service_pipeline: n(service.pipeline_total || service.prepared_service_opportunities),
      service_contacted: n(service.real_contacted),
      intelligence_candidates: n(intelligence.verified_candidates),
      intelligence_contacted: n(intelligence.real_contacted),
      partner_stores: n(partner.stores_total),
      active_partners: n(partner.active_partners),
      referral_offers: n(partner.referral_offers_active),
    },
    distribution: {
      jobs_total: n(distribution.jobs_total),
      owned_live: n(distribution.owned_live),
      external_verified: n(distribution.external_verified),
      awaiting_connector: n(distribution.awaiting_connector),
      campaigns_active: n(acquisition.campaigns_active),
      clicks: n(acquisition.clicks),
      leads: n(acquisition.leads),
    },
    workforce: {
      fleet_size: fleetSize,
      assignments_created: n(workforce.assignments_created),
      assignments_completed: n(workforce.assignments_completed),
      searches: n(workforce.provider_searches || workforce.web_searches),
      cache_hits: n(workforce.search_cache_hits),
      errors: n(workforce.errors),
      bottleneck: s(workforce.bottleneck, "verification_contact"),
      scale_direction: s(workforce.scale_direction, "hold"),
      workload_score: n(workforce.workload_score),
      by_role: byRole,
      top_findings: arr(workforce.top_findings).slice(0, 9),
    },
    strategy: {
      canonical_lane: s(canonical.canonical_lane || crd.primary_lane, "demand_discovery"),
      management_department: s(meta.management_department, "Market Intelligence"),
      controller_mode: s(meta.controller_mode, "BUILD_VALUE"),
      recommended_scenario: s(meta.recommended_scenario, "baseline"),
    },
    activity: activities,
    pending,
    news,
  };
}

const HTML = `<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#071018"><title>LUMEN · Centro de Comando</title>
<style>
:root{color-scheme:dark;--bg:#060d13;--bg2:#0a1822;--card:#0c1720;--card2:#0f202b;--line:#1b3544;--line2:#274e61;--text:#eef7fb;--muted:#86a0af;--lime:#d7ff64;--good:#8ee8bf;--warn:#ffd36e;--bad:#ff8f94;--blue:#7bdcff;--violet:#b8a7ff;--shadow:0 18px 50px #0007}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:radial-gradient(circle at 95% 0,#153a47 0,#0a1922 24%,#060d13 55%) fixed;color:var(--text);font:14px Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;padding:0}.shell{max-width:1420px;margin:auto;padding:18px 18px 88px}.topbar{position:sticky;top:0;z-index:10;padding:14px 0 12px;background:linear-gradient(180deg,#060d13f5 70%,#060d1300);backdrop-filter:blur(16px)}.brandline{display:flex;justify-content:space-between;gap:16px;align-items:center}.brand{display:flex;align-items:center;gap:12px}.mark{width:42px;height:42px;border-radius:13px;background:linear-gradient(145deg,var(--lime),#76e2bc);color:#071018;display:grid;place-items:center;font-weight:1000;box-shadow:0 0 26px #d7ff6433}.logo{font-size:25px;font-weight:950;letter-spacing:.16em;line-height:1}.sub{color:var(--muted);font-size:12px;margin-top:5px}.topactions{display:flex;gap:8px;align-items:center}.pill{display:inline-flex;align-items:center;gap:7px;border:1px solid var(--line2);border-radius:999px;padding:8px 11px;color:var(--good);background:#0b211b;font-size:12px;white-space:nowrap}.dot{width:8px;height:8px;border-radius:50%;background:currentColor;box-shadow:0 0 12px currentColor}.btn{background:var(--lime);color:#071018;border:0;border-radius:11px;padding:10px 13px;font-weight:900;cursor:pointer}.btn:active{transform:translateY(1px)}.tabs{display:flex;gap:8px;overflow:auto;padding:8px 0 2px;scrollbar-width:none}.tabs::-webkit-scrollbar{display:none}.tab{border:1px solid var(--line);background:#0a151d;color:var(--muted);padding:8px 12px;border-radius:999px;white-space:nowrap;cursor:pointer;font-weight:700}.tab.active{color:#071018;background:var(--lime);border-color:var(--lime)}.view{display:none}.view.active{display:block}.hero{display:grid;grid-template-columns:1.55fr .9fr;gap:12px;margin-top:10px}.heroMain{background:linear-gradient(135deg,#0d202b,#0b151d 70%);border:1px solid var(--line);border-radius:22px;padding:22px;box-shadow:var(--shadow);position:relative;overflow:hidden}.heroMain:after{content:"";position:absolute;width:240px;height:240px;border-radius:50%;right:-90px;top:-110px;background:radial-gradient(circle,#d7ff6430,#d7ff6400 67%)}.eyebrow{text-transform:uppercase;letter-spacing:.16em;font-size:10px;color:var(--muted);font-weight:800}.headline{font-size:clamp(25px,4vw,43px);font-weight:950;line-height:1.03;margin:8px 0 12px;max-width:780px}.headline em{font-style:normal;color:var(--lime)}.heroText{max-width:780px;color:#a9c0cc;line-height:1.55}.heroMeta{display:flex;flex-wrap:wrap;gap:8px;margin-top:18px}.chip{border:1px solid #28485a;border-radius:10px;background:#08131a;padding:8px 10px;color:#b7cad5;font-size:12px}.heroSide{display:grid;grid-template-columns:1fr 1fr;gap:10px}.mini{background:linear-gradient(180deg,#0e1d27,#0a151d);border:1px solid var(--line);border-radius:18px;padding:16px}.mini .val{font-size:26px;font-weight:900;margin-top:8px}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.section{margin-top:12px}.card{background:linear-gradient(180deg,#0e1c26,#0a151d);border:1px solid var(--line);border-radius:18px;padding:16px;box-shadow:0 12px 34px #0004}.cardTitle{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px}.label{text-transform:uppercase;letter-spacing:.13em;font-size:10px;color:var(--muted);font-weight:800}.kpi{font-size:29px;font-weight:900;margin-top:7px;letter-spacing:-.02em}.kpi.sm{font-size:22px}.good{color:var(--good)}.warn{color:var(--warn)}.bad{color:var(--bad)}.blue{color:var(--blue)}.muted{color:var(--muted)}.tiny{font-size:12px;color:var(--muted);line-height:1.45}.cols{display:grid;grid-template-columns:1.2fr .8fr;gap:12px}.colsEqual{display:grid;grid-template-columns:1fr 1fr;gap:12px}.bar{height:8px;background:#071018;border:1px solid #173241;border-radius:999px;overflow:hidden;margin-top:10px}.bar>i{display:block;height:100%;background:linear-gradient(90deg,var(--lime),var(--good));width:0;transition:width .35s ease}.bar.warnbar>i{background:linear-gradient(90deg,var(--warn),var(--lime))}.row{display:grid;grid-template-columns:1fr auto;gap:12px;padding:10px 0;border-bottom:1px solid #17303e;align-items:center}.row:last-child{border-bottom:0}.row b{font-variant-numeric:tabular-nums}.funnelRow{display:grid;grid-template-columns:minmax(130px,1fr) minmax(90px,2fr) 42px;gap:10px;align-items:center;padding:8px 0}.funnelTrack{height:9px;border-radius:999px;background:#071018;border:1px solid #173241;overflow:hidden}.funnelFill{height:100%;min-width:2px;background:linear-gradient(90deg,#56cfb2,var(--lime));border-radius:999px}.channel{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:11px 0;border-bottom:1px solid #17303e}.channel:last-child{border-bottom:0}.channelLeft{display:flex;align-items:center;gap:10px}.icon{width:34px;height:34px;border-radius:10px;display:grid;place-items:center;background:#102532;border:1px solid #214658;font-weight:900}.state{padding:5px 8px;border-radius:999px;font-size:10px;font-weight:900;letter-spacing:.05em;background:#13231d;color:var(--good);border:1px solid #275443}.state.off{background:#261719;color:var(--bad);border-color:#593036}.state.wait{background:#272214;color:var(--warn);border-color:#594c25}.activity{max-height:520px;overflow:auto;padding-right:4px}.event{padding:11px 0;border-bottom:1px solid #17303e}.event:last-child{border-bottom:0}.time{font-size:11px;color:#668396;margin-top:4px}.priority{border:1px solid #1b3544;border-radius:13px;padding:12px;margin-top:8px;background:#09151d}.priorityHead{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}.priorityScore{font-size:11px;padding:4px 7px;border-radius:8px;background:#17242d;color:var(--lime)}.roles{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:10px}.role{padding:11px;border-radius:13px;border:1px solid #1d3948;background:#0a161e}.role b{display:block;font-size:18px;margin-top:4px}.lane{border:1px solid #1b3544;border-radius:14px;padding:13px;background:#09151d}.laneTop{display:flex;justify-content:space-between;gap:10px;align-items:center}.metricline{display:flex;gap:15px;flex-wrap:wrap;margin-top:9px}.metricline span{font-size:11px;color:var(--muted)}.metricline b{color:var(--text);font-size:13px;margin-left:4px}.banner{padding:13px 14px;border:1px solid #3b5b2a;background:#142017;border-radius:15px;color:#dff5b3;line-height:1.5}.empty{padding:20px 0;color:var(--muted);text-align:center}.bottomNav{display:none}.skeleton{opacity:.5;animation:pulse 1.2s infinite}@keyframes pulse{50%{opacity:.8}}@media(max-width:980px){.hero{grid-template-columns:1fr}.grid{grid-template-columns:1fr 1fr}.cols,.colsEqual{grid-template-columns:1fr}.roles{grid-template-columns:1fr 1fr}}@media(max-width:620px){.shell{padding:10px 12px 88px}.topbar{padding-top:8px}.brandline{align-items:flex-start}.topactions .pill{display:none}.logo{font-size:22px}.mark{width:38px;height:38px}.heroMain{padding:18px}.heroSide{grid-template-columns:1fr 1fr}.grid{grid-template-columns:1fr 1fr}.card{padding:14px}.kpi{font-size:26px}.headline{font-size:29px}.roles{grid-template-columns:1fr 1fr}.tabs{display:none}.bottomNav{display:grid;grid-template-columns:repeat(4,1fr);position:fixed;left:10px;right:10px;bottom:10px;z-index:20;background:#0a151df2;border:1px solid #284456;border-radius:18px;padding:6px;box-shadow:var(--shadow);backdrop-filter:blur(18px)}.navBtn{border:0;background:transparent;color:#7f98a6;padding:9px 2px;border-radius:12px;font-size:10px;font-weight:800}.navBtn.active{background:#17272f;color:var(--lime)}.funnelRow{grid-template-columns:110px 1fr 35px}.heroMeta{gap:6px}.chip{padding:7px 8px}}@media(max-width:380px){.grid{grid-template-columns:1fr}.heroSide{grid-template-columns:1fr 1fr}.roles{grid-template-columns:1fr}.headline{font-size:26px}}
</style></head><body><div class="shell">
<div class="topbar"><div class="brandline"><div class="brand"><div class="mark">L</div><div><div class="logo">LUMEN</div><div class="sub">Centro de Comando · Zero Cost Runtime</div></div></div><div class="topactions"><span class="pill"><i class="dot"></i><span id="updatedTop">Cargando estado</span></span><button class="btn" onclick="load()">Actualizar</button></div></div><div class="tabs"><button class="tab active" data-view="summary">Resumen</button><button class="tab" data-view="commercial">Comercial</button><button class="tab" data-view="operations">Operación</button><button class="tab" data-view="activity">Actividad</button></div></div>

<section class="view active" id="view-summary">
<div class="hero"><div class="heroMain"><div class="eyebrow">Misión actual</div><div class="headline">Convertir investigación en <em>negocios reales</em>.</div><div class="heroText" id="missionText">LUMEN está leyendo el estado operativo y comercial.</div><div class="heroMeta"><span class="chip" id="modeChip">Modo —</span><span class="chip" id="laneChip">Carril —</span><span class="chip" id="cycleChip">Ciclo —</span><span class="chip" id="freshChip">Estado —</span></div></div><div class="heroSide"><div class="mini"><div class="label">Watchdog</div><div class="val" id="watchdogHero">–</div><div class="bar"><i id="watchbarHero"></i></div></div><div class="mini"><div class="label">Fuerza digital</div><div class="val" id="fleetHero">–</div><div class="tiny" id="fleetHeroDetail">agentes</div></div><div class="mini"><div class="label">Scout disponible</div><div class="val" id="searchHero">–</div><div class="tiny" id="searchHeroDetail">búsquedas</div></div><div class="mini"><div class="label">Email</div><div class="val" id="mailHero">–</div><div class="tiny" id="mailHeroDetail">canal</div></div></div></div>
<div class="grid section"><div class="card"><div class="label">Leads de investigación</div><div class="kpi" id="leads">–</div><div class="tiny">materia prima comercial</div></div><div class="card"><div class="label">Empresas verificadas</div><div class="kpi blue" id="verified">–</div><div class="tiny">identidad corporativa confirmada</div></div><div class="card"><div class="label">Prospectos habilitados</div><div class="kpi" id="eligible">–</div><div class="tiny">aptos para salida comercial</div></div><div class="card"><div class="label">Ingresos realizados USD</div><div class="kpi good" id="revenue">–</div><div class="tiny">sólo cobros/realizaciones verificadas</div></div></div>
<div class="cols section"><div class="card"><div class="cardTitle"><div class="label">Embudo comercial real</div><span class="tiny" id="funnelHint"></span></div><div id="funnelVisual"></div></div><div class="card"><div class="cardTitle"><div class="label">Cuello de botella</div><span class="state wait" id="blockerState">ATENCIÓN</span></div><div class="kpi sm" id="blocker">–</div><div class="tiny" id="blockerDetail"></div><div class="banner section" id="nextAction">Analizando próxima acción…</div></div></div>
<div class="colsEqual section"><div class="card"><div class="cardTitle"><div class="label">Canales externos</div><span class="tiny">estado real</span></div><div id="channels"></div></div><div class="card"><div class="cardTitle"><div class="label">Presupuesto de búsqueda</div><span class="tiny" id="searchProvider"></span></div><div class="row"><span>General</span><b id="generalBudget">–</b></div><div class="bar"><i id="generalBar"></i></div><div class="row"><span>Demanda / compras públicas</span><b id="demandBudget">–</b></div><div class="bar warnbar"><i id="demandBar"></i></div><div class="tiny section" id="budgetReason"></div></div></div>
</section>

<section class="view" id="view-commercial">
<div class="grid section"><div class="card"><div class="label">Inbound recibido</div><div class="kpi" id="inbound">–</div></div><div class="card"><div class="label">Emails enviados</div><div class="kpi" id="sent">–</div></div><div class="card"><div class="label">Oportunidades</div><div class="kpi" id="opps">–</div></div><div class="card"><div class="label">Propuestas</div><div class="kpi" id="proposals">–</div></div></div>
<div class="colsEqual section"><div class="card"><div class="cardTitle"><div class="label">Monetización</div><span class="tiny">rutas paralelas</span></div><div id="moneyLanes"></div></div><div class="card"><div class="cardTitle"><div class="label">Distribución / adquisición</div><span class="tiny">canales propios y autorizados</span></div><div id="distribution"></div></div></div>
<div class="cols section"><div class="card"><div class="label">Embudo detallado</div><div id="funnelRows"></div></div><div class="card"><div class="label">Estrategia comercial</div><div id="strategyRows"></div></div></div>
</section>

<section class="view" id="view-operations">
<div class="grid section"><div class="card"><div class="label">Agentes activos</div><div class="kpi" id="fleet">–</div></div><div class="card"><div class="label">Asignaciones completadas</div><div class="kpi" id="assignments">–</div></div><div class="card"><div class="label">Búsquedas este ciclo</div><div class="kpi" id="cycleSearches">–</div></div><div class="card"><div class="label">Errores de agentes</div><div class="kpi" id="agentErrors">–</div></div></div>
<div class="colsEqual section"><div class="card"><div class="cardTitle"><div class="label">Equipos digitales</div><span class="tiny" id="scaleDirection"></span></div><div class="roles" id="roles"></div></div><div class="card"><div class="cardTitle"><div class="label">Hallazgos del ciclo</div><span class="tiny" id="workload"></span></div><div id="findings"></div></div></div>
<div class="colsEqual section"><div class="card"><div class="label">Sistema</div><div id="systemRows"></div></div><div class="card"><div class="label">Estado de búsqueda</div><div id="searchRows"></div></div></div>
</section>

<section class="view" id="view-activity">
<div class="cols section"><div class="card"><div class="cardTitle"><div class="label">Actividad reciente</div><span class="tiny">últimos eventos persistidos</span></div><div class="activity" id="activity"></div></div><div><div class="card"><div class="cardTitle"><div class="label">Prioridades de LUMEN</div><span class="tiny">orden operativo</span></div><div id="pending"></div></div><div class="card section"><div class="cardTitle"><div class="label">Novedades</div><span class="tiny">eventos ejecutivos</span></div><div id="news"></div></div></div></div>
</section>
</div>
<div class="bottomNav"><button class="navBtn active" data-view="summary">RESUMEN</button><button class="navBtn" data-view="commercial">COMERCIAL</button><button class="navBtn" data-view="operations">OPERACIÓN</button><button class="navBtn" data-view="activity">ACTIVIDAD</button></div>
<script>
const $=id=>document.getElementById(id);const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=n=>Number(n||0).toLocaleString('es-AR');
const pct=(a,b)=>b>0?Math.max(0,Math.min(100,(Number(a||0)/Number(b))*100)):0;
function rows(items){return items.map(([a,b])=>'<div class="row"><span>'+esc(a)+'</span><b>'+esc(b)+'</b></div>').join('')}
function setView(name){document.querySelectorAll('.view').forEach(x=>x.classList.toggle('active',x.id==='view-'+name));document.querySelectorAll('[data-view]').forEach(x=>x.classList.toggle('active',x.dataset.view===name));window.scrollTo({top:0,behavior:'smooth'});}
document.querySelectorAll('[data-view]').forEach(x=>x.addEventListener('click',()=>setView(x.dataset.view)));
function stateBadge(ok,waiting){return '<span class="state '+(ok?'':waiting?'wait':'off')+'">'+(ok?'OPERATIVO':waiting?'EN ESPERA':'NO LISTO')+'</span>'}
function channelRow(icon,title,detail,ok,waiting){return '<div class="channel"><div class="channelLeft"><div class="icon">'+esc(icon)+'</div><div><b>'+esc(title)+'</b><div class="tiny">'+esc(detail)+'</div></div></div>'+stateBadge(ok,waiting)+'</div>'}
function funnelVisual(d){const stages=[['Leads',d.research_leads],['Candidatas',d.candidate_accounts],['Verificadas',d.verified_companies],['Contactos',d.verified_contacts],['Demanda',d.buyers_with_demand],['Oportunidades',d.opportunities],['Propuestas',d.proposals],['Cierre',d.close_ready]];const max=Math.max(1,...stages.map(x=>Number(x[1]||0)));return stages.map(x=>'<div class="funnelRow"><span>'+esc(x[0])+'</span><div class="funnelTrack"><div class="funnelFill" style="width:'+Math.max(x[1]?3:0,(Number(x[1]||0)/max)*100)+'%"></div></div><b>'+fmt(x[1])+'</b></div>').join('')}
function lane(title,status,metrics){return '<div class="lane section"><div class="laneTop"><b>'+esc(title)+'</b><span class="state '+(status==='activo'?'':'wait')+'">'+esc(status.toUpperCase())+'</span></div><div class="metricline">'+metrics.map(x=>'<span>'+esc(x[0])+' <b>'+esc(x[1])+'</b></span>').join('')+'</div></div>'}
function roleName(k){return ({buyer_hunter:'Buyer Hunter',supplier_hunter:'Supplier Hunter',market_scout:'Market Scout',research_analyst:'Research',revops:'RevOps',negotiator:'Negociador',market_manager:'Market',risk_quality:'Risk & QA',finance:'Finance'})[k]||k}
function humanBlocker(x){return ({no_eligible_external_prospects:'Sin prospectos verificados habilitados',outbound_live_disabled:'Salida comercial desactivada',mail_provider_api_probe_failed:'Email no disponible'})[x]||x||'Sin bloqueo crítico'}
function freshLabel(ts){if(!ts)return 'sin fecha';const d=new Date(String(ts).replace(' UTC','Z'));if(Number.isNaN(d.getTime()))return ts;const mins=Math.round((Date.now()-d.getTime())/60000);if(mins<2)return 'actualizado ahora';if(mins<60)return 'hace '+mins+' min';const h=Math.round(mins/60);return 'hace '+h+' h'}
async function load(){try{const r=await fetch('/api/summary',{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);const d=await r.json();const okMail=d.outbound.mail_ready&&d.outbound.live;const updated=freshLabel(d.status.state_updated_at);$('updatedTop').textContent=updated;$('modeChip').textContent='Modo '+d.status.master_mode;$('laneChip').textContent='Carril '+d.revenue.primary_lane;$('cycleChip').textContent='Ciclo '+d.status.company_cycle;$('freshChip').textContent=updated;$('missionText').textContent=d.revenue.primary_action||d.revenue.objective;$('watchdogHero').textContent=Number(d.status.watchdog_score||0).toFixed(1)+'%';$('watchdogHero').className='val '+(d.status.watchdog_score>=90?'good':d.status.watchdog_score>=75?'warn':'bad');$('watchbarHero').style.width=Math.max(0,Math.min(100,d.status.watchdog_score))+'%';$('fleetHero').textContent=fmt(d.status.fleet_size);$('fleetHeroDetail').textContent='agentes · '+d.status.worker_status;$('searchHero').textContent=fmt(d.scout.remaining);$('searchHeroDetail').textContent='de '+fmt(d.scout.hard_cap)+' búsquedas diarias';$('mailHero').textContent=okMail?'OK':'WAIT';$('mailHero').className='val '+(okMail?'good':'warn');$('mailHeroDetail').textContent=(d.outbound.mail_provider||'sin proveedor')+' · enviados '+fmt(d.funnel.outbound_sent);
$('leads').textContent=fmt(d.funnel.research_leads);$('verified').textContent=fmt(d.funnel.verified_companies);$('eligible').textContent=fmt(d.outbound.eligible_prospects);$('revenue').textContent='$'+Number(d.revenue.realized_usd||0).toFixed(2);$('funnelVisual').innerHTML=funnelVisual(d.funnel);$('funnelHint').textContent=fmt(d.funnel.research_leads)+' → '+fmt(d.funnel.close_ready);$('blocker').textContent=humanBlocker(d.outbound.blocker);$('blocker').className='kpi sm '+(d.outbound.blocker?'warn':'good');$('blockerState').textContent=d.outbound.blocker?'ATENCIÓN':'LIBRE';$('blockerState').className='state '+(d.outbound.blocker?'wait':'');$('blockerDetail').textContent='Elegibles '+fmt(d.outbound.eligible_prospects)+' · Outbox '+fmt(d.outbound.outbox_ready)+' · Social esperando '+fmt(d.outbound.social_waiting);$('nextAction').textContent=d.revenue.primary_action||'Seguir construyendo evidencia comercial verificada.';
$('channels').innerHTML=channelRow('@','Email',d.outbound.mail_provider||'sin proveedor',okMail,!okMail)+channelRow('IG','Instagram',d.outbound.instagram_configured?'conector autorizado':'conector pendiente',d.outbound.instagram_configured,!d.outbound.instagram_configured)+channelRow('WA','WhatsApp',d.outbound.whatsapp_ready?'entrega disponible':'conector pendiente',d.outbound.whatsapp_ready,!d.outbound.whatsapp_ready);$('searchProvider').textContent=d.scout.provider;$('generalBudget').textContent=fmt(d.scout.general_used)+' / '+fmt(d.scout.general_daily);$('generalBar').style.width=pct(d.scout.general_used,d.scout.general_daily)+'%';$('demandBudget').textContent=fmt(d.scout.demand_used)+' / '+fmt(d.scout.demand_daily);$('demandBar').style.width=pct(d.scout.demand_used,d.scout.demand_daily)+'%';$('budgetReason').textContent=d.scout.budget_reason||'Presupuesto compartido con tope diario.';
$('inbound').textContent=fmt(d.funnel.inbound_received);$('sent').textContent=fmt(d.funnel.outbound_sent);$('opps').textContent=fmt(d.funnel.opportunities);$('proposals').textContent=fmt(d.funnel.proposals);$('moneyLanes').innerHTML=lane('First Cash / negocio B2B',d.revenue.primary_lane?'activo':'espera',[['Oportunidades',fmt(d.funnel.opportunities)],['Close ready',fmt(d.funnel.close_ready)]])+lane('Servicios',d.revenue.service_pipeline||d.revenue.service_contacted?'activo':'espera',[['Pipeline',fmt(d.revenue.service_pipeline)],['Contactados',fmt(d.revenue.service_contacted)]])+lane('Inteligencia comercial',d.revenue.intelligence_candidates||d.revenue.intelligence_contacted?'activo':'espera',[['Candidatos',fmt(d.revenue.intelligence_candidates)],['Contactados',fmt(d.revenue.intelligence_contacted)]])+lane('Partners / referral',d.revenue.active_partners?'activo':'espera',[['Tiendas',fmt(d.revenue.partner_stores)],['Partners',fmt(d.revenue.active_partners)],['Ofertas',fmt(d.revenue.referral_offers)]]);$('distribution').innerHTML=rows([['Jobs preparados',fmt(d.distribution.jobs_total)],['Owned live',fmt(d.distribution.owned_live)],['Externos verificados',fmt(d.distribution.external_verified)],['Esperando conector',fmt(d.distribution.awaiting_connector)],['Campañas activas',fmt(d.distribution.campaigns_active)],['Clicks',fmt(d.distribution.clicks)],['Leads',fmt(d.distribution.leads)]]);$('funnelRows').innerHTML=rows([['Leads investigación',fmt(d.funnel.research_leads)],['Cuentas candidatas',fmt(d.funnel.candidate_accounts)],['Empresas verificadas',fmt(d.funnel.verified_companies)],['Compradores verificados',fmt(d.funnel.verified_buyers)],['Proveedores verificados',fmt(d.funnel.verified_suppliers)],['Contactos verificados',fmt(d.funnel.verified_contacts)],['Demanda pública',fmt(d.funnel.buyers_with_demand)],['Requisitos listos',fmt(d.funnel.requirements_ready)],['Oportunidades',fmt(d.funnel.opportunities)],['Ofertas reales',fmt(d.funnel.real_offers)],['Propuestas',fmt(d.funnel.proposals)],['Deals viables',fmt(d.funnel.viable_deals)],['Close ready',fmt(d.funnel.close_ready)]]);$('strategyRows').innerHTML=rows([['Carril canónico',d.strategy.canonical_lane],['Área a mejorar',d.strategy.management_department],['Controller',d.strategy.controller_mode],['Escenario',d.strategy.recommended_scenario],['Objetivo',d.revenue.objective]]);
$('fleet').textContent=fmt(d.workforce.fleet_size);$('assignments').textContent=fmt(d.workforce.assignments_completed)+'/'+fmt(d.workforce.assignments_created);$('cycleSearches').textContent=fmt(d.workforce.searches);$('agentErrors').textContent=fmt(d.workforce.errors);$('agentErrors').className='kpi '+(d.workforce.errors?'bad':'good');$('scaleDirection').textContent='escala '+d.workforce.scale_direction;$('workload').textContent='carga '+Number(d.workforce.workload_score||0).toFixed(1);$('roles').innerHTML=d.workforce.by_role.length?d.workforce.by_role.map(x=>'<div class="role"><div class="tiny">'+esc(roleName(x.key))+'</div><b>'+fmt(x.recruited)+'</b><div class="tiny">'+fmt(x.assignments)+' asignaciones · '+fmt(x.errors)+' errores</div></div>').join(''):'<div class="empty">Sin desglose de roles en este estado.</div>';$('findings').innerHTML=d.workforce.top_findings.length?d.workforce.top_findings.map(x=>'<div class="event">'+esc(x)+'</div>').join(''):'<div class="empty">Sin hallazgos persistidos.</div>';$('systemRows').innerHTML=rows([['Runtime',d.status.runtime],['Persistencia',d.status.persistence],['Estado D1',updated],['Watchdog',Number(d.status.watchdog_score||0).toFixed(1)+'%'],['Ciclos',fmt(d.status.ticks)],['Estado workforce',d.status.worker_status]]);$('searchRows').innerHTML=rows([['Proveedor',d.scout.provider],['Pagado',d.scout.paid_search?'sí':'no'],['Usadas',fmt(d.scout.used)],['Restantes',fmt(d.scout.remaining)],['Tope diario',fmt(d.scout.hard_cap)],['Estrategia',d.scout.strategy]]);
$('activity').innerHTML=d.activity.length?d.activity.map(x=>'<div class="event"><div>'+esc(x.msg)+'</div><div class="time">'+esc(x.ts)+'</div></div>').join(''):'<div class="empty">Sin actividad.</div>';$('pending').innerHTML=d.pending.length?d.pending.map(x=>'<div class="priority"><div class="priorityHead"><b>'+esc(x.title)+'</b><span class="priorityScore">P '+Number(x.priority||0).toFixed(0)+'</span></div><div class="tiny section">'+esc(x.reason)+'</div></div>').join(''):'<div class="empty">Sin pendientes prioritarios.</div>';$('news').innerHTML=d.news.length?d.news.map(x=>'<div class="event"><b>'+esc(x.title)+'</b><div class="tiny">'+esc(x.summary)+'</div><div class="time">'+esc(x.created_at)+'</div></div>').join(''):'<div class="empty">Sin novedades nuevas.</div>';
}catch(e){$('updatedTop').textContent='Error leyendo estado';console.error(e)}}load();setInterval(load,30000);
</script></body></html>`;

export default {
  async fetch(request, env) {
    const auth = authOK(request, env);
    if (auth === null) return locked();
    if (!auth) return unauthorized();

    const url = new URL(request.url);
    if (url.pathname === "/health") {
      return Response.json({ ok: true, service: "lumen-zero-dashboard", backend: "cloudflare-worker+d1", ui: "command-center-v2" }, { headers: { "Cache-Control": "no-store" } });
    }
    if (url.pathname === "/api/summary") {
      try {
        const { state, manifest } = await loadState(env);
        return Response.json(summarize(state, manifest), { headers: { "Cache-Control": "no-store" } });
      } catch (e) {
        return Response.json({ ok: false, error: String(e && e.message || e) }, { status: 503, headers: { "Cache-Control": "no-store" } });
      }
    }
    if (url.pathname === "/" || url.pathname === "/index.html") {
      return new Response(HTML, { headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff", "Permissions-Policy": "camera=(), microphone=(), geolocation=()" } });
    }
    return new Response("Not found", { status: 404 });
  },
};
