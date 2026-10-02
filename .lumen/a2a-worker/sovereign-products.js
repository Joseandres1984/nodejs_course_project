import { ACTIVE_PLAYBOOKS } from "./sovereign-operations.js";
import { OFFERS } from "./proposal-engine.js";
import { host, clean, iso, V4_POLICY } from "./sovereign-store.js";

const SHARED_HOSTS = new Set(["api.a2a-registry.org", "a2a-registry.org", "github.com", "clavis.citriac.deno.net"]);
export function marketRadar(opportunities, settlements) {
  const groups = new Map();
  for (const row of opportunities) {
    if (row.synthetic_or_test_only || !row.commercially_actionable || !OFFERS[row.revenue_offer_id]) continue;
    const domain = host(row.endpoint);
    if (!domain || SHARED_HOSTS.has(domain) || !["medium", "strong"].includes(row.evidence_strength)) continue;
    if (!groups.has(row.revenue_offer_id)) groups.set(row.revenue_offer_id, { offerId: row.revenue_offer_id, hosts: new Set(), evidenceIds: new Set() });
    const group = groups.get(row.revenue_offer_id); group.hosts.add(domain); group.evidenceIds.add(row.id);
  }
  return [...groups.values()].map(g => ({ offerId: g.offerId, distinctHostSignals: g.hosts.size,
    hosts: [...g.hosts].sort(), evidenceIds: [...g.evidenceIds].sort(),
    verifiedSettlements: settlements.filter(s => s.offer_id === g.offerId).length,
    verifiedRevenueUsd: settlements.filter(s => s.offer_id === g.offerId).reduce((sum,s) => sum + s.amount_usd, 0),
    independentBuyerCount: null, hostCountIsBuyerCount: false
  })).sort((a,b) => b.verifiedRevenueUsd - a.verifiedRevenueUsd || b.distinctHostSignals - a.distinctHostSignals || a.offerId.localeCompare(b.offerId));
}

export function productSpec(signal) {
  const offer = OFFERS[signal.offerId];
  if (!offer || signal.distinctHostSignals < ACTIVE_PLAYBOOKS.minimumProductHostSignals) return null;
  return { offerId: signal.offerId, name: `${offer.name} — evidence brief`,
    underlyingCapability: signal.offerId, packagingExperiment: true,
    inputSchema: { type: "object", required: ["requirement"], properties: { requirement: { type: "string", minLength: 8, maxLength: 3000 } }, additionalProperties: false },
    outputSchema: { type: "object", required: ["evidence", "limitations", "recommendation"], properties: {
      evidence: { type: "array", items: { type: "object", required: ["url", "observed_at"] } },
      limitations: { type: "array", items: { type: "string" } }, recommendation: { type: "string" }
    } },
    promisedOutcome: offer.outcome, proposedPriceUsd: offer.priceUsd,
    priceSource: "existing_proposal_catalog", newPriceExperiment: false,
    sla: { status: "NEEDS_MEASURED_DELIVERY_BENCHMARK", promisedHours: null },
    projectedComputeMinutes: 4, demandEvidence: signal,
    releaseRequirements: ["fulfillment_certification", "catalog_checkout_price_parity", "human_publication_approval"],
    published: false, checkoutEnabled: false, protocolCatalogPublished: false };
}
export async function createProductDrafts(env, radar) {
  const created = [];
  for (const signal of radar.filter(s => s.distinctHostSignals >= ACTIVE_PLAYBOOKS.minimumProductHostSignals).slice(0, V4_POLICY.maxProductDraftsPerCycle)) {
    const spec = productSpec(signal), id = `V4-PRODUCT-${signal.offerId}`;
    // A refreshed evidence draft must never overwrite a future publication state.
    await env.DB.prepare("INSERT INTO lumen_v4_products VALUES(?,?,?,'DRAFT',?) ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,spec_json=excluded.spec_json WHERE lumen_v4_products.status='DRAFT'")
      .bind(id, signal.offerId, iso(), JSON.stringify(spec)).run();
    created.push({ id, offerId: signal.offerId, distinctHostSignals: signal.distinctHostSignals });
  }
  return { drafts: created, publishesProducts: false, createsNewCapabilities: false };
}
