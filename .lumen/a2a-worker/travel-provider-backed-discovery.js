import { calculateTravelOptions, TRAVEL_CONSUMER_DESTINATIONS } from "./travel-consumer-engine.js";
import { quoteTravelComponents, TRAVEL_PROVIDER_CONTRACT_VERSION } from "./travel-provider-registry.js";

const VERSION = "1.1-travel-provider-backed-discovery";
const DISCOVERY_ENGINE_VERSION = "1.0-travel-consumer-discovery";
const PROVIDER_REGISTRY_VERSION = "1.1-travel-provider-registry";

function clean(value, limit = 500) {
  return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit);
}

function json(data, status = 200) {
  return Response.json(data, {
    status,
    headers: {
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "access-control-allow-origin": "*",
      "access-control-allow-headers": "content-type",
      "access-control-allow-methods": "GET,POST,OPTIONS"
    }
  });
}

function quoteByComponent(bundle, component) {
  return bundle?.quotes?.find(quote => quote.component === component) || null;
}

function providerPricingMode(bundle) {
  const modes = [...new Set((bundle?.quotes || []).map(quote => clean(quote.providerMode, 60)).filter(Boolean))];
  if (!modes.length) return "UNKNOWN";
  return modes.length === 1 ? modes[0] : "MIXED";
}

function providerConfidence(bundle) {
  const quotes = bundle?.quotes || [];
  if (!quotes.length) return 0.25;
  const amount = quotes.reduce((sum, quote) => sum + Math.max(0, Number(quote.amountUSD || 0)), 0);
  if (amount <= 0) return Number((quotes.reduce((sum, q) => sum + Number(q.confidence || 0.25), 0) / quotes.length).toFixed(2));
  const weighted = quotes.reduce((sum, quote) => sum + Math.max(0, Number(quote.amountUSD || 0)) * Number(quote.confidence || 0.25), 0) / amount;
  return Number(Math.max(0.25, Math.min(0.95, weighted)).toFixed(2));
}

function pricedDestinationFromBundle(destination, bundle) {
  const flight = quoteByComponent(bundle, "FLIGHT");
  const accommodation = quoteByComponent(bundle, "ACCOMMODATION");
  const activities = quoteByComponent(bundle, "ACTIVITIES");
  if (!flight || !accommodation || !activities) return null;
  const originCode = bundle.input.originCode;
  const existingRoute = destination.routes?.[originCode];
  if (!existingRoute) return null;

  return {
    ...destination,
    hotelNightUSD: Number(accommodation.unitAmountUSD),
    activityDailyUSD: Number(activities.unitAmountUSD),
    routes: {
      ...destination.routes,
      [originCode]: { ...existingRoute, avgFlightUSD: Number(flight.unitAmountUSD) }
    }
  };
}

function attachProviderEvidence(option, bundle) {
  const quotedComponentsUSD = Number(bundle?.totals?.quotedComponentsUSD || 0);
  const totalUSD = Math.max(1, Number(option?.breakdown?.totalUSD || 0));
  const confidence = providerConfidence(bundle);
  const components = (bundle?.quotes || []).map(quote => ({
    component: quote.component,
    providerId: quote.providerId,
    providerName: quote.providerName,
    providerMode: quote.providerMode,
    amountUSD: quote.amountUSD,
    unitAmountUSD: quote.unitAmountUSD,
    quantity: quote.quantity,
    confidence: quote.confidence,
    isRealtime: quote.isRealtime,
    bookable: quote.bookable,
    affiliateEligible: quote.affiliateEligible,
    affiliateUrl: quote.affiliateUrl,
    retrievedAt: quote.retrievedAt,
    expiresAt: quote.expiresAt,
    sourceReference: quote.sourceReference,
    evidence: quote.evidence || null,
    fallbackFromProviderId: quote.fallbackFromProviderId || null,
    fallbackReason: quote.fallbackReason || null
  }));

  return {
    ...option,
    confidenceLevel: Number(((confidence * 0.8) + (Number(option.confidenceLevel || 0.25) * 0.2)).toFixed(2)),
    pricingMode: providerPricingMode(bundle),
    realTimeFare: components.length > 0 && components.every(component => component.isRealtime === true),
    bookingAvailable: components.length > 0 && components.every(component => component.bookable === true),
    affiliateLinksAvailable: components.some(component => Boolean(component.affiliateUrl)),
    providerBacked: true,
    providerPricing: {
      registryVersion: PROVIDER_REGISTRY_VERSION,
      contractVersion: TRAVEL_PROVIDER_CONTRACT_VERSION,
      pricingMode: providerPricingMode(bundle),
      quotedComponentsUSD,
      quotedShareOfTrip: Number(Math.min(1, quotedComponentsUSD / totalUSD).toFixed(3)),
      unquotedComponents: ["TRANSFERS", "FOOD_AND_DAILY_EXPENSES"],
      components,
      fallbacks: bundle?.fallbacks || [],
      allRealtime: components.length > 0 && components.every(component => component.isRealtime === true),
      anyAffiliateLink: components.some(component => Boolean(component.affiliateUrl)),
      anyBookable: components.some(component => component.bookable === true),
      externalNetworkCalls: Boolean(bundle?.guardrails?.externalNetworkCalls)
    }
  };
}

