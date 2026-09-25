const VERSION = "2.0-commerce-machine-shadow";
const MAX_CANDIDATES_PER_CYCLE = 12;
const MAX_MARKET_LOOKUPS_PER_CYCLE = 5;
const DEFAULT_FEE_PCT = 14;
const DEFAULT_LOGISTICS_PCT = 5;
const DEFAULT_MIN_MARGIN_PCT = 18;

function clean(value, limit = 3000) {
  return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit);
}

function num(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, Number(value || 0)));
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

function roundMoney(value) {
  return Math.round((Number(value) || 0) * 100) / 100;
}

export function median(values) {
  const rows = values.map(Number).filter(value => Number.isFinite(value) && value > 0).sort((a, b) => a - b);
  if (!rows.length) return 0;
  const middle = Math.floor(rows.length / 2);
  return rows.length % 2 ? rows[middle] : (rows[middle - 1] + rows[middle]) / 2;
}

export function buildCatalogCopy(candidate) {
  const title = clean(candidate?.title, 120);
  const vendor = clean(candidate?.vendor, 100);
  const sku = clean(candidate?.sku, 100);
  const gtin = clean(candidate?.gtin, 100);
  const facts = [];
  if (vendor) facts.push(`Marca / fabricante: ${vendor}.`);
  if (sku) facts.push(`SKU: ${sku}.`);
  if (gtin) facts.push(`GTIN / código universal: ${gtin}.`);
  facts.push("Producto ofrecido sujeto a disponibilidad confirmada al momento de la venta.");
  facts.push("La publicación se genera a partir de datos estructurados; no reutiliza texto promocional del proveedor.");
  return {
    title,
    description: facts.join("\n"),
    sourceCopyReused: false,
    sourceImagesReused: false
  };
}

function economicsConfig(env) {
  return {
    feePct: clamp(env?.LUMEN_COMMERCE_FEE_PCT ?? DEFAULT_FEE_PCT, 0, 40),
    logisticsPct: clamp(env?.LUMEN_COMMERCE_LOGISTICS_PCT ?? DEFAULT_LOGISTICS_PCT, 0, 40),
    minMarginPct: clamp(env?.LUMEN_COMMERCE_MIN_MARGIN_PCT ?? DEFAULT_MIN_MARGIN_PCT, 1, 70)
  };
}

export function planPrice(candidate, market = {}, config = {}) {
  const feePct = clamp(config.feePct ?? DEFAULT_FEE_PCT, 0, 40);
  const logisticsPct = clamp(config.logisticsPct ?? DEFAULT_LOGISTICS_PCT, 0, 40);
  const minMarginPct = clamp(config.minMarginPct ?? DEFAULT_MIN_MARGIN_PCT, 1, 70);
  const supplierCost = Math.max(0, num(candidate?.supplier_cost));
  const baseCandidate = Math.max(0, num(candidate?.candidate_sell_price));
  const metadata = safeJson(candidate?.metadata_json, {});
  const storedFloor = Math.max(0, num(metadata?.economics?.minimumSellPrice));
  const totalRate = (feePct + logisticsPct + minMarginPct) / 100;
  const calculatedFloor = totalRate < 0.95 && supplierCost > 0 ? supplierCost / (1 - totalRate) : 0;
  const floor = Math.max(storedFloor, calculatedFloor, supplierCost);
  const marketMedian = Math.max(0, num(market?.medianPrice));

  let recommended = Math.max(floor, baseCandidate || floor);
  let competitiveness = "UNMEASURED";
  let viable = recommended > 0;
  const reasons = [];

  if (marketMedian > 0) {
    if (floor > marketMedian * 1.05) {
      viable = false;
      competitiveness = "MARKET_TOO_TIGHT";
      reasons.push("minimum_viable_price_above_market");
    } else {
      const competitiveTarget = marketMedian * 0.98;
      recommended = Math.max(floor, Math.min(baseCandidate || competitiveTarget, competitiveTarget));
      competitiveness = recommended <= marketMedian ? "COMPETITIVE" : "ABOVE_MEDIAN";
    }
  }

  const fees = recommended * (feePct / 100);
  const logistics = recommended * (logisticsPct / 100);
  const projectedProfit = recommended - supplierCost - fees - logistics;
  const projectedMarginPct = recommended > 0 ? (projectedProfit / recommended) * 100 : 0;
  if (projectedMarginPct + 0.01 < minMarginPct) {
    viable = false;
    reasons.push("margin_below_floor");
  }

  return {
    viable,
    reasons,
    supplierCost: roundMoney(supplierCost),
    floorPrice: roundMoney(floor),
    recommendedPrice: roundMoney(recommended),
    marketMedian: roundMoney(marketMedian),
    projectedProfit: roundMoney(projectedProfit),
    projectedMarginPct: roundMoney(projectedMarginPct),
    competitiveness,
    feePct,
    logisticsPct,
    minMarginPct
  };
}

