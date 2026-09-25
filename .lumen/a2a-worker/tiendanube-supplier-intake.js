const VERSION = "1.0-tiendanube-supplier-intake";
const API_BASE = "https://api.tiendanube.com/v1";
const FEED_ID = "tiendanube_supplier_staging";
const MAX_PAGES_PER_RUN = 5;
const PER_PAGE = 30;
const DEFAULT_FIXED_SHIPPING_ARS = 9999.99;
const DEFAULT_PAYMENT_FEE_PCT = 8;
const DEFAULT_RISK_RESERVE_PCT = 3;
const DEFAULT_TARGET_MARGIN_PCT = 20;
const DEFAULT_MIN_STOCK = 10;
const MAX_COMBO_QTY = 3;
const WEBHOOK_EVENTS = ["product/created", "product/updated"];

function clean(value, limit = 3000) {
  return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit);
}

function num(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, num(value)));
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
  const secret = clean(env?.TIENDANUBE_CLIENT_SECRET, 1000);
  const admin = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 1000);
  if (!secret || !admin) throw new Error("missing_encryption_seed");
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`${admin}:${secret}`));
  return crypto.subtle.importKey("raw", digest, { name: "AES-GCM" }, false, ["decrypt"]);
}

async function decryptToken(env, cipher, iv) {
  const key = await encryptionKey(env);
  const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: base64ToBytes(iv) }, key, base64ToBytes(cipher));
  return new TextDecoder().decode(plain);
}

function config(env) {
  return {
    fixedShippingArs: Math.max(0, num(env?.UNIDROP_TN_FIXED_SHIPPING_ARS || DEFAULT_FIXED_SHIPPING_ARS)),
    paymentFeePct: clamp(env?.LUMEN_TN_PAYMENT_FEE_PCT || DEFAULT_PAYMENT_FEE_PCT, 0, 30),
    riskReservePct: clamp(env?.LUMEN_TN_RISK_RESERVE_PCT || DEFAULT_RISK_RESERVE_PCT, 0, 20),
    targetMarginPct: clamp(env?.LUMEN_TN_TARGET_MARGIN_PCT || DEFAULT_TARGET_MARGIN_PCT, 1, 60),
    minStock: Math.max(1, Math.floor(num(env?.LUMEN_TN_MIN_STOCK || DEFAULT_MIN_STOCK))),
    publicBaseUrl: clean(env?.LUMEN_PUBLIC_BASE_URL || "https://lumen-zero-a2a.lumen-b2b.workers.dev", 500),
    userAgent: clean(env?.TIENDANUBE_USER_AGENT || "LUMEN Commerce (43575)", 300)
  };
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_tiendanube_connections (store_id TEXT PRIMARY KEY,status TEXT NOT NULL,scope TEXT,access_token_cipher TEXT NOT NULL,access_token_iv TEXT NOT NULL,installed_at TEXT NOT NULL,updated_at TEXT NOT NULL,last_verified_at TEXT,last_error TEXT,metadata_json TEXT)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_supplier_intake_products (store_id TEXT NOT NULL,product_id TEXT NOT NULL,variant_id TEXT NOT NULL,title TEXT NOT NULL,sku TEXT,currency TEXT NOT NULL,supplier_cost REAL NOT NULL,listed_price REAL NOT NULL,stock INTEGER NOT NULL,visibility TEXT NOT NULL,live_allowed INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL,score INTEGER NOT NULL DEFAULT 0,last_seen_at TEXT NOT NULL,metadata_json TEXT,PRIMARY KEY(store_id,variant_id))"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_supplier_intake_rank ON lumen_supplier_intake_products(status,score DESC,stock DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_supplier_intake_runs (id TEXT PRIMARY KEY,started_at TEXT NOT NULL,finished_at TEXT,status TEXT NOT NULL,products_seen INTEGER NOT NULL DEFAULT 0,variants_seen INTEGER NOT NULL DEFAULT 0,candidates INTEGER NOT NULL DEFAULT 0,hidden INTEGER NOT NULL DEFAULT 0,error TEXT,metadata_json TEXT)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_supplier_intake_webhooks (store_id TEXT NOT NULL,event TEXT NOT NULL,webhook_id TEXT,url TEXT NOT NULL,status TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(store_id,event))"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_product_candidates (candidate_id TEXT PRIMARY KEY,feed_id TEXT NOT NULL,source_product_id TEXT NOT NULL,parent_product_id TEXT,title TEXT NOT NULL,vendor TEXT,sku TEXT,gtin TEXT,currency TEXT NOT NULL,supplier_cost REAL NOT NULL,market_anchor REAL NOT NULL,candidate_sell_price REAL NOT NULL,projected_profit REAL NOT NULL,projected_margin_pct REAL NOT NULL,score INTEGER NOT NULL,status TEXT NOT NULL,source_url TEXT NOT NULL,rejection_json TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,metadata_json TEXT,UNIQUE(feed_id,source_product_id))"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_product_candidates_rank ON lumen_product_candidates(status,score DESC,projected_margin_pct DESC)")
  ]);
  return true;
}

