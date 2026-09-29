import assert from "node:assert/strict";
import {
  calculateTravelOptions,
  handleTravelConsumerEngine,
  TRAVEL_CONSUMER_DESTINATIONS
} from "../../.lumen/a2a-worker/travel-consumer-engine.js";

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

console.log(JSON.stringify({
  ok: true,
  version: policy.version,
  defaultResults: base.options.length,
  topDestination: base.options[0]?.destinationCode || null,
  tests: [
    "budget_cap",
    "score_bounds",
    "confidence_bounds",
    "no_fake_exact_dates",
    "no_booking_or_charge",
    "origin_alias",
    "validation",
    "deterministic_scoring",
    "policy_guardrails"
  ]
}, null, 2));
