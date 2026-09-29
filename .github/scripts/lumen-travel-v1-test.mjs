import assert from "node:assert/strict";
import {
  calculateTravelOptions,
  handleTravelConsumerEngine,
  TRAVEL_CONSUMER_DESTINATIONS
} from "../../.lumen/a2a-worker/travel-consumer-engine.js";
import {
  buildTravelDemandClusters,
  handleTravelDemandBridge,
  TRAVEL_DEMAND_MIN_CLUSTER_SIGNALS
} from "../../.lumen/a2a-worker/travel-demand-bridge.js";
import {
  handleTravelProviderRegistry,
  listTravelProviders,
  quoteTravelComponents,
  TRAVEL_PROVIDER_CONTRACT_VERSION
} from "../../.lumen/a2a-worker/travel-provider-registry.js";

function search(overrides = {}) {
  return calculateTravelOptions({
    originCode: "BUE",
    maxBudgetUSD: 1500,
    durationDays: 7,
    targetMonth: 2,
    flexibilityDays: 3,
    travelersCount: 1,
    preferences: ["PLAYA", "GASTRONOMIA", "AVENTURA"],
    ...overrides
  });
}

const base = search();
assert.equal(base.ok, true);
assert.ok(base.options.length >= 1 && base.options.length <= 5);
for (const option of base.options) {
  assert.ok(option.breakdown.totalUSD <= base.input.maxBudgetUSD, `${option.city} exceeded budget`);
  assert.ok(option.lumenScore >= 0 && option.lumenScore <= 100, `${option.city} score outside 0-100`);
  assert.ok(option.confidenceLevel >= 0.25 && option.confidenceLevel <= 0.95, `${option.city} confidence outside range`);
  assert.equal(option.pricingMode, "ESTIMATED_SEED");
  assert.equal(option.realTimeFare, false);
  assert.equal(option.bookingAvailable, false);
  assert.equal(option.affiliateLinksAvailable, false);
  assert.equal(option.recommendedWindow.exactDatesAvailable, false);
}

const alias = search({ originCode: "EZE" });
assert.equal(alias.input.originCode, "BUE");
assert.deepEqual(alias.options.map(x => x.destinationCode), base.options.map(x => x.destinationCode));

const invalid = search({ maxBudgetUSD: 50 });
assert.equal(invalid.ok, false);
assert.ok(invalid.errors.includes("invalid_budget"));

const impossible = search({ maxBudgetUSD: 100, durationDays: 30 });
assert.equal(impossible.ok, true);
assert.equal(impossible.options.length, 0);

const noRoute = search({ originCode: "ZZZ" });
assert.equal(noRoute.ok, true);
assert.equal(noRoute.options.length, 0);

const mockDestination = {
  code: "TST",
  city: "Test City",
  country: "Testland",
  dailyCostUSD: 50,
  hotelNightUSD: 40,
  transferPerPersonUSD: 10,
  activityDailyUSD: 10,
  qualityScore: 8,
  safetyIndex: 8,
  accessibilityScore: 8,
  tags: ["PLAYA"],
  routes: { BUE: { avgFlightUSD: 100, flightTimeHours: 2, volatility: 0.2 } },
  climate: { 2: "SHOULDER" }
};
const deterministic = calculateTravelOptions({
  originCode: "BUE",
  maxBudgetUSD: 1000,
  durationDays: 5,
  targetMonth: 2,
  travelersCount: 1,
  preferences: ["PLAYA"]
}, [mockDestination]);
assert.equal(deterministic.ok, true);
assert.equal(deterministic.options.length, 1);
assert.equal(deterministic.options[0].scoreBreakdown.preferenceFit, 100);
assert.equal(deterministic.options[0].scoreBreakdown.seasonFit, 100);
assert.ok(deterministic.options[0].breakdown.remainingMarginUSD >= 0);

assert.ok(TRAVEL_CONSUMER_DESTINATIONS.length >= 5);

const policyResponse = await handleTravelConsumerEngine(
  new Request("https://example.test/travel/discovery/policy"),
  {}
);
assert.equal(policyResponse.status, 200);
const policy = await policyResponse.json();
assert.equal(policy.version, "1.0-travel-consumer-discovery");
assert.equal(policy.realTimeFares, false);
assert.equal(policy.createsBooking, false);
assert.equal(policy.createsCharge, false);
assert.equal(policy.autonomousSpend, false);
assert.equal(policy.bindingActionsHumanGated, true);
assert.equal(policy.storesIpAddress, false);

