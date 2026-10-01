import assert from "node:assert/strict";
import { decideSuperautonomy, chooseTactic, portfolioPlan } from "./superautonomy-live.js";

function state(overrides={}) {
  return {
    metrics: {
      verifiedRevenueUsd:0,
      verifiedSettlements:0,
      verifiedPaidCommerceOrders:0,
      negotiating:0,
      qualifiedCommercialResponses:0,
      approvedUnsent:0,
      actionableOpportunities:0,
      activeCandidates:0,
      firstCashResponded:0,
      ...overrides.metrics
    },
    revenueFocus:{
      mode:"NORMAL_DISCOVERY",
      backlog:{closeIntent:0,followupsReady:0,...overrides.backlog}
    },
    nextEconomicAction: overrides.nextEconomicAction || "DISCOVER_AND_SCORE_NEW_OPPORTUNITIES"
  };
}

{
  const d=decideSuperautonomy(state({metrics:{activeCandidates:4}}));
  assert.equal(d.version,"2.0-superautonomy-live");
  assert.equal(d.phase,"QUALIFYING");
  assert.equal(d.humanGateRequired,false);
  assert.equal(d.authority.autonomousSpendUsd,0);
  assert.equal(d.v2Capabilities.goalManager,true);
  assert.equal(d.v2Capabilities.opportunityPortfolio,true);
  assert.equal(d.v2Capabilities.postmortems,true);
  assert.ok(d.goals.some(g=>g.id==="GOAL-VERIFIED-REVENUE"));
  assert.ok(d.goals.some(g=>g.id==="GOAL-HUMAN-ATTENTION"));
}

{
  const prev={cycle:3,stall_cycles:2,autonomy_ratio:1,state:{targetMetric:"activeCandidates",currentValue:4,selectedTactic:"discover_score_demand"}};
  const d=decideSuperautonomy(state({metrics:{activeCandidates:4}}),prev);
  assert.equal(d.stallCycles,3);
  assert.equal(d.recovery.accelerateGrowthLoop,true);
  assert.equal(d.recovery.level,2);
}

{
  const prev={cycle:4,stall_cycles:4,autonomy_ratio:1,state:{targetMetric:"activeCandidates",currentValue:4,selectedTactic:"discover_score_demand"}};
  const d=decideSuperautonomy(state({metrics:{activeCandidates:6}}),prev);
  assert.equal(d.verifiedProgress,true);
  assert.equal(d.stallCycles,0);
  assert.equal(d.recovery.level,0);
}

{
  const d=decideSuperautonomy(state({nextEconomicAction:"PURCHASE_VERIFIED_ORDER"}));
  assert.equal(d.humanGateRequired,true);
  assert.equal(d.humanGateCategory,"PURCHASE");
  assert.equal(d.humanPreflightAction,"PREPARE_PURCHASE_APPROVAL_PACKET");
  assert.equal(d.boundedAutonomyRatio,0);
  assert.equal(d.authority.autonomousPurchase,false);
  assert.equal(d.authority.bindingActionsHumanGated,true);
}

{
  const d=decideSuperautonomy(state({backlog:{closeIntent:1},metrics:{negotiating:1}}));
  assert.equal(d.phase,"CLOSING");
  assert.ok(["CLOSE_EXISTING_INTENT","PREPARE_COMPLETE_CLOSE_PACKET"].includes(d.nextAction));
}

{
  const tactic=chooseTactic("candidate_quality",{
    qualify_strongest:{score:0.4,attempts:5,wins:0,stalls:5},
    rotate_candidate:{score:1.5,attempts:2,wins:1,stalls:1}
  },3);
  assert.equal(tactic.id,"rotate_candidate");
}

{
  const plan=portfolioPlan([
    {id:"A",source_type:"SALES_PIPELINE",source_id:"1",lane:"CLOSE",stage:"NEGOTIATING",title:"A",estimated_value_usd:100,probability:.8,evidence_score:90,signal_score:90,economic_score:95,action_kind:"FIRST_CASH"},
    {id:"B",source_type:"DISCOVERY",source_id:"2",lane:"NEW_BUSINESS",stage:"qualified",title:"B",estimated_value_usd:0,probability:.3,evidence_score:70,signal_score:80,economic_score:75,action_kind:"BUILD_PROPOSAL"},
    {id:"C",source_type:"SALES_PIPELINE",source_id:"3",lane:"FOLLOW_UP",stage:"WAITING",title:"C",estimated_value_usd:50,probability:.2,evidence_score:60,signal_score:50,economic_score:65,action_kind:"FOLLOWUP"}
  ],0);
  assert.equal(plan.primary.id,"A");
  assert.equal(plan.backups.length,2);
  assert.equal(plan.rotationReady,true);
}

{
  const rows=[{debt_id:"DEBT-PURCHASE",category:"PURCHASE",hits:2,status:"OPEN"}];
  const d=decideSuperautonomy(state(),null,{openDebt:rows});
  assert.equal(d.humanAttentionDebt.open,1);
  const humanGoal=d.goals.find(g=>g.id==="GOAL-HUMAN-ATTENTION");
  assert.equal(humanGoal.current,1);
  assert.equal(humanGoal.status,"active");
}

console.log("SUPER_AUTONOMY_V2_LIVE_TESTS_OK");
