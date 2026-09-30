const VERSION = "1.0-travel-acquisition-engine";
const MAX_RECOMMENDATIONS = 5;
const VERIFIED_PAYOUT_STATUSES = ["PAID", "COMPLETED", "SENT", "PROCESSED"];

function clean(value, limit = 4000) {
  return String(value ?? "").trim().replace(/[\r\n\t]+/g, " ").slice(0, limit);
}

function json(data, status = 200) {
  return Response.json(data, {
    status,
    headers: {
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "access-control-allow-origin": "*",
      "access-control-allow-headers": "content-type,x-lumen-admin",
      "access-control-allow-methods": "GET,POST,OPTIONS"
    }
  });
}

function authorized(request, env) {
  const configured = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const provided = clean(request.headers.get("x-lumen-admin"), 500);
  return Boolean(configured && provided && configured === provided);
}

function num(value) {
  const n = Number(value || 0);
  return Number.isFinite(n) ? n : 0;
}

function bounded(value, min = 0, max = 100) {
  return Math.max(min, Math.min(max, value));
}

function slug(value, fallback = "travel") {
  const out = clean(value, 120)
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
  return out || fallback;
}

function safeUrl(value) {
  const raw = clean(value, 4000);
  if (!raw) return "";
  try {
    const u = new URL(raw);
    if (u.protocol !== "https:") return "";
    const host = u.hostname.toLowerCase();
    if (host !== "viator.com" && !host.endsWith(".viator.com")) return "";
    if (u.username || u.password) return "";
    return raw;
  } catch {
    return "";
  }
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_travel_acquisition_campaigns (id TEXT PRIMARY KEY,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,status TEXT NOT NULL,destination TEXT,product_id TEXT,source TEXT,channel TEXT,campaign TEXT,variant TEXT,content_angle TEXT,hook TEXT,body TEXT,cta TEXT,disclosure TEXT,target_url TEXT,tracking_path TEXT,score REAL NOT NULL DEFAULT 0,confidence TEXT NOT NULL,mode TEXT NOT NULL,rationale TEXT NOT NULL,metrics_snapshot_json TEXT NOT NULL,approval_required INTEGER NOT NULL DEFAULT 1,paid_spend_usd REAL NOT NULL DEFAULT 0,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_travel_acq_status_score ON lumen_travel_acquisition_campaigns(status,score DESC,updated_at DESC)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_travel_acq_destination ON lumen_travel_acquisition_campaigns(destination,updated_at DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_travel_acquisition_runs (id TEXT PRIMARY KEY,created_at TEXT NOT NULL,objective TEXT NOT NULL,recommendation_count INTEGER NOT NULL,exploit_count INTEGER NOT NULL,explore_count INTEGER NOT NULL,estimated_commission REAL NOT NULL DEFAULT 0,verified_paid_commission REAL NOT NULL DEFAULT 0,snapshot_json TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_travel_acq_runs_created ON lumen_travel_acquisition_runs(created_at DESC)")
  ]);
  return true;
}

async function safeAll(env, sql) {
  try {
    const result = await env.DB.prepare(sql).all();
    return result.results || [];
  } catch {
    return [];
  }
}

async function safeFirst(env, sql) {
  try { return await env.DB.prepare(sql).first(); }
  catch { return null; }
}

async function readSignals(env) {
  const [events, performance, intents, paid] = await Promise.all([
    safeAll(env, `SELECT
      COALESCE(NULLIF(destination,''),'') destination,
      COALESCE(NULLIF(product_id,''),'') product_id,
      COALESCE(NULLIF(source,''),'direct') source,
      COALESCE(NULLIF(campaign,''),'') campaign,
      COALESCE(NULLIF(variant,''),'') variant,
      SUM(CASE WHEN event_type='impression' THEN 1 ELSE 0 END) impressions,
      SUM(CASE WHEN event_type='search' THEN 1 ELSE 0 END) searches,
      SUM(CASE WHEN event_type='click' THEN 1 ELSE 0 END) clicks,
      MAX(CASE WHEN event_type='click' THEN target_url ELSE '' END) target_url,
      MAX(created_at) last_event
    FROM lumen_travel_events
    WHERE created_at >= datetime('now','-30 days')
    GROUP BY destination,product_id,source,campaign,variant
    ORDER BY clicks DESC,impressions DESC
    LIMIT 120`),
    safeAll(env, `SELECT
      COALESCE(NULLIF(campaign,''),'') campaign,
      COALESCE(NULLIF(source,''),'') source,
      SUM(sessions) sessions,
      SUM(pageviews) pageviews,
      SUM(bookings) bookings,
      SUM(booking_value) booking_value,
      SUM(commission_amount) estimated_commission,
      MAX(imported_at) last_import
    FROM lumen_viator_performance
    GROUP BY campaign,source
    ORDER BY estimated_commission DESC,bookings DESC,sessions DESC
    LIMIT 100`),
    safeAll(env, `SELECT id,destination,best_affiliate_url,recommendations_json,updated_at
      FROM lumen_travel_affiliate_intents
      WHERE status='READY'
      ORDER BY updated_at DESC
      LIMIT 100`),
    safeFirst(env, `SELECT
      COALESCE(SUM(commission_amount),0) paid_commission,
      COALESCE(SUM(bookings),0) paid_bookings,
      MAX(payout_date) last_payout
    FROM lumen_viator_payouts
    WHERE UPPER(COALESCE(payout_status,'UNKNOWN')) IN ('PAID','COMPLETED','SENT','PROCESSED')`)
  ]);
  return { events, performance, intents, paid: paid || {} };
}

function perfIndex(performance) {
  const map = new Map();
  for (const row of performance) {
    const campaign = clean(row.campaign, 180);
    const source = clean(row.source, 120);
    const keys = [`${campaign}|${source}`, `${campaign}|`, `|${source}`];
    for (const key of keys) {
      const prev = map.get(key) || { sessions:0,pageviews:0,bookings:0,bookingValue:0,estimatedCommission:0 };
      prev.sessions += num(row.sessions);
      prev.pageviews += num(row.pageviews);
      prev.bookings += num(row.bookings);
      prev.bookingValue += num(row.booking_value);
      prev.estimatedCommission += num(row.estimated_commission);
      map.set(key, prev);
    }
  }
  return map;
}

function lookupPerformance(index, campaign, source) {
  return index.get(`${campaign}|${source}`) || index.get(`${campaign}|`) || index.get(`|${source}`) || {
    sessions:0,pageviews:0,bookings:0,bookingValue:0,estimatedCommission:0
  };
}

function confidenceFor(metrics) {
  const evidence = Math.max(metrics.sessions, metrics.impressions, metrics.clicks * 5, metrics.bookings * 25);
  if (metrics.bookings >= 5 || evidence >= 250) return "HIGH";
  if (metrics.bookings >= 1 || evidence >= 60) return "MEDIUM";
  return "LOW";
}

function scoreCandidate(metrics) {
  const ctr = metrics.impressions > 0 ? metrics.clicks / metrics.impressions : 0;
  const bookingRate = metrics.sessions > 0 ? metrics.bookings / metrics.sessions : 0;
  const commissionPerSession = metrics.sessions > 0 ? metrics.estimatedCommission / metrics.sessions : 0;
  const revenueSignal = Math.min(38, metrics.estimatedCommission * 0.7) + Math.min(16, metrics.bookings * 4);
  const efficiencySignal = Math.min(14, commissionPerSession * 18) + Math.min(10, bookingRate * 250);
  const clickSignal = Math.min(14, ctr * 100) + Math.min(8, metrics.clicks * 0.8);
  const evidenceSignal = Math.min(6, Math.log10(1 + metrics.impressions + metrics.sessions) * 3);
  const score = bounded(18 + revenueSignal + efficiencySignal + clickSignal + evidenceSignal, 0, 100);
  return { score:Number(score.toFixed(2)), ctr, bookingRate, commissionPerSession };
}

function chooseVariant(existing, seed) {
  const normalized = clean(existing, 120).toLowerCase();
  if (normalized) return normalized;
  let sum = 0;
  for (const c of clean(seed, 200)) sum += c.charCodeAt(0);
  return sum % 2 === 0 ? "cta-price" : "cta-dates";
}

function ctaFor(variant) {
  return clean(variant, 80).includes("date") ? "Ver fechas disponibles" : "Ver precio y disponibilidad";
}

function draftFor(destination, variant) {
  const place = clean(destination, 120);
  const cta = ctaFor(variant);
  const hook = place
    ? `¿Viajás a ${place}? Estas experiencias merecen una mirada antes de armar el itinerario.`
    : "¿Estás armando un viaje? Compará experiencias antes de cerrar tu itinerario.";
  const body = place
    ? `LUMEN seleccionó opciones para ${place} según intención de viaje y señales reales de interés. Revisá detalles, precio y disponibilidad directamente antes de reservar.`
    : "LUMEN seleccionó experiencias según intención de viaje y señales reales de interés. Revisá detalles, precio y disponibilidad directamente antes de reservar.";
  return {
    contentAngle:"intent-led travel discovery",
    hook,
    body,
    cta,
    disclosure:"Enlace de afiliado: podemos recibir una comisión si reservás, sin costo adicional para vos."
  };
}

function channelFor(source) {
  const s = clean(source, 120).toLowerCase();
  if (s.includes("instagram") || s.includes("ig")) return "instagram_owned";
  if (s.includes("web") || s.includes("site")) return "web_owned";
  if (s.includes("inbound") || s.includes("a2a")) return "inbound_context";
  return "instagram_owned";
}

function trackingPath(targetUrl, fields) {
  if (!targetUrl) return "";
  const p = new URLSearchParams();
  p.set("url", targetUrl);
  p.set("source", fields.source || "travel-acquisition");
  p.set("campaign", fields.campaign || "lumen-travel");
  p.set("variant", fields.variant || "cta-price");
  if (fields.destination) p.set("destination", fields.destination);
  if (fields.productId) p.set("product_id", fields.productId);
  if (targetUrl.includes("pid=")) p.set("preserve", "1");
  return `/go/viator?${p.toString()}`;
}

function eventCandidates(signals) {
  const index = perfIndex(signals.performance);
  const out = [];
  for (const row of signals.events) {
    const destination = clean(row.destination, 160);
    const productId = clean(row.product_id, 180);
    const source = clean(row.source, 120) || "direct";
    const campaign = clean(row.campaign, 180) || `lumen-travel-${slug(destination)}`;
    const variant = chooseVariant(row.variant, `${destination}|${campaign}|${source}`);
    const perf = lookupPerformance(index, campaign, source);
    const metrics = {
      impressions:num(row.impressions), searches:num(row.searches), clicks:num(row.clicks),
      sessions:num(perf.sessions), bookings:num(perf.bookings), bookingValue:num(perf.bookingValue),
      estimatedCommission:num(perf.estimatedCommission)
    };
    const scored = scoreCandidate(metrics);
    const confidence = confidenceFor(metrics);
    const draft = draftFor(destination, variant);
    const targetUrl = safeUrl(row.target_url);
    out.push({
      destination, productId, source, campaign, variant, channel:channelFor(source), targetUrl,
      ...metrics, ...scored, confidence,
      mode:(metrics.bookings > 0 || metrics.estimatedCommission > 0 || confidence !== "LOW") ? "EXPLOIT" : "EXPLORE",
      rationale:metrics.estimatedCommission > 0
        ? "Prioridad por comisión estimada atribuida; CTR y reservas actúan como señales secundarias."
        : metrics.clicks > 0
          ? "Sin comisión atribuida todavía; prioridad provisional por clics/CTR hasta recibir Performance de Viator."
          : "Exploración controlada: todavía no hay evidencia suficiente para declararlo ganador.",
      ...draft
    });
  }
  return out;
}

function intentCandidates(signals, seenDestinations) {
  const out = [];
  for (const row of signals.intents) {
    const destination = clean(row.destination, 160);
    if (!destination || seenDestinations.has(destination.toLowerCase())) continue;
    const targetUrl = safeUrl(row.best_affiliate_url);
    if (!targetUrl) continue;
    const source = "travel-intent";
    const campaign = `lumen-travel-${slug(destination)}`;
    const variant = chooseVariant("", destination);
    const metrics = { impressions:0, searches:0, clicks:0, sessions:0, bookings:0, bookingValue:0, estimatedCommission:0 };
    const scored = scoreCandidate(metrics);
    const draft = draftFor(destination, variant);
    out.push({
      destination, productId:"", source, campaign, variant, channel:"instagram_owned", targetUrl,
      ...metrics, ...scored, confidence:"LOW", mode:"EXPLORE",
      rationale:"Nueva demanda Travel detectada sin historial suficiente; se propone como exploración controlada y medible.",
      ...draft
    });
  }
  return out;
}

function selectPortfolio(candidates) {
  const dedup = new Map();
  for (const item of candidates) {
    const key = `${item.destination}|${item.productId}|${item.source}|${item.variant}`.toLowerCase();
    const existing = dedup.get(key);
    if (!existing || item.score > existing.score) dedup.set(key, item);
  }
  const all = [...dedup.values()].sort((a,b) => b.score - a.score || b.estimatedCommission - a.estimatedCommission || b.clicks - a.clicks);
  const exploit = all.filter(x => x.mode === "EXPLOIT").slice(0, 4);
  const explore = all.filter(x => x.mode === "EXPLORE");
  const chosen = [...exploit];
  if (chosen.length < MAX_RECOMMENDATIONS && explore.length) chosen.push(explore[0]);
  for (const item of all) {
    if (chosen.length >= MAX_RECOMMENDATIONS) break;
    if (!chosen.includes(item)) chosen.push(item);
  }
  return chosen;
}

async function stableId(item) {
  const raw = `${item.destination}|${item.productId}|${item.source}|${item.campaign}|${item.variant}`;
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(raw)));
  const hash = [...digest].map(b => b.toString(16).padStart(2,"0")).join("").slice(0,24);
  return `TACQ-${hash.toUpperCase()}`;
}

