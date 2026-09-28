import assert from "node:assert/strict";
import {
  cognitiveEconomicOperatorPolicy,
  deriveCognitivePlan,
} from "./cognitive-economic-operator.js";

const locked = deriveCognitivePlan(
  {
    phase: "CLOSING",
    nextEconomicAction: "CLOSE_VERIFIED_INTENT",
    revenueFocus: { mode: "CONVERSION_FIRST" },
  },
  {
    decision: "prioritize",
    product: "tender-scan",
    priority: "high",
    confidence: 0.94,
  },
);
assert.equal(locked.mode, "CONVERSION_GUARD");
assert.equal(locked.hardEconomicAction, "CLOSE_VERIFIED_INTENT");
assert.equal(locked.externalCommercialAction, "CLOSE_VERIFIED_INTENT");
assert.equal(locked.hardEconomicActionPreserved, true);
assert.equal(locked.b2bDiscoveryBoost, false);
assert.equal(locked.productFocus, "tender-scan");

const exploring = deriveCognitivePlan(
  {
    phase: "DISCOVERING",
    nextEconomicAction: "DISCOVER_AND_SCORE_NEW_OPPORTUNITIES",
    revenueFocus: { mode: "NORMAL_DISCOVERY" },
  },
  {
    decision: "prioritize",
    product: "tender-scan",
    priority: "high",
    confidence: 0.81,
  },
);
assert.equal(exploring.mode, "COGNITIVE_ADVISORY");
assert.equal(exploring.productFocus, "tender-scan");
assert.equal(exploring.b2bDiscoveryBoost, true);
assert.equal(exploring.externalCommercialAction, "DISCOVER_AND_SCORE_NEW_OPPORTUNITIES");

const unsafeProduct = deriveCognitivePlan(
  {
    phase: "DISCOVERING",
    nextEconomicAction: "DISCOVER_AND_SCORE_NEW_OPPORTUNITIES",
    revenueFocus: { mode: "NORMAL_DISCOVERY" },
  },
  {
    decision: "prioritize",
    product: "wire-money-now",
    priority: "high",
    confidence: 1,
  },
);
assert.equal(unsafeProduct.productFocus, null);
assert.equal(unsafeProduct.b2bDiscoveryBoost, false);

const lowConfidence = deriveCognitivePlan(
  {
    phase: "BUILDING_PIPELINE",
    nextEconomicAction: "DISCOVER_AND_SCORE_NEW_OPPORTUNITIES",
    revenueFocus: { mode: "NORMAL_DISCOVERY" },
  },
  {
    decision: "research",
    product: "buyer-signals",
    priority: "medium",
    confidence: 0.2,
  },
);
assert.equal(lowConfidence.productFocus, "buyer-signals");
assert.equal(lowConfidence.b2bDiscoveryBoost, false);

const policy = cognitiveEconomicOperatorPolicy();
assert.equal(policy.authority.autonomousSpendUsd, 0);
assert.equal(policy.authority.autonomousPurchase, false);
assert.equal(policy.authority.autonomousDebt, false);
assert.equal(policy.authority.autonomousContract, false);
assert.equal(policy.authority.bindingActionsHumanGated, true);
assert.equal(policy.authority.externalMessagesCreated, false);
assert.equal(policy.authority.mayChangeExternalCommercialAction, false);
assert.equal(policy.authority.hardConversionPriorityOverride, false);

console.log("COGNITIVE_ECONOMIC_OPERATOR_GUARDRAILS_OK");
