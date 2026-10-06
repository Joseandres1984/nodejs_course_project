import assert from "node:assert/strict";
import {
  UNIFIED_BRAIN_POLICY,
  scoreEconomicHypothesis,
  normalizeEconomicHypothesis,
  chooseEconomicMission,
  specialistPlanForMission,
  detectEconomicBottleneck,
  learningAdjustment,
  isDemandFocusedHypothesis
} from "./unified-economic-brain-v1.js";

assert.equal(UNIFIED_BRAIN_POLICY.version,"1.1-demand-conversion-learning");
assert.equal(UNIFIED_BRAIN_POLICY.oneGlobalEconomicMission,true);
assert.equal(UNIFIED_BRAIN_POLICY.openEndedBusinessModels,true);
assert.equal(UNIFIED_BRAIN_POLICY.autonomousSpendUsd,0);
assert.equal(UNIFIED_BRAIN_POLICY.autonomousPurchase,false);
assert.equal(UNIFIED_BRAIN_POLICY.autonomousContract,false);
assert.equal(UNIFIED_BRAIN_POLICY.bindingActionsHumanGated,true);
assert.equal(UNIFIED_BRAIN_POLICY.revenueTruth,"provider_verified_settlement_only");
assert.equal(UNIFIED_BRAIN_POLICY.sentIsNotSuccess,true);
assert.equal(UNIFIED_BRAIN_POLICY.demandFirstWhenBuyerEvidenceZero,true);
assert.equal(UNIFIED_BRAIN_POLICY.persistentFunnelMemory,true);
assert.equal(UNIFIED_BRAIN_POLICY.strategyMemoryAffectsSelection,true);
assert.equal(UNIFIED_BRAIN_POLICY.monetizationFrontier,true);
assert.equal(UNIFIED_BRAIN_POLICY.distinctBusinessModelExploration,true);
assert.equal(UNIFIED_BRAIN_POLICY.frontierExplorationEscapesCurrentBottleneck,true);
assert.equal(UNIFIED_BRAIN_POLICY.maxAiHypotheses,5);
assert.equal(UNIFIED_BRAIN_POLICY.parallelMonetizationObservation,true);
assert.equal(UNIFIED_BRAIN_POLICY.travelAffiliateEconomicLearning,true);
assert.equal(UNIFIED_BRAIN_POLICY.clickIsWeakSignalNotRevenue,true);
assert.equal(UNIFIED_BRAIN_POLICY.confirmedBookingIsConversionNotCash,true);
assert.equal(UNIFIED_BRAIN_POLICY.verifiedAffiliatePayoutIsRevenue,true);
assert.equal(UNIFIED_BRAIN_POLICY.microincomeScaleEngine,true);
assert.equal(UNIFIED_BRAIN_POLICY.scaleRequiresEvidence,true);
assert.equal(UNIFIED_BRAIN_POLICY.projectedScaleIsNotRevenue,true);
assert.equal(UNIFIED_BRAIN_POLICY.targetScaleEvents,10000);
assert.equal(UNIFIED_BRAIN_POLICY.microincomeScaleEngine,true);
assert.equal(UNIFIED_BRAIN_POLICY.scaleRequiresEvidence,true);
assert.equal(UNIFIED_BRAIN_POLICY.projectedScaleIsNotRevenue,true);
assert.equal(UNIFIED_BRAIN_POLICY.targetScaleEvents,10000);

const fast=normalizeEconomicHypothesis({
  id:"fast",business_model:"novel zero-capital B2B information exchange",hypothesis:"Sell a verified information outcome to observed demand",execution_lane:"VENTURE",
  expected_profit_usd:100,probability_of_sale:.7,time_to_cash_hours:12,capital_required_usd:0,
  evidence_strength:.8,confidence:.75,novelty:.8,risk:.2,reversibility:.95
});
const slow=normalizeEconomicHypothesis({
  id:"slow",business_model:"slow experiment",hypothesis:"Validate a weak signal",execution_lane:"DISCOVERY",
  expected_profit_usd:100,probability_of_sale:.2,time_to_cash_hours:720,capital_required_usd:0,
  evidence_strength:.3,confidence:.3,novelty:.4,risk:.4,reversibility:.9
});
assert.ok(scoreEconomicHypothesis(fast)>scoreEconomicHypothesis(slow),"economic score must prefer stronger faster evidence");

