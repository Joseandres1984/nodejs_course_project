import { WorkflowEntrypoint } from "cloudflare:workers";
import { refreshCommercialTruth } from "./adaptive-entry.js";
import { runLiveCognitiveCycle } from "./cognitive-core-live.js";
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
const MUTATING_STEP={retries:{limit:0,delay:"1 second"},timeout:"3 minutes"}; const READ_STEP={retries:{limit:2,delay:"10 seconds",backoff:"exponential"},timeout:"1 minute"};
export class LumenDeepWorkflow extends WorkflowEntrypoint { async run(event,step){const env=withBudgetedAi(this.env),id=event.instanceId; await step.do("initialize",READ_STEP,async()=>{await ensureBoostSchema(env);await recordRun(env,id,"DEEP","RUNNING");return{ok:true};});
 if(event.payload?.sovereignOnly===true){
   const sovereign=await step.do("sovereign-revenue-v4",{retries:{limit:2,delay:"5 seconds",backoff:"exponential"},timeout:"2 minutes"},()=>runSovereignCycle(env,{runId:`v4-${id}`}));
   return step.do("finish",READ_STEP,async()=>{const result={ok:sovereign?.ok===true,failed:sovereign?.ok===true?[]:["sovereign-revenue-v4"],steps:1,autonomousSpendUsd:0,verificationMode:"isolated_sovereign_canary"};await recordRun(env,id,"DEEP",result.ok?"COMPLETED":"DEGRADED",result);return result;});
 }
 const tasks=[
["verified-commercial-truth",()=>refreshCommercialTruth(env)],["cognitive-reasoning",()=>runLiveCognitiveCycle(env,{trigger:"paid_boost_hourly_workflow"})],["meta-prepare",()=>runMetaControllerCycle(env,{trigger:"paid_boost_pre_superautonomy",applyNudge:true})],["superautonomy",()=>runSuperautonomyCycle(env,{trigger:"paid_boost_hourly_workflow"})],["self-learning",()=>runSelfLearningCycle(env,{trigger:"paid_boost_after_superautonomy"})],["meta-learn",()=>runMetaControllerCycle(env,{trigger:"paid_boost_after_self_learning",applyNudge:false})],["self-critic",()=>runSelfCriticCycle(env,{trigger:"paid_boost_after_meta_learning"})],["superautonomy-v3",()=>runSuperautonomyV3Cycle(env,{trigger:"paid_boost_after_self_critic"})],["viator-conversions",()=>syncViatorBookingConversions(env)],["travel-acquisition",()=>runTravelAcquisitionEngine(env)],["growth-multiplier",()=>runGrowthMultiplierV2Cycle(env,{trigger:"paid_boost_hourly_workflow"})],["foundry-experiments",()=>runGrowthEngineFoundryV2Cycle(env,{trigger:"paid_boost_hourly_workflow"})],["growth-decision",()=>runAutonomousGrowthLoop(env,{trigger:"paid_boost_hourly_workflow",scheduledTime:event.payload.scheduledTime})],["sovereign-revenue-v4",()=>runSovereignCycle(env,{runId:`v4-${id}`})],["venture-hunter-v1",()=>runVentureHunterV1(env,{mode:"prepare_only",topK:12})],["venture-founder-v2",()=>runVentureFounderV2(env,{limit:8})],["venture-builder-v1",()=>runVentureBuilderV1(env,{limit:5})],["venture-launcher-v1",()=>runVentureLauncherV1(env,{limit:5})],["revenue-loop-v5",()=>runRevenueLoopV5Cycle(env,{trigger:"paid_boost_hourly_workflow"})],["opportunity-observers",()=>startOpportunityObservers(env)]]; const results={}; for(const [name,action] of tasks) results[name]=await step.do(name,MUTATING_STEP,()=>checkpoint(env,id,name,action)); const failed=Object.entries(results).filter(([,v])=>v?.ok===false).map(([n])=>n); return step.do("finish",READ_STEP,async()=>{const result={ok:failed.length===0,failed,steps:tasks.length,autonomousSpendUsd:0};await recordRun(env,id,"DEEP",failed.length?"DEGRADED":"COMPLETED",result);await env.DB.prepare("DELETE FROM lumen_paid_boost_steps WHERE updated_at<datetime('now','-35 days') AND status<>'RUNNING'").run();await env.DB.prepare("DELETE FROM lumen_paid_boost_runs WHERE updated_at<datetime('now','-35 days') AND status<>'RUNNING'").run();return result;});}}
export class LumenOpportunityWorkflow extends WorkflowEntrypoint {async run(event,step){const env=this.env,proposalId=event.payload.proposalId,id=event.instanceId;if(typeof proposalId!=="string"||proposalId.length>160)throw new Error("invalid_proposal_id");await step.do("initialize",READ_STEP,async()=>{await ensureBoostSchema(env);await recordRun(env,id,"OPPORTUNITY","RUNNING");return{proposalId};});for(let check=0;check<84;check++){const observation=await step.do(`observe-${check}`,READ_STEP,()=>observeOpportunity(env,proposalId,id));if(observation.paymentVerified||observation.stage==="PROPOSAL_MISSING")return step.do("finish",READ_STEP,async()=>{await recordRun(env,id,"OPPORTUNITY","COMPLETED",observation);return observation;});await step.sleep(`wait-${check}`,"1 hour");}return step.do("finish",READ_STEP,async()=>{const result={ok:true,proposalId,status:"OBSERVATION_WINDOW_COMPLETE"};await recordRun(env,id,"OPPORTUNITY","COMPLETED",result);return result;});}}
