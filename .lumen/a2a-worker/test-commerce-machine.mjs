import assert from "node:assert/strict";
import { buildCatalogCopy, buildChannelPayloads, median, planPrice } from "./commerce-machine.js";

assert.equal(median([100, 200, 300]), 200);
assert.equal(median([100, 200, 300, 400]), 250);
assert.equal(median([]), 0);

const candidate = {
  candidate_id: "PC-feed-1",
  title: "Auriculares Modelo X",
  vendor: "Marca X",
  sku: "SKU-X",
  gtin: "7790000000001",
  currency: "ARS",
  supplier_cost: 10000,
  candidate_sell_price: 18000,
  metadata_json: JSON.stringify({ economics: { minimumSellPrice: 16000 } })
};

const copy = buildCatalogCopy(candidate);
assert.match(copy.title, /Auriculares/);
assert.match(copy.description, /SKU-X/);
assert.match(copy.description, /7790000000001/);
assert.equal(copy.sourceCopyReused, false);
assert.equal(copy.sourceImagesReused, false);

const price = planPrice(candidate, { medianPrice: 19000 }, { feePct: 14, logisticsPct: 5, minMarginPct: 18 });
assert.equal(price.viable, true);
assert.ok(price.recommendedPrice >= price.floorPrice);
assert.ok(price.projectedProfit > 0);
assert.ok(price.projectedMarginPct >= 18);
assert.equal(price.competitiveness, "COMPETITIVE");

const tight = planPrice(candidate, { medianPrice: 12000 }, { feePct: 14, logisticsPct: 5, minMarginPct: 18 });
assert.equal(tight.viable, false);
assert.ok(tight.reasons.includes("minimum_viable_price_above_market"));

const plans = buildChannelPayloads(copy, candidate, price);
assert.equal(plans.mercadolibre.publishable, false);
assert.equal(plans.tiendanube.publishable, false);
assert.ok(plans.mercadolibre.blockers.includes("human_approval_required"));
assert.ok(plans.tiendanube.blockers.includes("human_approval_required"));
assert.equal(plans.mercadolibre.payload.attributes.some(row => row.id === "GTIN"), true);
assert.equal(plans.mercadolibre.apiGeneration, "2026-user-products-ready");
assert.equal(plans.tiendanube.apiGeneration, "multi-inventory-ready");

console.log("COMMERCE_MACHINE_SHADOW ok");
