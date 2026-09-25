const VERSION = "1.0-product-commerce-radar";
const MAX_FEEDS_PER_CYCLE = 3;
const MAX_PRODUCTS_PER_FEED = 25;
const FETCH_TIMEOUT_MS = 8000;
const DEFAULT_TARGET_MARGIN_PCT = 18;
const DEFAULT_MARKETPLACE_FEE_PCT = 14;
const DEFAULT_SHIPPING_BUFFER_PCT = 5;

function clean(value, limit = 2000) {
  return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit);
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, Number(value || 0)));
}

function num(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function bool(value) {
  if (typeof value === "boolean") return value;
  return ["1", "true", "yes", "y", "in_stock", "available", "active"].includes(clean(value, 50).toLowerCase());
}

function authorized(request, env) {
  const expected = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const supplied = clean(request.headers.get("x-lumen-admin"), 500);
  return Boolean(expected && supplied && expected === supplied);
}

async function fetchJson(url) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const response = await fetch(url, {
      method: "GET",
      signal: controller.signal,
      headers: { accept: "application/json", "user-agent": "LUMEN-Product-Commerce-Radar/1.0" }
    });
    if (!response.ok) throw new Error(`http_${response.status}`);
    return await response.json();
  } finally {
    clearTimeout(timeout);
  }
}

