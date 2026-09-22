const VERSION = "1.0-revenue-expansion";

const SOURCING_SUCCESS = {
  id: "REV-SOURCING-SUCCESS",
  name: "LUMEN Sourcing Success",
  type: "success_fee_service",
  upfront_usd: 0,
  success_fee_pct: { min: 4, target: 6, max: 8 },
  fee_basis: "verified_completed_transaction_value",
  description: "LUMEN researches, verifies and compares suppliers for a concrete B2B requirement. The success fee applies only if the client completes the transaction.",
  requires_verified_demand: true,
  binding_acceptance_human_required: true
};

const SUBSCRIPTIONS = [
  { id: "REV-TENDER-RADAR-BASIC", name: "Tender Radar Basic", price_usd: 29, interval: "month", description: "Filtered public tender and procurement alerts for one category." },
  { id: "REV-TENDER-RADAR-PRO", name: "Tender Radar Pro", price_usd: 79, interval: "month", description: "Tender alerts plus buyer analysis, fit and commercial priority." },
  { id: "REV-TENDER-RADAR-PLUS", name: "Tender Radar + RFQ", price_usd: 199, interval: "month", description: "Tender alerts, analysis and non-binding RFQ preparation." },
  { id: "REV-BUYER-INTENT-FEED", name: "Buyer Intent Feed", price_usd: 99, interval: "month", description: "Evidence-backed feed of companies showing verifiable public buying signals for one category." }
];

const MACHINE_OFFERS = [
  { id: "MP-SUPPLIER-SNAPSHOT", name: "Supplier Snapshot", price_usd: 5, billing: "per_request", existing_catalog: "/machine/catalog" },
  { id: "MP-QUOTE-SANITY", name: "Quote Sanity Check", price_usd: 7, billing: "per_request", existing_catalog: "/machine/catalog" },
  { id: "MP-TENDER-SCAN", name: "Tender Quick Scan", price_usd: 9, billing: "per_request", existing_catalog: "/machine/catalog" },
  { id: "MP-SOURCING-5", name: "Supplier Shortlist 5", price_usd: 15, billing: "per_request", existing_catalog: "/machine/catalog" },
  { id: "MP-BUYER-SIGNALS", name: "Buyer Signal Scan", price_usd: 19, billing: "per_request", existing_catalog: "/machine/catalog" },
  { id: "MP-EXPORT-PULSE", name: "Export Market Pulse", price_usd: 25, billing: "per_request", existing_catalog: "/machine/catalog" }
];

function json(data, status = 200) {
  return Response.json(data, {
    status,
    headers: {
      "cache-control": status === 200 ? "public, max-age=120" : "no-store",
      "x-content-type-options": "nosniff",
      "access-control-allow-origin": "*"
    }
  });
}

function clean(value, limit = 1200) {
  return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit);
}

function catalog(origin) {
  return {
    name: "LUMEN Revenue Expansion",
    version: VERSION,
    currency: "USD",
    zero_cost_operator_budget_usd: 0,
    sourcing_success: SOURCING_SUCCESS,
    subscriptions: SUBSCRIPTIONS,
    machine_offers: MACHINE_OFFERS.map(x => ({ ...x, catalog_url: `${origin}${x.existing_catalog}` })),
    endpoints: {
      catalog: `${origin}/revenue/catalog`,
      intake: `${origin}/revenue/request`,
      a2a: `${origin}/a2a/v1`,
      machine_store: `${origin}/machine/catalog`,
      seller_catalog: `${origin}/seller/catalog`,
      payments: `${origin}/payments/status`
    },
    quote_methods: ["GetRevenueCatalog", "QuoteRevenuePlan", "QuoteSourcingSuccess"],
    truth_rule: "catalog_or_quote_is_not_a_sale; only verified settled payment or verified completed success-fee transaction counts as realized revenue",
    guardrails: {
      autonomous_outgoing_spend: false,
      autonomous_purchase: false,
      autonomous_contract: false,
      autonomous_discount: false,
      binding_actions_human_gated: true,
      verified_public_evidence_required: true
    }
  };
}

function quotePlan(plan, contextId = "") {
  const created = new Date();
  const validUntil = new Date(created.getTime() + 24 * 3600 * 1000);
  return {
    quote_id: `REVQ-${crypto.randomUUID().replaceAll("-", "").slice(0, 12).toUpperCase()}`,
    context_id: clean(contextId, 160) || null,
    item_type: "subscription",
    item_id: plan.id,
    item_name: plan.name,
    amount_usd: plan.price_usd,
    billing: `per_${plan.interval}`,
    status: "NON_BINDING_QUOTE",
    charge_created: false,
    created_at: created.toISOString(),
    valid_until: validUntil.toISOString(),
    next_action: "Submit /revenue/request or SendMessage through /a2a/v1. LUMEN verifies scope and provides the applicable collection route before activation.",
    binding_actions_human_gated: true
  };
}

