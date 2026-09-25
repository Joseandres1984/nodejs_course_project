const VERSION = "3.0-commerce-operations";
const MAX_SYNC_ITEMS_PER_CYCLE = 20;
const MAX_ORDER_EVENTS_PER_CYCLE = 20;
const DEFAULT_PRICE_DRIFT_PCT = 3;

function clean(value, limit = 3000) {
  return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit);
}

function num(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function authorized(request, env) {
  const expected = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const supplied = clean(request.headers.get("x-lumen-admin"), 500);
  return Boolean(expected && supplied && expected === supplied);
}

function safeJson(value, fallback = {}) {
  try {
    return JSON.parse(value || "null") ?? fallback;
  } catch {
    return fallback;
  }
}

function nowIso() {
  return new Date().toISOString();
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_commerce_publication_queue (queue_id TEXT PRIMARY KEY,plan_id TEXT NOT NULL UNIQUE,draft_id TEXT NOT NULL,channel TEXT NOT NULL,state TEXT NOT NULL,approved_by TEXT,approved_at TEXT,executed_at TEXT,external_id TEXT,last_error TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,metadata_json TEXT)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_commerce_publication_queue_state ON lumen_commerce_publication_queue(state,updated_at DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_commerce_inventory_state (channel TEXT NOT NULL,external_id TEXT NOT NULL,candidate_id TEXT,sku TEXT,gtin TEXT,last_known_stock INTEGER,last_supplier_stock INTEGER,last_sync_at TEXT,updated_at TEXT NOT NULL,metadata_json TEXT,PRIMARY KEY(channel,external_id))"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_commerce_price_state (channel TEXT NOT NULL,external_id TEXT NOT NULL,draft_id TEXT,last_known_price REAL,last_recommended_price REAL,last_sync_at TEXT,updated_at TEXT NOT NULL,metadata_json TEXT,PRIMARY KEY(channel,external_id))"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_commerce_order_events (event_id TEXT PRIMARY KEY,channel TEXT NOT NULL,external_order_id TEXT NOT NULL,event_type TEXT NOT NULL,received_at TEXT NOT NULL,verified INTEGER NOT NULL DEFAULT 0,currency TEXT,total_amount REAL NOT NULL DEFAULT 0,payload_json TEXT NOT NULL,metadata_json TEXT,UNIQUE(channel,external_order_id,event_type))"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_commerce_order_events_order ON lumen_commerce_order_events(channel,external_order_id,received_at DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_commerce_fulfillment_queue (fulfillment_id TEXT PRIMARY KEY,channel TEXT NOT NULL,external_order_id TEXT NOT NULL,state TEXT NOT NULL,supplier_reference TEXT,purchase_authorized INTEGER NOT NULL DEFAULT 0,purchase_executed INTEGER NOT NULL DEFAULT 0,tracking_code TEXT,last_error TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,metadata_json TEXT,UNIQUE(channel,external_order_id))"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_commerce_fulfillment_state ON lumen_commerce_fulfillment_queue(state,updated_at DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_commerce_ops_runs (run_id TEXT PRIMARY KEY,started_at TEXT NOT NULL,finished_at TEXT,status TEXT NOT NULL,publication_candidates INTEGER NOT NULL DEFAULT 0,inventory_checked INTEGER NOT NULL DEFAULT 0,price_checked INTEGER NOT NULL DEFAULT 0,orders_seen INTEGER NOT NULL DEFAULT 0,fulfillment_prepared INTEGER NOT NULL DEFAULT 0,error TEXT,metadata_json TEXT)")
  ]);
  return true;
}

async function queueApprovedPlans(env) {
  const rows = await env.DB.prepare("SELECT plan_id,draft_id,channel,payload_json,blockers_json,metadata_json FROM lumen_commerce_channel_plans WHERE state='APPROVED' AND publishable=1 ORDER BY updated_at ASC LIMIT ?")
    .bind(MAX_SYNC_ITEMS_PER_CYCLE).all();
  const now = nowIso();
  let queued = 0;
  for (const row of rows.results || []) {
    const queueId = `PUB-${row.plan_id}`.slice(0, 220);
    await env.DB.prepare("INSERT INTO lumen_commerce_publication_queue(queue_id,plan_id,draft_id,channel,state,created_at,updated_at,metadata_json) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(plan_id) DO UPDATE SET updated_at=excluded.updated_at")
      .bind(queueId, row.plan_id, row.draft_id, row.channel, "READY_FOR_HUMAN_EXECUTION", now, now, JSON.stringify({ version: VERSION, payload: safeJson(row.payload_json, {}), blockers: safeJson(row.blockers_json, []), sourcePlanMetadata: safeJson(row.metadata_json, {}) }))
      .run();
    queued += 1;
  }
  return queued;
}

async function preparePublishedSyncState(env) {
  const rows = await env.DB.prepare("SELECT p.plan_id,p.draft_id,p.channel,p.external_id,d.candidate_id,d.recommended_price,c.sku,c.gtin,c.metadata_json FROM lumen_commerce_channel_plans p JOIN lumen_commerce_catalog_drafts d ON d.draft_id=p.draft_id LEFT JOIN lumen_product_candidates c ON c.candidate_id=d.candidate_id WHERE p.state='PUBLISHED' AND p.external_id IS NOT NULL ORDER BY p.updated_at DESC LIMIT ?")
    .bind(MAX_SYNC_ITEMS_PER_CYCLE).all();
  const now = nowIso();
  let inventoryChecked = 0;
  let priceChecked = 0;
  for (const row of rows.results || []) {
    const productMeta = safeJson(row.metadata_json, {});
    const supplierStock = Number(productMeta?.stock ?? productMeta?.inventory ?? 1);
    await env.DB.prepare("INSERT INTO lumen_commerce_inventory_state(channel,external_id,candidate_id,sku,gtin,last_known_stock,last_supplier_stock,last_sync_at,updated_at,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(channel,external_id) DO UPDATE SET candidate_id=excluded.candidate_id,sku=excluded.sku,gtin=excluded.gtin,last_supplier_stock=excluded.last_supplier_stock,last_sync_at=excluded.last_sync_at,updated_at=excluded.updated_at,metadata_json=excluded.metadata_json")
      .bind(row.channel, row.external_id, row.candidate_id || null, row.sku || null, row.gtin || null, 1, Number.isFinite(supplierStock) ? supplierStock : 1, now, now, JSON.stringify({ version: VERSION, syncMode: "shadow_compare_only" }))
      .run();
    inventoryChecked += 1;

    await env.DB.prepare("INSERT INTO lumen_commerce_price_state(channel,external_id,draft_id,last_known_price,last_recommended_price,last_sync_at,updated_at,metadata_json) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(channel,external_id) DO UPDATE SET draft_id=excluded.draft_id,last_recommended_price=excluded.last_recommended_price,last_sync_at=excluded.last_sync_at,updated_at=excluded.updated_at,metadata_json=excluded.metadata_json")
      .bind(row.channel, row.external_id, row.draft_id, num(row.recommended_price), num(row.recommended_price), now, now, JSON.stringify({ version: VERSION, maxAutomaticDriftPct: 0, recommendedDriftAlertPct: DEFAULT_PRICE_DRIFT_PCT, writeAuthority: false }))
      .run();
    priceChecked += 1;
  }
  return { inventoryChecked, priceChecked };
}

async function prepareFulfillment(env) {
  const rows = await env.DB.prepare("SELECT channel,external_order_id,total_amount,currency,payload_json,metadata_json FROM lumen_commerce_order_events WHERE verified=1 AND event_type IN ('PAID','ORDER_PAID','PAYMENT_CONFIRMED') ORDER BY received_at ASC LIMIT ?")
    .bind(MAX_ORDER_EVENTS_PER_CYCLE).all();
  const now = nowIso();
  let prepared = 0;
  for (const row of rows.results || []) {
    const fulfillmentId = `FUL-${row.channel}-${row.external_order_id}`.replace(/[^a-z0-9_-]+/gi, "-").slice(0, 220);
    await env.DB.prepare("INSERT INTO lumen_commerce_fulfillment_queue(fulfillment_id,channel,external_order_id,state,purchase_authorized,purchase_executed,created_at,updated_at,metadata_json) VALUES(?,?,?,?,0,0,?,?,?) ON CONFLICT(channel,external_order_id) DO UPDATE SET updated_at=excluded.updated_at")
      .bind(fulfillmentId, row.channel, row.external_order_id, "AWAITING_HUMAN_PURCHASE_APPROVAL", now, now, JSON.stringify({ version: VERSION, orderTotal: num(row.total_amount), currency: row.currency || null, orderPayload: safeJson(row.payload_json, {}), sourceMetadata: safeJson(row.metadata_json, {}) }))
      .run();
    prepared += 1;
  }
  return prepared;
}

export async function runCommerceOperations(env) {
  if (!env?.DB) return { ok: false, skipped: true, reason: "missing_db" };
  await ensureSchema(env);
  const startedAt = nowIso();
  const runId = `CO-${Date.now()}`;
  await env.DB.prepare("INSERT INTO lumen_commerce_ops_runs(run_id,started_at,status,metadata_json) VALUES(?,?,?,?)")
    .bind(runId, startedAt, "RUNNING", JSON.stringify({ version: VERSION, mode: "governed_operations" })).run();
  try {
    const publicationCandidates = await queueApprovedPlans(env);
    const sync = await preparePublishedSyncState(env);
    const fulfillmentPrepared = await prepareFulfillment(env);
    const ordersSeenRow = await env.DB.prepare("SELECT COUNT(*) n FROM lumen_commerce_order_events WHERE received_at >= ?").bind(startedAt.slice(0, 10)).first();
    const ordersSeen = Number(ordersSeenRow?.n || 0);
    const finishedAt = nowIso();
    await env.DB.prepare("UPDATE lumen_commerce_ops_runs SET finished_at=?,status='SUCCESS',publication_candidates=?,inventory_checked=?,price_checked=?,orders_seen=?,fulfillment_prepared=?,metadata_json=? WHERE run_id=?")
      .bind(finishedAt, publicationCandidates, sync.inventoryChecked, sync.priceChecked, ordersSeen, fulfillmentPrepared, JSON.stringify({ version: VERSION, autonomousPublish: false, autonomousPurchase: false, autonomousSpendUsd: 0 }), runId).run();
    return { ok: true, status: "SUCCESS", runId, publicationCandidates, inventoryChecked: sync.inventoryChecked, priceChecked: sync.priceChecked, ordersSeen, fulfillmentPrepared, version: VERSION };
  } catch (error) {
    const finishedAt = nowIso();
    await env.DB.prepare("UPDATE lumen_commerce_ops_runs SET finished_at=?,status='FAILED',error=? WHERE run_id=?").bind(finishedAt, clean(error, 500), runId).run();
    return { ok: false, status: "FAILED", runId, error: clean(error, 500), version: VERSION };
  }
}

async function approvePublication(env, body) {
  const planId = clean(body?.planId, 220);
  const approver = clean(body?.approvedBy || "owner", 120);
  if (!planId) return { ok: false, error: "missing_plan_id" };
  const row = await env.DB.prepare("SELECT plan_id,draft_id,channel,state,publishable,blockers_json FROM lumen_commerce_channel_plans WHERE plan_id=?").bind(planId).first();
  if (!row) return { ok: false, error: "plan_not_found" };
  const blockers = safeJson(row.blockers_json, []);
  const unresolved = blockers.filter(value => value !== "human_approval_required");
  if (unresolved.length) return { ok: false, error: "unresolved_blockers", blockers: unresolved };
  const now = nowIso();
  await env.DB.prepare("UPDATE lumen_commerce_channel_plans SET state='APPROVED',publishable=1,blockers_json='[]',updated_at=? WHERE plan_id=?").bind(now, planId).run();
  const queueId = `PUB-${planId}`.slice(0, 220);
  await env.DB.prepare("INSERT INTO lumen_commerce_publication_queue(queue_id,plan_id,draft_id,channel,state,approved_by,approved_at,created_at,updated_at,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(plan_id) DO UPDATE SET state=excluded.state,approved_by=excluded.approved_by,approved_at=excluded.approved_at,updated_at=excluded.updated_at")
    .bind(queueId, planId, row.draft_id, row.channel, "READY_FOR_HUMAN_EXECUTION", approver, now, now, now, JSON.stringify({ version: VERSION, explicitHumanApproval: true })).run();
  return { ok: true, planId, queueId, state: "READY_FOR_HUMAN_EXECUTION", externalWriteExecuted: false };
}

async function ingestOrderEvent(env, body) {
  const channel = clean(body?.channel, 50).toUpperCase();
  const externalOrderId = clean(body?.externalOrderId, 180);
  const eventType = clean(body?.eventType, 80).toUpperCase();
  if (!channel || !externalOrderId || !eventType) return { ok: false, error: "missing_order_fields" };
  const verified = body?.verified === true ? 1 : 0;
  const now = nowIso();
  const eventId = `ORD-${channel}-${externalOrderId}-${eventType}`.replace(/[^a-z0-9_-]+/gi, "-").slice(0, 240);
  await env.DB.prepare("INSERT INTO lumen_commerce_order_events(event_id,channel,external_order_id,event_type,received_at,verified,currency,total_amount,payload_json,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(channel,external_order_id,event_type) DO UPDATE SET verified=MAX(lumen_commerce_order_events.verified,excluded.verified),payload_json=excluded.payload_json,metadata_json=excluded.metadata_json")
    .bind(eventId, channel, externalOrderId, eventType, now, verified, clean(body?.currency || "ARS", 10).toUpperCase(), num(body?.totalAmount), JSON.stringify(body?.payload || {}), JSON.stringify({ version: VERSION, source: clean(body?.source || "manual_or_adapter", 100) })).run();
  return { ok: true, eventId, verified: Boolean(verified) };
}

async function status(env) {
  if (!env?.DB) return { ok: false, reason: "missing_db" };
  await ensureSchema(env);
  const [publication, fulfillment, orders, latest] = await Promise.all([
    env.DB.prepare("SELECT state,COUNT(*) n FROM lumen_commerce_publication_queue GROUP BY state").all(),
    env.DB.prepare("SELECT state,COUNT(*) n FROM lumen_commerce_fulfillment_queue GROUP BY state").all(),
    env.DB.prepare("SELECT verified,COUNT(*) n FROM lumen_commerce_order_events GROUP BY verified").all(),
    env.DB.prepare("SELECT * FROM lumen_commerce_ops_runs ORDER BY started_at DESC LIMIT 1").first()
  ]);
  return {
    ok: true,
    version: VERSION,
    authority: { publish: false, purchase: false, supplierOrder: false, priceWrite: false, inventoryWrite: false, autonomousSpendUsd: 0, humanApprovalRequired: true },
    publicationQueue: publication.results || [],
    fulfillmentQueue: fulfillment.results || [],
    orderEvents: orders.results || [],
    lastRun: latest || null
  };
}

export async function handleCommerceOperations(request, env) {
  const url = new URL(request.url);
  if (url.pathname === "/commerce-ops/policy" && request.method === "GET") {
    return Response.json({ ok: true, version: VERSION, mode: "GOVERNED_OPERATIONS", publicationQueue: true, inventorySyncPreparation: true, priceSyncPreparation: true, orderEventIngestion: true, fulfillmentPreparation: true, autonomousPublishing: false, autonomousPurchasing: false, supplierOrdering: false, priceWriteAuthority: false, inventoryWriteAuthority: false, autonomousSpendUsd: 0, verifiedOrdersOnlyCanCreateFulfillment: true, humanApprovalRequired: true });
  }
  if (url.pathname === "/commerce-ops/status" && request.method === "GET") {
    if (!authorized(request, env)) return Response.json({ ok: false, error: "unauthorized" }, { status: 401 });
    return Response.json(await status(env));
  }
  if (url.pathname === "/commerce-ops/run" && request.method === "POST") {
    if (!authorized(request, env)) return Response.json({ ok: false, error: "unauthorized" }, { status: 401 });
    return Response.json(await runCommerceOperations(env));
  }
  if (url.pathname === "/commerce-ops/publication/approve" && request.method === "POST") {
    if (!authorized(request, env)) return Response.json({ ok: false, error: "unauthorized" }, { status: 401 });
    let body = {};
    try { body = await request.json(); } catch {}
    return Response.json(await approvePublication(env, body));
  }
  if (url.pathname === "/commerce-ops/orders/ingest" && request.method === "POST") {
    if (!authorized(request, env)) return Response.json({ ok: false, error: "unauthorized" }, { status: 401 });
    let body = {};
    try { body = await request.json(); } catch {}
    return Response.json(await ingestOrderEvent(env, body));
  }
  return null;
}