async function persistRecommendations(env, items) {
  const now = new Date().toISOString();
  let stored = 0;
  for (const item of items) {
    const id = await stableId(item);
    const tPath = trackingPath(item.targetUrl, item);
    const metrics = {
      impressions:item.impressions, searches:item.searches, clicks:item.clicks, ctr:item.ctr,
      sessions:item.sessions, bookings:item.bookings, bookingRate:item.bookingRate,
      bookingValue:item.bookingValue, estimatedCommission:item.estimatedCommission,
      commissionPerSession:item.commissionPerSession
    };
    await env.DB.prepare(`INSERT INTO lumen_travel_acquisition_campaigns
      (id,created_at,updated_at,status,destination,product_id,source,channel,campaign,variant,content_angle,hook,body,cta,disclosure,target_url,tracking_path,score,confidence,mode,rationale,metrics_snapshot_json,approval_required,paid_spend_usd,engine_version)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
      ON CONFLICT(id) DO UPDATE SET
        updated_at=excluded.updated_at,destination=excluded.destination,product_id=excluded.product_id,source=excluded.source,
        channel=excluded.channel,campaign=excluded.campaign,variant=excluded.variant,content_angle=excluded.content_angle,
        hook=excluded.hook,body=excluded.body,cta=excluded.cta,disclosure=excluded.disclosure,target_url=excluded.target_url,
        tracking_path=excluded.tracking_path,score=excluded.score,confidence=excluded.confidence,mode=excluded.mode,
        rationale=excluded.rationale,metrics_snapshot_json=excluded.metrics_snapshot_json,approval_required=1,paid_spend_usd=0,
        engine_version=excluded.engine_version,status=CASE WHEN lumen_travel_acquisition_campaigns.status IN ('APPROVED','PUBLISHED') THEN lumen_travel_acquisition_campaigns.status ELSE 'RECOMMENDED' END`)
      .bind(id,now,now,"RECOMMENDED",item.destination,item.productId,item.source,item.channel,item.campaign,item.variant,item.contentAngle,item.hook,item.body,item.cta,item.disclosure,item.targetUrl,tPath,item.score,item.confidence,item.mode,item.rationale,JSON.stringify(metrics),1,0,VERSION).run();
    stored += 1;
  }
  return stored;
}

