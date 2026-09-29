import assert from "node:assert/strict";
import {
  calculateTravelOptions,
  TRAVEL_CONSUMER_DESTINATIONS
} from "../../.lumen/a2a-worker/travel-consumer-engine.js";
import {
  calculateProviderBackedTravelOptions,
  handleProviderBackedTravelDiscovery
} from "../../.lumen/a2a-worker/travel-provider-backed-discovery.js";

const input = {
  originCode: "EZE",
  maxBudgetUSD: 1500,
  durationDays: 7,
  targetMonth: 2,
  flexibilityDays: 3,
  travelersCount: 1,
  preferences: ["PLAYA", "GASTRONOMIA", "AVENTURA"]
};

const legacySeed = calculateTravelOptions(input, TRAVEL_CONSUMER_DESTINATIONS);
const providerBacked = await calculateProviderBackedTravelOptions(input, TRAVEL_CONSUMER_DESTINATIONS);

assert.equal(providerBacked.ok, true);
assert.equal(providerBacked.providerBacked, true);
assert.equal(providerBacked.providerContractVersion, "1.0");
assert.equal(providerBacked.pricingMode, "ESTIMATED_SEED");
assert.equal(providerBacked.realTimeCoverage, false);
assert.equal(providerBacked.affiliateLinksAvailable, false);
assert.deepEqual(
  providerBacked.options.map(option => option.destinationCode),
  legacySeed.options.map(option => option.destinationCode)
);

for (const option of providerBacked.options) {
  assert.equal(option.providerBacked, true);
  assert.equal(option.pricingMode, "ESTIMATED_SEED");
  assert.equal(option.realTimeFare, false);
  assert.equal(option.bookingAvailable, false);
  assert.equal(option.affiliateLinksAvailable, false);
  assert.equal(option.providerPricing.contractVersion, "1.0");
  assert.equal(option.providerPricing.components.length, 3);
  assert.equal(option.providerPricing.allRealtime, false);
  assert.equal(option.providerPricing.anyAffiliateLink, false);
  assert.equal(option.providerPricing.anyBookable, false);
  assert.equal(option.providerPricing.externalNetworkCalls, false);
  assert.deepEqual(option.providerPricing.unquotedComponents, ["TRANSFERS", "FOOD_AND_DAILY_EXPENSES"]);
  assert.ok(option.providerPricing.quotedShareOfTrip > 0 && option.providerPricing.quotedShareOfTrip <= 1);
  assert.ok(option.confidenceLevel >= 0.25 && option.confidenceLevel <= 0.95);
  assert.ok(option.breakdown.totalUSD <= providerBacked.input.maxBudgetUSD);

  const flight = option.providerPricing.components.find(component => component.component === "FLIGHT");
  const accommodation = option.providerPricing.components.find(component => component.component === "ACCOMMODATION");
  const activities = option.providerPricing.components.find(component => component.component === "ACTIVITIES");
  assert.ok(flight);
  assert.ok(accommodation);
  assert.ok(activities);
  assert.equal(option.breakdown.flightUSD, flight.amountUSD);
  assert.equal(option.breakdown.accommodationUSD, accommodation.amountUSD);
  assert.equal(option.breakdown.activitiesUSD, activities.amountUSD);
}

const invalid = await calculateProviderBackedTravelOptions({ ...input, maxBudgetUSD: 50 }, TRAVEL_CONSUMER_DESTINATIONS);
assert.equal(invalid.ok, false);
assert.ok(invalid.errors.includes("invalid_budget"));

const noRoute = await calculateProviderBackedTravelOptions({ ...input, originCode: "ZZZ" }, TRAVEL_CONSUMER_DESTINATIONS);
assert.equal(noRoute.ok, true);
assert.equal(noRoute.options.length, 0);
assert.equal(noRoute.providerBacked, true);

const policyResponse = await handleProviderBackedTravelDiscovery(
  new Request("https://example.test/travel/discovery/policy"),
  {},
  TRAVEL_CONSUMER_DESTINATIONS
);
assert.equal(policyResponse.status, 200);
const policy = await policyResponse.json();
assert.equal(policy.version, "1.0-travel-provider-backed-discovery");
assert.equal(policy.searchUsesProviderRegistry, true);
assert.equal(policy.providerReplacementWithoutDiscoveryRewrite, true);
assert.equal(policy.realTimeFares, false);
assert.equal(policy.affiliateLinksEnabled, false);
assert.equal(policy.createsBooking, false);
assert.equal(policy.createsCharge, false);
assert.equal(policy.autonomousSpend, false);

const searchResponse = await handleProviderBackedTravelDiscovery(
  new Request("https://example.test/travel/discovery/search", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input)
  }),
  {},
  TRAVEL_CONSUMER_DESTINATIONS
);
assert.equal(searchResponse.status, 200);
const payload = await searchResponse.json();
assert.equal(payload.ok, true);
assert.equal(payload.providerBacked, true);
assert.equal(payload.guardrails.searchUsesProviderRegistry, true);
assert.equal(payload.guardrails.bookingCreated, false);
assert.equal(payload.guardrails.chargeCreated, false);
assert.equal(payload.guardrails.autonomousSpend, false);
assert.equal(payload.guardrails.autonomousPurchase, false);
assert.equal(payload.persistence.stored, false);
assert.equal(payload.persistence.reason, "persistence_unavailable");

console.log(JSON.stringify({
  ok: true,
  version: policy.version,
  providerContractVersion: providerBacked.providerContractVersion,
  resultCount: providerBacked.options.length,
  topDestination: providerBacked.options[0]?.destinationCode || null,
  tests: [
    "discovery_uses_provider_registry",
    "seed_provider_parity",
    "provider_quotes_feed_breakdown",
    "provider_evidence_attached",
    "provider_confidence_attached",
    "no_realtime_claims_without_realtime_provider",
    "no_affiliate_claims_without_partner",
    "no_booking_or_charge",
    "budget_filter_after_provider_quotes",
    "provider_replacement_without_discovery_rewrite"
  ]
}, null, 2));