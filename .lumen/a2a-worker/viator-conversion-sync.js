import { getViatorApiStatus, viatorApiRequest } from "./viator-api.js";

const VERSION = "1.0-viator-conversion-sync";
const SYNC_MIN_INTERVAL_MS = 55 * 60 * 1000;
const FIRST_SYNC_LOOKBACK_DAYS = 30;
const PAGE_SIZE = 100;
const MAX_PAGES_PER_RUN = 5;

function clean(value, limit = 4000) {
  return String(value ?? "").trim().slice(0, limit);
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

function n(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function first(...values) {
  for (const value of values) {
    if (value !== undefined && value !== null && value !== "") return value;
  }
  return null;
}

function amount(value) {
  if (value == null) return 0;
  if (typeof value === "number") return Number.isFinite(value) ? value : 0;
  if (typeof value === "object") {
    return amount(first(
      value.amount,
      value.value,
      value.recommendedRetailPrice,
      value.partnerTotalPrice,
      value.price?.recommendedRetailPrice,
      value.price?.partnerTotalPrice,
      value.price?.amount
    ));
  }
  const parsed = Number(String(value).replace(/[^0-9.-]/g, ""));
  return Number.isFinite(parsed) ? parsed : 0;
}

function eventRows(data) {
  if (Array.isArray(data)) return data;
  for (const key of ["bookingEvents", "events", "bookings", "bookingNotifications", "notifications", "results"]) {
    if (Array.isArray(data?.[key])) return data[key];
  }
  return [];
}

function nextCursor(data) {
  return clean(first(data?.nextCursor, data?.cursor?.next, data?.pagination?.nextCursor), 2000) || null;
}

function normalizedEvent(raw = {}) {
  const priceObject = raw?.totalPrice;
  const transactionRef = clean(first(raw.transactionRef, raw.bookingRef, raw.bookingReference, raw.transactionReference), 240);
  const bookingRef = clean(first(raw.bookingRef, raw.bookingReference, raw.transactionRef), 240);
  const eventType = clean(first(raw.eventType, raw.type, raw.status, raw.bookingStatus), 80).toUpperCase();
  const lastUpdated = clean(first(raw.lastUpdated, raw.lastUpdatedAt, raw.updatedAt, raw.timestamp), 100) || new Date().toISOString();
  const currency = clean(first(
    raw.currency,
    raw.currencyCode,
    priceObject?.currency,
    priceObject?.currencyCode,
    priceObject?.price?.currency,
    priceObject?.price?.currencyCode
  ), 20).toUpperCase() || "UNKNOWN";

  return {
    transactionRef: transactionRef || bookingRef || "unknown",
    bookingRef: bookingRef || transactionRef || null,
    partnerBookingRef: clean(first(raw.partnerBookingRef, raw.partnerReference), 240) || null,
    eventType: eventType || "UNKNOWN",
    productCode: clean(first(raw.productCode, raw.product?.productCode), 160) || null,
    campaignValue: clean(first(raw.campaignValue, raw.campaign, raw.campaignId), 240) || null,
    travelDate: clean(first(raw.travelDate, raw.startDate), 40) || null,
    lastUpdated,
    totalPrice: amount(priceObject),
    currency,
    status: clean(first(raw.status, raw.bookingStatus, eventType), 80).toUpperCase() || eventType || "UNKNOWN",
    raw
  };
}

async function stableKey(item) {
  const value = [item.transactionRef, item.eventType, item.lastUpdated, item.productCode || ""].join("|");
  const bytes = new TextEncoder().encode(value);
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  return [...digest].map(b => b.toString(16).padStart(2, "0")).join("").slice(0, 48);
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_viator_booking_events (id TEXT PRIMARY KEY,row_key TEXT NOT NULL UNIQUE,transaction_ref TEXT NOT NULL,booking_ref TEXT,partner_booking_ref TEXT,event_type TEXT NOT NULL,product_code TEXT,campaign_value TEXT,travel_date TEXT,last_updated TEXT,total_price REAL NOT NULL DEFAULT 0,currency TEXT NOT NULL DEFAULT 'UNKNOWN',booking_status TEXT,imported_at TEXT NOT NULL,raw_json TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_viator_booking_event_campaign ON lumen_viator_booking_events(campaign_value,event_type,last_updated DESC)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_viator_booking_event_product ON lumen_viator_booking_events(product_code,event_type,last_updated DESC)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_viator_booking_event_transaction ON lumen_viator_booking_events(transaction_ref,last_updated DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_viator_booking_sync_state (id TEXT PRIMARY KEY CHECK(id='primary'),cursor TEXT,last_sync_at TEXT,last_success_at TEXT,last_error TEXT,events_seen INTEGER NOT NULL DEFAULT 0,events_inserted INTEGER NOT NULL DEFAULT 0,pages_seen INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL)"),
    env.DB.prepare("INSERT OR IGNORE INTO lumen_viator_booking_sync_state(id,cursor,last_sync_at,last_success_at,last_error,events_seen,events_inserted,pages_seen,updated_at) VALUES('primary',NULL,NULL,NULL,NULL,0,0,0,datetime('now'))")
  ]);
  return true;
}

async function syncState(env) {
  await ensureSchema(env);
  return await env.DB.prepare("SELECT cursor,last_sync_at,last_success_at,last_error,events_seen,events_inserted,pages_seen,updated_at FROM lumen_viator_booking_sync_state WHERE id='primary'").first();
}

function due(state, force = false) {
  if (force) return true;
  if (!state?.last_success_at) return true;
  const then = Date.parse(state.last_success_at);
  return !Number.isFinite(then) || Date.now() - then >= SYNC_MIN_INTERVAL_MS;
}

async function saveEvent(env, raw) {
  const item = normalizedEvent(raw);
  const key = await stableKey(item);
  const result = await env.DB.prepare("INSERT OR IGNORE INTO lumen_viator_booking_events(id,row_key,transaction_ref,booking_ref,partner_booking_ref,event_type,product_code,campaign_value,travel_date,last_updated,total_price,currency,booking_status,imported_at,raw_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
    .bind(
      `VBE-${key.slice(0, 28)}`,
      key,
      item.transactionRef,
      item.bookingRef,
      item.partnerBookingRef,
      item.eventType,
      item.productCode,
      item.campaignValue,
      item.travelDate,
      item.lastUpdated,
      item.totalPrice,
      item.currency,
      item.status,
      new Date().toISOString(),
      JSON.stringify(item.raw)
    ).run();
  return Number(result?.meta?.changes || 0) > 0;
}

export async function syncViatorBookingConversions(env, options = {}) {
  const apiStatus = getViatorApiStatus(env);
  await ensureSchema(env);
  const state = await syncState(env);
  const force = options.force === true;

  if (!apiStatus.configured) {
    return { ok: false, skipped: true, reason: "viator_api_key_not_configured", version: VERSION };
  }
  if (!due(state, force)) {
    return { ok: true, skipped: true, reason: "hourly_cadence_not_due", version: VERSION, lastSuccessAt: state?.last_success_at || null };
  }

  const startedAt = new Date().toISOString();
  await env.DB.prepare("UPDATE lumen_viator_booking_sync_state SET last_sync_at=?,last_error=NULL,updated_at=? WHERE id='primary'")
    .bind(startedAt, startedAt).run();

  let cursor = clean(state?.cursor, 2000) || null;
  let seen = 0;
  let inserted = 0;
  let pages = 0;
  let rateLimitRemaining = null;
  let trackingId = null;

  try {
    const maxPages = Math.max(1, Math.min(Number(options.maxPages || MAX_PAGES_PER_RUN), 20));
    while (pages < maxPages) {
      const query = { count: PAGE_SIZE };
      if (cursor) query.cursor = cursor;
      else {
        const lookbackDays = Math.max(1, Math.min(Number(options.lookbackDays || FIRST_SYNC_LOOKBACK_DAYS), 365));
        query["modified-since"] = new Date(Date.now() - lookbackDays * 86400000).toISOString();
      }

      const result = await viatorApiRequest(env, "/bookings/modified-since", { method: "GET", query });
      trackingId = result.trackingId || trackingId;
      rateLimitRemaining = result.rateLimitRemaining || rateLimitRemaining;
      const rows = eventRows(result.data);
      for (const row of rows) {
        seen += 1;
        if (await saveEvent(env, row)) inserted += 1;
      }
      pages += 1;

      const next = nextCursor(result.data);
      cursor = next || cursor;
      if (!next || rows.length === 0) break;
    }

    const completedAt = new Date().toISOString();
    await env.DB.prepare("UPDATE lumen_viator_booking_sync_state SET cursor=?,last_success_at=?,last_error=NULL,events_seen=events_seen+?,events_inserted=events_inserted+?,pages_seen=pages_seen+?,updated_at=? WHERE id='primary'")
      .bind(cursor, completedAt, seen, inserted, pages, completedAt).run();

    return {
      ok: true,
      version: VERSION,
      provider: "viator",
      environment: apiStatus.environment,
      seen,
      inserted,
      pages,
      cursorStored: Boolean(cursor),
      trackingId,
      rateLimitRemaining,
      bookingAuthority: false,
      paymentAuthority: false,
      autonomousSpendUsd: 0
    };
  } catch (error) {
    const failedAt = new Date().toISOString();
    await env.DB.prepare("UPDATE lumen_viator_booking_sync_state SET last_error=?,updated_at=? WHERE id='primary'")
      .bind(clean(error?.message || error, 300), failedAt).run();
    return {
      ok: false,
      version: VERSION,
      error: clean(error?.message || error, 200),
      upstream: error?.details || null,
      provider: "viator",
      environment: apiStatus.environment,
      bookingAuthority: false,
      paymentAuthority: false,
      autonomousSpendUsd: 0
    };
  }
}

async function optimizerSnapshot(env) {
  await ensureSchema(env);
  const [state, eventTotals, campaigns] = await Promise.all([
    syncState(env),
    env.DB.prepare("SELECT event_type,COUNT(*) total,SUM(total_price) value FROM lumen_viator_booking_events GROUP BY event_type ORDER BY total DESC").all(),
    env.DB.prepare("SELECT COALESCE(NULLIF(campaign_value,''),'unattributed') campaign,SUM(CASE WHEN event_type='CONFIRMATION' THEN 1 ELSE 0 END) confirmations,SUM(CASE WHEN event_type IN ('CANCELLATION','CUSTOMER_CANCELLATION','REJECTION') THEN 1 ELSE 0 END) negative_events,SUM(CASE WHEN event_type='CONFIRMATION' THEN total_price ELSE 0 END) confirmed_value,MAX(last_updated) last_event FROM lumen_viator_booking_events GROUP BY COALESCE(NULLIF(campaign_value,''),'unattributed') ORDER BY confirmations DESC,confirmed_value DESC LIMIT 20").all()
  ]);

  const clicks = await env.DB.prepare("SELECT COALESCE(NULLIF(campaign,''),'unattributed') campaign,COUNT(*) clicks FROM lumen_travel_events WHERE event_type='click' GROUP BY COALESCE(NULLIF(campaign,''),'unattributed')").all().catch(() => ({ results: [] }));
  const clickMap = new Map((clicks.results || []).map(row => [String(row.campaign), n(row.clicks)]));
  const ranked = (campaigns.results || []).map(row => {
    const confirmations = n(row.confirmations);
    const campaignClicks = clickMap.get(String(row.campaign)) || 0;
    return {
      campaign: String(row.campaign),
      confirmations,
      negativeEvents: n(row.negative_events),
      confirmedValue: n(row.confirmed_value),
      clicks: campaignClicks,
      clickToConfirmationRate: campaignClicks > 0 ? Number(((confirmations / campaignClicks) * 100).toFixed(2)) : null,
      lastEvent: row.last_event || null
    };
  });
  const winner = ranked.find(row => row.confirmations >= 3 && row.clicks >= 20) || null;

  return {
    ok: true,
    version: VERSION,
    provider: "viator",
    reportingMode: "api_booking_events",
    sync: state || {},
    eventTotals: eventTotals.results || [],
    campaigns: ranked,
    optimization: {
      winner,
      minimumEvidence: { confirmations: 3, clicks: 20 },
      policy: winner ? "prefer_proven_campaign_keep_exploration" : "collect_more_evidence",
      explorationSharePct: winner ? 20 : 50,
      noFabricatedSignificance: true
    },
    guardrails: {
      bookingAuthority: false,
      paymentAuthority: false,
      autonomousSpendUsd: 0,
      rawCustomerDataExposed: false
    }
  };
}

export async function handleViatorConversionSync(request, env) {
  const url = new URL(request.url);
  const paths = [
    "/health/viator-conversions",
    "/viator/conversions/status",
    "/viator/conversions/sync"
  ];
  if (!paths.includes(url.pathname)) return null;

  if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: { "access-control-allow-origin": "*", "access-control-allow-headers": "content-type,x-lumen-admin", "access-control-allow-methods": "GET,POST,OPTIONS" } });

  if (request.method === "GET" && url.pathname === "/health/viator-conversions") {
    const status = getViatorApiStatus(env);
    return json({
      ok: true,
      version: VERSION,
      configured: Boolean(status.configured),
      environment: status.environment,
      mode: "booking-event-attribution",
      recommendedPolling: "hourly",
      bookingAuthority: false,
      paymentAuthority: false,
      autonomousSpendUsd: 0
    });
  }

  if (!authorized(request, env)) return json({ ok: false, error: "unauthorized", version: VERSION }, 401);

  if (request.method === "GET" && url.pathname === "/viator/conversions/status") {
    return json(await optimizerSnapshot(env));
  }

  if (request.method === "POST" && url.pathname === "/viator/conversions/sync") {
    return json(await syncViatorBookingConversions(env, { force: true }));
  }

  return json({ ok: false, error: "method_not_allowed", version: VERSION }, 405);
}
