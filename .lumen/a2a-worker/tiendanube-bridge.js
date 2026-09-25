const VERSION = "1.0-tiendanube-bridge";
const API_BASE = "https://api.tiendanube.com/v1";
const AUTHORIZE_BASE = "https://www.tiendanube.com/apps";
const TOKEN_URL = "https://www.tiendanube.com/apps/authorize/token";
const WEBHOOK_EVENTS = ["order/paid", "order/cancelled", "product/updated", "app/suspended", "app/resumed", "app/uninstalled"];

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

function bytesToBase64(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function base64ToBytes(value) {
  const binary = atob(value);
  return Uint8Array.from(binary, ch => ch.charCodeAt(0));
}

async function encryptionKey(env) {
  const seed = `${clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500)}:${clean(env?.TIENDANUBE_CLIENT_SECRET, 1000)}`;
  if (!env?.OPPORTUNITY_ADMIN_TOKEN || !env?.TIENDANUBE_CLIENT_SECRET) throw new Error("missing_encryption_seed");
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(seed));
  return crypto.subtle.importKey("raw", digest, { name: "AES-GCM" }, false, ["encrypt", "decrypt"]);
}

async function encryptToken(env, token) {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const key = await encryptionKey(env);
  const cipher = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, new TextEncoder().encode(token));
  return { cipher: bytesToBase64(new Uint8Array(cipher)), iv: bytesToBase64(iv) };
}

async function decryptToken(env, cipher, iv) {
  const key = await encryptionKey(env);
  const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: base64ToBytes(iv) }, key, base64ToBytes(cipher));
  return new TextDecoder().decode(plain);
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_tiendanube_connections (store_id TEXT PRIMARY KEY,status TEXT NOT NULL,scope TEXT,access_token_cipher TEXT NOT NULL,access_token_iv TEXT NOT NULL,installed_at TEXT NOT NULL,updated_at TEXT NOT NULL,last_verified_at TEXT,last_error TEXT,metadata_json TEXT)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_tiendanube_oauth_states (state TEXT PRIMARY KEY,created_at TEXT NOT NULL,expires_at TEXT NOT NULL,used_at TEXT)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_tiendanube_webhooks (store_id TEXT NOT NULL,event TEXT NOT NULL,webhook_id TEXT,url TEXT NOT NULL,status TEXT NOT NULL,updated_at TEXT NOT NULL,metadata_json TEXT,PRIMARY KEY(store_id,event))"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_tiendanube_events (event_key TEXT PRIMARY KEY,store_id TEXT NOT NULL,event TEXT NOT NULL,resource_id TEXT,verified INTEGER NOT NULL DEFAULT 0,received_at TEXT NOT NULL,payload_json TEXT NOT NULL,processed_at TEXT,metadata_json TEXT)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_tn_events ON lumen_tiendanube_events(event,received_at DESC)")
  ]);
  return true;
}

function appConfig(env) {
  return {
    appId: clean(env?.TIENDANUBE_APP_ID, 100),
    clientSecret: clean(env?.TIENDANUBE_CLIENT_SECRET, 1000),
    userAgent: clean(env?.TIENDANUBE_USER_AGENT || "LUMEN Commerce (lumen-b2b)", 300),
    publicBaseUrl: clean(env?.LUMEN_PUBLIC_BASE_URL || "https://lumen-zero-a2a.lumen-b2b.workers.dev", 500)
  };
}

async function getConnection(env, storeId = null) {
  await ensureSchema(env);
  if (storeId) return env.DB.prepare("SELECT * FROM lumen_tiendanube_connections WHERE store_id=? AND status='ACTIVE'").bind(String(storeId)).first();
  return env.DB.prepare("SELECT * FROM lumen_tiendanube_connections WHERE status='ACTIVE' ORDER BY updated_at DESC LIMIT 1").first();
}

