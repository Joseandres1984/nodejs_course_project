const VERSION = "1.0-travel-demand-bridge";
const SOURCE = "travel_demand_first";
const OFFER_ID = "TRAVEL-DEMAND-INTEL";
const MIN_CLUSTER_SIGNALS = 2;
const MAX_EVENTS_PER_SYNC = 2000;

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

function clean(value, limit = 1000) {
  return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit);
}

function num(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function clamp(value, min = 0, max = 100) {
  return Math.max(min, Math.min(max, num(value)));
}

function safeArray(value) {
  if (Array.isArray(value)) return value;
  try {
    const parsed = JSON.parse(value || "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function authorized(request, env) {
  const configured = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const provided = clean(request.headers.get("x-lumen-admin"), 500);
  return Boolean(configured && provided && configured === provided);
}

async function sha256(text) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, "0")).join("");
}

function recencyBoost(lastSeen, nowMs) {
  const timestamp = new Date(lastSeen || 0).getTime();
  if (!Number.isFinite(timestamp) || timestamp <= 0) return 0;
  const days = Math.max(0, (nowMs - timestamp) / 86400000);
  if (days <= 7) return 15;
  if (days <= 30) return 8;
  if (days <= 90) return 3;
  return 0;
}

function clusterScore(cluster, nowMs) {
  const repeatedDemand = Math.min(30, Math.max(0, cluster.demandCount - 1) * 10);
  const preferenceClarity = Math.min(10, cluster.topPreferences.length * 2);
  const score = 40 + repeatedDemand + recencyBoost(cluster.lastSeen, nowMs) + preferenceClarity;
  return Math.round(clamp(score));
}

export function buildTravelDemandClusters(events = [], nowMs = Date.now()) {
  const groups = new Map();

  for (const event of events) {
    const originCode = clean(event?.origin_code, 8).toUpperCase();
    const targetMonth = Math.round(num(event?.target_month));
    const budgetBucketUSD = Math.round(num(event?.budget_bucket_usd));
    if (!originCode || targetMonth < 1 || targetMonth > 12 || budgetBucketUSD <= 0) continue;

    const key = `${originCode}|${targetMonth}|${budgetBucketUSD}`;
    const createdAt = clean(event?.created_at, 64) || new Date(nowMs).toISOString();
    const preferences = safeArray(event?.preferences_json)
      .map(value => clean(value, 40).toUpperCase())
      .filter(Boolean);

    if (!groups.has(key)) {
      groups.set(key, {
        clusterKey: key,
        originCode,
        targetMonth,
        budgetBucketUSD,
        demandCount: 0,
        firstSeen: createdAt,
        lastSeen: createdAt,
        eventIds: [],
        preferenceCounts: new Map()
      });
    }

    const cluster = groups.get(key);
    cluster.demandCount += 1;
    if (event?.id) cluster.eventIds.push(clean(event.id, 160));
    if (createdAt < cluster.firstSeen) cluster.firstSeen = createdAt;
    if (createdAt > cluster.lastSeen) cluster.lastSeen = createdAt;
    for (const preference of preferences) {
      cluster.preferenceCounts.set(preference, (cluster.preferenceCounts.get(preference) || 0) + 1);
    }
  }

  return [...groups.values()]
    .map(cluster => {
      const topPreferences = [...cluster.preferenceCounts.entries()]
        .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
        .slice(0, 6)
        .map(([name, count]) => ({ name, count }));
      const normalized = { ...cluster, topPreferences };
      delete normalized.preferenceCounts;
      const score = clusterScore(normalized, nowMs);
      return {
        ...normalized,
        score,
        fit: score >= 75 ? "A" : score >= 55 ? "B" : score >= 35 ? "C" : "D",
        eligibleForBridge: normalized.demandCount >= MIN_CLUSTER_SIGNALS
      };
    })
    .sort((a, b) => b.score - a.score || b.demandCount - a.demandCount || a.clusterKey.localeCompare(b.clusterKey));
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_travel_demand_events (id TEXT PRIMARY KEY,search_id TEXT NOT NULL,created_at TEXT NOT NULL,event_type TEXT NOT NULL,origin_code TEXT NOT NULL,target_month INTEGER NOT NULL,budget_bucket_usd INTEGER NOT NULL,preferences_json TEXT NOT NULL,result_count INTEGER NOT NULL,status TEXT NOT NULL,engine_version TEXT NOT NULL,UNIQUE(search_id,event_type))"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_travel_demand_events_status ON lumen_travel_demand_events(status,event_type,created_at DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_opportunities (id TEXT PRIMARY KEY, discovered_at TEXT NOT NULL, updated_at TEXT NOT NULL, source TEXT NOT NULL, remote_id TEXT NOT NULL, name TEXT, endpoint TEXT, description TEXT, tags_json TEXT, score INTEGER NOT NULL, fit TEXT NOT NULL, demand_signal INTEGER NOT NULL DEFAULT 0, revenue_offer_id TEXT, status TEXT NOT NULL, evidence TEXT, raw_json TEXT)"),
    env.DB.prepare("CREATE UNIQUE INDEX IF NOT EXISTS idx_lumen_opportunities_source_remote ON lumen_opportunities(source,remote_id)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_travel_demand_bridge_runs (id TEXT PRIMARY KEY,started_at TEXT NOT NULL,finished_at TEXT NOT NULL,status TEXT NOT NULL,events_scanned INTEGER NOT NULL DEFAULT 0,clusters_found INTEGER NOT NULL DEFAULT 0,opportunities_bridged INTEGER NOT NULL DEFAULT 0,details_json TEXT,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_travel_demand_bridge_runs_started ON lumen_travel_demand_bridge_runs(started_at DESC)")
  ]);
  return true;
}