function parseFeeds(env) {
  let rows = [];
  try {
    rows = JSON.parse(env?.LUMEN_PRODUCT_FEEDS_JSON || "[]");
  } catch {
    rows = [];
  }
  if (!Array.isArray(rows)) return [];
  return rows
    .filter(row => row && row.enabled !== false && row.allowed === true && /^https:\/\//i.test(clean(row.url, 1200)))
    .map((row, index) => ({
      id: clean(row.id || `feed_${index + 1}`, 120),
      name: clean(row.name || row.id || `Feed ${index + 1}`, 200),
      url: clean(row.url, 1200),
      format: clean(row.format || "generic", 80).toLowerCase(),
      currency: clean(row.currency || "ARS", 10).toUpperCase(),
      marketplaceFeePct: clamp(row.marketplaceFeePct ?? DEFAULT_MARKETPLACE_FEE_PCT, 0, 40),
      shippingBufferPct: clamp(row.shippingBufferPct ?? DEFAULT_SHIPPING_BUFFER_PCT, 0, 40),
      targetMarginPct: clamp(row.targetMarginPct ?? DEFAULT_TARGET_MARGIN_PCT, 1, 70),
      protected: row.protected !== false
    }))
    .slice(0, 20);
}

function getAttr(product, names) {
  for (const name of names) {
    if (product?.[name] != null && product[name] !== "") return product[name];
  }
  return null;
}

function normalizeShopifyProduct(product, feed) {
  const variants = Array.isArray(product?.variants) ? product.variants : [];
  return variants.map(variant => {
    const price = num(variant?.price);
    const compareAt = num(variant?.compare_at_price);
    const inventory = variant?.inventory_quantity;
    const available = variant?.available === true || (Number.isFinite(Number(inventory)) && Number(inventory) > 0);
    return {
      sourceProductId: clean(variant?.id || product?.id, 160),
      parentProductId: clean(product?.id, 160),
      title: clean([product?.title, variant?.title && variant.title !== "Default Title" ? variant.title : ""].filter(Boolean).join(" - "), 260),
      vendor: clean(product?.vendor, 160),
      sku: clean(variant?.sku, 160),
      gtin: clean(variant?.barcode, 160),
      cost: price,
      marketAnchor: compareAt,
      currency: feed.currency,
      available,
      sourceUrl: clean(product?.handle ? new URL(`/products/${product.handle}`, feed.url).toString() : feed.url, 1200),
      raw: { productType: clean(product?.product_type, 160), variantId: variant?.id || null }
    };
  });
}

function normalizeGenericProduct(product, feed) {
  const cost = num(getAttr(product, ["cost", "supplier_price", "wholesale_price", "price"]));
  const marketAnchor = num(getAttr(product, ["suggested_retail_price", "retail_price", "compare_at_price", "msrp", "list_price"]));
  const stock = getAttr(product, ["stock", "inventory", "quantity", "inventory_quantity"]);
  const availableRaw = getAttr(product, ["available", "in_stock", "status"]);
  const available = Number.isFinite(Number(stock)) ? Number(stock) > 0 : bool(availableRaw);
  return [{
    sourceProductId: clean(getAttr(product, ["id", "product_id", "item_id", "sku", "gtin"]), 160),
    parentProductId: clean(getAttr(product, ["parent_id", "group_id"]), 160),
    title: clean(getAttr(product, ["title", "name", "product_name"]), 260),
    vendor: clean(getAttr(product, ["vendor", "brand", "manufacturer"]), 160),
    sku: clean(getAttr(product, ["sku", "seller_sku"]), 160),
    gtin: clean(getAttr(product, ["gtin", "ean", "upc", "barcode"]), 160),
    cost,
    marketAnchor,
    currency: clean(getAttr(product, ["currency"]) || feed.currency, 10).toUpperCase(),
    available,
    sourceUrl: clean(getAttr(product, ["url", "permalink", "product_url"]) || feed.url, 1200),
    raw: {}
  }];
}

function normalizePayload(payload, feed) {
  const rows = Array.isArray(payload) ? payload :
    Array.isArray(payload?.products) ? payload.products :
    Array.isArray(payload?.items) ? payload.items :
    Array.isArray(payload?.results) ? payload.results : [];
  const normalized = [];
  for (const product of rows.slice(0, MAX_PRODUCTS_PER_FEED)) {
    const variants = feed.format === "shopify" ? normalizeShopifyProduct(product, feed) : normalizeGenericProduct(product, feed);
    for (const row of variants) normalized.push(row);
    if (normalized.length >= MAX_PRODUCTS_PER_FEED) break;
  }
  return normalized.slice(0, MAX_PRODUCTS_PER_FEED);
}

function economics(product, feed) {
  const cost = Math.max(0, num(product.cost));
  const anchor = Math.max(0, num(product.marketAnchor));
  const feeRate = feed.marketplaceFeePct / 100;
  const shippingRate = feed.shippingBufferPct / 100;
  const targetMarginRate = feed.targetMarginPct / 100;
  const totalRate = feeRate + shippingRate + targetMarginRate;
  const minimumSellPrice = totalRate >= 0.95 ? 0 : cost / (1 - totalRate);
  const candidateSellPrice = anchor > 0 ? anchor : minimumSellPrice;
  const fee = candidateSellPrice * feeRate;
  const shippingBuffer = candidateSellPrice * shippingRate;
  const projectedProfit = candidateSellPrice - cost - fee - shippingBuffer;
  const projectedMarginPct = candidateSellPrice > 0 ? (projectedProfit / candidateSellPrice) * 100 : 0;
  const spreadPct = cost > 0 && anchor > 0 ? ((anchor - cost) / cost) * 100 : 0;
  return {
    cost,
    marketAnchor: anchor,
    minimumSellPrice: Number(minimumSellPrice.toFixed(2)),
    candidateSellPrice: Number(candidateSellPrice.toFixed(2)),
    marketplaceFee: Number(fee.toFixed(2)),
    shippingBuffer: Number(shippingBuffer.toFixed(2)),
    projectedProfit: Number(projectedProfit.toFixed(2)),
    projectedMarginPct: Number(projectedMarginPct.toFixed(2)),
    spreadPct: Number(spreadPct.toFixed(2))
  };
}

function scoreCandidate(product, econ, feed) {
  let score = 0;
  if (product.available) score += 25;
  if (product.sku || product.gtin) score += 12;
  if (product.gtin) score += 8;
  if (product.sourceUrl) score += 5;
  if (econ.marketAnchor > 0) score += 15;
  if (econ.projectedMarginPct >= feed.targetMarginPct) score += 25;
  else if (econ.projectedMarginPct >= feed.targetMarginPct * 0.75) score += 10;
  if (econ.projectedProfit > 0) score += 10;
  return Math.round(clamp(score, 0, 100));
}

function rejectionReasons(product, econ, feed) {
  const reasons = [];
  if (!product.sourceProductId) reasons.push("missing_source_product_id");
  if (!product.title) reasons.push("missing_title");
  if (!product.available) reasons.push("stock_not_confirmed");
  if (!(econ.cost > 0)) reasons.push("missing_supplier_cost");
  if (!(econ.marketAnchor > 0)) reasons.push("missing_market_price_anchor");
  if (econ.projectedProfit <= 0) reasons.push("no_projected_profit");
  if (econ.projectedMarginPct < feed.targetMarginPct) reasons.push("margin_below_target");
  return reasons;
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_product_feeds (feed_id TEXT PRIMARY KEY,name TEXT NOT NULL,url TEXT NOT NULL,format TEXT NOT NULL,currency TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1,protected INTEGER NOT NULL DEFAULT 1,runs INTEGER NOT NULL DEFAULT 0,products_seen INTEGER NOT NULL DEFAULT 0,candidates INTEGER NOT NULL DEFAULT 0,verified_orders INTEGER NOT NULL DEFAULT 0,verified_revenue REAL NOT NULL DEFAULT 0,last_run_at TEXT,last_error TEXT,updated_at TEXT NOT NULL,metadata_json TEXT)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_product_candidates (candidate_id TEXT PRIMARY KEY,feed_id TEXT NOT NULL,source_product_id TEXT NOT NULL,parent_product_id TEXT,title TEXT NOT NULL,vendor TEXT,sku TEXT,gtin TEXT,currency TEXT NOT NULL,supplier_cost REAL NOT NULL,market_anchor REAL NOT NULL,candidate_sell_price REAL NOT NULL,projected_profit REAL NOT NULL,projected_margin_pct REAL NOT NULL,score INTEGER NOT NULL,status TEXT NOT NULL,source_url TEXT NOT NULL,rejection_json TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,metadata_json TEXT,UNIQUE(feed_id,source_product_id))"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_product_candidates_rank ON lumen_product_candidates(status,score DESC,projected_margin_pct DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_product_commerce_runs (id TEXT PRIMARY KEY,started_at TEXT NOT NULL,finished_at TEXT,status TEXT NOT NULL,feeds_scanned INTEGER NOT NULL DEFAULT 0,products_seen INTEGER NOT NULL DEFAULT 0,candidates INTEGER NOT NULL DEFAULT 0,error TEXT,metadata_json TEXT)")
  ]);
  return true;
}