export async function runTravelAcquisitionEngine(env) {
  if (!await ensureSchema(env)) return { ok:false,error:"db_not_bound",version:VERSION };
  const signals = await readSignals(env);
  const fromEvents = eventCandidates(signals);
  const seen = new Set(fromEvents.map(x => x.destination.toLowerCase()).filter(Boolean));
  const fromIntents = intentCandidates(signals, seen);
  const recommendations = selectPortfolio([...fromEvents, ...fromIntents]);
  const stored = await persistRecommendations(env, recommendations);
  const estimatedCommission = signals.performance.reduce((sum,row) => sum + num(row.estimated_commission), 0);
  const verifiedPaidCommission = num(signals.paid.paid_commission);
  const now = new Date().toISOString();
  const exploitCount = recommendations.filter(x => x.mode === "EXPLOIT").length;
  const exploreCount = recommendations.filter(x => x.mode === "EXPLORE").length;
  const runId = `TARUN-${now.replace(/[-:.TZ]/g,"")}-${crypto.randomUUID().slice(0,8).toUpperCase()}`;
  const snapshot = {
    eventGroups:signals.events.length, performanceGroups:signals.performance.length, readyTravelIntents:signals.intents.length,
    estimatedCommission, verifiedPaidCommission, lastPayout:signals.paid.last_payout || null
  };
  await env.DB.prepare("INSERT INTO lumen_travel_acquisition_runs(id,created_at,objective,recommendation_count,exploit_count,explore_count,estimated_commission,verified_paid_commission,snapshot_json,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?)")
    .bind(runId,now,"verified_commission_then_estimated_commission_then_qualified_ctr",recommendations.length,exploitCount,exploreCount,estimatedCommission,verifiedPaidCommission,JSON.stringify(snapshot),VERSION).run();
  return {
    ok:true,version:VERSION,runId,stored,recommendationCount:recommendations.length,exploitCount,exploreCount,
    objective:"verified commission when attributable, otherwise estimated commission, otherwise qualified CTR",
    estimatedCommission:Number(estimatedCommission.toFixed(2)),verifiedPaidCommission:Number(verifiedPaidCommission.toFixed(2)),
    publicationAuthority:false,paidAds:false,autonomousSpendUsd:0,bindingActionsHumanGated:true
  };
}

