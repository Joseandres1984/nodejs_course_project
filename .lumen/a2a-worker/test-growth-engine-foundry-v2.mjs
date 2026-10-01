import assert from "node:assert/strict";
import {
  conversionSignalForCandidate,
  computeExhaustion,
  experimentValue,
  decideExperimentWinner,
  chooseExperimentArm
} from "./growth-engine-foundry-v2.js";

const candidate = { primitives:["B2B_DISCOVERY","B2B_CONVERSION"] };
const before = conversionSignalForCandidate(candidate, {
  B2B:{ activeCandidates:10,inbound7d:3,quotes7d:1,negotiating:0,verifiedSettlements30d:0 }
});
const after = conversionSignalForCandidate(candidate, {
  B2B:{ activeCandidates:10,inbound7d:3,quotes7d:3,negotiating:2,verifiedSettlements30d:1 }
});
assert.ok(after > before, "downstream B2B conversion progress should increase the directional conversion signal");

const fresh = computeExhaustion({
  trials:2,positiveTrials:1,consecutiveNoProgress:1,lastScore:65,peakScore:68,verifiedRevenueDeltaUsd:0,cumulativeDelta:2
});
assert.equal(fresh.exhausted,false);
assert.ok(fresh.exhaustionScore < 70);

const exhausted = computeExhaustion({
  trials:7,positiveTrials:1,consecutiveNoProgress:4,lastScore:38,peakScore:75,verifiedRevenueDeltaUsd:0,cumulativeDelta:-3
});
assert.equal(exhausted.exhausted,true);
assert.ok(exhausted.exhaustionScore >= 70);

const revenueRescue = computeExhaustion({
  trials:7,positiveTrials:1,consecutiveNoProgress:4,lastScore:38,peakScore:75,verifiedRevenueDeltaUsd:12,cumulativeDelta:-3
});
assert.equal(revenueRescue.exhausted,false,"verified revenue must prevent an exhaustion declaration for the current evidence window");

assert.ok(experimentValue({runs:2,proofGain:6,conversionGain:4,revenueGainUsd:0}) > 0);

const challengerWins = decideExperimentWinner({
  champion:{runs:2,proofGain:2,conversionGain:1,revenueGainUsd:0},
  challenger:{runs:2,proofGain:8,conversionGain:5,revenueGainUsd:0}
});
assert.equal(challengerWins.winner,"CHALLENGER");

const revenueWinner = decideExperimentWinner({
  champion:{runs:2,proofGain:10,conversionGain:8,revenueGainUsd:0},
  challenger:{runs:2,proofGain:1,conversionGain:0,revenueGainUsd:2}
});
assert.equal(revenueWinner.winner,"CHALLENGER");
assert.equal(revenueWinner.reason,"verified_revenue_breaks_tie");

const inconclusive = decideExperimentWinner({
  champion:{runs:2,proofGain:1,conversionGain:0,revenueGainUsd:0},
  challenger:{runs:2,proofGain:1.1,conversionGain:0,revenueGainUsd:0}
});
assert.equal(inconclusive.winner,"INCONCLUSIVE");

assert.equal(chooseExperimentArm({cyclesObserved:0},{}),"CHAMPION");
assert.equal(chooseExperimentArm({cyclesObserved:1},{}),"CHALLENGER");
assert.equal(chooseExperimentArm({cyclesObserved:2},{championExhausted:true,challengerExhausted:false}),"CHALLENGER");
assert.equal(chooseExperimentArm({cyclesObserved:3},{championExhausted:false,challengerExhausted:true}),"CHAMPION");

console.log("GROWTH_ENGINE_FOUNDRY_V2_TESTS_OK");
