const VERSION = "1.0-source-intelligence";

export function handleSourceIntelligencePolicy(request) {
  const url = new URL(request.url);
  if (request.method !== "GET" || url.pathname !== "/source-intelligence/policy") return null;

  return Response.json({
    version: VERSION,
    name: "LUMEN Multisource Market Radar + Source Intelligence",
    sources: [
      { sourceId: "global_a2a_registry", kind: "EXISTING_PIPELINE", scanMode: "OBSERVE_ONLY", protected: true },
      { sourceId: "ted_eu_public_procurement", kind: "PUBLIC_PROCUREMENT", scanMode: "ACTIVE", protected: true },
      { sourceId: "uk_contracts_finder", kind: "PUBLIC_PROCUREMENT", scanMode: "ACTIVE", protected: true }
    ],
    selectionPolicy: "bounded_source_explore_exploit",
    sourceLearning: "direct_opportunity_to_verified_settlement_attribution",
    maxExternalSourcesPerCycle: 2,
    maxResultsPerSource: 20,
    createsExternalMessages: false,
    autonomousSpendUsd: 0,
    autonomousPurchase: false,
    autonomousContract: false,
    verifiedRevenueOnly: true,
    bindingActionsHumanGated: true
  }, {
    headers: {
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "access-control-allow-origin": "*"
    }
  });
}