const searchResponse = await handleTravelConsumerEngine(
  new Request("https://example.test/travel/discovery/search", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      originCode: "BUE",
      maxBudgetUSD: 1500,
      durationDays: 7,
      targetMonth: 2,
      travelersCount: 1,
      preferences: ["PLAYA", "GASTRONOMIA"]
    })
  }),
  {}
);
assert.equal(searchResponse.status, 200);
const searchPayload = await searchResponse.json();
assert.equal(searchPayload.ok, true);
assert.equal(searchPayload.guardrails.recommendationOnly, true);
assert.equal(searchPayload.guardrails.bookingCreated, false);
assert.equal(searchPayload.guardrails.chargeCreated, false);
assert.equal(searchPayload.guardrails.autonomousSpend, false);

const providerCatalog = listTravelProviders();
assert.equal(TRAVEL_PROVIDER_CONTRACT_VERSION, "1.0");
assert.equal(providerCatalog.length, 3);
assert.deepEqual(providerCatalog.map(x => x.component).sort(), ["ACCOMMODATION", "ACTIVITIES", "FLIGHT"]);
for (const provider of providerCatalog) {
  assert.equal(provider.mode, "ESTIMATED_SEED");
  assert.equal(provider.supportsRealtime, false);
  assert.equal(provider.supportsBooking, false);
  assert.equal(provider.supportsAffiliate, false);
  assert.equal(provider.externalNetworkCalls, false);
  assert.equal(provider.requiresSecret, false);
}

const providerQuote = await quoteTravelComponents({
  originCode: "EZE",
  destinationCode: "GIG",
  durationDays: 7,
  targetMonth: 2,
  travelersCount: 2
}, TRAVEL_CONSUMER_DESTINATIONS);
assert.equal(providerQuote.ok, true);
assert.equal(providerQuote.input.originCode, "BUE");
assert.equal(providerQuote.destination.code, "GIG");
assert.equal(providerQuote.quotes.length, 3);
assert.equal(providerQuote.pricingMode, "ESTIMATED_SEED");
assert.equal(providerQuote.realTimeCoverage, false);
assert.equal(providerQuote.affiliateLinksAvailable, false);
assert.equal(providerQuote.guardrails.quoteOnly, true);
assert.equal(providerQuote.guardrails.externalNetworkCalls, false);
assert.equal(providerQuote.guardrails.createsBooking, false);
assert.equal(providerQuote.guardrails.createsCharge, false);
assert.equal(providerQuote.guardrails.autonomousSpend, false);
const flightQuote = providerQuote.quotes.find(x => x.component === "FLIGHT");
const accommodationQuote = providerQuote.quotes.find(x => x.component === "ACCOMMODATION");
const activityQuote = providerQuote.quotes.find(x => x.component === "ACTIVITIES");
assert.equal(flightQuote.amountUSD, 840);
assert.equal(accommodationQuote.amountUSD, 432);
assert.equal(activityQuote.amountUSD, 252);
assert.equal(providerQuote.totals.quotedComponentsUSD, 1524);
for (const quote of providerQuote.quotes) {
  assert.equal(quote.currency, "USD");
  assert.equal(quote.isRealtime, false);
  assert.equal(quote.bookable, false);
  assert.equal(quote.affiliateEligible, false);
  assert.equal(quote.affiliateUrl, null);
  assert.ok(quote.confidence >= 0.25 && quote.confidence <= 0.95);
}

const providerPolicyResponse = await handleTravelProviderRegistry(
  new Request("https://example.test/travel/providers/policy"),
  {},
  TRAVEL_CONSUMER_DESTINATIONS
);
assert.equal(providerPolicyResponse.status, 200);
const providerPolicy = await providerPolicyResponse.json();
assert.equal(providerPolicy.version, "1.0-travel-provider-registry");
assert.equal(providerPolicy.contractVersion, "1.0");
assert.equal(providerPolicy.providerReplacementWithoutTravelEngineRewrite, true);
assert.equal(providerPolicy.externalNetworkCalls, false);
assert.equal(providerPolicy.realTimePrices, false);
assert.equal(providerPolicy.bookingAuthority, false);
assert.equal(providerPolicy.affiliateLinksEnabled, false);
assert.equal(providerPolicy.createsBooking, false);
assert.equal(providerPolicy.createsCharge, false);
assert.equal(providerPolicy.autonomousSpend, false);

const unsupportedProviderQuote = await handleTravelProviderRegistry(
  new Request("https://example.test/travel/providers/quote", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ originCode: "BUE", destinationCode: "XXX", durationDays: 7, targetMonth: 2, travelersCount: 1 })
  }),
  {},
  TRAVEL_CONSUMER_DESTINATIONS
);
assert.equal(unsupportedProviderQuote.status, 400);
const unsupportedProviderPayload = await unsupportedProviderQuote.json();
assert.ok(unsupportedProviderPayload.errors.includes("unsupported_destination"));