function marketQuery(candidate) {
  const gtin = clean(candidate?.gtin, 100);
  if (gtin) return gtin;
  return clean(candidate?.title, 120);
}

async function fetchJson(url, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8000);
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    if (!response.ok) throw new Error(`http_${response.status}`);
    return await response.json();
  } finally {
    clearTimeout(timeout);
  }
}

async function lookupMercadoLibre(candidate, env) {
  const token = clean(env?.MELI_ACCESS_TOKEN, 2000);
  const query = marketQuery(candidate);
  if (!token || !query) return { available: false, reason: token ? "missing_query" : "missing_token", sampleCount: 0, medianPrice: 0 };
  const url = `https://api.mercadolibre.com/sites/MLA/search?q=${encodeURIComponent(query)}&limit=20`;
  const data = await fetchJson(url, { headers: { authorization: `Bearer ${token}`, accept: "application/json" } });
  const results = Array.isArray(data?.results) ? data.results : [];
  const prices = results.map(row => num(row?.price)).filter(value => value > 0);
  return {
    available: true,
    sampleCount: prices.length,
    medianPrice: roundMoney(median(prices)),
    minPrice: prices.length ? roundMoney(Math.min(...prices)) : 0,
    maxPrice: prices.length ? roundMoney(Math.max(...prices)) : 0,
    query
  };
}

export function buildChannelPayloads(draft, candidate, pricePlan) {
  const gtin = clean(candidate?.gtin, 100);
  const sku = clean(candidate?.sku, 100);
  const currency = clean(candidate?.currency || "ARS", 10).toUpperCase();
  const safeDescriptionHtml = `<p>${draft.description.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll("\n", "<br>")}</p>`;
  return {
    mercadolibre: {
      channel: "MERCADOLIBRE",
      state: "SHADOW_DRAFT",
      publishable: false,
      blockers: ["human_approval_required", "category_resolution_required", "listing_type_cost_check_required", "image_rights_required"],
      apiGeneration: "2026-user-products-ready",
      payload: {
        title: draft.title,
        category_id: null,
        price: pricePlan.recommendedPrice,
        currency_id: currency,
        available_quantity: 1,
        attributes: [
          ...(gtin ? [{ id: "GTIN", value_name: gtin }] : []),
          { id: "ITEM_CONDITION", value_name: "Nuevo" }
        ],
        seller_custom_field: sku || undefined
      }
    },
    tiendanube: {
      channel: "TIENDANUBE",
      state: "SHADOW_DRAFT",
      publishable: false,
      blockers: ["human_approval_required", "store_capability_check_required", "image_rights_required"],
      apiGeneration: "multi-inventory-ready",
      payload: {
        name: { es: draft.title },
        description: { es: safeDescriptionHtml },
        variants: [{ price: String(pricePlan.recommendedPrice), sku: sku || null, stock_management: true, stock: 1 }]
      }
    }
  };
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_commerce_catalog_drafts (draft_id TEXT PRIMARY KEY,candidate_id TEXT NOT NULL UNIQUE,title TEXT NOT NULL,description TEXT NOT NULL,currency TEXT NOT NULL,recommended_price REAL NOT NULL,projected_profit REAL NOT NULL,projected_margin_pct REAL NOT NULL,market_median REAL NOT NULL DEFAULT 0,market_sample_count INTEGER NOT NULL DEFAULT 0,competitiveness TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,metadata_json TEXT)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_commerce_drafts_rank ON lumen_commerce_catalog_drafts(status,projected_margin_pct DESC,projected_profit DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_commerce_channel_plans (plan_id TEXT PRIMARY KEY,draft_id TEXT NOT NULL,channel TEXT NOT NULL,state TEXT NOT NULL,publishable INTEGER NOT NULL DEFAULT 0,external_id TEXT,payload_json TEXT NOT NULL,blockers_json TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,metadata_json TEXT,UNIQUE(draft_id,channel))"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_commerce_channel_plans_state ON lumen_commerce_channel_plans(channel,state,updated_at DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_commerce_shadow_runs (run_id TEXT PRIMARY KEY,started_at TEXT NOT NULL,finished_at TEXT,status TEXT NOT NULL,candidates_seen INTEGER NOT NULL DEFAULT 0,drafts_ready INTEGER NOT NULL DEFAULT 0,market_lookups INTEGER NOT NULL DEFAULT 0,rejected INTEGER NOT NULL DEFAULT 0,error TEXT,metadata_json TEXT)")
  ]);
  return true;
}