const demand=normalizeEconomicHypothesis({
  id:"demand",business_model:"verified buyer demand acquisition",hypothesis:"Find an explicit RFQ from a current buyer",target:"buyer with active procurement need",execution_lane:"DISCOVERY",
  probability_of_sale:.35,time_to_cash_hours:36,evidence_strength:.8,confidence:.8,novelty:.45,risk:.08,reversibility:.99
});
const supply=normalizeEconomicHypothesis({
  id:"supply",business_model:"generic catalog expansion",hypothesis:"Expand supplier catalog breadth and publish more generic supply",target:"generic supplier market",execution_lane:"COMMERCE",
  probability_of_sale:.8,time_to_cash_hours:12,evidence_strength:.9,confidence:.9,novelty:.7,risk:.1,reversibility:.99
});
assert.equal(isDemandFocusedHypothesis(demand),true);
assert.ok(scoreEconomicHypothesis(demand,{bottleneck:"DEMAND"})>scoreEconomicHypothesis(demand,{}));
assert.ok(scoreEconomicHypothesis(supply,{bottleneck:"DEMAND"})<scoreEconomicHypothesis(supply,{}));
assert.equal(chooseEconomicMission([supply,demand],"1",{bottleneck:"DEMAND"}).id,"demand");

assert.equal(detectEconomicBottleneck({}),"DEMAND");
assert.equal(detectEconomicBottleneck({qualifiedCommercialCandidates:2}),"PROPOSAL");
assert.equal(detectEconomicBottleneck({proposals:2}),"OUTBOUND");
assert.equal(detectEconomicBottleneck({sent:2}),"DELIVERY_OR_RESPONSE");
assert.equal(detectEconomicBottleneck({verifiedResponses:1}),"CLOSE");
assert.equal(detectEconomicBottleneck({verifiedSettlements:1}),"REPEAT_WINNER");

assert.ok(
  learningAdjustment(demand,{attempts:5,reward:120},{bottleneck:"DEMAND"})
  > learningAdjustment(demand,{attempts:5,reward:-10},{bottleneck:"DEMAND"})
);

const unsafe=normalizeEconomicHypothesis({
  id:"unsafe",business_model:"buy inventory then resell",hypothesis:"Purchase stock first",execution_lane:"COMMERCE",
  capital_required_usd:25,probability_of_sale:.9,time_to_cash_hours:4,evidence_strength:.9,confidence:.9,novelty:.9,risk:.1,reversibility:.9
});
assert.equal(unsafe.executionLane,"HOLD");
assert.equal(unsafe.score,0);
assert.equal(unsafe.safetyOverride,"requires_human_authority_or_nonzero_capital");

const binding=normalizeEconomicHypothesis({
  id:"binding",business_model:"service",hypothesis:"sign contract automatically",execution_lane:"REVENUE",capital_required_usd:0
});
assert.equal(binding.executionLane,"HOLD");

const sellerMonetization=normalizeEconomicHypothesis({
  id:"seller-monetization",business_model:"x402 pay-per-use API",hypothesis:"Buyer pays per successful API call",next_step:"Expose a paid endpoint through the existing payment rail",execution_lane:"VENTURE",capital_required_usd:0
});
assert.notEqual(sellerMonetization.executionLane,"HOLD","seller-side pay-per-use language must not be mistaken for autonomous spend");

const scalableEvidence=normalizeEconomicHypothesis({
  id:"scalable-evidence",
  business_model:"x402 paid API",
  hypothesis:"Sell a repeatable API result to observed machine demand",
  execution_lane:"VENTURE",
  probability_of_sale:.35,
  time_to_cash_hours:24,
  evidence_strength:.85,
  confidence:.75,
  novelty:.7,
  risk:.08,
  reversibility:.99,
  monetizable_event:"api_call",
  unit_revenue_target_usd:1,
  scale_potential:.98,
  repeatability:1,
  distribution_leverage:1,
  marginal_cost_efficiency:.98,
  target_scale_events:10000,
  projected_scale_revenue_usd:10000
});
const scalableWeak=normalizeEconomicHypothesis({
  id:"scalable-weak",
  business_model:"hypothetical viral API",
  hypothesis:"Maybe sell a repeatable API someday",
  execution_lane:"VENTURE",
  probability_of_sale:.35,
  time_to_cash_hours:24,
  evidence_strength:.10,
  confidence:.40,
  novelty:.9,
  risk:.08,
  reversibility:.99,
  monetizable_event:"api_call",
  unit_revenue_target_usd:1,
  scale_potential:.98,
  repeatability:1,
  distribution_leverage:1,
  marginal_cost_efficiency:.98,
  target_scale_events:10000,
  projected_scale_revenue_usd:10000
});
assert.equal(scalableEvidence.targetScaleEvents,10000);
assert.equal(scalableEvidence.projectedScaleRevenueUsd,10000);
assert.ok(scoreEconomicHypothesis(scalableEvidence)>scoreEconomicHypothesis(scalableWeak),"scale must be discounted when evidence is weak");

