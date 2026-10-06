import { WorkflowEntrypoint } from "cloudflare:workers";
import { refreshCommercialTruth } from "./adaptive-entry.js";
import { runMetaControllerCycle } from "./meta-controller.js";
import { runSuperautonomyCycle } from "./superautonomy-live.js";
import { runSelfLearningCycle } from "./self-learning-engine.js";
import { runSelfCriticCycle } from "./teacher-self-critic.js";
import { runSuperautonomyV3Cycle } from "./superautonomy-v3.js";
import { runGrowthMultiplierV2Cycle } from "./growth-multiplier-v2.js";
import { runGrowthEngineFoundryV2Cycle } from "./growth-engine-foundry-v2.js";
import { runAutonomousGrowthLoop } from "./autonomous-growth-loop-v11.js";
import { syncViatorBookingConversions } from "./viator-conversion-sync.js";
import { runTravelAcquisitionEngine } from "./travel-acquisition-engine.js";
import { withBudgetedAi } from "./ai-router.js";
import { ensureBoostSchema, checkpoint, recordRun, startOpportunityObservers, observeOpportunity } from "./paid-boost-runtime.js";
import { runSovereignCycle } from "./sovereign-runtime.js";
import { runRevenueLoopV5Cycle } from "./revenue-loop-v5.js";
import { runVentureHunterV1 } from "./venture-hunter-v1.js";
import { runVentureFounderV2 } from "./venture-founder-v2.js";
import { runVentureBuilderV1 } from "./venture-builder-v1.js";
import { runVentureLauncherV1 } from "./venture-launcher-v1.js";
import { runSupplierMarketLaunchEvolution } from "./supplier-market-launch.js";
import { runUnifiedEconomicBrain, specialistPlanForMission } from "./unified-economic-brain-v1.js";

const MUTATING_STEP={retries:{limit:0,delay:"1 second"},timeout:"3 minutes"};
const READ_STEP={retries:{limit:2,delay:"10 seconds",backoff:"exponential"},timeout:"1 minute"};

async function runChecked(env,id,name,action){
  return checkpoint(env,id,name,action);
}

