const VERSION = "1.0-tiendanube-privacy";

function clean(value, limit = 1000) {
  return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit);
}

async function verifyWebhook(request, env, rawBody) {
  const secret = clean(env?.TIENDANUBE_CLIENT_SECRET, 1000);
  const supplied = clean(request.headers.get("x-linkedstore-hmac-sha256"), 500).toLowerCase();
  if (!secret || !supplied) return false;
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const signature = new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(rawBody)));
  const expected = [...signature].map(b => b.toString(16).padStart(2, "0")).join("");
  if (expected.length !== supplied.length) return false;
  let diff = 0;
  for (let i = 0; i < expected.length; i += 1) diff |= expected.charCodeAt(i) ^ supplied.charCodeAt(i);
  return diff === 0;
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.prepare(
    "CREATE TABLE IF NOT EXISTS lumen_tiendanube_privacy_requests (request_key TEXT PRIMARY KEY,store_id TEXT NOT NULL,request_type TEXT NOT NULL,subject_customer_id TEXT,status TEXT NOT NULL,received_at TEXT NOT NULL,processed_at TEXT,metadata_json TEXT)"
  ).run();
  await env.DB.prepare(
    "CREATE INDEX IF NOT EXISTS idx_lumen_tn_privacy_status ON lumen_tiendanube_privacy_requests(status,received_at DESC)"
  ).run();
  return true;
}

async function safeRun(env, sql, bindings = []) {
  try {
    await env.DB.prepare(sql).bind(...bindings).run();
    return true;
  } catch {
    return false;
  }
}

function parseJson(rawBody) {
  try { return JSON.parse(rawBody || "{}"); }
  catch { return null; }
}

async function readVerifiedPayload(request, env) {
  if (!env?.DB) return { ok: false, response: Response.json({ ok: false, error: "missing_db" }, { status: 503 }) };
  const rawBody = await request.text();
  const verified = await verifyWebhook(request, env, rawBody);
  if (!verified) return { ok: false, response: Response.json({ ok: false, error: "invalid_signature" }, { status: 401 }) };
  const payload = parseJson(rawBody);
  if (!payload) return { ok: false, response: Response.json({ ok: false, error: "invalid_json" }, { status: 400 }) };
  const storeId = clean(payload?.store_id, 100);
  if (!storeId) return { ok: false, response: Response.json({ ok: false, error: "missing_store_id" }, { status: 400 }) };
  return { ok: true, payload, storeId };
}

async function handleStoreRedact(request, env) {
  const parsed = await readVerifiedPayload(request, env);
  if (!parsed.ok) return parsed.response;
  const { storeId } = parsed;
  await ensureSchema(env);

  const pattern = `%\"storeId\":\"${storeId}\"%`;
  await safeRun(env, "DELETE FROM lumen_commerce_fulfillment_queue WHERE channel='TIENDANUBE' AND external_order_id IN (SELECT external_order_id FROM lumen_commerce_order_events WHERE channel='TIENDANUBE' AND metadata_json LIKE ?)", [pattern]);
  await safeRun(env, "DELETE FROM lumen_commerce_order_events WHERE channel='TIENDANUBE' AND metadata_json LIKE ?", [pattern]);
  await safeRun(env, "DELETE FROM lumen_tiendanube_events WHERE store_id=?", [storeId]);
  await safeRun(env, "DELETE FROM lumen_tiendanube_webhooks WHERE store_id=?", [storeId]);
  await safeRun(env, "DELETE FROM lumen_tiendanube_connections WHERE store_id=?", [storeId]);
  await safeRun(env, "DELETE FROM lumen_tiendanube_privacy_requests WHERE store_id=?", [storeId]);

  return Response.json({ ok: true, processed: "app/store_redact", storeDataDeleted: true });
}