async function persistDraft(env, candidate, copy, pricePlan, market) {
  const now = new Date().toISOString();
  const draftId = `CD-${clean(candidate.candidate_id, 150)}`;
  const status = pricePlan.viable ? "SHADOW_READY" : "SHADOW_REJECTED";
  await env.DB.prepare("INSERT INTO lumen_commerce_catalog_drafts(draft_id,candidate_id,title,description,currency,recommended_price,projected_profit,projected_margin_pct,market_median,market_sample_count,competitiveness,status,created_at,updated_at,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(candidate_id) DO UPDATE SET title=excluded.title,description=excluded.description,currency=excluded.currency,recommended_price=excluded.recommended_price,projected_profit=excluded.projected_profit,projected_margin_pct=excluded.projected_margin_pct,market_median=excluded.market_median,market_sample_count=excluded.market_sample_count,competitiveness=excluded.competitiveness,status=CASE WHEN lumen_commerce_catalog_drafts.status IN ('APPROVED','PUBLISHED','SOLD') THEN lumen_commerce_catalog_drafts.status ELSE excluded.status END,updated_at=excluded.updated_at,metadata_json=excluded.metadata_json")
    .bind(draftId, candidate.candidate_id, copy.title, copy.description, candidate.currency || "ARS", pricePlan.recommendedPrice, pricePlan.projectedProfit, pricePlan.projectedMarginPct, pricePlan.marketMedian, market.sampleCount || 0, pricePlan.competitiveness, status, now, now, JSON.stringify({ version: VERSION, pricePlan, market, sourceCopyReused: false, sourceImagesReused: false }))
    .run();
  return { draftId, status };
}

async function persistChannelPlans(env, draftId, plans) {
  const now = new Date().toISOString();
  for (const plan of Object.values(plans)) {
    const planId = `CP-${draftId}-${plan.channel}`.slice(0, 220);
    await env.DB.prepare("INSERT INTO lumen_commerce_channel_plans(plan_id,draft_id,channel,state,publishable,payload_json,blockers_json,created_at,updated_at,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(draft_id,channel) DO UPDATE SET state=CASE WHEN lumen_commerce_channel_plans.state IN ('APPROVED','PUBLISHED','SOLD') THEN lumen_commerce_channel_plans.state ELSE excluded.state END,publishable=CASE WHEN lumen_commerce_channel_plans.state IN ('APPROVED','PUBLISHED','SOLD') THEN lumen_commerce_channel_plans.publishable ELSE excluded.publishable END,payload_json=excluded.payload_json,blockers_json=excluded.blockers_json,updated_at=excluded.updated_at,metadata_json=excluded.metadata_json")
      .bind(planId, draftId, plan.channel, plan.state, plan.publishable ? 1 : 0, JSON.stringify(plan.payload), JSON.stringify(plan.blockers), now, now, JSON.stringify({ version: VERSION, apiGeneration: plan.apiGeneration }))
      .run();
  }
}