const fixedNow = new Date("2026-09-29T18:00:00Z").getTime();
const clustered = buildTravelDemandClusters([
  {
    id: "E1",
    created_at: "2026-09-29T15:00:00Z",
    origin_code: "BUE",
    target_month: 2,
    budget_bucket_usd: 1200,
    preferences_json: JSON.stringify(["PLAYA", "RELAX"])
  },
  {
    id: "E2",
    created_at: "2026-09-29T16:00:00Z",
    origin_code: "BUE",
    target_month: 2,
    budget_bucket_usd: 1200,
    preferences_json: JSON.stringify(["PLAYA", "GASTRONOMIA"])
  },
  {
    id: "E3",
    created_at: "2026-09-29T17:00:00Z",
    origin_code: "BUE",
    target_month: 2,
    budget_bucket_usd: 1200,
    preferences_json: JSON.stringify(["PLAYA", "RELAX"])
  },
  {
    id: "E4",
    created_at: "2026-09-29T17:30:00Z",
    origin_code: "BUE",
    target_month: 3,
    budget_bucket_usd: 900,
    preferences_json: JSON.stringify(["CIUDAD"])
  }
], fixedNow);
assert.equal(TRAVEL_DEMAND_MIN_CLUSTER_SIGNALS, 2);
assert.equal(clustered.length, 2);
const repeatedCluster = clustered.find(x => x.clusterKey === "BUE|2|1200");
assert.ok(repeatedCluster);
assert.equal(repeatedCluster.demandCount, 3);
assert.equal(repeatedCluster.eligibleForBridge, true);
assert.equal(repeatedCluster.fit, "A");
assert.equal(repeatedCluster.topPreferences[0].name, "PLAYA");
assert.equal(repeatedCluster.topPreferences[0].count, 3);
const singleCluster = clustered.find(x => x.clusterKey === "BUE|3|900");
assert.ok(singleCluster);
assert.equal(singleCluster.demandCount, 1);
assert.equal(singleCluster.eligibleForBridge, false);

const demandPolicyResponse = await handleTravelDemandBridge(
  new Request("https://example.test/travel/demand/policy"),
  {}
);
assert.equal(demandPolicyResponse.status, 200);
const demandPolicy = await demandPolicyResponse.json();
assert.equal(demandPolicy.version, "1.0-travel-demand-bridge");
assert.equal(demandPolicy.minimumSignalsPerCluster, 2);
assert.equal(demandPolicy.storesPii, false);
assert.equal(demandPolicy.automaticBridging, true);
assert.equal(demandPolicy.automaticCommercialActivation, false);
assert.equal(demandPolicy.activationRequiresAdmin, true);
assert.equal(demandPolicy.automaticOutreach, false);
assert.equal(demandPolicy.createsBooking, false);
assert.equal(demandPolicy.createsCharge, false);
assert.equal(demandPolicy.autonomousSpend, false);

const unauthorizedActivation = await handleTravelDemandBridge(
  new Request("https://example.test/travel/demand/activate", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ opportunityId: "OPP-TRAVEL-TEST" })
  }),
  { OPPORTUNITY_ADMIN_TOKEN: "protected-secret" }
);
assert.equal(unauthorizedActivation.status, 403);
const unauthorizedPayload = await unauthorizedActivation.json();
assert.equal(unauthorizedPayload.error, "admin_token_required");

console.log(JSON.stringify({
  ok: true,
  version: policy.version,
  demandBridgeVersion: demandPolicy.version,
  providerRegistryVersion: providerPolicy.version,
  providerContractVersion: providerPolicy.contractVersion,
  defaultResults: base.options.length,
  topDestination: base.options[0]?.destinationCode || null,
  repeatedDemandScore: repeatedCluster.score,
  providerQuotedComponentsUSD: providerQuote.totals.quotedComponentsUSD,
  tests: [
    "budget_cap",
    "score_bounds",
    "confidence_bounds",
    "no_fake_exact_dates",
    "no_booking_or_charge",
    "origin_alias",
    "validation",
    "deterministic_scoring",
    "policy_guardrails",
    "provider_contract",
    "provider_normalized_quotes",
    "provider_amounts",
    "provider_no_network_calls",
    "provider_no_booking_or_charge",
    "provider_affiliate_disabled_until_configured",
    "demand_cluster_aggregation",
    "minimum_signal_threshold",
    "no_single_search_promotion",
    "human_gated_commercial_activation"
  ]
}, null, 2));