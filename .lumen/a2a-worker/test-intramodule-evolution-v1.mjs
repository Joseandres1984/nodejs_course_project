import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const proposal = await readFile(new URL("./proposal-engine.js", import.meta.url), "utf8");
const firstCash = await readFile(new URL("./first-cash-closer.js", import.meta.url), "utf8");

// Preserve public runtime contracts while evolving internals.
assert.match(proposal, /const VERSION = "1\.6-first-cash-microbuyer-revision"/);
assert.match(firstCash, /const VERSION = "1\.1-shared-response-first-cash-closer"/);
assert.match(firstCash, /const FAST_LANE_VERSION = "1\.0-first-settlement-fast-lane"/);

for (const id of ["direct_outcome", "evidence_first", "scope_first", "low_friction"]) {
  assert.match(proposal, new RegExp(`id: ["']${id}["']`), `proposal variant ${id} must exist`);
}
assert.match(proposal, /lumen_proposal_variant_assignments/);
assert.match(proposal, /lumen_x402_revenue_bridge/);
assert.match(proposal, /classifyCommercialResponse/);
assert.match(proposal, /OUTREACH_EXPOSURE_STATES/);
assert.match(proposal, /QUALIFIED_RESPONSE_CLASSES/);
assert.match(proposal, /settlementRate \* 10000 \+ revenuePerExposure \* 100 \+ responseRate \* 120/);
assert.match(proposal, /countsOnlyActualOutreachAsExposure: true/);
assert.match(proposal, /qualifiedResponseClassification: true/);
assert.match(proposal, /one_time_revision/);
assert.match(proposal, /verified_settlement_rate/);
assert.match(proposal, /selfModifyingCode: false/);
assert.match(proposal, /mutatesPrice: false/);
assert.match(proposal, /autonomousPriceChange: false/);

const fixedPrices = {
  "MP-SUPPLIER-SNAPSHOT": 1,
  "MP-QUOTE-SANITY": 7,
  "MP-TENDER-SCAN": 9,
  "MP-SOURCING-5": 15,
  "MP-BUYER-SIGNALS": 19,
  "MP-EXPORT-PULSE": 25
};
for (const [offer, price] of Object.entries(fixedPrices)) {
  const escaped = offer.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  assert.match(proposal, new RegExp(`"${escaped}"\\s*:\\s*\\{[^}]*priceUsd:\\s*${price}(?:[,}])`), `${offer} fixed price must remain ${price}`);
}

for (const id of ["direct_checkout", "scope_reassurance", "intent_mirror"]) {
  assert.match(firstCash, new RegExp(`id: ["']${id}["']`), `closer strategy ${id} must exist`);
}
assert.match(firstCash, /lumen_first_cash_strategy_assignments/);
assert.match(firstCash, /COUNT\(DISTINCT receipt_id\)/);
assert.match(firstCash, /outcome\.settlements \* 1000 \+ outcome\.revenueUsd \* 20/);
assert.match(firstCash, /settlements \* 10000 \+ revenueUsd \* 100 \+ responses \* 10/);
assert.match(firstCash, /settlementRate \* 10000 \+ revenuePerAssignment \* 100 \+ responseRate \* 120/);
assert.match(firstCash, /COUNT\(DISTINCT CASE WHEN c\.status IN \('SENT','SENT_TASK','RESPONDED'\)/);
assert.match(firstCash, /FAILED_RETRY_COOLDOWN_HOURS = 6/);
assert.match(firstCash, /c\.status='SEND_FAILED'/);
assert.match(firstCash, /countsOnlySuccessfulCloseSendsAsExposure: true/);
assert.match(firstCash, /conversionRateScoring: true/);
assert.match(firstCash, /PURCHASE_INTENT/);
assert.match(firstCash, /COMMERCIAL_INTEREST/);
assert.match(firstCash, /maxExternalMessagesPerRun: 1/);
assert.match(firstCash, /selfModifyingCode: false/);
assert.match(firstCash, /mutatesPrice: false/);
assert.match(firstCash, /autonomousSpend: false/);
assert.match(firstCash, /autonomousContract: false/);
assert.match(firstCash, /bindingActionsHumanGated: true/);

console.log("INTRAMODULE_EVOLUTION_V1_GUARDRAILS_OK");