export async function calculateProviderBackedTravelOptions(rawInput, destinationDataset = TRAVEL_CONSUMER_DESTINATIONS, env = {}, fetchImpl = fetch) {
  const validation = calculateTravelOptions(rawInput, []);
  if (!validation.ok) {
    return {
      ...validation,
      version: VERSION,
      discoveryEngineVersion: DISCOVERY_ENGINE_VERSION,
      providerRegistryVersion: PROVIDER_REGISTRY_VERSION,
      providerBacked: true,
      providerErrors: []
    };
  }

  const input = validation.input;
  const pricedDestinations = [];
  const bundles = new Map();
  const providerErrors = [];

  for (const destination of destinationDataset) {
    if (!destination?.routes?.[input.originCode]) continue;
    const bundle = await quoteTravelComponents({
      originCode: input.originCode,
      destinationCode: destination.code,
      durationDays: input.durationDays,
      targetMonth: input.targetMonth,
      travelersCount: input.travelersCount
    }, destinationDataset, env, fetchImpl);

    if (!bundle.ok) {
      providerErrors.push({ destinationCode: destination.code, errors: bundle.errors || ["provider_quote_failed"] });
      continue;
    }

    const pricedDestination = pricedDestinationFromBundle(destination, bundle);
    if (!pricedDestination) {
      providerErrors.push({ destinationCode: destination.code, errors: ["incomplete_provider_components"] });
      continue;
    }

    pricedDestinations.push(pricedDestination);
    bundles.set(destination.code, bundle);
  }

  const ranked = calculateTravelOptions(input, pricedDestinations);
  const options = ranked.options.map(option => attachProviderEvidence(option, bundles.get(option.destinationCode)));
  const modes = [...new Set(options.map(option => option.pricingMode).filter(Boolean))];

  return {
    ...ranked,
    options,
    version: VERSION,
    discoveryEngineVersion: DISCOVERY_ENGINE_VERSION,
    providerRegistryVersion: PROVIDER_REGISTRY_VERSION,
    providerContractVersion: TRAVEL_PROVIDER_CONTRACT_VERSION,
    providerBacked: true,
    providerErrors,
    pricingMode: modes.length === 1 ? modes[0] : modes.length > 1 ? "MIXED" : "UNKNOWN",
    realTimeCoverage: options.length > 0 && options.every(option => option.realTimeFare === true),
    affiliateLinksAvailable: options.some(option => option.affiliateLinksAvailable === true),
    externalProvidersUsed: options.some(option => option.providerPricing?.externalNetworkCalls === true)
  };
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_travel_consumer_searches (id TEXT PRIMARY KEY,created_at TEXT NOT NULL,origin_code TEXT NOT NULL,max_budget_usd REAL NOT NULL,duration_days INTEGER NOT NULL,target_month INTEGER NOT NULL,flexibility_days INTEGER NOT NULL,travelers_count INTEGER NOT NULL,preferences_json TEXT NOT NULL,result_count INTEGER NOT NULL,best_destination_code TEXT,best_lumen_score INTEGER,pricing_mode TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_travel_consumer_demand ON lumen_travel_consumer_searches(origin_code,target_month,max_budget_usd,created_at DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_travel_demand_events (id TEXT PRIMARY KEY,search_id TEXT NOT NULL,created_at TEXT NOT NULL,event_type TEXT NOT NULL,origin_code TEXT NOT NULL,target_month INTEGER NOT NULL,budget_bucket_usd INTEGER NOT NULL,preferences_json TEXT NOT NULL,result_count INTEGER NOT NULL,status TEXT NOT NULL,engine_version TEXT NOT NULL,UNIQUE(search_id,event_type))"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_travel_demand_events_status ON lumen_travel_demand_events(status,event_type,created_at DESC)")
  ]);
  return true;
}

