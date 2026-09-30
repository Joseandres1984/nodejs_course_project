import { createExternalTravelProviders, getExternalTravelProviderStatus } from "./travel-external-providers.js";

const VERSION = "1.1-travel-provider-registry";
const CONTRACT_VERSION = "1.0";
const CURRENCY = "USD";

// Provider contract v1:
// - one adapter owns one commercial component (FLIGHT, ACCOMMODATION, ACTIVITIES)
// - quote() returns a normalized USD quote envelope
// - buildAffiliateLink() must return null until a real partner relationship is configured
// - adapters declare network/secrets/realtime/booking/affiliate capabilities
// - external adapters are opt-in via environment credentials and replace only their component

function clean(value, limit = 400) {
  return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit);
}

function clamp(value, min = 0, max = 1) {
  const n = Number(value);
  if (!Number.isFinite(n)) return min;
  return Math.max(min, Math.min(max, n));
}

function normalizeOrigin(value) {
  const origin = clean(value, 8).toUpperCase();
  if (["BUE", "EZE", "AEP"].includes(origin)) return "BUE";
  return origin;
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

function validateQuoteInput(raw = {}, destinationDataset = []) {
  const input = {
    originCode: normalizeOrigin(raw.originCode || raw.origin || ""),
    destinationCode: clean(raw.destinationCode || raw.destination || "", 8).toUpperCase(),
    durationDays: Math.round(Number(raw.durationDays ?? raw.duration)),
    targetMonth: Math.round(Number(raw.targetMonth ?? raw.month)),
    travelersCount: Math.max(1, Math.min(8, Math.round(Number(raw.travelersCount ?? 1))))
  };

  const errors = [];
  if (!input.originCode) errors.push("origin_required");
  if (!input.destinationCode) errors.push("destination_required");
  if (!Number.isInteger(input.durationDays) || input.durationDays < 1 || input.durationDays > 90) errors.push("invalid_duration");
  if (!Number.isInteger(input.targetMonth) || input.targetMonth < 1 || input.targetMonth > 12) errors.push("invalid_month");

  const destination = destinationDataset.find(x => clean(x?.code, 8).toUpperCase() === input.destinationCode) || null;
  if (input.destinationCode && !destination) errors.push("unsupported_destination");
  if (destination && !destination.routes?.[input.originCode]) errors.push("unsupported_route");

  return { input, destination, errors };
}

function quoteEnvelope(provider, component, amountUSD, unitAmountUSD, quantity, confidence, sourceReference) {
  const now = new Date().toISOString();
  return {
    component,
    providerId: provider.id,
    providerName: provider.name,
    providerMode: provider.mode,
    contractVersion: CONTRACT_VERSION,
    currency: CURRENCY,
    amountUSD: Math.round(Number(amountUSD) || 0),
    unitAmountUSD: Math.round(Number(unitAmountUSD) || 0),
    quantity: Number(quantity) || 0,
    confidence: Number(clamp(confidence, 0.25, 0.95).toFixed(2)),
    isRealtime: false,
    bookable: false,
    affiliateEligible: false,
    affiliateUrl: null,
    retrievedAt: now,
    expiresAt: null,
    sourceReference: clean(sourceReference, 300) || null
  };
}

const seedFlightProvider = {
  id: "seed-flight-v1",
  name: "LUMEN Seed Flight Estimate",
  component: "FLIGHT",
  mode: "ESTIMATED_SEED",
  supportsRealtime: false,
  supportsBooking: false,
  supportsAffiliate: false,
  externalNetworkCalls: false,
  requiresSecret: false,
  async quote({ input, destination }) {
    const route = destination.routes[input.originCode];
    const quantity = input.travelersCount;
    const amountUSD = route.avgFlightUSD * quantity;
    const confidence = 0.67 - Math.min(0.24, Number(route.volatility || 0.25) * 0.4);
    return quoteEnvelope(this, this.component, amountUSD, route.avgFlightUSD, quantity, confidence, `seed:flight:${input.originCode}-${destination.code}`);
  },
  buildAffiliateLink() { return null; }
};

const seedAccommodationProvider = {
  id: "seed-accommodation-v1",
  name: "LUMEN Seed Accommodation Estimate",
  component: "ACCOMMODATION",
  mode: "ESTIMATED_SEED",
  supportsRealtime: false,
  supportsBooking: false,
  supportsAffiliate: false,
  externalNetworkCalls: false,
  requiresSecret: false,
  async quote({ input, destination }) {
    const nights = Math.max(1, input.durationDays - 1);
    const rooms = Math.max(1, Math.ceil(input.travelersCount / 2));
    const roomNights = nights * rooms;
    const amountUSD = destination.hotelNightUSD * roomNights;
    return quoteEnvelope(this, this.component, amountUSD, destination.hotelNightUSD, roomNights, 0.62, `seed:hotel:${destination.code}`);
  },
  buildAffiliateLink() { return null; }
};

const seedActivitiesProvider = {
  id: "seed-activities-v1",
  name: "LUMEN Seed Activities Estimate",
  component: "ACTIVITIES",
  mode: "ESTIMATED_SEED",
  supportsRealtime: false,
  supportsBooking: false,
  supportsAffiliate: false,
  externalNetworkCalls: false,
  requiresSecret: false,
  async quote({ input, destination }) {
    const personDays = input.durationDays * input.travelersCount;
    const amountUSD = destination.activityDailyUSD * personDays;
    return quoteEnvelope(this, this.component, amountUSD, destination.activityDailyUSD, personDays, 0.58, `seed:activities:${destination.code}`);
  },
  buildAffiliateLink() { return null; }
};

const SEED_PROVIDERS = Object.freeze([
  seedFlightProvider,
  seedAccommodationProvider,
  seedActivitiesProvider
]);

function resolveProviders(env = {}, fetchImpl = fetch) {
  const providers = new Map(SEED_PROVIDERS.map(provider => [provider.component, provider]));
  for (const external of createExternalTravelProviders(env, fetchImpl)) providers.set(external.component, external);
  return [...providers.values()];
}

export function listTravelProviders(env = {}) {
  return resolveProviders(env).map(provider => ({
    id: provider.id,
    name: provider.name,
    component: provider.component,
    mode: provider.mode,
    contractVersion: CONTRACT_VERSION,
    supportsRealtime: provider.supportsRealtime,
    supportsBooking: provider.supportsBooking,
    supportsAffiliate: provider.supportsAffiliate,
    externalNetworkCalls: provider.externalNetworkCalls,
    requiresSecret: provider.requiresSecret
  }));
}

export async function quoteTravelComponents(rawInput, destinationDataset = [], env = {}, fetchImpl = fetch) {
  const { input, destination, errors } = validateQuoteInput(rawInput, destinationDataset);
  if (errors.length) return { ok: false, version: VERSION, contractVersion: CONTRACT_VERSION, input, errors, quotes: [] };

  const providers = resolveProviders(env, fetchImpl);
  const quotes = [];
  const fallbacks = [];

  for (const provider of providers) {
    try {
      const quote = await provider.quote({ input, destination });
      quotes.push(quote);
    } catch (error) {
      const fallback = SEED_PROVIDERS.find(seed => seed.component === provider.component);
      if (!fallback) throw error;
      const quote = await fallback.quote({ input, destination });
      quotes.push({ ...quote, fallbackFromProviderId: provider.id, fallbackReason: clean(error?.message || error, 120) || "provider_error" });
      fallbacks.push({ component: provider.component, providerId: provider.id, reason: clean(error?.message || error, 120) || "provider_error" });
    }
  }

  const totalQuotedUSD = quotes.reduce((sum, quote) => sum + Number(quote.amountUSD || 0), 0);
  const allRealtime = quotes.length > 0 && quotes.every(quote => quote.isRealtime === true);
  const anyAffiliate = quotes.some(quote => Boolean(quote.affiliateUrl));
  const modes = [...new Set(quotes.map(quote => quote.providerMode))];
  const hasNetworkProviders = providers.some(provider => provider.externalNetworkCalls === true);

  return {
    ok: true,
    version: VERSION,
    contractVersion: CONTRACT_VERSION,
    input,
    destination: {
      code: destination.code,
      city: destination.city,
      country: destination.country
    },
    quotes,
    totals: {
      currency: CURRENCY,
      quotedComponentsUSD: Math.round(totalQuotedUSD)
    },
    pricingMode: modes.length === 1 ? modes[0] : "MIXED_PROVIDER_MODES",
    realTimeCoverage: allRealtime,
    affiliateLinksAvailable: anyAffiliate,
    fallbacks,
    guardrails: {
      quoteOnly: true,
      externalNetworkCalls: hasNetworkProviders,
      createsBooking: false,
      createsCharge: false,
      storesPaymentData: false,
      storesPassportData: false,
      autonomousSpend: false,
      autonomousPurchase: false,
      bindingActionsHumanGated: true
    }
  };
}

export async function handleTravelProviderRegistry(request, env, destinationDataset = []) {
  const url = new URL(request.url);

  if (request.method === "OPTIONS" && url.pathname.startsWith("/travel/providers")) {
    return new Response(null, {
      status: 204,
      headers: {
        "access-control-allow-origin": "*",
        "access-control-allow-headers": "content-type",
        "access-control-allow-methods": "GET,POST,OPTIONS"
      }
    });
  }

  if (request.method === "GET" && url.pathname === "/travel/providers/policy") {
    const providers = listTravelProviders(env);
    return json({
      version: VERSION,
      contractVersion: CONTRACT_VERSION,
      architecture: "adapter_registry",
      components: ["FLIGHT", "ACCOMMODATION", "ACTIVITIES"],
      providerSelection: "external_over_seed_per_component",
      configuredProviders: providers,
      externalProviderStatus: getExternalTravelProviderStatus(env),
      realTimePrices: providers.some(x => x.supportsRealtime),
      bookingAuthority: false,
      affiliateLinksEnabled: providers.some(x => x.supportsAffiliate),
      providerReplacementWithoutTravelEngineRewrite: true,
      createsBooking: false,
      createsCharge: false,
      autonomousSpend: false,
      autonomousPurchase: false,
      bindingActionsHumanGated: true
    });
  }

  if (request.method === "GET" && url.pathname === "/travel/providers") {
    return json({ version: VERSION, contractVersion: CONTRACT_VERSION, providers: listTravelProviders(env), externalProviderStatus: getExternalTravelProviderStatus(env) });
  }

  if (request.method === "POST" && url.pathname === "/travel/providers/quote") {
    let body = {};
    try { body = await request.json(); }
    catch { return json({ ok: false, version: VERSION, error: "invalid_json" }, 400); }
    const result = await quoteTravelComponents(body, destinationDataset, env);
    return json(result, result.ok ? 200 : 400);
  }

  return null;
}

export const TRAVEL_PROVIDER_CONTRACT_VERSION = CONTRACT_VERSION;