async function getConnection(env, storeId = null) {
  await ensureSchema(env);
  if (storeId) return env.DB.prepare("SELECT * FROM lumen_tiendanube_connections WHERE store_id=? AND status='ACTIVE'").bind(String(storeId)).first();
  return env.DB.prepare("SELECT * FROM lumen_tiendanube_connections WHERE status='ACTIVE' ORDER BY updated_at DESC LIMIT 1").first();
}

async function apiRequest(env, connection, path, options = {}) {
  if (!connection) throw new Error("tiendanube_not_connected");
  const token = await decryptToken(env, connection.access_token_cipher, connection.access_token_iv);
  const cfg = config(env);
  const response = await fetch(`${API_BASE}/${connection.store_id}${path}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      "User-Agent": cfg.userAgent,
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

function localized(value) {
  if (typeof value === "string") return clean(value, 260);
  if (!value || typeof value !== "object") return "";
  return clean(value.es || value.pt || value.en || Object.values(value)[0] || "", 260);
}

function landedEconomics(cost, listedPrice, stock, cfg) {
  const feeRate = cfg.paymentFeePct / 100;
  const riskRate = cfg.riskReservePct / 100;
  const targetRate = cfg.targetMarginPct / 100;
  const denominator = 1 - feeRate - riskRate - targetRate;
  const baseFloor = denominator > 0 ? cost / denominator : 0;
  const combos = [];
  for (let qty = 1; qty <= MAX_COMBO_QTY; qty += 1) {
    const sellerPaidUnitFloor = denominator > 0 ? ((cost * qty) + cfg.fixedShippingArs) / qty / denominator : 0;
    combos.push({
      qty,
      sellerPaidUnitFloor: Number(sellerPaidUnitFloor.toFixed(2)),
      customerPaidShippingUnitFloor: Number(baseFloor.toFixed(2)),
      listedPriceViableWithSellerPaidShipping: listedPrice >= sellerPaidUnitFloor,
      listedPriceViableWithCustomerPaidShipping: listedPrice >= baseFloor
    });
  }
  const sellerPaidViable = combos.find(row => row.listedPriceViableWithSellerPaidShipping) || null;
  const customerPaidViable = listedPrice >= baseFloor;
  const minimumSellPrice = Math.max(baseFloor, 0);
  const fee = listedPrice * feeRate;
  const risk = listedPrice * riskRate;
  const profitCustomerPaidShipping = listedPrice - cost - fee - risk;
  const marginCustomerPaidShippingPct = listedPrice > 0 ? (profitCustomerPaidShipping / listedPrice) * 100 : 0;
  const shippingStrategy = sellerPaidViable ? `SELLER_PAID_COMBO_${sellerPaidViable.qty}` : customerPaidViable ? "CUSTOMER_PAID_SHIPPING" : "PRICE_INCREASE_REQUIRED";
  return {
    minimumSellPrice: Number(minimumSellPrice.toFixed(2)),
    fixedShippingArs: cfg.fixedShippingArs,
    paymentFeePct: cfg.paymentFeePct,
    riskReservePct: cfg.riskReservePct,
    targetMarginPct: cfg.targetMarginPct,
    projectedProfit: Number(profitCustomerPaidShipping.toFixed(2)),
    projectedMarginPct: Number(marginCustomerPaidShippingPct.toFixed(2)),
    shippingStrategy,
    combos,
    stock
  };
}

function rankVariant({ cost, price, stock, sku, economics, cfg }) {
  let score = 0;
  if (cost > 0) score += 20;
  if (price > 0) score += 10;
  if (stock >= cfg.minStock) score += 25;
  else if (stock > 0) score += 8;
  if (sku) score += 10;
  if (economics.shippingStrategy.startsWith("SELLER_PAID_COMBO")) score += 25;
  else if (economics.shippingStrategy === "CUSTOMER_PAID_SHIPPING") score += 18;
  else if (price > 0 && economics.minimumSellPrice <= price * 1.35) score += 8;
  if (economics.projectedMarginPct >= cfg.targetMarginPct) score += 10;
  return Math.round(clamp(score, 0, 100));
}

function rejectionReasons({ cost, price, stock, economics, cfg }) {
  const reasons = [];
  if (!(cost > 0)) reasons.push("missing_supplier_cost");
  if (!(price > 0)) reasons.push("missing_listed_price");
  if (!(stock > 0)) reasons.push("out_of_stock");
  if (stock > 0 && stock < cfg.minStock) reasons.push("stock_below_target");
  if (economics.shippingStrategy === "PRICE_INCREASE_REQUIRED" && economics.minimumSellPrice > price * 1.35) reasons.push("price_far_below_landed_floor");
  return reasons;
}

async function liveAllowed(env, storeId, productId) {
  const row = await env.DB.prepare("SELECT MAX(live_allowed) AS allowed FROM lumen_supplier_intake_products WHERE store_id=? AND product_id=?").bind(String(storeId), String(productId)).first();
  return Number(row?.allowed || 0) === 1;
}

async function hideForStaging(env, connection, product) {
  if (!product?.id || clean(product?.visibility, 40) === "hidden") return false;
  if (await liveAllowed(env, connection.store_id, product.id)) return false;
  await apiRequest(env, connection, `/products/${encodeURIComponent(product.id)}`, {
    method: "PUT",
    body: JSON.stringify({ visibility: "hidden" })
  });
  return true;
}

async function persistVariant(env, connection, product, variant) {
  const cfg = config(env);
  const title = localized(product?.name) || `Tiendanube product ${product?.id}`;
  const variantLabel = Array.isArray(variant?.values) ? variant.values.map(localized).filter(Boolean).join(" / ") : "";
  const fullTitle = clean(variantLabel ? `${title} - ${variantLabel}` : title, 260);
  const cost = Math.max(0, num(variant?.cost));
  const price = Math.max(0, num(variant?.price));
  const stock = Math.max(0, Math.floor(num(variant?.stock)));
  const sku = clean(variant?.sku, 160);
  const gtin = clean(variant?.barcode, 160);
  const econ = landedEconomics(cost, price, stock, cfg);
  const reasons = rejectionReasons({ cost, price, stock, economics: econ, cfg });
  const score = rankVariant({ cost, price, stock, sku, economics: econ, cfg });
  const status = reasons.some(reason => ["missing_supplier_cost", "missing_listed_price", "out_of_stock", "price_far_below_landed_floor"].includes(reason)) ? "REJECTED" : "DRAFT_READY";
  const now = new Date().toISOString();
  const productId = String(product?.id || "");
  const variantId = String(variant?.id || productId);
  const sourceProductId = `TN-${productId}-${variantId}`;
  const candidateId = `PC-${FEED_ID}-${productId}-${variantId}`.slice(0, 180);
  const visibility = clean(product?.visibility || (product?.published ? "visible" : "hidden"), 40);
  const metadata = {
    version: VERSION,
    source: "TIENDANUBE_CONNECTED_SUPPLIER",
    staging: true,
    dimensions: { weight: num(variant?.weight), width: num(variant?.width), height: num(variant?.height), depth: num(variant?.depth) },
    economics: econ,
    supplierIntegration: "connected_tiendanube_catalog",
    supplierAssetsAuthorizedByIntegration: true
  };

  await env.DB.prepare("INSERT INTO lumen_supplier_intake_products(store_id,product_id,variant_id,title,sku,currency,supplier_cost,listed_price,stock,visibility,status,score,last_seen_at,metadata_json) VALUES(?,?,?,?,?,'ARS',?,?,?,?,?,?,?,?) ON CONFLICT(store_id,variant_id) DO UPDATE SET product_id=excluded.product_id,title=excluded.title,sku=excluded.sku,supplier_cost=excluded.supplier_cost,listed_price=excluded.listed_price,stock=excluded.stock,visibility=excluded.visibility,status=excluded.status,score=excluded.score,last_seen_at=excluded.last_seen_at,metadata_json=excluded.metadata_json")
    .bind(connection.store_id, productId, variantId, fullTitle, sku || null, cost, price, stock, visibility, status, score, now, JSON.stringify(metadata)).run();

  await env.DB.prepare("INSERT INTO lumen_product_candidates(candidate_id,feed_id,source_product_id,parent_product_id,title,vendor,sku,gtin,currency,supplier_cost,market_anchor,candidate_sell_price,projected_profit,projected_margin_pct,score,status,source_url,rejection_json,created_at,updated_at,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(feed_id,source_product_id) DO UPDATE SET title=excluded.title,sku=excluded.sku,gtin=excluded.gtin,supplier_cost=excluded.supplier_cost,market_anchor=excluded.market_anchor,candidate_sell_price=excluded.candidate_sell_price,projected_profit=excluded.projected_profit,projected_margin_pct=excluded.projected_margin_pct,score=excluded.score,status=CASE WHEN lumen_product_candidates.status IN ('PUBLISHED','ORDERED','FULFILLED') THEN lumen_product_candidates.status ELSE excluded.status END,rejection_json=excluded.rejection_json,updated_at=excluded.updated_at,metadata_json=excluded.metadata_json")
    .bind(candidateId, FEED_ID, sourceProductId, productId, fullTitle, clean(product?.brand, 160) || "Unidrop/Unistore", sku || null, gtin || null, "ARS", cost, price, Math.max(price, econ.minimumSellPrice), econ.projectedProfit, econ.projectedMarginPct, score, status, `tiendanube://store/${connection.store_id}/product/${productId}`, JSON.stringify(reasons), now, now, JSON.stringify(metadata)).run();

  return { status, score, sourceProductId, reasons, economics: econ };
}

async function ingestProduct(env, connection, product, { hide = true } = {}) {
  const hidden = hide ? await hideForStaging(env, connection, product) : false;
  const variants = Array.isArray(product?.variants) ? product.variants : [];
  const results = [];
  for (const variant of variants) results.push(await persistVariant(env, connection, product, variant));
  return { productId: String(product?.id || ""), hidden, variants: results };
}

async function fetchProduct(env, connection, productId) {
  return apiRequest(env, connection, `/products/${encodeURIComponent(productId)}`);
}

async function registerWebhooks(env, connection) {
  const cfg = config(env);
  const existing = await apiRequest(env, connection, "/webhooks?per_page=200");
  const rows = Array.isArray(existing) ? existing : [];
  const url = `${cfg.publicBaseUrl}/supplier-intake/webhook`;
  const results = [];
  for (const event of WEBHOOK_EVENTS) {
    const found = rows.find(row => row?.event === event && row?.url === url);
    let webhook = found;
    if (!webhook) webhook = await apiRequest(env, connection, "/webhooks", { method: "POST", body: JSON.stringify({ event, url }) });
    const now = new Date().toISOString();
    await env.DB.prepare("INSERT INTO lumen_supplier_intake_webhooks(store_id,event,webhook_id,url,status,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(store_id,event) DO UPDATE SET webhook_id=excluded.webhook_id,url=excluded.url,status=excluded.status,updated_at=excluded.updated_at")
      .bind(connection.store_id, event, String(webhook?.id || ""), url, "ACTIVE", now).run();
    results.push({ event, webhookId: webhook?.id || null, reused: Boolean(found) });
  }
  return results;
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

async function handleWebhook(request, env) {
  const rawBody = await request.text();
  if (!(await verifyWebhook(request, env, rawBody))) return Response.json({ ok: false, error: "invalid_signature" }, { status: 401 });
  let payload = {};
  try { payload = JSON.parse(rawBody); } catch { return Response.json({ ok: false, error: "invalid_json" }, { status: 400 }); }
  if (!WEBHOOK_EVENTS.includes(clean(payload?.event, 100))) return Response.json({ ok: true, ignored: true });
  const connection = await getConnection(env, payload?.store_id);
  if (!connection) return Response.json({ ok: false, error: "store_not_connected" }, { status: 404 });
  const product = await fetchProduct(env, connection, payload?.id);
  const result = await ingestProduct(env, connection, product, { hide: true });
  return Response.json({ ok: true, version: VERSION, result });
}

export async function runTiendanubeSupplierIntake(env) {
  const startedAt = new Date().toISOString();
  if (!env?.DB) return { ok: false, skipped: true, reason: "missing_db" };
  await ensureSchema(env);
  const connection = await getConnection(env);
  if (!connection) return { ok: true, skipped: true, reason: "tiendanube_not_connected", version: VERSION };
  const runId = `TSI-${Date.now()}`;
  await env.DB.prepare("INSERT INTO lumen_supplier_intake_runs(id,started_at,status,metadata_json) VALUES(?,?,?,?)")
    .bind(runId, startedAt, "RUNNING", JSON.stringify({ version: VERSION, mode: "staging_auto_intake" })).run();
  let productsSeen = 0;
  let variantsSeen = 0;
  let candidates = 0;
  let hidden = 0;
  const errors = [];
  try {
    await registerWebhooks(env, connection);
    for (let page = 1; page <= MAX_PAGES_PER_RUN; page += 1) {
      const products = await apiRequest(env, connection, `/products?per_page=${PER_PAGE}&page=${page}&sort_by=created-at-descending`);
      if (!Array.isArray(products) || !products.length) break;
      for (const product of products) {
        productsSeen += 1;
        try {
          const result = await ingestProduct(env, connection, product, { hide: true });
          if (result.hidden) hidden += 1;
          variantsSeen += result.variants.length;
          candidates += result.variants.filter(row => row.status === "DRAFT_READY").length;
        } catch (error) {
          errors.push({ productId: String(product?.id || ""), error: clean(error, 300) });
        }
      }
      if (products.length < PER_PAGE) break;
    }
    const finishedAt = new Date().toISOString();
    const status = errors.length ? "PARTIAL" : "SUCCESS";
    await env.DB.prepare("UPDATE lumen_supplier_intake_runs SET finished_at=?,status=?,products_seen=?,variants_seen=?,candidates=?,hidden=?,error=?,metadata_json=? WHERE id=?")
      .bind(finishedAt, status, productsSeen, variantsSeen, candidates, hidden, errors.length ? JSON.stringify(errors.slice(0, 10)) : null, JSON.stringify({ version: VERSION, storeId: connection.store_id }), runId).run();
    return { ok: true, version: VERSION, status, storeId: connection.store_id, productsSeen, variantsSeen, candidates, hidden, errors: errors.slice(0, 10) };
  } catch (error) {
    const finishedAt = new Date().toISOString();
    await env.DB.prepare("UPDATE lumen_supplier_intake_runs SET finished_at=?,status='FAILED',error=? WHERE id=?").bind(finishedAt, clean(error, 500), runId).run();
    return { ok: false, version: VERSION, error: clean(error, 500) };
  }
}

async function status(env) {
  await ensureSchema(env);
  const [connection, run, counts, top] = await Promise.all([
    getConnection(env),
    env.DB.prepare("SELECT * FROM lumen_supplier_intake_runs ORDER BY started_at DESC LIMIT 1").first(),
    env.DB.prepare("SELECT COUNT(*) AS variants,SUM(CASE WHEN status='DRAFT_READY' THEN 1 ELSE 0 END) AS candidates,SUM(CASE WHEN status='REJECTED' THEN 1 ELSE 0 END) AS rejected FROM lumen_supplier_intake_products").first(),
    env.DB.prepare("SELECT store_id,product_id,variant_id,title,sku,supplier_cost,listed_price,stock,status,score,metadata_json FROM lumen_supplier_intake_products WHERE status='DRAFT_READY' ORDER BY score DESC,stock DESC LIMIT 20").all()
  ]);
  return { ok: true, version: VERSION, storeId: connection?.store_id || null, connected: Boolean(connection), lastRun: run || null, counts: counts || {}, topCandidates: top?.results || [] };
}

export async function handleTiendanubeSupplierIntake(request, env) {
  const url = new URL(request.url);
  if (url.pathname === "/supplier-intake/policy" && request.method === "GET") {
    const cfg = config(env);
    return Response.json({
      ok: true,
      version: VERSION,
      mode: "TIENDANUBE_CONNECTED_SUPPLIER_STAGING",
      supplierCatalogAccess: "via_connected_tiendanube_products",
      realTimeEvents: WEBHOOK_EVENTS,
      readsVariantCost: true,
      readsStock: true,
      readsDimensions: true,
      fixedShippingArs: cfg.fixedShippingArs,
      paymentFeeReservePct: cfg.paymentFeePct,
      riskReservePct: cfg.riskReservePct,
      targetMarginPct: cfg.targetMarginPct,
      maxComboQty: MAX_COMBO_QTY,
      importedProductsAutoHiddenInStaging: true,
      autonomousPublishing: false,
      autonomousPurchasing: false,
      supplierOrdering: false,
      autonomousSpendUsd: 0,
      approvalRequiredBeforeLive: true
    });
  }
  if (url.pathname === "/supplier-intake/webhook" && request.method === "POST") return handleWebhook(request, env);
  if (url.pathname === "/supplier-intake/status" && request.method === "GET") {
    if (!authorized(request, env)) return Response.json({ ok: false, error: "unauthorized" }, { status: 401 });
    return Response.json(await status(env));
  }
  if (url.pathname === "/supplier-intake/run" && request.method === "POST") {
    if (!authorized(request, env)) return Response.json({ ok: false, error: "unauthorized" }, { status: 401 });
    return Response.json(await runTiendanubeSupplierIntake(env));
  }
  if (url.pathname === "/supplier-intake/register" && request.method === "POST") {
    if (!authorized(request, env)) return Response.json({ ok: false, error: "unauthorized" }, { status: 401 });
    const connection = await getConnection(env);
    if (!connection) return Response.json({ ok: false, error: "tiendanube_not_connected" }, { status: 404 });
    return Response.json({ ok: true, version: VERSION, storeId: connection.store_id, webhooks: await registerWebhooks(env, connection) });
  }
  return null;
}