function quoteSuccess(contextId = "") {
  return {
    quote_id: `REVS-${crypto.randomUUID().replaceAll("-", "").slice(0, 12).toUpperCase()}`,
    context_id: clean(contextId, 160) || null,
    item_type: "success_fee_service",
    item_id: SOURCING_SUCCESS.id,
    upfront_usd: 0,
    success_fee_pct: SOURCING_SUCCESS.success_fee_pct,
    fee_basis: SOURCING_SUCCESS.fee_basis,
    status: "NON_BINDING_COMMERCIAL_FRAMEWORK",
    charge_created: false,
    requires_verified_demand: true,
    binding_acceptance_human_required: true,
    next_action: "Submit the concrete requirement. LUMEN may research and prepare sourcing non-bindingly; any fee agreement or completed transaction remains human-confirmed."
  };
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_revenue_inquiries (id TEXT PRIMARY KEY, received_at TEXT NOT NULL, offer_id TEXT NOT NULL, company TEXT, contact TEXT, details TEXT NOT NULL, source TEXT NOT NULL, status TEXT NOT NULL, metadata TEXT)").run();
  await env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_revenue_inquiries_status ON lumen_revenue_inquiries(status,received_at)").run();
  return true;
}

async function storeInquiry(request, env) {
  if (!env?.DB) return json({ ok: false, error: "persistence_unavailable" }, 503);
  let body;
  try { body = await request.json(); } catch { return json({ ok: false, error: "invalid_json" }, 400); }
  const offerId = clean(body?.offer_id || body?.offerId, 100);
  const details = clean(body?.details, 4000);
  if (!offerId || !details) return json({ ok: false, error: "offer_id_and_details_required" }, 400);
  const validIds = new Set([SOURCING_SUCCESS.id, ...SUBSCRIPTIONS.map(x => x.id), ...MACHINE_OFFERS.map(x => x.id)]);
  if (!validIds.has(offerId)) return json({ ok: false, error: "unknown_offer_id" }, 400);
  await ensureSchema(env);
  const id = `REVIN-${crypto.randomUUID().replaceAll("-", "").slice(0, 12).toUpperCase()}`;
  await env.DB.prepare("INSERT INTO lumen_revenue_inquiries(id,received_at,offer_id,company,contact,details,source,status,metadata) VALUES(?,?,?,?,?,?,?,?,?)")
    .bind(id, new Date().toISOString(), offerId, clean(body?.company, 240), clean(body?.contact, 300), details, "revenue_expansion", "received_unverified", JSON.stringify({ category: clean(body?.category, 240), website: clean(body?.website, 300) })).run();
  return json({
    ok: true,
    inquiry_id: id,
    offer_id: offerId,
    status: "received_unverified",
    next_action: "LUMEN will verify company, scope and evidence before any commercial commitment.",
    charge_created: false,
    binding_actions_human_gated: true
  }, 202);
}

async function handleRpc(request, origin) {
  let payload;
  try { payload = await request.clone().json(); } catch { return null; }
  if (!payload || payload.jsonrpc !== "2.0") return null;
  const id = payload.id ?? null;
  const method = String(payload.method || "");
  if (method === "GetRevenueCatalog") return json({ jsonrpc: "2.0", id, result: { catalog: catalog(origin) } });
  if (method === "QuoteRevenuePlan") {
    const planId = clean(payload?.params?.planId || payload?.params?.plan_id, 100);
    const plan = SUBSCRIPTIONS.find(x => x.id === planId);
    if (!plan) return json({ jsonrpc: "2.0", id, error: { code: -32602, message: "Unknown revenue plan identifier." } });
    return json({ jsonrpc: "2.0", id, result: { quote: quotePlan(plan, payload?.params?.contextId || payload?.params?.context_id) } });
  }
  if (method === "QuoteSourcingSuccess") return json({ jsonrpc: "2.0", id, result: { quote: quoteSuccess(payload?.params?.contextId || payload?.params?.context_id) } });
  return null;
}

export async function handleRevenue(request, env) {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/revenue/catalog") return json(catalog(url.origin));
  if (request.method === "GET" && url.pathname === "/revenue/subscriptions") return json({ version: VERSION, subscriptions: SUBSCRIPTIONS, binding_actions_human_gated: true });
  if (request.method === "GET" && url.pathname === "/revenue/sourcing-success") return json({ version: VERSION, sourcing_success: SOURCING_SUCCESS, binding_actions_human_gated: true });
  if (request.method === "POST" && url.pathname === "/revenue/request") return storeInquiry(request, env);
  if (request.method === "POST" && url.pathname === "/a2a/v1") return handleRpc(request, url.origin);
  return null;
}
