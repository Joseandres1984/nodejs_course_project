import assert from "node:assert/strict";
import { UNIFIED_BRAIN_POLICY, scoreEconomicHypothesis, normalizeEconomicHypothesis, chooseEconomicMission, specialistPlanForMission } from "./unified-economic-brain-v1.js";

assert.equal(UNIFIED_BRAIN_POLICY.oneGlobalEconomicMission,true);
assert.equal(UNIFIED_BRAIN_POLICY.openEndedBusinessModels,true);
assert.equal(UNIFIED_BRAIN_POLICY.autonomousSpendUsd,0);
assert.equal(UNIFIED_BRAIN_POLICY.autonomousPurchase,false);
assert.equal(UNIFIED_BRAIN_POLICY.autonomousContract,false);
assert.equal(UNIFIED_BRAIN_POLICY.bindingActionsHumanGated,true);
assert.equal(UNIFIED_BRAIN_POLICY.revenueTruth,"provider_verified_settlement_only");

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

console.log("UNIFIED_ECONOMIC_BRAIN_V1_OK");