async function upsertObservationalOpportunity(env, cluster) {
  const hash = await sha256(`${SOURCE}|${cluster.clusterKey}`);
  const id = `OPP-TRAVEL-${hash.slice(0, 16).toUpperCase()}`;
  const now = new Date().toISOString();
  const preferenceNames = cluster.topPreferences.map(item => item.name);
  const tags = [
    "travel",
    "consumer-demand",
    "unmet-demand",
    `origin:${cluster.originCode.toLowerCase()}`,
    `month:${cluster.targetMonth}`,
    ...preferenceNames.map(value => `preference:${value.toLowerCase()}`)
  ];
  const name = `Travel demand ${cluster.originCode} · mes ${cluster.targetMonth} · ~USD ${cluster.budgetBucketUSD}`;
  const preferencesText = preferenceNames.length ? preferenceNames.join(", ") : "sin preferencia dominante";
  const description = `${cluster.demandCount} búsquedas agregadas no encontraron una opción viable desde ${cluster.originCode} para el mes ${cluster.targetMonth}, con presupuesto aproximado de USD ${cluster.budgetBucketUSD}. Preferencias dominantes: ${preferencesText}. Señal agregada y sin PII; requiere validación comercial antes de cualquier acción externa.`;
  const raw = {
    vertical: "TRAVEL",
    demandKind: "CONSUMER_UNMET_DEMAND",
    clusterKey: cluster.clusterKey,
    originCode: cluster.originCode,
    targetMonth: cluster.targetMonth,
    budgetBucketUSD: cluster.budgetBucketUSD,
    demandCount: cluster.demandCount,
    firstSeen: cluster.firstSeen,
    lastSeen: cluster.lastSeen,
    topPreferences: cluster.topPreferences,
    observationalOnly: true,
    containsPii: false
  };

  await env.DB.prepare("INSERT INTO lumen_opportunities(id,discovered_at,updated_at,source,remote_id,name,endpoint,description,tags_json,score,fit,demand_signal,revenue_offer_id,status,evidence,raw_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,name=excluded.name,description=excluded.description,tags_json=excluded.tags_json,score=MAX(lumen_opportunities.score,excluded.score),fit=CASE WHEN excluded.score>lumen_opportunities.score THEN excluded.fit ELSE lumen_opportunities.fit END,demand_signal=1,revenue_offer_id=excluded.revenue_offer_id,evidence=excluded.evidence,raw_json=excluded.raw_json,status=CASE WHEN lumen_opportunities.status IN ('new','watching','qualified') THEN lumen_opportunities.status ELSE 'travel_demand' END")
    .bind(id, now, now, SOURCE, cluster.clusterKey, name, "", description, JSON.stringify(tags), cluster.score, cluster.fit, 1, OFFER_ID, "travel_demand", `aggregated_travel_demand:${cluster.demandCount}`, JSON.stringify(raw)).run();

  if (cluster.eventIds.length) {
    await env.DB.batch(cluster.eventIds.map(eventId => env.DB.prepare("UPDATE lumen_travel_demand_events SET status='BRIDGED' WHERE id=? AND event_type='TRAVEL_DEMAND_UNMET'").bind(eventId)));
  }

  return { id, score: cluster.score, fit: cluster.fit, demandCount: cluster.demandCount };
}

