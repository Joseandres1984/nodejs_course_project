import assert from "node:assert/strict";
import {
  deriveGrowthMotorBlueprints,
  proofForCandidate,
  scoreFoundryCandidate,
  decideCandidateLifecycle,
  chooseFoundryCandidate
} from "./growth-engine-foundry.js";

const gapBlueprints = deriveGrowthMotorBlueprints({
  topGap:{ capability:"verification", priority:90, status:"OPEN" },
  B2B:{ activeCandidates:2, quotes7d:1, negotiating:0 },
  PARTNER:{ matches:0 },
  VENTURE:{}, REFERRAL:{}, TRAVEL:{}
});
const gapMotor = gapBlueprints.find(x => x.sourceKey === "CAPABILITY_GAP");
assert.ok(gapMotor, "capability gap should create a motor candidate");
assert.deepEqual(gapMotor.primitives, ["PARTNER_NETWORK","B2B_DISCOVERY"]);
assert.ok(gapMotor.primitives.length <= 3);

const ventureBlueprints = deriveGrowthMotorBlueprints({
  topGap:null,
  B2B:{ activeCandidates:1, quotes7d:0, negotiating:0 },
  PARTNER:{ matches:0 },
  VENTURE:{ highPotential:2, review:1, ingestedPass:1 },
  REFERRAL:{}, TRAVEL:{}
});
const ventureMotor = ventureBlueprints.find(x => x.sourceKey === "VENTURE_DEMAND_BRIDGE");
assert.ok(ventureMotor, "venture evidence should create a venture-to-market candidate");
assert.deepEqual(ventureMotor.primitives, ["VENTURE_INTAKE","B2B_DISCOVERY","B2B_CONVERSION"]);

const promotedObserved = decideCandidateLifecycle({
  score:70,trials:2,positiveTrials:2,stalls:0,cumulativeDelta:5,verifiedRevenueDeltaUsd:0
}, 80);
assert.equal(promotedObserved.status, "PROMOTED");

const promotedRevenue = decideCandidateLifecycle({
  score:58,trials:1,positiveTrials:1,stalls:0,cumulativeDelta:1.5,verifiedRevenueDeltaUsd:4
}, 92);
assert.equal(promotedRevenue.status, "PROMOTED");
assert.equal(promotedRevenue.reason, "verified_economic_progress_observed");

const rejected = decideCandidateLifecycle({
  score:30,trials:4,positiveTrials:0,stalls:4,cumulativeDelta:-2,verifiedRevenueDeltaUsd:0
}, 70);
assert.equal(rejected.status, "REJECTED");

const proofBefore = proofForCandidate({ primitives:["B2B_DISCOVERY","B2B_CONVERSION"] }, {
  B2B:{ activeCandidates:2, quotes7d:1, inbound7d:0, negotiating:0, verifiedSettlements30d:0 }
});
const proofAfter = proofForCandidate({ primitives:["B2B_DISCOVERY","B2B_CONVERSION"] }, {
  B2B:{ activeCandidates:3, quotes7d:2, inbound7d:1, negotiating:1, verifiedSettlements30d:0 }
});
assert.ok(proofAfter > proofBefore, "relevant downstream progress should increase proof");

const ranked = [
  { id:"PROMOTED", status:"PROMOTED", score:75, trials:3, positive_trials:2 },
  { id:"CHALLENGER", status:"DISCOVERED", score:68, trials:0, positive_trials:0 }
];
assert.equal(chooseFoundryCandidate(ranked, 3, 80)?.id, "PROMOTED");
assert.equal(chooseFoundryCandidate(ranked, 4, 80)?.id, "CHALLENGER");

const score = scoreFoundryCandidate({
  sourceStrength:82,status:"TRIAL",positiveTrials:2,stalls:0,cumulativeDelta:6,verifiedRevenueDeltaUsd:0
}, 72);
assert.ok(score >= 60 && score <= 100);

console.log("GROWTH_ENGINE_FOUNDRY_TESTS_OK");