async function upsertFeed(env, feed) {
  const now = new Date().toISOString();
  await env.DB.prepare("INSERT INTO lumen_product_feeds(feed_id,name,url,format,currency,enabled,protected,updated_at,metadata_json) VALUES(?,?,?,?,?,1,?,?,?) ON CONFLICT(feed_id) DO UPDATE SET name=excluded.name,url=excluded.url,format=excluded.format,currency=excluded.currency,protected=excluded.protected,updated_at=excluded.updated_at")
    .bind(feed.id, feed.name, feed.url, feed.format, feed.currency, feed.protected ? 1 : 0, now, JSON.stringify({ version: VERSION, feePct: feed.marketplaceFeePct, shippingBufferPct: feed.shippingBufferPct, targetMarginPct: feed.targetMarginPct }))
    .run();
}

async function persistCandidate(env, feed, product) {
  const econ = economics(product, feed);
  const reasons = rejectionReasons(product, econ, feed);
  const score = scoreCandidate(product, econ, feed);
  const candidateId = `PC-${feed.id}-${product.sourceProductId}`.replace(/[^a-z0-9_-]+/gi, "-").slice(0, 180);
  const now = new Date().toISOString();
  const status = reasons.length ? "REJECTED" : "DRAFT_READY";
  await env.DB.prepare("INSERT INTO lumen_product_candidates(candidate_id,feed_id,source_product_id,parent_product_id,title,vendor,sku,gtin,currency,supplier_cost,market_anchor,candidate_sell_price,projected_profit,projected_margin_pct,score,status,source_url,rejection_json,created_at,updated_at,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(feed_id,source_product_id) DO UPDATE SET title=excluded.title,vendor=excluded.vendor,sku=excluded.sku,gtin=excluded.gtin,currency=excluded.currency,supplier_cost=excluded.supplier_cost,market_anchor=excluded.market_anchor,candidate_sell_price=excluded.candidate_sell_price,projected_profit=excluded.projected_profit,projected_margin_pct=excluded.projected_margin_pct,score=excluded.score,status=CASE WHEN lumen_product_candidates.status IN ('PUBLISHED','ORDERED','FULFILLED') THEN lumen_product_candidates.status ELSE excluded.status END,source_url=excluded.source_url,rejection_json=excluded.rejection_json,updated_at=excluded.updated_at,metadata_json=excluded.metadata_json")
    .bind(candidateId, feed.id, product.sourceProductId, product.parentProductId || null, product.title, product.vendor || null, product.sku || null, product.gtin || null, product.currency || feed.currency, econ.cost, econ.marketAnchor, econ.candidateSellPrice, econ.projectedProfit, econ.projectedMarginPct, score, status, product.sourceUrl, JSON.stringify(reasons), now, now, JSON.stringify({ version: VERSION, economics: econ, raw: product.raw || {}, originalCopyReused: false, originalImagesReused: false }))
    .run();
  return { status, score, econ };
}