export async function syncTravelDemandToOpportunities(env) {
  if (!(await ensureSchema(env))) {
    return { ok: false, version: VERSION, error: "persistence_unavailable", bridged: 0 };
  }

  const startedAt = new Date().toISOString();
  const rows = await env.DB.prepare("SELECT id,created_at,origin_code,target_month,budget_bucket_usd,preferences_json,status FROM lumen_travel_demand_events WHERE event_type='TRAVEL_DEMAND_UNMET' ORDER BY created_at DESC LIMIT ?")
    .bind(MAX_EVENTS_PER_SYNC).all();
  const events = rows.results || [];
  const clusters = buildTravelDemandClusters(events);
  const eligible = clusters.filter(cluster => cluster.eligibleForBridge);
  const bridged = [];

  for (const cluster of eligible) {
    bridged.push(await upsertObservationalOpportunity(env, cluster));
  }

  const finishedAt = new Date().toISOString();
  const runId = `TRDB-${crypto.randomUUID().replaceAll("-", "").slice(0, 14).toUpperCase()}`;
  await env.DB.prepare("INSERT INTO lumen_travel_demand_bridge_runs(id,started_at,finished_at,status,events_scanned,clusters_found,opportunities_bridged,details_json,engine_version) VALUES(?,?,?,?,?,?,?,?,?)")
    .bind(runId, startedAt, finishedAt, "complete", events.length, clusters.length, bridged.length, JSON.stringify({ minimumSignals: MIN_CLUSTER_SIGNALS, bridged: bridged.slice(0, 50) }), VERSION).run();

  return {
    ok: true,
    version: VERSION,
    runId,
    eventsScanned: events.length,
    clustersFound: clusters.length,
    eligibleClusters: eligible.length,
    bridged: bridged.length,
    opportunities: bridged,
    guardrails: {
      aggregatedDemandOnly: true,
      storesPii: false,
      observationalStatus: "travel_demand",
      automaticCommercialActivation: false,
      createsProposal: false,
      sendsMessage: false,
      createsBooking: false,
      createsCharge: false,
      autonomousSpend: false,
      bindingActionsHumanGated: true
    }
  };
}

async function activateOpportunity(env, opportunityId) {
  if (!(await ensureSchema(env))) return { ok: false, error: "persistence_unavailable" };
  const id = clean(opportunityId, 120);
  if (!id) return { ok: false, error: "opportunity_id_required" };
  const row = await env.DB.prepare("SELECT id,source,status,score,fit,name FROM lumen_opportunities WHERE id=? LIMIT 1").bind(id).first();
  if (!row || row.source !== SOURCE) return { ok: false, error: "travel_demand_opportunity_not_found" };
  if (!["travel_demand", "watching", "qualified", "new"].includes(clean(row.status, 40))) return { ok: false, error: "opportunity_not_activatable", status: row.status };
  const now = new Date().toISOString();
  await env.DB.prepare("UPDATE lumen_opportunities SET status='watching',updated_at=? WHERE id=? AND source=?").bind(now, id, SOURCE).run();
  return {
    ok: true,
    version: VERSION,
    opportunityId: id,
    previousStatus: row.status,
    status: "watching",
    name: row.name,
    score: num(row.score),
    fit: row.fit,
    guardrails: {
      humanAdminActivation: true,
      createsProposalImmediately: false,
      sendsMessageImmediately: false,
      createsBooking: false,
      createsCharge: false,
      autonomousSpend: false
    }
  };
}