async function status(env) {
  if (!env?.DB) return { ok:false,version:VERSION,dbBound:false };
  await ensureSchema(env);
  const [summary, latestRun, payout] = await Promise.all([
    safeFirst(env, `SELECT COUNT(*) total,SUM(CASE WHEN status='RECOMMENDED' THEN 1 ELSE 0 END) recommended,SUM(CASE WHEN status='APPROVED' THEN 1 ELSE 0 END) approved,SUM(CASE WHEN status='PUBLISHED' THEN 1 ELSE 0 END) published,SUM(CASE WHEN mode='EXPLOIT' THEN 1 ELSE 0 END) exploit,SUM(CASE WHEN mode='EXPLORE' THEN 1 ELSE 0 END) explore,MAX(updated_at) last_updated FROM lumen_travel_acquisition_campaigns`),
    safeFirst(env, `SELECT id,created_at,recommendation_count,exploit_count,explore_count,estimated_commission,verified_paid_commission FROM lumen_travel_acquisition_runs ORDER BY created_at DESC LIMIT 1`),
    safeFirst(env, `SELECT configured,method,confirmed_by_user FROM lumen_viator_payout_settings WHERE id='primary'`)
  ]);
  return {
    ok:true,version:VERSION,dbBound:true,
    campaigns:{ total:num(summary?.total),recommended:num(summary?.recommended),approved:num(summary?.approved),published:num(summary?.published),exploit:num(summary?.exploit),explore:num(summary?.explore),lastUpdated:summary?.last_updated || null },
    latestRun:latestRun || null,
    payoutMethod:{ configured:Boolean(payout?.configured),method:clean(payout?.method,40)||"UNKNOWN",confirmedByUser:Boolean(payout?.confirmed_by_user) },
    publicationAuthority:false,paidAds:false,autonomousSpendUsd:0
  };
}

