import assert from "node:assert/strict";
import { decideSuperautonomy } from "./superautonomy-live.js";

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
  assert.equal(d.phase,"QUALIFYING");
  assert.equal(d.nextAction,"QUALIFY_STRONGEST_CANDIDATE");
  assert.equal(d.humanGateRequired,false);
  assert.equal(d.authority.autonomousSpendUsd,0);
}

{
  const prev={cycle:3,stall_cycles:2,autonomy_ratio:1,state:{targetMetric:"activeCandidates",currentValue:4}};
  const d=decideSuperautonomy(state({metrics:{activeCandidates:4}}),prev);
  assert.equal(d.stallCycles,3);
  assert.equal(d.recovery.accelerateGrowthLoop,true);
  assert.equal(d.recovery.level,2);
}

{
  const prev={cycle:4,stall_cycles:4,autonomy_ratio:1,state:{targetMetric:"activeCandidates",currentValue:4}};
  const d=decideSuperautonomy(state({metrics:{activeCandidates:6}}),prev);
  assert.equal(d.verifiedProgress,true);
  assert.equal(d.stallCycles,0);
  assert.equal(d.recovery.level,0);
}

{
  const d=decideSuperautonomy(state({nextEconomicAction:"PURCHASE_VERIFIED_ORDER"}));
  assert.equal(d.humanGateRequired,true);
  assert.equal(d.boundedAutonomyRatio,0);
  assert.equal(d.authority.autonomousPurchase,false);
  assert.equal(d.authority.bindingActionsHumanGated,true);
}

{
  const d=decideSuperautonomy(state({backlog:{closeIntent:1},metrics:{negotiating:1}}));
  assert.equal(d.phase,"CLOSING");
  assert.equal(d.nextAction,"CLOSE_EXISTING_INTENT");
}

console.log("SUPER_AUTONOMY_LIVE_TESTS_OK");
