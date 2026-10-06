import assert from "node:assert/strict";
import { TRAVEL_CONSUMER_DESTINATIONS } from "../../.lumen/a2a-worker/travel-consumer-engine.js";
import { quoteTravelComponents, listTravelProviders } from "../../.lumen/a2a-worker/travel-provider-registry.js";
import { getExternalTravelProviderStatus } from "../../.lumen/a2a-worker/travel-external-providers.js";
import { listTravelAffiliateOffers, handleTravelAffiliateRegistry } from "../../.lumen/a2a-worker/travel-affiliate-registry.js";
import { calculateProviderBackedTravelOptions } from "../../.lumen/a2a-worker/travel-provider-backed-discovery.js";

const seedCatalog = listTravelProviders({});
assert.equal(seedCatalog.length, 3);
assert.ok(seedCatalog.every(provider => provider.mode === "ESTIMATED_SEED"));
const emptyStatus = getExternalTravelProviderStatus({});
assert.ok(emptyStatus.providers.every(provider => provider.configured === false));

const mockFetch = async (url, options = {}) => {
  const target = String(url);
  if (target.includes("api.travelpayouts.com")) {
    return new Response(JSON.stringify({
      success: true,
      data: {
        "2027-02-10": {
          origin: "BUE",
          destination: "GIG",
          price: 350,
          airline: "AR",
          departure_at: "2027-02-10T10:00:00Z",
          return_at: "2027-02-17T10:00:00Z",
          transfers: 0,
          return_transfers: 0,
          link: "/search/mock"
        }
      }
    }), { status: 200, headers: { "content-type": "application/json" } });
  }
  if (target.includes("api.viator.com")) {
    assert.equal(options.method, "POST");
    assert.equal(options.headers["exp-api-key"], "viator-test-key");
    return new Response(JSON.stringify({
      products: [
        { productCode: "P1", title: "Tour A", pricing: { summary: { fromPrice: 40 }, currency: "USD" }, productUrl: "https://www.viator.com/tours/mock-a?pid=test" },
        { productCode: "P2", title: "Tour B", pricing: { summary: { fromPrice: 50 }, currency: "USD" }, productUrl: "https://www.viator.com/tours/mock-b?pid=test" },
        { productCode: "P3", title: "Tour C", pricing: { summary: { fromPrice: 60 }, currency: "USD" }, productUrl: "https://www.viator.com/tours/mock-c?pid=test" }
      ]
    }), { status: 200, headers: { "content-type": "application/json" } });
  }
  throw new Error(`unexpected_url:${target}`);
};

const env = {
  TRAVELPAYOUTS_API_TOKEN: "travelpayouts-test-token",
  VIATOR_API_KEY: "viator-test-key",
  VIATOR_DESTINATION_MAP_JSON: JSON.stringify({ GIG: "123" })
};

const configured = listTravelProviders(env);
assert.equal(configured.find(x => x.component === "FLIGHT").id, "aviasales-data-v2");
assert.equal(configured.find(x => x.component === "ACTIVITIES").id, "viator-basic-affiliate-v1");
assert.equal(configured.find(x => x.component === "ACCOMMODATION").id, "seed-accommodation-v1");

const quote = await quoteTravelComponents({
  originCode: "BUE",
  destinationCode: "GIG",
  durationDays: 7,
  targetMonth: 2,
  travelersCount: 2
}, TRAVEL_CONSUMER_DESTINATIONS, env, mockFetch);
assert.equal(quote.ok, true);
assert.equal(quote.guardrails.externalNetworkCalls, true);
assert.equal(quote.guardrails.createsBooking, false);
assert.equal(quote.guardrails.createsCharge, false);
const flight = quote.quotes.find(x => x.component === "FLIGHT");
const activities = quote.quotes.find(x => x.component === "ACTIVITIES");
const accommodation = quote.quotes.find(x => x.component === "ACCOMMODATION");
assert.equal(flight.providerId, "aviasales-data-v2");
assert.equal(flight.amountUSD, 700);
assert.equal(flight.isRealtime, false);
assert.equal(activities.providerId, "viator-basic-affiliate-v1");
assert.equal(activities.unitAmountUSD, 50);
assert.equal(activities.amountUSD, 300);
assert.equal(activities.affiliateEligible, true);
assert.ok(activities.affiliateUrl.includes("viator.com"));
assert.equal(accommodation.providerId, "seed-accommodation-v1");
assert.equal(quote.affiliateLinksAvailable, true);

const gigOnly = TRAVEL_CONSUMER_DESTINATIONS.filter(x => x.code === "GIG");
const discovery = await calculateProviderBackedTravelOptions({
  originCode: "BUE",
  maxBudgetUSD: 2500,
  durationDays: 7,
  targetMonth: 2,
  travelersCount: 2,
  preferences: ["PLAYA", "GASTRONOMIA"]
}, gigOnly, env, mockFetch);
assert.equal(discovery.ok, true);
assert.equal(discovery.externalProvidersUsed, true);
assert.equal(discovery.options.length, 1);
assert.equal(discovery.options[0].providerPricing.externalNetworkCalls, true);
assert.equal(discovery.options[0].affiliateLinksAvailable, true);
assert.equal(discovery.options[0].bookingAvailable, false);

const failedFetch = async () => new Response("failure", { status: 503 });
const fallback = await quoteTravelComponents({
  originCode: "BUE",
  destinationCode: "GIG",
  durationDays: 7,
  targetMonth: 2,
  travelersCount: 1
}, TRAVEL_CONSUMER_DESTINATIONS, { TRAVELPAYOUTS_API_TOKEN: "x" }, failedFetch);
assert.equal(fallback.ok, true);
const fallbackFlight = fallback.quotes.find(x => x.component === "FLIGHT");
assert.equal(fallbackFlight.providerId, "seed-flight-v1");
assert.equal(fallbackFlight.fallbackFromProviderId, "aviasales-data-v2");
assert.ok(fallback.fallbacks.length >= 1);

const emptyAffiliates = listTravelAffiliateOffers({});
assert.equal(emptyAffiliates.length, 3);
assert.ok(emptyAffiliates.every(offer => offer.enabled === false));
const affiliateEnv = {
  AIRALO_AFFILIATE_URL: "https://example.com/airalo-track",
  SAFETYWING_AMBASSADOR_URL: "https://example.com/safetywing-track",
  DISCOVERCARS_AFFILIATE_URL: "https://example.com/discovercars-track"
};
const configuredAffiliates = listTravelAffiliateOffers(affiliateEnv);
assert.ok(configuredAffiliates.every(offer => offer.enabled === true));
const affiliatePolicyResponse = await handleTravelAffiliateRegistry(new Request("https://example.test/travel/affiliates/policy"), affiliateEnv);
assert.equal(affiliatePolicyResponse.status, 200);
const affiliatePolicy = await affiliatePolicyResponse.json();
assert.equal(affiliatePolicy.enabledOffers, 3);
assert.equal(affiliatePolicy.noSyntheticAffiliateIds, true);
assert.equal(affiliatePolicy.noBookingAuthority, true);
assert.equal(affiliatePolicy.createsCharge, false);
assert.equal(affiliatePolicy.autonomousSpend, false);

console.log(JSON.stringify({
  ok: true,
  tests: [
    "external_providers_disabled_without_credentials",
    "aviasales_cached_market_adapter",
    "viator_basic_affiliate_adapter",
    "seed_accommodation_fallback",
    "provider_failure_falls_back_to_seed",
    "discovery_uses_configured_external_providers",
    "affiliate_links_only_when_configured",
    "no_booking_charge_or_autonomous_spend"
  ]
}, null, 2));