async function stats(env) {
  if (!(await ensureSchema(env))) return { version: VERSION, persistence: false, observational: 0, activated: 0 };
  const row = await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN status='travel_demand' THEN 1 ELSE 0 END) observational,SUM(CASE WHEN status IN ('watching','qualified','new') THEN 1 ELSE 0 END) activated,MAX(score) max_score FROM lumen_opportunities WHERE source=?").bind(SOURCE).first();
  const recentRun = await env.DB.prepare("SELECT id,started_at,finished_at,status,events_scanned,clusters_found,opportunities_bridged FROM lumen_travel_demand_bridge_runs ORDER BY started_at DESC LIMIT 1").first();
  return {
    version: VERSION,
    persistence: true,
    opportunities: num(row?.total),
    observational: num(row?.observational),
    activated: num(row?.activated),
    maxScore: row?.max_score == null ? null : num(row.max_score),
    recentRun: recentRun || null
  };
}

async function listOpportunities(env) {
  if (!(await ensureSchema(env))) return [];
  const rows = await env.DB.prepare("SELECT id,discovered_at,updated_at,name,description,score,fit,status,evidence,raw_json FROM lumen_opportunities WHERE source=? ORDER BY score DESC,updated_at DESC LIMIT 50").bind(SOURCE).all();
  return (rows.results || []).map(row => {
    let aggregate = {};
    try { aggregate = JSON.parse(row.raw_json || "{}"); } catch {}
    return {
      id: row.id,
      discoveredAt: row.discovered_at,
      updatedAt: row.updated_at,
      name: row.name,
      description: row.description,
      score: num(row.score),
      fit: row.fit,
      status: row.status,
      evidence: row.evidence,
      aggregate
    };
  });
}

export async function handleTravelDemandBridge(request, env) {
  const url = new URL(request.url);
  if (request.method === "OPTIONS" && url.pathname.startsWith("/travel/demand/")) return new Response(null, { status: 204, headers: { "access-control-allow-origin":"*", "access-control-allow-headers":"content-type,x-lumen-admin", "access-control-allow-methods":"GET,POST,OPTIONS" } });

  if (request.method === "GET" && url.pathname === "/travel/demand/policy") {
    return json({
      version: VERSION,
      name: "LUMEN Travel Demand-First Bridge",
      source: SOURCE,
      minimumSignalsPerCluster: MIN_CLUSTER_SIGNALS,
      clusterDimensions: ["origin", "targetMonth", "budgetBucketUSD"],
      storesPii: false,
      automaticBridging: true,
      automaticCommercialActivation: false,
      activationRequiresAdmin: true,
      automaticOutreach: false,
      createsBooking: false,
      createsCharge: false,
      autonomousSpend: false,
      bindingActionsHumanGated: true
    });
  }

  if (request.method === "GET" && url.pathname === "/travel/demand/stats") return json(await stats(env));
  if (request.method === "GET" && url.pathname === "/travel/demand/opportunities") return json({ version: VERSION, opportunities: await listOpportunities(env) });

  if (request.method === "POST" && url.pathname === "/travel/demand/sync") {
    if (!authorized(request, env)) return json({ ok: false, error: "admin_token_required" }, 403);
    return json(await syncTravelDemandToOpportunities(env), 202);
  }

  if (request.method === "POST" && url.pathname === "/travel/demand/activate") {
    if (!authorized(request, env)) return json({ ok: false, error: "admin_token_required" }, 403);
    let body = {};
    try { body = await request.json(); } catch { return json({ ok: false, error: "invalid_json" }, 400); }
    const result = await activateOpportunity(env, body.opportunityId);
    return json(result, result.ok ? 202 : 400);
  }

  return null;
}

export const TRAVEL_DEMAND_MIN_CLUSTER_SIGNALS = MIN_CLUSTER_SIGNALS;