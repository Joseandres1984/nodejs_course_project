import assert from "node:assert/strict";
import { runVentureHunterV1 } from "./venture-hunter-v1.js";

const signals = [
  { id:"s1", company:"Acme", url:"https://example.com/rfq", text:"Urgent RFQ: looking for supplier quotes and market comparison for industrial parts", score:92 },
  { id:"s2", company:"Beta", text:"Need a daily price monitoring alert for competitor catalog changes", intent_score:88 },
  { id:"s3", company:"Gamma", text:"Looking to extract invoice data from PDF documents automatically", priority_score:81 },
  { id:"s4", company:"AgentCo", url:"https://example.com/agent", text:"A2A agent needs a JSON API enrichment endpoint with x402 pay per call", score:90 },
  { id:"s5", company:"TradeCo", text:"Seeking importers and distributors for export market entry", score:84 },
];

const result = await runVentureHunterV1({}, { signals, topK: 15 });
assert.equal(result.ok,true);
assert.equal(result.engine,"LUMEN Venture Hunter v1.1");
assert.equal(result.version,"1.2-microincome-scale-frontier");
assert.equal(result.signalsExamined,5);
assert.ok(result.rawIdeasGenerated>result.signalsExamined,"one demand signal should be allowed to generate multiple monetization hypotheses");
assert.ok(result.ideasGenerated<=15);
assert.ok(result.familiesCovered>=5,"frontier should cover multiple distinct monetization families");
assert.ok(result.revenueModelsCovered>=5,"frontier should explore multiple revenue mechanisms");
assert.ok(result.frontierBreadth>0);
assert.equal(result.policy.multiArchetypePerSignal,true);
assert.equal(result.policy.diversityFirstRanking,true);
assert.equal(result.policy.eventScaleRanking,true);
assert.equal(result.policy.scaleRequiresEvidence,true);
assert.equal(result.policy.scaleTargetsAreNotRevenue,true);
assert.equal(result.policy.targetScenarioEvents,10000);
assert.equal(result.policy.maxArchetypesPerSignal,3);
assert.ok(result.policy.monetizationFamiliesAvailable>=12);
assert.equal(result.policy.autonomousExternalLaunch,false);
assert.equal(result.policy.autonomousSpending,false);
assert.equal(result.policy.autonomousContracting,false);
assert.equal(result.policy.bindingActionsHumanGated,true);
assert.ok(result.topOpportunity.metrics.score>0.6);
assert.ok(["BUILD_CANDIDATE","VALIDATE"].includes(result.topOpportunity.status));
assert.ok(result.ideas.some(x=>x.revenueModel==="x402_pay_per_call_or_task" || x.revenueModel==="x402_pay_per_call"),"agent-native pay-per-use must be part of the opportunity frontier");
assert.ok(result.ideas.some(x=>x.monetizationFamily==="trade_intelligence"),"export/trade intelligence must be represented when demand evidence exists");
assert.ok(result.highScaleIdeas>0);
assert.ok(result.veryHighScaleIdeas>0);
assert.ok(result.bestScaleCandidate.metrics.scalePotential>0.5);
assert.equal(result.bestScaleCandidate.metrics.scaleTruth,"target_scenario_not_realized_revenue");
assert.equal(result.scaleScenario.targetEvents,10000);
assert.equal(result.scaleScenario.realizedRevenueClaim,false);
const apiIdea=result.ideas.find(x=>x.revenueModel==="x402_pay_per_call_or_task" || x.revenueModel==="x402_pay_per_call");
assert.ok(apiIdea);
assert.equal(apiIdea.metrics.monetizableEvent==="api_call" || apiIdea.metrics.monetizableEvent==="agent_task_or_tool_call",true);
assert.ok(apiIdea.metrics.tenThousandEventRevenueTargetUsd>=10000);
console.log(JSON.stringify({
  ok:true,
  familiesCovered:result.familiesCovered,
  revenueModelsCovered:result.revenueModelsCovered,
  top:result.topOpportunity,
  policy:result.policy
}, null, 2));