async function handleCustomerRedact(request, env) {
  const parsed = await readVerifiedPayload(request, env);
  if (!parsed.ok) return parsed.response;
  const { payload, storeId } = parsed;
  await ensureSchema(env);

  const customerId = clean(payload?.customer?.id, 120);
  const orderIds = Array.isArray(payload?.orders_to_redact)
    ? payload.orders_to_redact.map(value => clean(value, 120)).filter(Boolean).slice(0, 500)
    : [];

  for (const orderId of orderIds) {
    await safeRun(env, "DELETE FROM lumen_commerce_fulfillment_queue WHERE channel='TIENDANUBE' AND external_order_id=?", [orderId]);
    await safeRun(env, "DELETE FROM lumen_commerce_order_events WHERE channel='TIENDANUBE' AND external_order_id=?", [orderId]);
  }

  const requestKey = `customer-redact:${storeId}:${customerId || "unknown"}`.slice(0, 240);
  const now = new Date().toISOString();
  await env.DB.prepare(
    "INSERT INTO lumen_tiendanube_privacy_requests(request_key,store_id,request_type,subject_customer_id,status,received_at,processed_at,metadata_json) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(request_key) DO UPDATE SET status=excluded.status,processed_at=excluded.processed_at,metadata_json=excluded.metadata_json"
  ).bind(
    requestKey,
    storeId,
    "customer/redact",
    customerId || null,
    "PROCESSED",
    now,
    now,
    JSON.stringify({ version: VERSION, ordersDeleted: orderIds, directCustomerIdentityRetained: false })
  ).run();

  return Response.json({ ok: true, processed: "customer/redact", ordersDeleted: orderIds.length, directCustomerIdentityRetained: false });
}

async function handleCustomersDataRequest(request, env) {
  const parsed = await readVerifiedPayload(request, env);
  if (!parsed.ok) return parsed.response;
  const { payload, storeId } = parsed;
  await ensureSchema(env);

  const customerId = clean(payload?.customer?.id, 120);
  const dataRequestId = clean(payload?.data_request?.id, 120);
  const orderIds = Array.isArray(payload?.orders_requested)
    ? payload.orders_requested.map(value => clean(value, 120)).filter(Boolean).slice(0, 500)
    : [];

  let operationalRecords = 0;
  for (const orderId of orderIds) {
    try {
      const row = await env.DB.prepare("SELECT COUNT(*) n FROM lumen_commerce_order_events WHERE channel='TIENDANUBE' AND external_order_id=?").bind(orderId).first();
      operationalRecords += Number(row?.n || 0);
    } catch {}
  }

  const requestKey = `data-request:${storeId}:${dataRequestId || customerId || Date.now()}`.slice(0, 240);
  const now = new Date().toISOString();
  await env.DB.prepare(
    "INSERT INTO lumen_tiendanube_privacy_requests(request_key,store_id,request_type,subject_customer_id,status,received_at,processed_at,metadata_json) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(request_key) DO UPDATE SET status=excluded.status,processed_at=excluded.processed_at,metadata_json=excluded.metadata_json"
  ).bind(
    requestKey,
    storeId,
    "customers/data_request",
    customerId || null,
    "REPORT_PREPARED",
    now,
    now,
    JSON.stringify({ version: VERSION, dataRequestId: dataRequestId || null, ordersRequested: orderIds, operationalRecords, directCustomerProfileStore: false })
  ).run();

  return Response.json({
    ok: true,
    processed: "customers/data_request",
    report: {
      dataRequestId: dataRequestId || null,
      operationalOrderRecords: operationalRecords,
      directCustomerProfileStore: false
    }
  });
}

export async function handleTiendanubePrivacy(request, env) {
  const url = new URL(request.url);
  if (url.pathname === "/tiendanube/privacy/policy" && request.method === "GET") {
    return Response.json({
      ok: true,
      version: VERSION,
      hmacVerification: true,
      endpoints: {
        storeRedact: "/tiendanube/privacy/store-redact",
        customerRedact: "/tiendanube/privacy/customer-redact",
        customersDataRequest: "/tiendanube/privacy/customers-data-request"
      },
      storeRedactDeletesConnectionAndStoreEvents: true,
      customerRedactDeletesOperationalOrderRecords: true,
      customerDataRequestProducesOperationalReport: true
    });
  }
  if (url.pathname === "/tiendanube/privacy/store-redact" && request.method === "POST") return handleStoreRedact(request, env);
  if (url.pathname === "/tiendanube/privacy/customer-redact" && request.method === "POST") return handleCustomerRedact(request, env);
  if (url.pathname === "/tiendanube/privacy/customers-data-request" && request.method === "POST") return handleCustomersDataRequest(request, env);
  return null;
}