export async function runProductCommerceRadar(env) {
  const startedAt = new Date().toISOString();
  if (!env?.DB) return { ok: false, skipped: true, reason: "missing_db" };
  await ensureSchema(env);
  const feeds = parseFeeds(env);
  if (!feeds.length) return { ok: true, skipped: true, reason: "no_allowed_product_feeds", version: VERSION };
  const runId = `PCR-${Date.now()}`;
  await env.DB.prepare("INSERT INTO lumen_product_commerce_runs(id,started_at,status,metadata_json) VALUES(?,?,?,?)")
    .bind(runId, startedAt, "RUNNING", JSON.stringify({ version: VERSION, authority: "observe_and_draft_only" })).run();

  let feedsScanned = 0;
  let productsSeen = 0;
  let candidates = 0;
  const errors = [];

  for (const feed of feeds.slice(0, MAX_FEEDS_PER_CYCLE)) {
    await upsertFeed(env, feed);
    const feedNow = new Date().toISOString();
    try {
      const payload = await fetchJson(feed.url);
      const products = normalizePayload(payload, feed);
      feedsScanned += 1;
      productsSeen += products.length;
      let feedCandidates = 0;
      for (const product of products) {
        const result = await persistCandidate(env, feed, product);
        if (result.status === "DRAFT_READY") {
          candidates += 1;
          feedCandidates += 1;
        }
      }
      await env.DB.prepare("UPDATE lumen_product_feeds SET runs=runs+1,products_seen=products_seen+?,candidates=candidates+?,last_run_at=?,last_error=NULL,updated_at=? WHERE feed_id=?")
        .bind(products.length, feedCandidates, feedNow, feedNow, feed.id).run();
    } catch (error) {
      errors.push({ feedId: feed.id, error: clean(error, 300) });
      await env.DB.prepare("UPDATE lumen_product_feeds SET runs=runs+1,last_run_at=?,last_error=?,updated_at=? WHERE feed_id=?")
        .bind(feedNow, clean(error, 300), feedNow, feed.id).run();
    }
  }

  const finishedAt = new Date().toISOString();
  const status = errors.length === feeds.length && feeds.length ? "FAILED" : errors.length ? "PARTIAL" : "SUCCESS";
  await env.DB.prepare("UPDATE lumen_product_commerce_runs SET finished_at=?,status=?,feeds_scanned=?,products_seen=?,candidates=?,error=?,metadata_json=? WHERE id=?")
    .bind(finishedAt, status, feedsScanned, productsSeen, candidates, errors.length ? JSON.stringify(errors) : null, JSON.stringify({ version: VERSION, publicationAuthority: false, purchaseAuthority: false, spendAuthorityUsd: 0 }), runId).run();
  return { ok: status !== "FAILED", status, runId, feedsScanned, productsSeen, candidates, errors, version: VERSION };
}

async function status(env) {
  if (!env?.DB) return { ok: false, reason: "missing_db" };
  await ensureSchema(env);
  const [run, counts, top] = await Promise.all([
    env.DB.prepare("SELECT * FROM lumen_product_commerce_runs ORDER BY started_at DESC LIMIT 1").first(),
    env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN status='DRAFT_READY' THEN 1 ELSE 0 END) draft_ready,SUM(CASE WHEN status='REJECTED' THEN 1 ELSE 0 END) rejected,SUM(CASE WHEN status='PUBLISHED' THEN 1 ELSE 0 END) published,SUM(CASE WHEN status IN ('ORDERED','FULFILLED') THEN 1 ELSE 0 END) ordered FROM lumen_product_candidates").first(),
    env.DB.prepare("SELECT candidate_id,feed_id,title,currency,supplier_cost,market_anchor,candidate_sell_price,projected_profit,projected_margin_pct,score,status,source_url FROM lumen_product_candidates WHERE status='DRAFT_READY' ORDER BY score DESC,projected_margin_pct DESC LIMIT 10").all()
  ]);
  return { ok: true, version: VERSION, authority: { observe: true, draft: true, publish: false, purchase: false, contract: false, autonomousSpendUsd: 0 }, lastRun: run || null, counts: counts || {}, topCandidates: top?.results || [] };
}

export async function handleProductCommerceRadar(request, env) {
  const url = new URL(request.url);
  if (url.pathname === "/product-commerce/policy" && request.method === "GET") {
    return Response.json({
      ok: true,
      version: VERSION,
      mode: "OBSERVE_SCORE_DRAFT_ONLY",
      maxFeedsPerCycle: MAX_FEEDS_PER_CYCLE,
      maxProductsPerFeed: MAX_PRODUCTS_PER_FEED,
      publicationAuthority: false,
      purchaseAuthority: false,
      contractAuthority: false,
      autonomousSpendUsd: 0,
      copiesSupplierListingText: false,
      reusesSupplierImages: false,
      requiresAllowedFeed: true,
      requiresConfirmedStock: true,
      requiresPositiveUnitEconomics: true,
      revenueRule: "verified_orders_and_settlements_only"
    });
  }
  if (url.pathname === "/product-commerce/status" && request.method === "GET") {
    if (!authorized(request, env)) return Response.json({ ok: false, error: "unauthorized" }, { status: 401 });
    return Response.json(await status(env));
  }
  if (url.pathname === "/product-commerce/run" && request.method === "POST") {
    if (!authorized(request, env)) return Response.json({ ok: false, error: "unauthorized" }, { status: 401 });
    return Response.json(await runProductCommerceRadar(env));
  }
  return null;
}
