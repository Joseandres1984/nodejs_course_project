import assert from "node:assert/strict";
import { UNIFIED_BRAIN_POLICY, scoreEconomicHypothesis, normalizeEconomicHypothesis, chooseEconomicMission, specialistPlanForMission, detectEconomicBottleneck, learningAdjustment, isDemandFocusedHypothesis } from "./unified-economic-brain-v1.js";

assert.equal(UNIFIED_BRAIN_POLICY.oneGlobalEconomicMission,true);
assert.equal(UNIFIED_BRAIN_POLICY.openEndedBusinessModels,true);
assert.equal(UNIFIED_BRAIN_POLICY.autonomousSpendUsd,0);
assert.equal(UNIFIED_BRAIN_POLICY.autonomousPurchase,false);
assert.equal(UNIFIED_BRAIN_POLICY.autonomousContract,false);
assert.equal(UNIFIED_BRAIN_POLICY.bindingActionsHumanGated,true);
assert.equal(UNIFIED_BRAIN_POLICY.revenueTruth,"provider_verified_settlement_only");
assert.equal(UNIFIED_BRAIN_POLICY.version,"1.1-demand-conversion-learning");
assert.equal(UNIFIED_BRAIN_POLICY.sentIsNotSuccess,true);
assert.equal(UNIFIED_BRAIN_POLICY.demandFirstWhenBuyerEvidenceZero,true);
assert.equal(UNIFIED_BRAIN_POLICY.persistentFunnelMemory,true);
assert.equal(UNIFIED_BRAIN_POLICY.strategyMemoryAffectsSelection,true);

const fast=normalizeEconomicHypothesis({
  id:"fast", business_model:"novel zero-capital B2B information exchange", hypothesis:"Sell a verified information outcome to observed demand", execution_lane:"VENTURE",
  expected_profit_usd:100, probability_of_sale:.7, time_to_cash_hours:12, capital_required_usd:0,
  evidence_strength:.8, confidence:.75, novelty:.8, risk:.2, reversibility:.95
});
const slow=normalizeEconomicHypothesis({
  id:"slow", business_model:"slow experiment", hypothesis:"Validate a weak signal", execution_lane:"DISCOVERY",
  expected_profit_usd:100, probability_of_sale:.2, time_to_cash_hours:720, capital_required_usd:0,
  evidence_strength:.3, confidence:.3, novelty:.4, risk:.4, reversibility:.9
});
assert.ok(scoreEconomicHypothesis(fast)>scoreEconomicHypothesis(slow),"economic score must prefer stronger faster evidence");

const demand=normalizeEconomicHypothesis({
  id:"demand",business_model:"verified buyer demand acquisition",hypothesis:"Find an explicit RFQ from a current buyer",target:"buyer with active procurement need",execution_lane:"DISCOVERY",
  probability_of_sale:.35,time_to_cash_hours:36,evidence_strength:.8,confidence:.8,novelty:.45,risk:.08,reversibility:.99
});
const shinySupply=normalizeEconomicHypothesis({
  id:"shiny-supply",business_model:"new supplier catalog expansion",hypothesis:"Expand a catalog without current buyer evidence",target:"generic supplier market",execution_lane:"COMMERCE",
  probability_of_sale:.55,time_to_cash_hours:24,evidence_strength:.7,confidence:.75,novelty:.8,risk:.1,reversibility:.95
});

assert.equal(isDemandFocusedHypothesis(demand),true);
assert.equal(detectEconomicBottleneck({}),"DEMAND");
assert.equal(detectEconomicBottleneck({qualifiedCommercialCandidates:3}),"PROPOSAL");
assert.equal(detectEconomicBottleneck({proposals:2}),"OUTBOUND");
assert.equal(detectEconomicBottleneck({sent:2}),"DELIVERY_OR_RESPONSE");
assert.equal(detectEconomicBottleneck({verifiedResponses:1}),"CLOSE");
assert.equal(detectEconomicBottleneck({verifiedSettlements:1}),"REPEAT_WINNER");
assert.ok(scoreEconomicHypothesis(demand,{bottleneck:"DEMAND"}) > scoreEconomicHypothesis(demand,{}),"demand bottleneck must boost demand-focused hypotheses");
assert.ok(scoreEconomicHypothesis(shinySupply,{bottleneck:"DEMAND"}) < scoreEconomicHypothesis(shinySupply,{}),"demand bottleneck must suppress unrelated supply expansion");
assert.ok(learningAdjustment(fast,{attempts:5,reward:120},{bottleneck:"CLOSE"}) > learningAdjustment(fast,{attempts:5,reward:-10},{bottleneck:"CLOSE"}),"strategy memory must reward evidence-backed progress and penalize stagnation");

const unsafe=normalizeEconomicHypothesis({
  id:"unsafe", business_model:"buy inventory then resell", hypothesis:"Purchase stock first", execution_lane:"COMMERCE",
  capital_required_usd:25, probability_of_sale:.9, time_to_cash_hours:4, evidence_strength:.9, confidence:.9, novelty:.9, risk:.1, reversibility:.9
});
assert.equal(unsafe.executionLane,"HOLD");
assert.equal(unsafe.score,0);
assert.equal(unsafe.safetyOverride,"requires_human_authority_or_nonzero_capital");

const binding=normalizeEconomicHypothesis({
  id:"binding", business_model:"service", hypothesis:"sign contract automatically", execution_lane:"REVENUE", capital_required_usd:0
});
assert.equal(binding.executionLane,"HOLD");

const exploit=chooseEconomicMission([fast,slow],"1");
assert.equal(exploit.id,"fast");
assert.equal(exploit.selectionMode,"EXPLOIT");

const demandFirst=chooseEconomicMission([shinySupply,demand],"1",{bottleneck:"DEMAND"});
assert.equal(demandFirst.id,"demand");

const novel=normalizeEconomicHypothesis({
  id:"novel",business_model:"new pattern",hypothesis:"Test a new reversible zero-capital path",execution_lane:"EXPLORE",
  probability_of_sale:.12,time_to_cash_hours:96,evidence_strength:.25,confidence:.4,novelty:1,risk:.25,reversibility:.98
});
let explorationKey=null;
for(let i=0;i<100;i++){
  const key=String(i);
  if(chooseEconomicMission([fast,novel],key).selectionMode==="EXPLORE"){ explorationKey=key; break; }
}
assert.ok(explorationKey!==null,"bounded exploration slot must exist");
assert.equal(chooseEconomicMission([fast,novel],explorationKey).id,"novel");

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