export class LumenDeepWorkflow extends WorkflowEntrypoint {
  async run(event,step){
    const env=withBudgetedAi(this.env),id=event.instanceId;
    await step.do("initialize",READ_STEP,async()=>{await ensureBoostSchema(env);await recordRun(env,id,"DEEP","RUNNING");return{ok:true};});
    if(event.payload?.sovereignOnly===true){
      const sovereign=await step.do("sovereign-revenue-v4",{retries:{limit:2,delay:"5 seconds",backoff:"exponential"},timeout:"2 minutes"},()=>runSovereignCycle(env,{runId:`v4-${id}`}));
      return step.do("finish",READ_STEP,async()=>{const result={ok:sovereign?.ok===true,failed:sovereign?.ok===true?[]:["sovereign-revenue-v4"],steps:1,autonomousSpendUsd:0,verificationMode:"isolated_sovereign_canary"};await recordRun(env,id,"DEEP",result.ok?"COMPLETED":"DEGRADED",result);return result;});
    }

    const results={};
    results["verified-commercial-truth"]=await step.do("verified-commercial-truth",MUTATING_STEP,()=>runChecked(env,id,"verified-commercial-truth",()=>refreshCommercialTruth(env)));
    results["venture-hunter-v1"]=await step.do("venture-hunter-v1",MUTATING_STEP,()=>runChecked(env,id,"venture-hunter-v1",()=>runVentureHunterV1(env,{mode:"prepare_only",topK:12})));
    results["viator-conversions-observe"]=await step.do("viator-conversions-observe",MUTATING_STEP,()=>runChecked(env,id,"viator-conversions-observe",async()=>{const x=await syncViatorBookingConversions(env);return x?.skipped?{...x,ok:true,observationSkipped:true}:x;}));
    results["unified-economic-brain-v1"]=await step.do("unified-economic-brain-v1",MUTATING_STEP,()=>runChecked(env,id,"unified-economic-brain-v1",()=>runUnifiedEconomicBrain(env,{trigger:"paid_boost_hourly_workflow",scheduledTime:event.payload.scheduledTime})));

    const brain=results["unified-economic-brain-v1"];
    const plan=brain?.plan || specialistPlanForMission(brain?.mission || {executionLane:"EXPLORE"});
    const tasks=[];

    if(plan.learning){
      tasks.push(["meta-prepare",()=>runMetaControllerCycle(env,{trigger:"brain_governed_pre_execution",applyNudge:true})]);
      tasks.push(["self-learning",()=>runSelfLearningCycle(env,{trigger:"brain_governed_learning"})]);
      tasks.push(["meta-learn",()=>runMetaControllerCycle(env,{trigger:"brain_governed_post_learning",applyNudge:false})]);
      tasks.push(["self-critic",()=>runSelfCriticCycle(env,{trigger:"brain_governed_self_critic"})]);
    }
    if(plan.growthDiscovery){
      tasks.push(["superautonomy",()=>runSuperautonomyCycle(env,{trigger:"unified_brain_discovery"})]);
      tasks.push(["superautonomy-v3",()=>runSuperautonomyV3Cycle(env,{trigger:"unified_brain_discovery"})]);
      tasks.push(["growth-multiplier",()=>runGrowthMultiplierV2Cycle(env,{trigger:"unified_brain_discovery"})]);
      tasks.push(["foundry-experiments",()=>runGrowthEngineFoundryV2Cycle(env,{trigger:"unified_brain_discovery"})]);
      tasks.push(["growth-decision",()=>runAutonomousGrowthLoop(env,{trigger:"unified_brain_discovery",scheduledTime:event.payload.scheduledTime})]);
    }
    if(plan.venture){
      tasks.push(["venture-founder-v2",()=>runVentureFounderV2(env,{limit:8})]);
      tasks.push(["venture-builder-v1",()=>runVentureBuilderV1(env,{limit:5})]);
      tasks.push(["venture-launcher-v1",()=>runVentureLauncherV1(env,{limit:5})]);
    }
    if(plan.commerce){
      tasks.push(["supplier-market-launch",()=>runSupplierMarketLaunchEvolution(env)]);
    }
    if(plan.travel){
      tasks.push(["travel-acquisition",()=>runTravelAcquisitionEngine(env)]);
    }
    if(plan.revenue){
      tasks.push(["sovereign-revenue-v4",()=>runSovereignCycle(env,{runId:`v4-${id}`})]);
      tasks.push(["revenue-loop-v5",()=>runRevenueLoopV5Cycle(env,{trigger:"unified_brain_revenue"})]);
      tasks.push(["opportunity-observers",()=>startOpportunityObservers(env)]);
    }

    for(const [name,action] of tasks) results[name]=await step.do(name,MUTATING_STEP,()=>runChecked(env,id,name,action));
    const failed=Object.entries(results).filter(([,v])=>v?.ok===false).map(([n])=>n);
    return step.do("finish",READ_STEP,async()=>{
      const result={ok:failed.length===0,failed,steps:Object.keys(results).length,autonomousSpendUsd:0,brain:{version:brain?.version||null,missionId:brain?.mission?.id||null,lane:brain?.mission?.executionLane||plan.lane||null,selectionMode:brain?.mission?.selectionMode||null,hypothesesConsidered:brain?.hypothesesConsidered||null},specialistPlan:plan};
      await recordRun(env,id,"DEEP",failed.length?"DEGRADED":"COMPLETED",result);
      await env.DB.prepare("DELETE FROM lumen_paid_boost_steps WHERE updated_at<datetime('now','-35 days') AND status<>'RUNNING'").run();
      await env.DB.prepare("DELETE FROM lumen_paid_boost_runs WHERE updated_at<datetime('now','-35 days') AND status<>'RUNNING'").run();
      return result;
    });
  }
}

export class LumenOpportunityWorkflow extends WorkflowEntrypoint {
  async run(event,step){
    const env=this.env,proposalId=event.payload.proposalId,id=event.instanceId;
    if(typeof proposalId!=="string"||proposalId.length>160)throw new Error("invalid_proposal_id");
    await step.do("initialize",READ_STEP,async()=>{await ensureBoostSchema(env);await recordRun(env,id,"OPPORTUNITY","RUNNING");return{proposalId};});
    for(let check=0;check<84;check++){
      const observation=await step.do(`observe-${check}`,READ_STEP,()=>observeOpportunity(env,proposalId,id));
      if(observation.paymentVerified||observation.stage==="PROPOSAL_MISSING")return step.do("finish",READ_STEP,async()=>{await recordRun(env,id,"OPPORTUNITY","COMPLETED",observation);return observation;});
      await step.sleep(`wait-${check}`,"1 hour");
    }
    return step.do("finish",READ_STEP,async()=>{const result={ok:true,proposalId,status:"OBSERVATION_WINDOW_COMPLETE"};await recordRun(env,id,"OPPORTUNITY","COMPLETED",result);return result;});
  }
}
