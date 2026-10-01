import assert from "node:assert/strict";
import { scoreGrowthLanes, chooseGrowthAllocation, buildActivationPlan, growthProof } from "./growth-multiplier-v2.js";

function emptySnapshot() {
  return {
    B2B:{verifiedRevenueUsd30d:0,verifiedSettlements30d:0,negotiating:0,quotes7d:0,inbound7d:0,machineRequests7d:0,activeCandidates:0},
    TRAVEL:{verifiedRevenueUsd30d:0,verifiedRewards30d:0,confirmations30d:0,clicks7d:0,results7d:0,recommendedCampaigns:0},
    REFERRAL:{verifiedRevenueUsd30d:0,verifiedSettlements30d:0,paymentDue:0,agreedPendingClose:0,proposalReady:0},
    PARTNER:{partnerAgents:0,matches:0,councils:0},
    VENTURE:{highPotential:0,review:0,bestScore:0,ingestedPass:0}
  };
}

{
  const s=emptySnapshot();
  s.B2B={...s.B2B,negotiating:8,quotes7d:80,inbound7d:30,machineRequests7d:40,activeCandidates:60};
  s.TRAVEL={...s.TRAVEL,verifiedRevenueUsd30d:20,verifiedRewards30d:1,confirmations30d:1};
  const ranked=scoreGrowthLanes(s,{});
  assert.equal(ranked[0].lane,"TRAVEL","verified Travel revenue must outrank noisy B2B activity volume");
  assert.ok(ranked[0].verifiedRevenueUsd>0);
}

{
  const s=emptySnapshot();
  s.B2B={...s.B2B,negotiating:3,quotes7d:6,inbound7d:4,activeCandidates:10};
  s.TRAVEL={...s.TRAVEL,clicks7d:2,results7d:12};
  const ranked=scoreGrowthLanes(s,{});
  assert.equal(ranked[0].lane,"B2B","downstream B2B conversion evidence should lead when no verified alternative exists");
}

{
  const s=emptySnapshot();
  s.PARTNER={partnerAgents:20,matches:8,councils:4};
  s.VENTURE={highPotential:4,review:2,bestScore:88,ingestedPass:3};
  const ranked=scoreGrowthLanes(s,{});
  assert.ok(["VENTURE","PARTNER"].includes(ranked[0].lane));
  const allocation=chooseGrowthAllocation(ranked,{},2);
  assert.ok(allocation.explorationLane,"without verified revenue LUMEN should keep a bounded challenger");
  assert.notEqual(allocation.explorationLane,allocation.primaryLane);
}

{
  const s=emptySnapshot();
  s.B2B={...s.B2B,verifiedRevenueUsd30d:100,verifiedSettlements30d:2,negotiating:2};
  s.TRAVEL={...s.TRAVEL,confirmations30d:1,clicks7d:8};
  const memory={B2B:{stalls:3,learnedWeight:0}};
  const ranked=scoreGrowthLanes(s,memory);
  const allocation=chooseGrowthAllocation(ranked,memory,3);
  assert.equal(allocation.primaryLane,"B2B");
  assert.ok(allocation.explorationLane,"repeated stalls must trigger bounded exploration even when the primary lane has historic verified revenue");
  assert.equal(allocation.allocation.primary,.8);
  assert.equal(allocation.allocation.exploration,.2);
}

{
  const s=emptySnapshot();
  s.TRAVEL={...s.TRAVEL,clicks7d:5000,results7d:20000,recommendedCampaigns:20};
  s.REFERRAL={...s.REFERRAL,verifiedRevenueUsd30d:30,verifiedSettlements30d:1};
  const ranked=scoreGrowthLanes(s,{});
  assert.equal(ranked[0].lane,"REFERRAL","verified economic evidence must outrank click and discovery volume");
}

{
  const plan=buildActivationPlan({primaryLane:"B2B",explorationLane:"PARTNER",allocation:{primary:.8,exploration:.2}});
  assert.equal(plan.primary.createsExternalMessages,false);
  assert.equal(plan.primary.autonomousSpendUsd,0);
  assert.equal(plan.exploration.createsExternalMessages,false);
  assert.equal(plan.exploration.autonomousSpendUsd,0);
  assert.equal(plan.externalCommercialSlot,"not_consumed_by_growth_multiplier");
}

{
  const before=growthProof("VENTURE",{highPotential:1,review:0,bestScore:70,ingestedPass:1});
  const after=growthProof("VENTURE",{highPotential:2,review:0,bestScore:82,ingestedPass:2});
  assert.ok(after>before,"venture proof should increase when evidence-gated ideas improve");
}

console.log("GROWTH_MULTIPLIER_V2_DECISIONS_OK");
