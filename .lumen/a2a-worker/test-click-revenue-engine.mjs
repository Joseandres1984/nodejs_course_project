import assert from "node:assert/strict";
import {
  CLICK_REVENUE_POLICY,
  normalizeClickProgram,
  scoreClickProgram,
  buildTrackedDestination
} from "./click-revenue-engine.js";

assert.equal(CLICK_REVENUE_POLICY.targetScaleEvents, 10000);
assert.equal(CLICK_REVENUE_POLICY.clickIsRevenue, false);
assert.equal(CLICK_REVENUE_POLICY.providerVerifiedPayoutIsRevenue, true);
assert.equal(CLICK_REVENUE_POLICY.syntheticClicksForbidden, true);
assert.equal(CLICK_REVENUE_POLICY.selfClicksForbidden, true);
assert.equal(CLICK_REVENUE_POLICY.autonomousSpendUsd, 0);

const inactive = normalizeClickProgram({
  id:"demo-cpc",
  provider:"Demo",
  model:"CPC",
  trackingUrl:"https://example.com/offer",
  approved:false,
  termsVerified:true,
  expectedCpcUsd:0.25
});
assert.equal(inactive.active, false);

const active = normalizeClickProgram({
  id:"demo-cpc",
  provider:"Demo",
  model:"CPC",
  trackingUrl:"https://example.com/offer?campaign=x",
  approved:true,
  termsVerified:true,
  clickIdParam:"subid",
  expectedCpcUsd:0.25
});
assert.equal(active.active, true);
const destination = buildTrackedDestination(active,"CLK-123");
assert.equal(new URL(destination).searchParams.get("subid"),"CLK-123");
assert.equal(new URL(destination).hostname,"example.com");

const wrongModel = normalizeClickProgram({
  id:"demo-cpa",
  provider:"Demo",
  model:"CPA",
  trackingUrl:"https://example.com/offer",
  approved:true,
  termsVerified:true
});
assert.equal(wrongModel.active, false);

const untrusted = normalizeClickProgram({
  id:"local",
  model:"CPC",
  trackingUrl:"http://127.0.0.1/test",
  approved:true,
  termsVerified:true
});
assert.equal(untrusted.active, false);

assert(scoreClickProgram(active,{observedClicks:100,verifiedPaidClicks:10,verifiedEpcUsd:0.20}) >
       scoreClickProgram(inactive,{observedClicks:0,verifiedPaidClicks:0,verifiedEpcUsd:0}));

console.log("CLICK_REVENUE_LANE_POLICY_AND_ROUTING_OK");