async function persistSearch(env, result) {
  if (!(await ensureSchema(env))) return { stored: false, reason: "persistence_unavailable" };
  const id = `TRVC-${crypto.randomUUID().replaceAll("-", "").slice(0, 18).toUpperCase()}`;
  const now = new Date().toISOString();
  const best = result.options[0] || null;
  const input = result.input;
  const pricingMode = clean(result.pricingMode || best?.pricingMode || "UNKNOWN", 60) || "UNKNOWN";

  await env.DB.prepare("INSERT INTO lumen_travel_consumer_searches(id,created_at,origin_code,max_budget_usd,duration_days,target_month,flexibility_days,travelers_count,preferences_json,result_count,best_destination_code,best_lumen_score,pricing_mode,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
    .bind(id, now, input.originCode, input.maxBudgetUSD, input.durationDays, input.targetMonth, input.flexibilityDays, input.travelersCount, JSON.stringify(input.preferences), result.options.length, best?.destinationCode || null, best?.lumenScore ?? null, pricingMode, VERSION).run();

  const eventType = result.options.length ? "TRAVEL_SEARCH_SERVED" : "TRAVEL_DEMAND_UNMET";
  const bucket = Math.max(100, Math.round(input.maxBudgetUSD / 100) * 100);
  await env.DB.prepare("INSERT OR IGNORE INTO lumen_travel_demand_events(id,search_id,created_at,event_type,origin_code,target_month,budget_bucket_usd,preferences_json,result_count,status,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?)")
    .bind(`TDE-${id.slice(5)}`, id, now, eventType, input.originCode, input.targetMonth, bucket, JSON.stringify(input.preferences), result.options.length, "NEW", VERSION).run();

  return { stored: true, searchId: id, demandEvent: eventType, pricingMode };
}

export async function handleProviderBackedTravelDiscovery(request, env, destinationDataset = TRAVEL_CONSUMER_DESTINATIONS) {
  const url = new URL(request.url);

  if (request.method === "OPTIONS" && url.pathname.startsWith("/travel/discovery/")) {
    return new Response(null, { status: 204, headers: { "access-control-allow-origin": "*", "access-control-allow-headers": "content-type", "access-control-allow-methods": "GET,POST,OPTIONS" } });
  }

  if (request.method === "GET" && url.pathname === "/travel/discovery/policy") {
    return json({
      version: VERSION,
      discoveryEngineVersion: DISCOVERY_ENGINE_VERSION,
      providerRegistryVersion: PROVIDER_REGISTRY_VERSION,
      providerContractVersion: TRAVEL_PROVIDER_CONTRACT_VERSION,
      name: "LUMEN Travel Discovery",
      architecture: "discovery_via_provider_registry",
      searchUsesProviderRegistry: true,
      currentPricingMode: "DYNAMIC_PROVIDER_REGISTRY",
      providerReplacementWithoutDiscoveryRewrite: true,
      exactDatesClaimed: false,
      createsBooking: false,
      createsCharge: false,
      storesPaymentData: false,
      storesPassportData: false,
      storesIpAddress: false,
      autonomousSpend: false,
      autonomousPurchase: false,
      bindingActionsHumanGated: true,
      supportedOriginAliases: ["BUE", "EZE", "AEP"]
    });
  }

  if (request.method !== "POST" || url.pathname !== "/travel/discovery/search") return null;

  let body = {};
  try { body = await request.json(); }
  catch { return json({ ok: false, version: VERSION, error: "invalid_json" }, 400); }

  const result = await calculateProviderBackedTravelOptions(body, destinationDataset, env);
  if (!result.ok) return json(result, 400);

  let persistence = { stored: false, reason: "not_attempted" };
  try { persistence = await persistSearch(env, result); }
  catch (error) { persistence = { stored: false, reason: clean(error?.message || error, 160) || "storage_error" }; }

  return json({
    ...result,
    persistence,
    guardrails: {
      recommendationOnly: true,
      searchUsesProviderRegistry: true,
      pricingIsEstimated: result.realTimeCoverage !== true,
      realTimeFareClaim: result.realTimeCoverage === true,
      bookingCreated: false,
      chargeCreated: false,
      storesPaymentData: false,
      storesPassportData: false,
      autonomousSpend: false,
      autonomousPurchase: false,
      bindingActionsHumanGated: true
    }
  });
}
