import { withBudgetedAi } from "./ai-router.js";
import { runUnifiedEconomicBrain, getUnifiedBrainStatus, UNIFIED_BRAIN_POLICY } from "./unified-economic-brain-v1.js";
import { runVentureHunterV1 } from "./venture-hunter-v1.js";
import { runVentureFounderV2 } from "./venture-founder-v2.js";
import { runVentureBuilderV1 } from "./venture-builder-v1.js";
import { runVentureLauncherV1 } from "./venture-launcher-v1.js";
import { recomputeRevenueDirector } from "./revenue-director.js";

const VERSION = "1.2-entrepreneur-role-council";
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


function clamp01(v){return Math.max(0,Math.min(1,Number(v)||0));}
function parseModelJson(text){
  const raw=String(text||"").replace(/^\x60\x60\x60(?:json)?\s*/i,"").replace(/\s*\x60\x60\x60$/,"");
  const a=raw.indexOf("{"),b=raw.lastIndexOf("}");
  if(a<0||b<=a)throw new Error("entrepreneur_council_json_missing");
  return JSON.parse(raw.slice(a,b+1));
}
function unsafeAdvisoryText(v){return /\b(spend|buy|purchase|loan|debt|sign contract|accept contract|private key|seed phrase|fake clicks?|self[- ]?click|click farm|spam)\b/i.test(String(v||""));}

export function deterministicEntrepreneurCouncil({mission={},hunter={},founder={},director={},truth={},pressure={}}={}){
  const top=founder?.topVenture||hunter?.topOpportunity||hunter?.bestScaleCandidate||null;
  const opportunity=clean(mission?.hypothesis||top?.product||top?.title||"Find a current buyer problem that LUMEN can solve with existing capabilities.",420);
  const target=clean(mission?.target||top?.title||"current buyer demand",220);
  const model=clean(mission?.businessModel||top?.revenueModel||"zero-capital paid service",220);
  const cash=Number(truth?.verifiedRevenueUsd||0);
  const settlements=Number(truth?.verifiedSettlements||0);
  const bottleneck=clean(director?.bottleneck||"unknown",100);
  const roleViews=[
    {role:"SCOUT",verdict:"Prioritize evidence of an active buyer problem around "+target+".",recommendation:"Search for current demand, RFQs, purchase intent or repeated pain before expanding supply.",confidence:.78},
    {role:"FOUNDER",verdict:"Package the smallest paid version of "+model+".",recommendation:"Use an existing capability and prepare the minimum deliverable that can test willingness to pay.",confidence:.74},
    {role:"SELLER",verdict:"Current commercial bottleneck: "+bottleneck+".",recommendation:"Prefer the nearest existing buyer conversation or qualified demand over additional cold volume.",confidence:.82},
    {role:"GROWTH",verdict:"Scale only after a paid or strongly attributable conversion signal exists.",recommendation:"Favor repeatable low-marginal-cost channels and measure monetizable events, not activity.",confidence:.80},
    {role:"CFO",verdict:"Verified cash is USD "+cash.toFixed(2)+" across "+settlements+" verified settlements.",recommendation:"Reject projections as revenue and keep autonomous capital at zero until a verified winner exists.",confidence:.98}
  ];
  return {
    source:"DETERMINISTIC_FALLBACK",
    roles:roleViews,
    consensus:{
      opportunity,
      businessModel:model,
      customer:target,
      smallestTest:clean(mission?.nextStep||"Validate one real buyer signal using an existing zero-cost LUMEN capability.",360),
      successMetric:"buyer purchase intent, quote request, attributable conversion, or verified settlement",
      killCondition:"stop or pivot after repeated zero-signal attempts or if evidence weakens",
      timeBoxHours:Math.max(1,Math.min(168,Number(mission?.timeToCashHours||48))),
      confidence:clamp01(Number(mission?.confidence||mission?.score||0.55)),
      executionBoundary:"INTERNAL_RECOMMENDATION_ONLY"
    }
  };
}

