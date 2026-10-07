import { withBudgetedAi } from "./ai-router.js";
import { runUnifiedEconomicBrain, getUnifiedBrainStatus, UNIFIED_BRAIN_POLICY } from "./unified-economic-brain-v1.js";
import { runVentureHunterV1 } from "./venture-hunter-v1.js";
import { runVentureFounderV2 } from "./venture-founder-v2.js";
import { runVentureBuilderV1 } from "./venture-builder-v1.js";
import { runVentureLauncherV1 } from "./venture-launcher-v1.js";
import { recomputeRevenueDirector } from "./revenue-director.js";

const VERSION = "1.2-entrepreneur-commercial-steering";
const ROLES = Object.freeze([
  { id:"SCOUT", objective:"find current demand and overlooked zero-capital monetization signals" },
  { id:"FOUNDER", objective:"turn evidence into distinct business models and minimum paid offers" },
  { id:"SELLER", objective:"prefer the shortest truthful path from buyer signal to verified settlement" },
  { id:"GROWTH", objective:"look for repeatable low-marginal-cost distribution and monetizable events" },
  { id:"CFO", objective:"count only verified settlements or provider-verified payouts as revenue" }
]);

function clean(v,n=1000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}
function json(data,status=200){return Response.json(data,{status,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function authorized(request,env){const expected=clean(env?.OPPORTUNITY_ADMIN_TOKEN,500),provided=clean(request.headers.get("x-lumen-admin"),500);return Boolean(expected&&provided&&expected===provided);}
function now(){return new Date().toISOString();}

async function ensure(env){
  if(!env?.DB) throw new Error("entrepreneur_mode_persistence_required");
  await env.DB.prepare(`CREATE TABLE IF NOT EXISTS lumen_entrepreneur_cycles (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    trigger TEXT NOT NULL,
    brain_cycle_key TEXT,
    selected_lane TEXT,
    selection_mode TEXT,
    business_model TEXT,
    hypothesis TEXT,
    target TEXT,
    score REAL NOT NULL DEFAULT 0,
    probability_sale REAL NOT NULL DEFAULT 0,
    time_to_cash_hours REAL NOT NULL DEFAULT 0,
    venture_ideas INTEGER NOT NULL DEFAULT 0,
    mvp_ready INTEGER NOT NULL DEFAULT 0,
    builds_prepared INTEGER NOT NULL DEFAULT 0,
    launch_packets_ready INTEGER NOT NULL DEFAULT 0,
    verified_revenue_usd REAL NOT NULL DEFAULT 0,
    verified_settlements INTEGER NOT NULL DEFAULT 0,
    result_json TEXT NOT NULL,
    engine_version TEXT NOT NULL
  )`).run();
  await env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_entrepreneur_cycles_created ON lumen_entrepreneur_cycles(created_at DESC)").run();
}

async function revenueTruth(env){
  const row=await env.DB.prepare("SELECT COALESCE(SUM(amount_usd),0) revenue,COUNT(*) settlements FROM lumen_revenue_events WHERE status='verified' AND event_type IN ('payment_settled','affiliate_reward_confirmed','cpc_payout_verified')").first().catch(()=>null);
  return {verifiedRevenueUsd:Number(row?.revenue||0),verifiedSettlements:Number(row?.settlements||0)};
}

async function cashPressureState(env,truth){
  const r=await env.DB.prepare("SELECT business_model,verified_revenue_usd,verified_settlements FROM lumen_entrepreneur_cycles ORDER BY created_at DESC LIMIT 12").all().catch(()=>({results:[]}));
  const recent=r?.results||[];
  let consecutiveZeroCashCycles=0;
  for(const row of recent){
    if(Number(row?.verified_settlements||0)>0 || Number(row?.verified_revenue_usd||0)>0) break;
    consecutiveZeroCashCycles+=1;
  }
  const pressure=truth.verifiedSettlements>0?"WINNER":
    consecutiveZeroCashCycles>=8?"CRITICAL":
    consecutiveZeroCashCycles>=4?"HIGH":
    consecutiveZeroCashCycles>=2?"MEDIUM":"NORMAL";
  return {pressure,consecutiveZeroCashCycles,recentCyclesObserved:recent.length};
}

export function entrepreneurCommercialDirective(mission={},brainPlan={},director={},pressure={}){
  const lane=clean(mission.executionLane||mission.lane||"",30).toUpperCase();
  const score=Number(mission.score||0);
  const probability=Number(mission.probabilityOfSale||0);
  const bottleneck=clean(director?.bottleneck||"",80).toLowerCase();
  let action="PORTFOLIO";
  let reason="entrepreneur_mission_prepares_evidence_but_keeps_existing_commercial_priority";

  if(lane==="TRAVEL" && brainPlan?.travel){
    action="TRAVEL_REFERRAL";
    reason="entrepreneur_selected_travel_and_existing_bounded_travel_referral_lane_can_validate_demand";
  }else if(lane==="DISCOVERY"||lane==="EXPLORE"){
    action="NEW_OUTREACH";
    reason="entrepreneur_selected_demand_discovery_and_existing_quality_gates_can_attempt_one_verified_buyer_touch";
  }else if(lane==="REVENUE"){
    if(bottleneck==="conversion"){
      action="FIRST_CASH";
      reason="entrepreneur_selected_revenue_and_revenue_director_detected_conversion_bottleneck";
    }else if(bottleneck==="response_qualification"){
      action="COMMERCIAL_REPLY";
      reason="entrepreneur_selected_revenue_and_existing_responses_need_qualification";
    }else if(bottleneck==="response_generation"){
      action="FOLLOWUP";
      reason="entrepreneur_selected_revenue_and_existing_sent_pipeline_needs_bounded_followup";
    }
  }

  const evidenceStrongEnough=score>=0.45 || probability>=0.30 || ["HIGH","CRITICAL","WINNER"].includes(clean(pressure?.pressure,20).toUpperCase());
  if(action!=="PORTFOLIO"&&!evidenceStrongEnough){
    return {action:"PORTFOLIO",requestedAction:action,steerExistingCommercialSlot:false,reason:"entrepreneur_evidence_below_execution_threshold",lane,score,probability};
  }
  return {action,steerExistingCommercialSlot:action!=="PORTFOLIO",reason,lane,score,probability};
}

export const ENTREPRENEUR_POLICY = Object.freeze({
  version:VERSION,
  identity:"LUMEN Entrepreneur Mode",
  objective:"continuously discover, formulate, validate and prepare zero-capital business opportunities that can become verified revenue",
  roles:ROLES,
  cycle:["OBSERVE_DEMAND","GENERATE_BUSINESS_HYPOTHESES","SELECT_ONE_MISSION","PREPARE_MVP","PREPARE_GOVERNED_LAUNCH","MEASURE_REAL_CASH","LEARN"],
  businessModelsOpenEnded:true,
  distinctModelExploration:true,
  zeroCapitalAutonomousExperiments:true,
  huntBeforeDecision:true,
  stalledStrategyPivot:true,
  verifiedWinnerCompounding:true,
  cashDiscipline:["START_FROM_DEMAND","SELL_BEFORE_BUILD","RUN_SMALLEST_REVERSIBLE_TEST","KILL_STALLED_STRATEGIES","REPEAT_VERIFIED_WINNERS","CASH_IS_TRUTH"],
  externalCommercialExecution:"mission_may_steer_existing_quality_governor_and_one-message-slot",
  missionSteersBoundedCommercialSlot:true,
  maxDelegatedExternalMessagesPerCycle:1,
  noSyntheticDemand:true,
  noFakeBuyers:true,
  noFakeClicks:true,
  noSpam:true,
  noDeceptiveClaims:true,
  autonomousSpendUsd:0,
  autonomousPurchase:false,
  autonomousContract:false,
  autonomousDebt:false,
  autonomousPriceMutation:false,
  autonomousExternalPublish:false,
  verifiedRevenueTruth:"settled_or_provider_verified_payout_only",
  bindingActionsHumanGated:true
});

export async function runEntrepreneurMode(env,{trigger="scheduled",scheduledTime=Date.now()}={}){
  await ensure(env);
  const scheduled=Number(scheduledTime||Date.now());
  const cycleKey=String(trigger||"").startsWith("cloudflare_hourly_entrepreneur")
    ? `entrepreneur-${Math.floor(scheduled/3600000)}`
    : `entrepreneur-manual-${scheduled}`;
  // Entrepreneur order matters: hunt first so the decision is made with the
  // freshest opportunity set rather than yesterday's idea inventory.
  const hunter=await runVentureHunterV1(env,{limit:80,topK:18,mode:"entrepreneur_zero_capital"});
  const brain=await runUnifiedEconomicBrain(withBudgetedAi(env),{trigger:`entrepreneur_mode:${trigger}`,scheduledTime,cycleKey});
  const founder=await runVentureFounderV2(env,{limit:10});
  const builder=await runVentureBuilderV1(env,{limit:5});
  const launcher=await runVentureLauncherV1(env,{limit:5});
  const director=await recomputeRevenueDirector(env);
  const truth=await revenueTruth(env);
  const pressure=await cashPressureState(env,truth);

  const mission=brain?.mission||{};
  const priorAttempts=Number(mission.priorAttempts||0);
  const priorReward=Number(mission.priorReward||0);
  const strategyDisposition=truth.verifiedSettlements>0
    ? "REPEAT_VERIFIED_WINNER"
    : priorAttempts>=3&&priorReward<=0
      ? "PIVOT_AWAY_FROM_STALLED_STRATEGY"
      : pressure.pressure==="CRITICAL"||pressure.pressure==="HIGH"
        ? "PREFER_FASTEST_EVIDENCE_BACKED_CASH_TEST"
        : "RUN_SMALLEST_REVERSIBLE_TEST";
  const commercialDirective=entrepreneurCommercialDirective(mission,brain?.plan||{},director,pressure);
  const result={
    ok:true,
    version:VERSION,
    roles:ROLES,
    mission:{
      id:mission.id||null,
      lane:mission.executionLane||null,
      selectionMode:mission.selectionMode||null,
      businessModel:mission.businessModel||null,
      hypothesis:mission.hypothesis||null,
      target:mission.target||null,
      score:Number(mission.score||0),
      probabilityOfSale:Number(mission.probabilityOfSale||0),
      timeToCashHours:Number(mission.timeToCashHours||0),
      rationaleSummary:mission.rationaleSummary||null,
      nextStep:mission.nextStep||null
    },
    brainPlan:brain?.plan||null,
    venture:{
      signalsExamined:Number(hunter?.signalsExamined||0),
      ideasGenerated:Number(hunter?.ideasGenerated||0),
      buildCandidates:Number(hunter?.buildCandidates||0),
      familiesCovered:Number(hunter?.familiesCovered||0),
      bestScaleCandidate:hunter?.bestScaleCandidate||null,
      mvpReady:Number(founder?.mvpReady||0),
      topVenture:founder?.topVenture||null,
      buildsPrepared:Number(builder?.prepared||0),
      launchPacketsReady:Number(launcher?.awaitingApproval||0)
    },
    revenueDirector:{
      bottleneck:director?.bottleneck||null,
      tactic:director?.tactic||null,
      targetMetric:director?.targetMetric||null,
      preferredOffers:director?.preferredOffers||[]
    },
    commercialDirective,
    revenueTruth:truth,
    cashSprint:{
      pressure:pressure.pressure,
      consecutiveZeroCashCycles:pressure.consecutiveZeroCashCycles,
      strategyDisposition,
      priorAttempts,
      priorReward,
      founderRules:{
        startFromDemand:true,
        sellBeforeBuild:true,
        smallestReversibleTest:true,
        abandonRepeatedZeroSignalStrategy:true,
        repeatVerifiedWinner:true,
        countOnlyVerifiedCash:true
      }
    },
    actionBoundary:{
      preparesBusinessesAutonomously:true,
      canResearchAndGenerateIdeas:true,
      canPrepareMvp:true,
      canPrepareLaunchPacket:true,
      huntRunsBeforeEconomicDecision:true,
      externalMessagesHandledByExistingBoundedCommercialLoop:true,
      missionCanSteerExistingCommercialSlot:true,
      maxDelegatedExternalMessagesPerCycle:1,
      maxExternalMessagesAddedByEntrepreneurMode:0,
      autonomousSpendUsd:0,
      autonomousContract:false,
      autonomousPriceMutation:false
    }
  };

  const id=`ENT-${crypto.randomUUID().replaceAll("-","").slice(0,18).toUpperCase()}`;
  await env.DB.prepare(`INSERT INTO lumen_entrepreneur_cycles(
    id,created_at,trigger,brain_cycle_key,selected_lane,selection_mode,business_model,hypothesis,target,score,probability_sale,time_to_cash_hours,
    venture_ideas,mvp_ready,builds_prepared,launch_packets_ready,verified_revenue_usd,verified_settlements,result_json,engine_version
  ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`)
    .bind(id,now(),clean(trigger,80),cycleKey,mission.executionLane||null,mission.selectionMode||null,mission.businessModel||null,mission.hypothesis||null,mission.target||null,Number(mission.score||0),Number(mission.probabilityOfSale||0),Number(mission.timeToCashHours||0),Number(hunter?.ideasGenerated||0),Number(founder?.mvpReady||0),Number(builder?.prepared||0),Number(launcher?.awaitingApproval||0),truth.verifiedRevenueUsd,truth.verifiedSettlements,JSON.stringify(result).slice(0,50000),VERSION).run();

  return {...result,cycleId:id};
}

export async function getEntrepreneurStatus(env){
  await ensure(env);
  const latest=await env.DB.prepare("SELECT * FROM lumen_entrepreneur_cycles ORDER BY created_at DESC LIMIT 1").first();
  const totals=await env.DB.prepare("SELECT COUNT(*) cycles,COALESCE(SUM(venture_ideas),0) ideas,COALESCE(MAX(verified_revenue_usd),0) verified_revenue_usd,COALESCE(MAX(verified_settlements),0) verified_settlements,COALESCE(SUM(mvp_ready),0) mvp_ready,COALESCE(SUM(builds_prepared),0) builds_prepared FROM lumen_entrepreneur_cycles").first();
  const brain=await getUnifiedBrainStatus(env);
  return {
    ok:true,
    version:VERSION,
    policy:ENTREPRENEUR_POLICY,
    latest:latest?{...latest,result:JSON.parse(latest.result_json||"{}")}:null,
    totals:{
      cycles:Number(totals?.cycles||0),
      ideasGenerated:Number(totals?.ideas||0),
      mvpReady:Number(totals?.mvp_ready||0),
      buildsPrepared:Number(totals?.builds_prepared||0),
      verifiedRevenueUsd:Number(totals?.verified_revenue_usd||0),
      verifiedSettlements:Number(totals?.verified_settlements||0)
    },
    brain:{
      currentMission:brain?.currentMission||null,
      currentFunnel:brain?.currentFunnel||null,
      learning:brain?.learning||[]
    }
  };
}

export async function handleEntrepreneurMode(request,env){
  const u=new URL(request.url);
  if(!u.pathname.startsWith("/entrepreneur/")) return null;
  if(request.method==="GET"&&u.pathname==="/entrepreneur/policy") return json(ENTREPRENEUR_POLICY);
  if(!authorized(request,env)) return json({ok:false,error:"admin_token_required"},403);
  if(request.method==="GET"&&u.pathname==="/entrepreneur/status") return json(await getEntrepreneurStatus(env));
  if(request.method==="POST"&&u.pathname==="/entrepreneur/run"){
    return json(await runEntrepreneurMode(env,{trigger:"owner_or_operator",scheduledTime:Date.now()}),202);
  }
  return json({ok:false,error:"not_found"},404);
}