export async function runCommerceMachine(env) {
  if (!env?.DB) return { ok: false, skipped: true, reason: "missing_db" };
  await ensureSchema(env);
  const startedAt = new Date().toISOString();
  const runId = `CM-${Date.now()}`;
  await env.DB.prepare("INSERT INTO lumen_commerce_shadow_runs(run_id,started_at,status,metadata_json) VALUES(?,?,?,?)")
    .bind(runId, startedAt, "RUNNING", JSON.stringify({ version: VERSION, mode: "shadow" })).run();

  let rows = [];
  try {
    const result = await env.DB.prepare("SELECT candidate_id,feed_id,title,vendor,sku,gtin,currency,supplier_cost,market_anchor,candidate_sell_price,projected_profit,projected_margin_pct,score,status,source_url,metadata_json FROM lumen_product_candidates WHERE status='DRAFT_READY' ORDER BY score DESC,projected_margin_pct DESC LIMIT ?")
      .bind(MAX_CANDIDATES_PER_CYCLE).all();
    rows = result.results || [];
  } catch (error) {
    const finishedAt = new Date().toISOString();
    await env.DB.prepare("UPDATE lumen_commerce_shadow_runs SET finished_at=?,status='FAILED',error=? WHERE run_id=?").bind(finishedAt, clean(error, 500), runId).run();
    return { ok: false, status: "FAILED", runId, error: clean(error, 500) };
  }

  const config = economicsConfig(env);
  let marketLookups = 0;
  let draftsReady = 0;
  let rejected = 0;
  const errors = [];

  for (const candidate of rows) {
    let market = { available: false, reason: "lookup_budget_not_used", sampleCount: 0, medianPrice: 0 };
    if (marketLookups < MAX_MARKET_LOOKUPS_PER_CYCLE && env?.MELI_ACCESS_TOKEN) {
      try {
        market = await lookupMercadoLibre(candidate, env);
        marketLookups += 1;
      } catch (error) {
        marketLookups += 1;
        market = { available: false, reason: clean(error, 200), sampleCount: 0, medianPrice: 0 };
        errors.push({ candidateId: candidate.candidate_id, stage: "market_lookup", error: clean(error, 200) });
      }
    }
    const copy = buildCatalogCopy(candidate);
    const pricePlan = planPrice(candidate, market, config);
    const persisted = await persistDraft(env, candidate, copy, pricePlan, market);
    if (pricePlan.viable) {
      const plans = buildChannelPayloads(copy, candidate, pricePlan);
      await persistChannelPlans(env, persisted.draftId, plans);
      draftsReady += 1;
    } else {
      rejected += 1;
    }
  }

  const finishedAt = new Date().toISOString();
  const status = errors.length ? "PARTIAL" : "SUCCESS";
  await env.DB.prepare("UPDATE lumen_commerce_shadow_runs SET finished_at=?,status=?,candidates_seen=?,drafts_ready=?,market_lookups=?,rejected=?,error=?,metadata_json=? WHERE run_id=?")
    .bind(finishedAt, status, rows.length, draftsReady, marketLookups, rejected, errors.length ? JSON.stringify(errors) : null, JSON.stringify({ version: VERSION, config, authority: { publish: false, purchase: false, spendUsd: 0 } }), runId).run();
  return { ok: true, status, runId, candidatesSeen: rows.length, draftsReady, rejected, marketLookups, errors, version: VERSION };
}

async function status(env) {
  if (!env?.DB) return { ok: false, reason: "missing_db" };
  await ensureSchema(env);
  const [lastRun, counts, topDrafts] = await Promise.all([
    env.DB.prepare("SELECT * FROM lumen_commerce_shadow_runs ORDER BY started_at DESC LIMIT 1").first(),
    env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN status='SHADOW_READY' THEN 1 ELSE 0 END) shadow_ready,SUM(CASE WHEN status='SHADOW_REJECTED' THEN 1 ELSE 0 END) rejected,SUM(CASE WHEN status='APPROVED' THEN 1 ELSE 0 END) approved,SUM(CASE WHEN status='PUBLISHED' THEN 1 ELSE 0 END) published,SUM(CASE WHEN status='SOLD' THEN 1 ELSE 0 END) sold FROM lumen_commerce_catalog_drafts").first(),
    env.DB.prepare("SELECT draft_id,candidate_id,title,currency,recommended_price,projected_profit,projected_margin_pct,market_median,market_sample_count,competitiveness,status FROM lumen_commerce_catalog_drafts ORDER BY projected_profit DESC,projected_margin_pct DESC LIMIT 10").all()
  ]);
  return {
    ok: true,
    version: VERSION,
    mode: "SHADOW_COMMERCE",
    authority: { observe: true, researchPrices: true, draftCatalog: true, publish: false, purchase: false, contract: false, autonomousSpendUsd: 0 },
    lastRun: lastRun || null,
    counts: counts || {},
    topDrafts: topDrafts?.results || []
  };
}

export async function handleCommerceMachine(request, env) {
  const url = new URL(request.url);
  if (url.pathname === "/commerce-machine/policy" && request.method === "GET") {
    return Response.json({
      ok: true,
      version: VERSION,
      mode: "SHADOW_COMMERCE",
      marketIntelligence: { mercadoLibre: "read_only_when_token_present", maxLookupsPerCycle: MAX_MARKET_LOOKUPS_PER_CYCLE },
      channelsPrepared: ["MERCADOLIBRE", "TIENDANUBE"],
      publicationAuthority: false,
      purchaseAuthority: false,
      contractAuthority: false,
      autonomousSpendUsd: 0,
      sourceCopyReused: false,
      sourceImagesReused: false,
      revenueRule: "verified_sale_and_settlement_only"
    });
  }
  if (url.pathname === "/commerce-machine/status" && request.method === "GET") {
    if (!authorized(request, env)) return Response.json({ ok: false, error: "unauthorized" }, { status: 401 });
    return Response.json(await status(env));
  }
  if (url.pathname === "/commerce-machine/run" && request.method === "POST") {
    if (!authorized(request, env)) return Response.json({ ok: false, error: "unauthorized" }, { status: 401 });
    return Response.json(await runCommerceMachine(env));
  }
  return null;
}
