const VERSION = "1.1-supplier-market-launch-evolving";
const API_BASE = "https://api.tiendanube.com/v1";
const DEFAULT_FIXED_SHIPPING_ARS = 9999.99;
const DEFAULT_PAYMENT_FEE_PCT = 8;
const DEFAULT_RISK_RESERVE_PCT = 3;
const DEFAULT_MIN_MARGIN_PCT = 18;
const MAX_BENCHMARK_AGE_DAYS = 7;
const MAX_AUTOMATIC_BENCHMARK_AGE_HOURS = 48;
const MIN_AUTOMATIC_MARKET_SAMPLES = 2;
const EVOLUTION_CANDIDATE_LIMIT = 25;

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

function safeJson(value, fallback = {}) {
  try { return JSON.parse(value || "null") ?? fallback; } catch { return fallback; }
}

function authorized(request, env) {
  const expected = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const supplied = clean(request.headers.get("x-lumen-admin"), 500);
  return Boolean(expected && supplied && expected === supplied);
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
    minMarginPct: clamp(env?.LUMEN_LAUNCH_MIN_MARGIN_PCT || DEFAULT_MIN_MARGIN_PCT, 1, 60),
    userAgent: clean(env?.TIENDANUBE_USER_AGENT || "LUMEN Commerce (43575)", 300)
  };
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_supplier_market_benchmarks (sku TEXT PRIMARY KEY,title TEXT,market_min REAL NOT NULL,market_median REAL NOT NULL,market_max REAL NOT NULL,sample_count INTEGER NOT NULL,observed_at TEXT NOT NULL,source_notes TEXT,metadata_json TEXT,updated_at TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_supplier_launches (launch_id TEXT PRIMARY KEY,store_id TEXT NOT NULL,product_id TEXT NOT NULL,variant_id TEXT NOT NULL,sku TEXT NOT NULL,title TEXT NOT NULL,launch_price REAL NOT NULL,supplier_cost REAL NOT NULL,fixed_shipping REAL NOT NULL,projected_profit REAL NOT NULL,projected_margin_pct REAL NOT NULL,market_median REAL NOT NULL,market_sample_count INTEGER NOT NULL,approved_by TEXT NOT NULL,approval_note TEXT NOT NULL,state TEXT NOT NULL,created_at TEXT NOT NULL,metadata_json TEXT)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_supplier_launches_state ON lumen_supplier_launches(state,created_at DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_supplier_launch_queue (sku TEXT PRIMARY KEY,title TEXT,store_id TEXT,product_id TEXT,variant_id TEXT,launch_price REAL NOT NULL DEFAULT 0,projected_profit REAL NOT NULL DEFAULT 0,projected_margin_pct REAL NOT NULL DEFAULT 0,market_median REAL NOT NULL DEFAULT 0,market_sample_count INTEGER NOT NULL DEFAULT 0,rank_score REAL NOT NULL DEFAULT 0,state TEXT NOT NULL,blockers_json TEXT,metadata_json TEXT,updated_at TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_supplier_launch_queue_rank ON lumen_supplier_launch_queue(state,rank_score DESC,updated_at DESC)")
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

export function computeSupplierLaunchEconomics(cost, launchPrice, cfg) {
  const totalRate = (cfg.paymentFeePct + cfg.riskReservePct) / 100;
  const projectedProfit = launchPrice * (1 - totalRate) - cost - cfg.fixedShippingArs;
  const projectedMarginPct = launchPrice > 0 ? projectedProfit / launchPrice * 100 : 0;
  const minimumLaunchPrice = (cost + cfg.fixedShippingArs) / Math.max(0.01, 1 - totalRate - cfg.minMarginPct / 100);
  return {
    projectedProfit: Number(projectedProfit.toFixed(2)),
    projectedMarginPct: Number(projectedMarginPct.toFixed(2)),
    minimumLaunchPrice: Number(minimumLaunchPrice.toFixed(2)),
    paymentFeePct: cfg.paymentFeePct,
    riskReservePct: cfg.riskReservePct,
    fixedShippingArs: cfg.fixedShippingArs,
    minMarginPct: cfg.minMarginPct
  };
}

async function writeBenchmark(env, body, options = {}) {
  await ensureSchema(env);
  const sku = clean(body?.sku, 160);
  const title = clean(body?.title, 260);
  const marketMin = Math.max(0, num(body?.marketMin));
  const marketMedian = Math.max(0, num(body?.marketMedian));
  const marketMax = Math.max(0, num(body?.marketMax));
  const sampleCount = Math.max(0, Math.floor(num(body?.sampleCount)));
  const observedAt = clean(body?.observedAt || new Date().toISOString(), 80);
  const sourceNotes = clean(body?.sourceNotes, 2000);
  const source = clean(options?.source || "human_verified_public_market_snapshot", 160);
  const automatic = Boolean(options?.automatic);
  if (!sku || !(marketMedian > 0) || sampleCount < 2) return { ok: false, error: "invalid_benchmark" };
  const observedMs = Date.parse(observedAt);
  if (!Number.isFinite(observedMs)) return { ok: false, error: "invalid_observed_at" };

  const existing = await env.DB.prepare("SELECT observed_at,metadata_json FROM lumen_supplier_market_benchmarks WHERE sku=? LIMIT 1").bind(sku).first();
  if (automatic && existing) {
    const existingObservedMs = Date.parse(String(existing.observed_at || ""));
    const existingMeta = safeJson(existing.metadata_json, {});
    const existingAgeMs = Number.isFinite(existingObservedMs) ? Date.now() - existingObservedMs : Number.POSITIVE_INFINITY;
    if (clean(existingMeta?.source, 160) === "human_verified_public_market_snapshot" && existingAgeMs <= MAX_BENCHMARK_AGE_DAYS * 86400000) {
      return { ok: true, skipped: true, reason: "fresh_human_benchmark_preserved", sku };
    }
    if (Number.isFinite(existingObservedMs) && existingObservedMs > observedMs) {
      return { ok: true, skipped: true, reason: "newer_benchmark_preserved", sku };
    }
  }

  const now = new Date().toISOString();
  await env.DB.prepare("INSERT INTO lumen_supplier_market_benchmarks(sku,title,market_min,market_median,market_max,sample_count,observed_at,source_notes,metadata_json,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(sku) DO UPDATE SET title=excluded.title,market_min=excluded.market_min,market_median=excluded.market_median,market_max=excluded.market_max,sample_count=excluded.sample_count,observed_at=excluded.observed_at,source_notes=excluded.source_notes,metadata_json=excluded.metadata_json,updated_at=excluded.updated_at")
    .bind(sku, title || null, marketMin, marketMedian, marketMax, sampleCount, observedAt, sourceNotes || null, JSON.stringify({ version: VERSION, source, automatic, currency: "ARS" }), now).run();
  return { ok: true, sku, marketMedian, sampleCount, source, automatic };
}

async function upsertBenchmark(env, body) {
  return writeBenchmark(env, body, { source: "human_verified_public_market_snapshot", automatic: false });
}

export async function hydrateSupplierMarketBenchmarks(env) {
  await ensureSchema(env);
  if (!env?.DB) return { ok: false, error: "db_binding_missing", hydrated: 0 };
  const table = await env.DB.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name='lumen_commerce_catalog_drafts' LIMIT 1").first();
  if (!table) return { ok: true, hydrated: 0, skipped: true, reason: "commerce_market_evidence_not_initialized" };

  const rows = await env.DB.prepare("SELECT c.sku,c.title,c.market_min,c.market_median,c.market_max,c.market_sample_count,c.market_currency,c.updated_at FROM lumen_commerce_catalog_drafts c INNER JOIN lumen_supplier_intake_products i ON i.sku=c.sku WHERE i.stock>0 AND i.status IN ('DRAFT_READY','PUBLISHED') AND UPPER(COALESCE(c.market_currency,''))='ARS' AND c.market_median>0 AND c.market_sample_count>=? ORDER BY c.updated_at DESC LIMIT 100")
    .bind(MIN_AUTOMATIC_MARKET_SAMPLES).all();

  const maxAgeMs = MAX_AUTOMATIC_BENCHMARK_AGE_HOURS * 3600000;
  const seen = new Set();
  const results = [];
  for (const row of rows.results || []) {
    const sku = clean(row?.sku, 160);
    if (!sku || seen.has(sku)) continue;
    seen.add(sku);
    const observedMs = Date.parse(String(row?.updated_at || ""));
    if (!Number.isFinite(observedMs) || Date.now() - observedMs > maxAgeMs) {
      results.push({ sku, ok: true, skipped: true, reason: "commerce_snapshot_stale" });
      continue;
    }
    results.push(await writeBenchmark(env, {
      sku,
      title: row.title,
      marketMin: num(row.market_min) || num(row.market_median),
      marketMedian: row.market_median,
      marketMax: num(row.market_max) || num(row.market_median),
      sampleCount: row.market_sample_count,
      observedAt: row.updated_at,
      sourceNotes: "Automatic benchmark from Commerce Machine read-only public market snapshot."
    }, { source: "commerce_machine_market_snapshot", automatic: true }));
  }

  return {
    ok: true,
    source: "commerce_machine_market_snapshot",
    requiredCurrency: "ARS",
    maxAgeHours: MAX_AUTOMATIC_BENCHMARK_AGE_HOURS,
    minSamples: MIN_AUTOMATIC_MARKET_SAMPLES,
    considered: seen.size,
    hydrated: results.filter(item => item?.ok && !item?.skipped).length,
    skipped: results.filter(item => item?.skipped).length,
    results: results.slice(0, 25)
  };
}

async function evaluateSku(env, sku, requestedPrice = 0, options = {}) {
  if (!options?.schemaReady) await ensureSchema(env);
  const cfg = config(env);
  const row = await env.DB.prepare("SELECT * FROM lumen_supplier_intake_products WHERE sku=? ORDER BY stock DESC LIMIT 1").bind(sku).first();
  if (!row) return { ok: false, error: "sku_not_found" };
  const benchmark = await env.DB.prepare("SELECT * FROM lumen_supplier_market_benchmarks WHERE sku=?").bind(sku).first();
  if (!benchmark) return { ok: false, error: "market_benchmark_missing", sku };
  const ageMs = Date.now() - new Date(benchmark.observed_at).getTime();
  if (!Number.isFinite(ageMs) || ageMs > MAX_BENCHMARK_AGE_DAYS * 86400000) return { ok: false, error: "market_benchmark_stale", sku };
  const launchPrice = requestedPrice > 0 ? requestedPrice : Math.round(Math.max(num(benchmark.market_median) * 0.98, num(row.listed_price)) / 100) * 100 - 100;
  const econ = computeSupplierLaunchEconomics(num(row.supplier_cost), launchPrice, cfg);
  const marketGapPct = num(benchmark.market_median) > 0 ? (launchPrice - num(benchmark.market_median)) / num(benchmark.market_median) * 100 : 0;
  const metadata = safeJson(row.metadata_json, {});
  const blockers = [];
  if (row.status !== "DRAFT_READY" && row.status !== "PUBLISHED") blockers.push("candidate_not_ready");
  if (num(row.stock) <= 0) blockers.push("out_of_stock");
  if (metadata?.source !== "TIENDANUBE_CONNECTED_SUPPLIER") blockers.push("untrusted_supplier_source");
  if (metadata?.supplierIntegration !== "connected_tiendanube_catalog") blockers.push("supplier_integration_not_verified");
  if (metadata?.supplierAssetsAuthorizedByIntegration !== true) blockers.push("supplier_rights_not_verified");
  if (num(benchmark.sample_count) < 2) blockers.push("insufficient_market_sample");
  if (econ.projectedMarginPct + 0.01 < cfg.minMarginPct) blockers.push("margin_below_launch_floor");
  if (marketGapPct > 15) blockers.push("price_too_far_above_market_median");
  return {
    ok: true,
    sku,
    title: row.title,
    storeId: row.store_id,
    productId: row.product_id,
    variantId: row.variant_id,
    stock: row.stock,
    supplierCost: row.supplier_cost,
    launchPrice,
    benchmark: {
      marketMin: benchmark.market_min,
      marketMedian: benchmark.market_median,
      marketMax: benchmark.market_max,
      sampleCount: benchmark.sample_count,
      observedAt: benchmark.observed_at,
      sourceNotes: benchmark.source_notes,
      source: safeJson(benchmark.metadata_json, {})?.source || null
    },
    economics: econ,
    marketGapPct: Number(marketGapPct.toFixed(2)),
    blockers,
    launchable: blockers.length === 0,
    authorityEvidence: {
      connectedSupplier: metadata?.supplierIntegration === "connected_tiendanube_catalog",
      supplierAssetsAuthorizedByIntegration: metadata?.supplierAssetsAuthorizedByIntegration === true
    }
  };
}

async function refreshLiveSupplier(env, connection, evaluation) {
  const product = await apiRequest(env, connection, `/products/${encodeURIComponent(evaluation.productId)}`);
  const variants = Array.isArray(product?.variants) ? product.variants : [];
  const variant = variants.find(item => String(item?.id || "") === String(evaluation.variantId || ""));
  if (!variant) return { ...evaluation, launchable: false, blockers: [...evaluation.blockers, "supplier_variant_missing_live"] };
  const freshStock = Math.max(0, Math.floor(num(variant?.stock)));
  const freshCost = Math.max(0, num(variant?.cost));
  const blockers = [...evaluation.blockers];
  if (freshStock <= 0) blockers.push("supplier_stock_not_live");
  if (!(freshCost > 0)) blockers.push("supplier_cost_not_live");
  const econ = computeSupplierLaunchEconomics(freshCost || evaluation.supplierCost, evaluation.launchPrice, config(env));
  if (!(econ.projectedProfit > 0)) blockers.push("live_non_positive_net_profit");
  if (econ.projectedMarginPct + 0.01 < config(env).minMarginPct) blockers.push("live_margin_below_launch_floor");
  return {
    ...evaluation,
    stock: freshStock,
    supplierCost: freshCost || evaluation.supplierCost,
    economics: econ,
    blockers: [...new Set(blockers)],
    launchable: [...new Set(blockers)].length === 0
  };
}

export function rankSupplierLaunchCandidate(evaluation) {
  if (!evaluation?.ok || !evaluation?.launchable) return 0;
  const samples = Math.max(0, num(evaluation?.benchmark?.sampleCount));
  const confidence = clamp(samples / 5, 0.4, 1);
  const marginMultiplier = 1 + clamp(evaluation?.economics?.projectedMarginPct, 0, 60) / 100;
  return Number((Math.max(0, num(evaluation?.economics?.projectedProfit)) * confidence * marginMultiplier).toFixed(2));
}

export async function runSupplierMarketLaunchEvolution(env) {
  if (!env?.DB) return { ok: false, skipped: true, reason: "missing_db", version: VERSION };
  await ensureSchema(env);
  const hydration = await hydrateSupplierMarketBenchmarks(env);
  const connection = await getConnection(env);
  if (!connection) return { ok: true, skipped: true, reason: "tiendanube_not_connected", version: VERSION, hydration };
  const rows = await env.DB.prepare("SELECT DISTINCT sku FROM lumen_supplier_intake_products WHERE sku IS NOT NULL AND TRIM(sku)<>'' AND stock>0 AND status='DRAFT_READY' ORDER BY sku LIMIT ?")
    .bind(EVOLUTION_CANDIDATE_LIMIT).all();

  const evaluations = [];
  const now = new Date().toISOString();
  for (const row of rows.results || []) {
    const sku = clean(row?.sku, 160);
    if (!sku) continue;
    let evaluation = await evaluateSku(env, sku, 0, { schemaReady: true });
    if (evaluation?.ok && evaluation?.launchable) {
      try { evaluation = await refreshLiveSupplier(env, connection, evaluation); }
      catch (error) { evaluation = { ...evaluation, launchable: false, blockers: [...(evaluation.blockers || []), `live_revalidation_failed:${clean(error, 120)}`] }; }
    }
    const rankScore = rankSupplierLaunchCandidate(evaluation);
    const state = evaluation?.ok && evaluation?.launchable ? "HUMAN_APPROVAL_REQUIRED" : "BLOCKED";
    const blockers = evaluation?.blockers || (evaluation?.error ? [evaluation.error] : ["unknown"]);
    await env.DB.prepare("INSERT INTO lumen_supplier_launch_queue(sku,title,store_id,product_id,variant_id,launch_price,projected_profit,projected_margin_pct,market_median,market_sample_count,rank_score,state,blockers_json,metadata_json,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(sku) DO UPDATE SET title=excluded.title,store_id=excluded.store_id,product_id=excluded.product_id,variant_id=excluded.variant_id,launch_price=excluded.launch_price,projected_profit=excluded.projected_profit,projected_margin_pct=excluded.projected_margin_pct,market_median=excluded.market_median,market_sample_count=excluded.market_sample_count,rank_score=excluded.rank_score,state=excluded.state,blockers_json=excluded.blockers_json,metadata_json=excluded.metadata_json,updated_at=excluded.updated_at")
      .bind(
        sku,
        evaluation?.title || null,
        evaluation?.storeId || null,
        evaluation?.productId || null,
        evaluation?.variantId || null,
        num(evaluation?.launchPrice),
        num(evaluation?.economics?.projectedProfit),
        num(evaluation?.economics?.projectedMarginPct),
        num(evaluation?.benchmark?.marketMedian),
        Math.floor(num(evaluation?.benchmark?.sampleCount)),
        rankScore,
        state,
        JSON.stringify(blockers),
        JSON.stringify({ version: VERSION, benchmarkSource: evaluation?.benchmark?.source || null, nextAction: state === "HUMAN_APPROVAL_REQUIRED" ? "EXPLICIT_HUMAN_APPROVAL_TO_PUBLISH" : "IMPROVE_EVIDENCE_OR_ECONOMICS", supplierRightsVerified: evaluation?.authorityEvidence?.supplierAssetsAuthorizedByIntegration === true, liveStockRevalidated: Boolean(evaluation?.ok && evaluation?.stock > 0), externalWriteExecuted: false }),
        now
      ).run();
    evaluations.push({ ...evaluation, rankScore, state });
  }

  const shortlist = evaluations
    .filter(item => item?.ok && item?.launchable)
    .sort((a, b) => b.rankScore - a.rankScore)
    .slice(0, 10)
    .map(item => ({
      sku: item.sku,
      title: item.title,
      launchPrice: item.launchPrice,
      projectedProfit: item.economics.projectedProfit,
      projectedMarginPct: item.economics.projectedMarginPct,
      marketMedian: item.benchmark.marketMedian,
      marketSampleCount: item.benchmark.sampleCount,
      benchmarkSource: item.benchmark.source,
      rankScore: item.rankScore,
      state: "HUMAN_APPROVAL_REQUIRED",
      nextAction: "EXPLICIT_HUMAN_APPROVAL_TO_PUBLISH"
    }));

  return {
    ok: true,
    version: VERSION,
    mode: "AUTOMATIC_INTERMEDIARY_EVALUATION_HUMAN_GATED_PUBLICATION",
    hydration,
    evaluated: evaluations.length,
    launchable: shortlist.length,
    shortlist,
    authority: {
      connectedSupplierOnly: true,
      supplierRightsRequired: true,
      liveStockRevalidation: true,
      positiveNetMarginRequired: true,
      autonomousPublishing: false,
      autonomousPurchasing: false,
      autonomousContracts: false,
      autonomousSpendUsd: 0,
      bindingActionsHumanGated: true
    }
  };
}

async function executeLaunch(env, body) {
  const sku = clean(body?.sku, 160);
  const approvedBy = clean(body?.approvedBy, 120);
  const approvalNote = clean(body?.approvalNote, 500);
  const requestedPrice = Math.max(0, num(body?.launchPrice));
  if (!sku || !approvedBy || !approvalNote) return { ok: false, error: "explicit_human_approval_required" };
  let evaluation = await evaluateSku(env, sku, requestedPrice);
  if (!evaluation.ok || !evaluation.launchable) return { ...evaluation, externalWriteExecuted: false };
  const connection = await getConnection(env, evaluation.storeId);
  if (!connection) return { ok: false, error: "tiendanube_not_connected", externalWriteExecuted: false };
  evaluation = await refreshLiveSupplier(env, connection, evaluation);
  if (!evaluation.launchable) return { ...evaluation, externalWriteExecuted: false };

  await apiRequest(env, connection, `/products/${encodeURIComponent(evaluation.productId)}/variants/${encodeURIComponent(evaluation.variantId)}`, {
    method: "PUT",
    body: JSON.stringify({ price: String(evaluation.launchPrice) })
  });
  await apiRequest(env, connection, `/products/${encodeURIComponent(evaluation.productId)}`, {
    method: "PUT",
    body: JSON.stringify({ visibility: "visible", free_shipping: true })
  });

  const now = new Date().toISOString();
  await env.DB.prepare("UPDATE lumen_supplier_intake_products SET live_allowed=1,status='PUBLISHED',listed_price=?,visibility='visible',last_seen_at=? WHERE store_id=? AND product_id=?")
    .bind(evaluation.launchPrice, now, evaluation.storeId, evaluation.productId).run();
  await env.DB.prepare("UPDATE lumen_product_candidates SET status='PUBLISHED',candidate_sell_price=?,updated_at=? WHERE sku=? AND status='DRAFT_READY'")
    .bind(evaluation.launchPrice, now, sku).run();
  await env.DB.prepare("UPDATE lumen_supplier_launch_queue SET state='LIVE',updated_at=? WHERE sku=?").bind(now, sku).run();
  const launchId = `SL-${Date.now()}-${sku}`.replace(/[^a-z0-9_-]+/gi, "-").slice(0, 220);
  await env.DB.prepare("INSERT INTO lumen_supplier_launches(launch_id,store_id,product_id,variant_id,sku,title,launch_price,supplier_cost,fixed_shipping,projected_profit,projected_margin_pct,market_median,market_sample_count,approved_by,approval_note,state,created_at,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
    .bind(launchId, evaluation.storeId, evaluation.productId, evaluation.variantId, sku, evaluation.title, evaluation.launchPrice, evaluation.supplierCost, evaluation.economics.fixedShippingArs, evaluation.economics.projectedProfit, evaluation.economics.projectedMarginPct, evaluation.benchmark.marketMedian, evaluation.benchmark.sampleCount, approvedBy, approvalNote, "LIVE", now, JSON.stringify({ version: VERSION, freeShipping: true, benchmark: evaluation.benchmark, externalWriteExecuted: true, mode: "EXPLICIT_HUMAN_APPROVAL" })).run();
  return { ...evaluation, launchId, state: "LIVE", externalWriteExecuted: true, freeShipping: true };
}

async function status(env) {
  await ensureSchema(env);
  const rows = await env.DB.prepare("SELECT i.sku,i.title,i.supplier_cost,i.listed_price,i.stock,i.status,i.visibility,b.market_min,b.market_median,b.market_max,b.sample_count,b.observed_at,q.launch_price,q.projected_profit,q.projected_margin_pct,q.rank_score,q.state AS launch_queue_state,q.updated_at AS launch_queue_updated_at FROM lumen_supplier_intake_products i LEFT JOIN lumen_supplier_market_benchmarks b ON b.sku=i.sku LEFT JOIN lumen_supplier_launch_queue q ON q.sku=i.sku WHERE i.sku IS NOT NULL GROUP BY i.sku ORDER BY COALESCE(q.rank_score,0) DESC,i.score DESC,i.stock DESC LIMIT 50").all();
  const launches = await env.DB.prepare("SELECT launch_id,sku,title,launch_price,projected_profit,projected_margin_pct,state,created_at FROM lumen_supplier_launches ORDER BY created_at DESC LIMIT 20").all();
  return { ok: true, version: VERSION, candidates: rows.results || [], launches: launches.results || [], authority: { publish: "EXPLICIT_ADMIN_HUMAN_APPROVAL_ONLY", purchase: false, spendUsd: 0, contract: false } };
}

export async function handleSupplierMarketLaunch(request, env) {
  const url = new URL(request.url);
  if (url.pathname === "/supplier-launch/policy" && request.method === "GET") {
    const cfg = config(env);
    return Response.json({
      ok: true,
      version: VERSION,
      mode: "AUTOMATIC_INTERMEDIARY_EVALUATION_HUMAN_GATED_PUBLICATION",
      fixedShippingArs: cfg.fixedShippingArs,
      paymentFeePct: cfg.paymentFeePct,
      riskReservePct: cfg.riskReservePct,
      minMarginPct: cfg.minMarginPct,
      freeShippingOnLaunch: true,
      maxBenchmarkAgeDays: MAX_BENCHMARK_AGE_DAYS,
      automaticBenchmarkHydration: true,
      automaticBenchmarkSource: "commerce_machine_market_snapshot",
      automaticBenchmarkRequiredCurrency: "ARS",
      automaticBenchmarkMaxAgeHours: MAX_AUTOMATIC_BENCHMARK_AGE_HOURS,
      automaticBenchmarkMinSamples: MIN_AUTOMATIC_MARKET_SAMPLES,
      automaticCandidateEvaluation: true,
      rankingObjective: "projected_net_margin_with_market_confidence",
      connectedSupplierOnly: true,
      supplierRightsRequired: true,
      liveStockRevalidation: true,
      positiveNetMarginRequired: true,
      autonomousPublishing: false,
      autonomousPurchasing: false,
      autonomousSpendUsd: 0,
      autonomousContracts: false,
      bindingActionsHumanGated: true,
      explicitHumanApprovalRequired: true
    });
  }
  if (url.pathname === "/supplier-launch/status" && request.method === "GET") {
    if (!authorized(request, env)) return Response.json({ ok: false, error: "unauthorized" }, { status: 401 });
    try { return Response.json(await status(env)); }
    catch (error) { return Response.json({ ok: false, error: clean(error, 500) }, { status: 400 }); }
  }
  if (url.pathname === "/supplier-launch/benchmark" && request.method === "POST") {
    if (!authorized(request, env)) return Response.json({ ok: false, error: "unauthorized" }, { status: 401 });
    let body = {};
    try { body = await request.json(); } catch {}
    try { return Response.json(await upsertBenchmark(env, body)); }
    catch (error) { return Response.json({ ok: false, error: clean(error, 500) }, { status: 400 }); }
  }
  if (url.pathname === "/supplier-launch/evaluate" && request.method === "POST") {
    if (!authorized(request, env)) return Response.json({ ok: false, error: "unauthorized" }, { status: 401 });
    let body = {};
    try { body = await request.json(); } catch {}
    try { return Response.json(await evaluateSku(env, clean(body?.sku, 160), Math.max(0, num(body?.launchPrice)))); }
    catch (error) { return Response.json({ ok: false, error: clean(error, 500) }, { status: 400 }); }
  }
  if (url.pathname === "/supplier-launch/evolve" && request.method === "POST") {
    if (!authorized(request, env)) return Response.json({ ok: false, error: "unauthorized" }, { status: 401 });
    try { return Response.json(await runSupplierMarketLaunchEvolution(env)); }
    catch (error) { return Response.json({ ok: false, error: clean(error, 500), externalWriteExecuted: false }, { status: 400 }); }
  }
  if (url.pathname === "/supplier-launch/execute" && request.method === "POST") {
    if (!authorized(request, env)) return Response.json({ ok: false, error: "unauthorized" }, { status: 401 });
    let body = {};
    try { body = await request.json(); } catch {}
    try { return Response.json(await executeLaunch(env, body)); }
    catch (error) { return Response.json({ ok: false, error: clean(error, 500), externalWriteExecuted: false }, { status: 400 }); }
  }
  return null;
}