async function apiRequest(env, connection, path, options = {}) {
  if (!connection) throw new Error("tiendanube_not_connected");
  const config = appConfig(env);
  const token = await decryptToken(env, connection.access_token_cipher, connection.access_token_iv);
  const response = await fetch(`${API_BASE}/${connection.store_id}${path}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      "User-Agent": config.userAgent,
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {})
    }
  });
  const text = await response.text();
  let body = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = text; }
  if (!response.ok) throw new Error(`tiendanube_http_${response.status}:${clean(typeof body === "string" ? body : JSON.stringify(body), 500)}`);
  return body;
}

function randomState() {
  const bytes = crypto.getRandomValues(new Uint8Array(24));
  return [...bytes].map(b => b.toString(16).padStart(2, "0")).join("");
}

async function startOAuth(env) {
  const config = appConfig(env);
  if (!config.appId || !config.clientSecret) return { ok: false, error: "missing_app_credentials", needs: ["TIENDANUBE_APP_ID", "TIENDANUBE_CLIENT_SECRET"] };
  await ensureSchema(env);
  const state = randomState();
  const createdAt = new Date();
  const expiresAt = new Date(createdAt.getTime() + 10 * 60 * 1000);
  await env.DB.prepare("INSERT INTO lumen_tiendanube_oauth_states(state,created_at,expires_at) VALUES(?,?,?)").bind(state, createdAt.toISOString(), expiresAt.toISOString()).run();
  return {
    ok: true,
    installUrl: `${AUTHORIZE_BASE}/${encodeURIComponent(config.appId)}/authorize?state=${encodeURIComponent(state)}`,
    callbackUrl: `${config.publicBaseUrl}/tiendanube/oauth/callback`,
    expiresAt: expiresAt.toISOString()
  };
}

async function exchangeOAuthCode(env, code, state) {
  const config = appConfig(env);
  await ensureSchema(env);
  const stateRow = await env.DB.prepare("SELECT * FROM lumen_tiendanube_oauth_states WHERE state=?").bind(state).first();
  if (!stateRow || stateRow.used_at || new Date(stateRow.expires_at).getTime() < Date.now()) throw new Error("invalid_or_expired_oauth_state");
  const response = await fetch(TOKEN_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ client_id: config.appId, client_secret: config.clientSecret, grant_type: "authorization_code", code })
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || !data?.access_token || !data?.user_id) throw new Error(`oauth_exchange_failed_${response.status}`);
  const encrypted = await encryptToken(env, data.access_token);
  const now = new Date().toISOString();
  await env.DB.batch([
    env.DB.prepare("UPDATE lumen_tiendanube_oauth_states SET used_at=? WHERE state=?").bind(now, state),
    env.DB.prepare("INSERT INTO lumen_tiendanube_connections(store_id,status,scope,access_token_cipher,access_token_iv,installed_at,updated_at,metadata_json) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(store_id) DO UPDATE SET status='ACTIVE',scope=excluded.scope,access_token_cipher=excluded.access_token_cipher,access_token_iv=excluded.access_token_iv,updated_at=excluded.updated_at,last_error=NULL,metadata_json=excluded.metadata_json")
      .bind(String(data.user_id), "ACTIVE", clean(data.scope, 1000), encrypted.cipher, encrypted.iv, now, now, JSON.stringify({ version: VERSION, tokenType: data.token_type || "bearer" }))
  ]);
  return { ok: true, storeId: String(data.user_id), scope: data.scope || "", connected: true };
}

async function verifyWebhook(request, env, rawBody) {
  const secret = clean(env?.TIENDANUBE_CLIENT_SECRET, 1000);
  const supplied = clean(request.headers.get("x-linkedstore-hmac-sha256"), 500).toLowerCase();
  if (!secret || !supplied) return false;
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const signature = new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(rawBody)));
  const expected = [...signature].map(b => b.toString(16).padStart(2, "0")).join("");
  if (expected.length !== supplied.length) return false;
  let diff = 0;
  for (let i = 0; i < expected.length; i += 1) diff |= expected.charCodeAt(i) ^ supplied.charCodeAt(i);
  return diff === 0;
}

async function persistCommerceOrderEvent(env, storeId, orderId, event, order) {
  const now = new Date().toISOString();
  const normalizedType = event === "order/paid" ? "ORDER_PAID" : event.toUpperCase().replaceAll("/", "_");
  const total = num(order?.total ?? order?.total_with_shipping ?? order?.subtotal);
  const currency = clean(order?.currency || "ARS", 10).toUpperCase();
  const externalOrderId = String(orderId);
  const eventId = `ORD-TIENDANUBE-${externalOrderId}-${normalizedType}`.slice(0, 240);
  await env.DB.prepare("INSERT INTO lumen_commerce_order_events(event_id,channel,external_order_id,event_type,received_at,verified,currency,total_amount,payload_json,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(channel,external_order_id,event_type) DO UPDATE SET verified=MAX(lumen_commerce_order_events.verified,excluded.verified),payload_json=excluded.payload_json,metadata_json=excluded.metadata_json")
    .bind(eventId, "TIENDANUBE", externalOrderId, normalizedType, now, event === "order/paid" ? 1 : 0, currency, total, JSON.stringify(order || {}), JSON.stringify({ version: VERSION, storeId, source: "verified_tiendanube_webhook" }))
    .run();
}

async function handleWebhook(request, env) {
  if (!env?.DB) return Response.json({ ok: false, error: "missing_db" }, { status: 503 });
  await ensureSchema(env);
  const rawBody = await request.text();
  const verified = await verifyWebhook(request, env, rawBody);
  if (!verified) return Response.json({ ok: false, error: "invalid_signature" }, { status: 401 });
  let payload = {};
  try { payload = JSON.parse(rawBody); } catch { return Response.json({ ok: false, error: "invalid_json" }, { status: 400 }); }
  const storeId = clean(payload?.store_id, 100);
  const event = clean(payload?.event, 100);
  const resourceId = clean(payload?.id, 120);
  const eventKey = `${storeId}:${event}:${resourceId || "none"}:${clean(payload?.event_launch_ts || "", 100)}`.slice(0, 240);
  const now = new Date().toISOString();
  await env.DB.prepare("INSERT OR IGNORE INTO lumen_tiendanube_events(event_key,store_id,event,resource_id,verified,received_at,payload_json,metadata_json) VALUES(?,?,?,?,1,?,?,?)")
    .bind(eventKey, storeId, event, resourceId || null, now, rawBody, JSON.stringify({ version: VERSION })).run();

  if (["app/uninstalled", "app/suspended"].includes(event)) {
    await env.DB.prepare("UPDATE lumen_tiendanube_connections SET status=?,updated_at=? WHERE store_id=?").bind(event === "app/uninstalled" ? "UNINSTALLED" : "SUSPENDED", now, storeId).run();
  } else if (event === "app/resumed") {
    await env.DB.prepare("UPDATE lumen_tiendanube_connections SET status='ACTIVE',updated_at=? WHERE store_id=?").bind(now, storeId).run();
  } else if (["order/paid", "order/cancelled"].includes(event) && resourceId) {
    const connection = await getConnection(env, storeId);
    if (connection) {
      const order = await apiRequest(env, connection, `/orders/${encodeURIComponent(resourceId)}`);
      await persistCommerceOrderEvent(env, storeId, resourceId, event, order);
    }
  }
  await env.DB.prepare("UPDATE lumen_tiendanube_events SET processed_at=? WHERE event_key=?").bind(new Date().toISOString(), eventKey).run();
  return Response.json({ ok: true });
}

async function registerWebhooks(env) {
  const connection = await getConnection(env);
  if (!connection) return { ok: false, error: "not_connected" };
  const config = appConfig(env);
  const existing = await apiRequest(env, connection, "/webhooks?per_page=200");
  const rows = Array.isArray(existing) ? existing : [];
  const results = [];
  for (const event of WEBHOOK_EVENTS) {
    const url = `${config.publicBaseUrl}/tiendanube/webhook`;
    const found = rows.find(row => row?.event === event && row?.url === url);
    let webhook = found;
    if (!webhook) webhook = await apiRequest(env, connection, "/webhooks", { method: "POST", body: JSON.stringify({ event, url }) });
    const now = new Date().toISOString();
    await env.DB.prepare("INSERT INTO lumen_tiendanube_webhooks(store_id,event,webhook_id,url,status,updated_at,metadata_json) VALUES(?,?,?,?,?,?,?) ON CONFLICT(store_id,event) DO UPDATE SET webhook_id=excluded.webhook_id,url=excluded.url,status=excluded.status,updated_at=excluded.updated_at,metadata_json=excluded.metadata_json")
      .bind(connection.store_id, event, String(webhook?.id || ""), url, "ACTIVE", now, JSON.stringify({ version: VERSION })).run();
    results.push({ event, webhookId: webhook?.id || null, reused: Boolean(found) });
  }
  return { ok: true, storeId: connection.store_id, webhooks: results };
}

export function normalizeTiendanubeProduct(payload = {}) {
  const name = payload?.name && typeof payload.name === "object" ? payload.name : { es: clean(payload?.name, 120) };
  const description = payload?.description && typeof payload.description === "object" ? payload.description : { es: clean(payload?.description, 5000) };
  const sourceVariant = Array.isArray(payload?.variants) && payload.variants.length ? payload.variants[0] : {};
  return {
    name,
    description,
    visibility: "hidden",
    requires_shipping: true,
    variants: [{
      price: String(sourceVariant?.price ?? payload?.price ?? "0"),
      sku: clean(sourceVariant?.sku || payload?.sku, 100) || undefined,
      stock: Math.max(0, Math.floor(num(sourceVariant?.stock ?? payload?.stock ?? 0)))
    }]
  };
}

async function executeApprovedPublication(env, body) {
  const queueId = clean(body?.queueId, 220);
  if (!queueId) return { ok: false, error: "missing_queue_id" };
  const connection = await getConnection(env);
  if (!connection) return { ok: false, error: "not_connected" };
  const row = await env.DB.prepare("SELECT * FROM lumen_commerce_publication_queue WHERE queue_id=? AND channel='TIENDANUBE'").bind(queueId).first();
  if (!row) return { ok: false, error: "queue_item_not_found" };
  if (row.state !== "READY_FOR_HUMAN_EXECUTION") return { ok: false, error: "queue_item_not_ready", state: row.state };
  const meta = (() => { try { return JSON.parse(row.metadata_json || "{}"); } catch { return {}; } })();
  const payload = normalizeTiendanubeProduct(meta?.payload || {});
  if (!payload?.name || !payload?.variants?.[0]?.price || Number(payload.variants[0].price) <= 0) return { ok: false, error: "invalid_product_payload" };
  const product = await apiRequest(env, connection, "/products", { method: "POST", body: JSON.stringify(payload) });
  const now = new Date().toISOString();
  await env.DB.batch([
    env.DB.prepare("UPDATE lumen_commerce_publication_queue SET state='EXECUTED_HIDDEN',executed_at=?,external_id=?,updated_at=?,last_error=NULL WHERE queue_id=?").bind(now, String(product?.id || ""), now, queueId),
    env.DB.prepare("UPDATE lumen_commerce_channel_plans SET state='PUBLISHED',external_id=?,updated_at=? WHERE plan_id=?").bind(String(product?.id || ""), now, row.plan_id)
  ]);
  return { ok: true, queueId, productId: product?.id || null, visibility: "hidden", externalWriteExecuted: true, publicVisibility: false };
}

async function status(env) {
  if (!env?.DB) return { ok: false, error: "missing_db" };
  await ensureSchema(env);
  const config = appConfig(env);
  const connection = await getConnection(env);
  const result = {
    ok: true,
    version: VERSION,
    configured: Boolean(config.appId && config.clientSecret),
    connected: Boolean(connection),
    storeId: connection?.store_id || null,
    scope: connection?.scope || null,
    liveProbe: null,
    authority: { autonomousPublishing: false, autonomousPurchasing: false, autonomousSpendUsd: 0, explicitPublicationExecutionRequired: true, newProductsCreatedHidden: true }
  };
  if (connection) {
    try {
      const store = await apiRequest(env, connection, "/store");
      result.liveProbe = { ok: true, storeId: String(store?.id || connection.store_id), name: store?.name || null };
      await env.DB.prepare("UPDATE lumen_tiendanube_connections SET last_verified_at=?,last_error=NULL,updated_at=? WHERE store_id=?").bind(new Date().toISOString(), new Date().toISOString(), connection.store_id).run();
    } catch (error) {
      result.liveProbe = { ok: false, error: clean(error, 300) };
      await env.DB.prepare("UPDATE lumen_tiendanube_connections SET last_error=?,updated_at=? WHERE store_id=?").bind(clean(error, 500), new Date().toISOString(), connection.store_id).run();
    }
  }
  return result;
}

export async function handleTiendanubeBridge(request, env) {
  const url = new URL(request.url);
  if (url.pathname === "/tiendanube/policy" && request.method === "GET") {
    return Response.json({
      ok: true,
      version: VERSION,
      architecture: "UNIDROP_NATIVE_TO_TIENDANUBE_PLUS_LUMEN_API_BRIDGE",
      oauth2: true,
      webhookHmacVerification: true,
      orderPaidIngestion: true,
      publicationExecution: "EXPLICIT_ADMIN_ONLY",
      newProductVisibility: "hidden",
      autonomousPublishing: false,
      autonomousPurchasing: false,
      supplierOrdering: false,
      autonomousSpendUsd: 0
    });
  }
  if (url.pathname === "/tiendanube/oauth/start" && request.method === "POST") {
    if (!authorized(request, env)) return Response.json({ ok: false, error: "unauthorized" }, { status: 401 });
    return Response.json(await startOAuth(env));
  }
  if (url.pathname === "/tiendanube/oauth/callback" && request.method === "GET") {
    const code = clean(url.searchParams.get("code"), 1000);
    const state = clean(url.searchParams.get("state"), 500);
    if (!code || !state) return Response.json({ ok: false, error: "missing_oauth_parameters" }, { status: 400 });
    try {
      const connected = await exchangeOAuthCode(env, code, state);
      return new Response(`<!doctype html><html><head><meta charset="utf-8"><title>LUMEN + Tiendanube</title></head><body style="font-family:system-ui;max-width:720px;margin:60px auto;padding:24px"><h1>Tiendanube conectada a LUMEN</h1><p>Tienda ${connected.storeId} conectada correctamente.</p><p>Ya podés cerrar esta ventana.</p></body></html>`, { headers: { "content-type": "text/html; charset=utf-8" } });
    } catch (error) {
      return Response.json({ ok: false, error: clean(error, 500) }, { status: 400 });
    }
  }
  if (url.pathname === "/tiendanube/webhook" && request.method === "POST") return handleWebhook(request, env);
  if (url.pathname === "/tiendanube/status" && request.method === "GET") {
    if (!authorized(request, env)) return Response.json({ ok: false, error: "unauthorized" }, { status: 401 });
    return Response.json(await status(env));
  }
  if (url.pathname === "/tiendanube/webhooks/register" && request.method === "POST") {
    if (!authorized(request, env)) return Response.json({ ok: false, error: "unauthorized" }, { status: 401 });
    return Response.json(await registerWebhooks(env));
  }
  if (url.pathname === "/tiendanube/publications/execute" && request.method === "POST") {
    if (!authorized(request, env)) return Response.json({ ok: false, error: "unauthorized" }, { status: 401 });
    let body = {};
    try { body = await request.json(); } catch {}
    try { return Response.json(await executeApprovedPublication(env, body)); }
    catch (error) { return Response.json({ ok: false, error: clean(error, 500) }, { status: 400 }); }
  }
  return null;
}