async function runEntrepreneurRoleCouncil(aiEnv,evidence){
  const fallback=deterministicEntrepreneurCouncil(evidence);
  if(!aiEnv?.AI?.run)return fallback;
  const compact={
    mission:evidence.mission,
    brainPlan:evidence.brainPlan,
    topOpportunity:evidence.hunter?.topOpportunity||null,
    bestScaleCandidate:evidence.hunter?.bestScaleCandidate||null,
    topVenture:evidence.founder?.topVenture||null,
    revenueDirector:{bottleneck:evidence.director?.bottleneck,tactic:evidence.director?.tactic,targetMetric:evidence.director?.targetMetric},
    revenueTruth:evidence.truth,
    cashPressure:evidence.pressure
  };
  const prompt=[
    "Act as five concise entrepreneurial roles inside LUMEN:",
    "SCOUT finds real demand; FOUNDER designs the smallest zero-capital offer;",
    "SELLER chooses the shortest truthful route to buyer intent;",
    "GROWTH looks for repeatability and distribution; CFO enforces verified-cash truth.",
    "Review the supplied evidence independently, then give one consensus.",
    "Do not invent buyers, payments, prices, demand or capabilities.",
    "Do not recommend spending, purchases, debt, contracts, fake clicks, self-clicking, spam or deceptive tactics.",
    "All recommendations are INTERNAL ONLY and grant no external authority.",
    "Return only JSON with roles [{role,verdict,recommendation,confidence}] and consensus",
    "{opportunity,businessModel,customer,smallestTest,successMetric,killCondition,timeBoxHours,confidence}.",
    "Do not provide chain-of-thought."
  ].join(" ");
  try{
    const r=await aiEnv.AI.run("@cf/meta/llama-3.1-8b-instruct-fast",{messages:[{role:"system",content:prompt},{role:"user",content:JSON.stringify(compact).slice(0,14000)}],temperature:.25,max_completion_tokens:360});
    const text=typeof r==="string"?r:(typeof r?.response==="string"?r.response:r?.choices?.[0]?.message?.content||"");
    const data=parseModelJson(text);
    const byRole=new Map((Array.isArray(data?.roles)?data.roles:[]).map(x=>[clean(x?.role,20).toUpperCase(),x]));
    const roles=ROLES.map((role,index)=>{
      const raw=byRole.get(role.id);
      const fb=fallback.roles[index];
      const verdict=clean(raw?.verdict||fb.verdict,360);
      const recommendation=clean(raw?.recommendation||fb.recommendation,360);
      return {
        role:role.id,
        verdict:unsafeAdvisoryText(verdict)?fb.verdict:verdict,
        recommendation:unsafeAdvisoryText(recommendation)?fb.recommendation:recommendation,
        confidence:clamp01(raw?.confidence??fb.confidence)
      };
    });
    const raw=data?.consensus||{};
    const safe=(value,fallbackValue,n=420)=>{const x=clean(value||fallbackValue,n);return unsafeAdvisoryText(x)?clean(fallbackValue,n):x;};
    return {
      source:"BUDGETED_AI_COUNCIL",
      roles,
      consensus:{
        opportunity:safe(raw.opportunity,fallback.consensus.opportunity),
        businessModel:safe(raw.businessModel,fallback.consensus.businessModel,240),
        customer:safe(raw.customer,fallback.consensus.customer,240),
        smallestTest:safe(raw.smallestTest,fallback.consensus.smallestTest),
        successMetric:safe(raw.successMetric,fallback.consensus.successMetric,320),
        killCondition:safe(raw.killCondition,fallback.consensus.killCondition,320),
        timeBoxHours:Math.max(1,Math.min(168,Number(raw.timeBoxHours||fallback.consensus.timeBoxHours))),
        confidence:clamp01(raw.confidence??fallback.consensus.confidence),
        executionBoundary:"INTERNAL_RECOMMENDATION_ONLY"
      }
    };
  }catch{
    return fallback;
  }
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
  multiRoleCouncil:true,
  roleCouncilNoChainOfThought:true,
  roleRecommendationsDoNotGrantExternalAuthority:true,
  externalCommercialExecution:"delegated_to_existing_quality_governor_and_one-message-slot",
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
  const budgetEnv=withBudgetedAi(env);
  const hunter=await runVentureHunterV1(env,{limit:80,topK:18,mode:"entrepreneur_zero_capital"});
  const brain=await runUnifiedEconomicBrain(budgetEnv,{trigger:`entrepreneur_mode:${trigger}`,scheduledTime,cycleKey});
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
  const council=await runEntrepreneurRoleCouncil(budgetEnv,{mission,hunter,founder,director,truth,pressure,brainPlan:brain?.plan||{}});
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
    roleCouncil:council,
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
      roleCouncilAdvisoryOnly:true,
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