async function recommendations(env) {
  await ensureSchema(env);
  const rows = await safeAll(env, `SELECT id,status,destination,product_id,source,channel,campaign,variant,content_angle,hook,body,cta,disclosure,target_url,tracking_path,score,confidence,mode,rationale,metrics_snapshot_json,approval_required,paid_spend_usd,updated_at FROM lumen_travel_acquisition_campaigns WHERE status IN ('RECOMMENDED','APPROVED') ORDER BY score DESC,updated_at DESC LIMIT 20`);
  return rows.map(row => ({
    ...row,
    approval_required:Boolean(row.approval_required),
    paid_spend_usd:num(row.paid_spend_usd),
    metrics:(() => { try { return JSON.parse(row.metrics_snapshot_json || "{}"); } catch { return {}; } })()
  }));
}

export async function handleTravelAcquisitionEngine(request, env) {
  const url = new URL(request.url);
  const paths = ["/travel/acquisition/policy","/travel/acquisition/status","/travel/acquisition/recommendations","/travel/acquisition/run"];
  if (!paths.includes(url.pathname)) return null;
  if (request.method === "OPTIONS") return new Response(null,{status:204,headers:{"access-control-allow-origin":"*","access-control-allow-headers":"content-type,x-lumen-admin","access-control-allow-methods":"GET,POST,OPTIONS"}});

  if (request.method === "GET" && url.pathname === "/travel/acquisition/policy") {
    return json({
      ok:true,version:VERSION,name:"LUMEN Travel Acquisition Engine",
      objective:"maximize qualified affiliate revenue using verified/estimated commission signals before CTR",
      portfolioPolicy:{ exploitShareTarget:0.8,exploreShareTarget:0.2,prematureWinnerClaims:false },
      channels:["instagram_owned","web_owned","inbound_context"],
      behavior:["learn from real Travel clicks","use Viator performance when imported","prepare approval-ready organic campaigns","exploit proven signals","reserve controlled exploration for new demand"],
      paidAds:false,autonomousSpendUsd:0,publicationAuthority:false,unsolicitedMassMessaging:false,storesPersonalData:false,
      bookingAuthority:false,paymentAuthority:false,autonomousPurchase:false,bindingActionsHumanGated:true,
      verifiedPayoutStatuses:VERIFIED_PAYOUT_STATUSES
    });
  }

  if (request.method === "GET" && url.pathname === "/travel/acquisition/status") return json(await status(env));

  if (!authorized(request, env)) return json({ ok:false,error:"unauthorized",version:VERSION },401);
  if (request.method === "GET" && url.pathname === "/travel/acquisition/recommendations") return json({ ok:true,version:VERSION,recommendations:await recommendations(env) });
  if (request.method === "POST" && url.pathname === "/travel/acquisition/run") return json(await runTravelAcquisitionEngine(env));
  return json({ ok:false,error:"method_not_allowed",version:VERSION },405);
}