const scaleWeak=normalizeEconomicHypothesis({
  id:"scale-weak",business_model:"x402 utility",hypothesis:"Potentially repeatable API",execution_lane:"VENTURE",
  probability_of_sale:.25,time_to_cash_hours:48,evidence_strength:.1,confidence:.3,novelty:.7,risk:.1,reversibility:.99,
  monetizable_event:"api_call",unit_revenue_target_usd:1,scale_potential:1,repeatability:1,distribution_leverage:1,marginal_cost_efficiency:.98,target_scale_events:10000,projected_scale_revenue_usd:10000
});
const scaleStrong=normalizeEconomicHypothesis({
  id:"scale-strong",business_model:"x402 utility",hypothesis:"Observed repeatable API demand",execution_lane:"VENTURE",
  probability_of_sale:.25,time_to_cash_hours:48,evidence_strength:.9,confidence:.7,novelty:.7,risk:.1,reversibility:.99,
  monetizable_event:"api_call",unit_revenue_target_usd:1,scale_potential:1,repeatability:1,distribution_leverage:1,marginal_cost_efficiency:.98,target_scale_events:10000,projected_scale_revenue_usd:10000
});
assert.equal(scaleStrong.targetScaleEvents,10000);
assert.equal(scaleStrong.projectedScaleRevenueUsd,10000);
assert.equal(scaleStrong.monetizableEvent,"api_call");
assert.ok(scoreEconomicHypothesis(scaleStrong)>scoreEconomicHypothesis(scaleWeak),"scale may help only when evidence exists");

const outgoingPayment=normalizeEconomicHypothesis({
  id:"outgoing-payment",business_model:"service",hypothesis:"Pay vendor fee automatically",execution_lane:"COMMERCE",capital_required_usd:0
});
assert.equal(outgoingPayment.executionLane,"HOLD","autonomous outgoing payment language must remain blocked");

const exploit=chooseEconomicMission([fast,slow],"1");
assert.equal(exploit.id,"fast");
assert.equal(exploit.selectionMode,"EXPLOIT");

const novel=normalizeEconomicHypothesis({
  id:"novel",business_model:"new pattern",hypothesis:"Test a new reversible zero-capital path",execution_lane:"EXPLORE",
  probability_of_sale:.12,time_to_cash_hours:96,evidence_strength:.25,confidence:.4,novelty:1,risk:.25,reversibility:.98
});
const frontier=normalizeEconomicHypothesis({
  id:"frontier",business_model:"x402 pay-per-use agent utility",hypothesis:"Expose a new paid agent-native API capability",target:"machine customers",execution_lane:"VENTURE",
  probability_of_sale:.18,time_to_cash_hours:72,evidence_strength:.35,confidence:.45,novelty:.99,risk:.15,reversibility:.99,
  monetizable_event:"agent_task_or_tool_call",unit_revenue_target_usd:1,scale_potential:.98,repeatability:1,distribution_leverage:1,marginal_cost_efficiency:.98,target_scale_events:10000,projected_scale_revenue_usd:10000
});
let explorationKey=null;
for(let i=0;i<100;i++){
  const key=String(i);
  if(chooseEconomicMission([fast,novel],key).selectionMode==="EXPLORE"){ explorationKey=key; break; }
}
assert.ok(explorationKey!==null,"bounded exploration slot must exist");
assert.equal(chooseEconomicMission([fast,novel],explorationKey).id,"novel");
const frontierDuringDemandGap=chooseEconomicMission([demand,frontier],explorationKey,{bottleneck:"DEMAND"});
assert.equal(frontierDuringDemandGap.selectionMode,"EXPLORE");
assert.equal(frontierDuringDemandGap.id,"frontier","bounded exploration must be able to leave the current bottleneck and search new monetization models");

const travelLive=normalizeEconomicHypothesis({
  id:"travel-live",business_model:"travel affiliate commission",hypothesis:"Convert measured travel clicks into attributable affiliate bookings",target:"travel buyer intent",execution_lane:"TRAVEL",
  probability_of_sale:.62,time_to_cash_hours:24,evidence_strength:.9,confidence:.88,novelty:.35,risk:.05,reversibility:.99
});
const travelCompetes=chooseEconomicMission([demand,travelLive],"1",{bottleneck:"DEMAND",travelMonetization:{commercialSignal:true}});
assert.equal(travelCompetes.id,"travel-live","a Travel lane with measured commercial signal must compete with generic demand discovery during exploitation");


const revenuePlan=specialistPlanForMission({executionLane:"REVENUE"});
assert.equal(revenuePlan.revenue,true);
assert.equal(revenuePlan.venture,false);
assert.equal(revenuePlan.commerce,false);

const discoveryPlan=specialistPlanForMission({executionLane:"DISCOVERY"});
assert.equal(discoveryPlan.revenue,true);
assert.equal(discoveryPlan.growthDiscovery,true);

const explorePlan=specialistPlanForMission({executionLane:"EXPLORE"});
assert.equal(explorePlan.revenue,true);
assert.equal(explorePlan.venture,true);
assert.equal(explorePlan.commerce,true);
assert.equal(explorePlan.travel,true);
assert.equal(explorePlan.growthDiscovery,true);

const fallback=chooseEconomicMission([],"fallback");
assert.equal(fallback.executionLane,"EXPLORE");
assert.equal(fallback.capitalRequiredUsd,0);
assert.ok(fallback.novelty>=.9);

console.log("UNIFIED_ECONOMIC_BRAIN_DEMAND_LEARNING_OK");
