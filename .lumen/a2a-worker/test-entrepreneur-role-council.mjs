import assert from "node:assert/strict";
import { deterministicEntrepreneurCouncil, ENTREPRENEUR_POLICY } from "./entrepreneur-mode.js";

const council=deterministicEntrepreneurCouncil({
  mission:{
    hypothesis:"Sell a bounded supplier verification result to a buyer with active demand.",
    target:"qualified procurement buyer",
    businessModel:"pay-per-use supplier verification",
    nextStep:"Validate one current buyer need before preparing delivery.",
    timeToCashHours:24,
    confidence:.7,
    score:.72
  },
  hunter:{},
  founder:{},
  director:{bottleneck:"conversion"},
  truth:{verifiedRevenueUsd:0,verifiedSettlements:0},
  pressure:{pressure:"HIGH"}
});

assert.equal(council.roles.length,5);
assert.deepEqual(council.roles.map(x=>x.role),["SCOUT","FOUNDER","SELLER","GROWTH","CFO"]);
assert.equal(council.consensus.executionBoundary,"INTERNAL_RECOMMENDATION_ONLY");
assert.ok(council.consensus.smallestTest.length>0);
assert.ok(council.consensus.successMetric.length>0);
assert.ok(council.consensus.killCondition.length>0);
assert.ok(council.consensus.timeBoxHours>=1&&council.consensus.timeBoxHours<=168);
assert.equal(ENTREPRENEUR_POLICY.autonomousSpendUsd,0);
assert.equal(ENTREPRENEUR_POLICY.autonomousPurchase,false);
assert.equal(ENTREPRENEUR_POLICY.autonomousContract,false);
assert.equal(ENTREPRENEUR_POLICY.autonomousExternalPublish,false);
assert.equal(ENTREPRENEUR_POLICY.roleRecommendationsDoNotGrantExternalAuthority,true);
assert.equal(ENTREPRENEUR_POLICY.multiRoleCouncil,true);

console.log("ENTREPRENEUR_ROLE_COUNCIL_OK");
