import { recomputeProfitFeedback } from "./profit-feedback-engine.js";
import { runTravelAcquisitionEngine } from "./travel-acquisition-engine.js";

const VERSION = "1.2-autonomous-growth-loop-commercial-truth";
const MIN_LEARNING_AGE_MS = 60 * 60 * 1000;
const MAX_MEMORY_PRIORITY = 15;

function clean(v,n=4000){return String(v??"").trim().replace(/[\r\n\t]+/g," ").slice(0,n);}
function num(v){const n=Number(v||0);return Number.isFinite(n)?n:0;}
function clamp(v,min,max){return Math.max(min,Math.min(max,num(v)));}
function parse(v,fallback={}){try{return JSON.parse(v||"");}catch{return fallback;}}
function json(data,status=200){return Response.json(data,{status,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*","access-control-allow-headers":"content-type,x-lumen-admin","access-control-allow-methods":"GET,POST,OPTIONS"}});}
function authorized(request,env){const expected=clean(env?.OPPORTUNITY_ADMIN_TOKEN,500),supplied=clean(request.headers.get("x-lumen-admin"),500);return Boolean(expected&&supplied&&expected===supplied);}
async function first(env,sql,bind=[]){try{const q=env.DB.prepare(sql);return bind.length?await q.bind(...bind).first():await q.first();}catch{return null;}}
async function all(env,sql,bind=[]){try{const q=env.DB.prepare(sql),r=bind.length?await q.bind(...bind).all():await q.all();return r.results||[];}catch{return[];}}
async function scalar(env,sql,bind=[]){const row=await first(env,sql,bind);return num(row?.n);}

async function ensureSchema(env){
  if(!env?.DB)return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_growth_cycles (id TEXT PRIMARY KEY,created_at TEXT NOT NULL,completed_at TEXT,trigger TEXT NOT NULL,phase TEXT NOT NULL,selected_lane TEXT NOT NULL,bottleneck TEXT NOT NULL,decision_reason TEXT NOT NULL,action_kind TEXT NOT NULL,action_status TEXT NOT NULL,confidence TEXT NOT NULL,before_snapshot_json TEXT NOT NULL,after_snapshot_json TEXT NOT NULL DEFAULT '{}',action_result_json TEXT NOT NULL DEFAULT '{}',learning_json TEXT NOT NULL DEFAULT '{}',evaluation_status TEXT NOT NULL DEFAULT 'PENDING',evaluated_at TEXT,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_growth_cycles_created ON lumen_growth_cycles(created_at DESC)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_growth_cycles_eval ON lumen_growth_cycles(evaluation_status,created_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_growth_memory (lane TEXT PRIMARY KEY,updated_at TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,evaluated_cycles INTEGER NOT NULL DEFAULT 0,positive_outcomes INTEGER NOT NULL DEFAULT 0,stalls INTEGER NOT NULL DEFAULT 0,cumulative_reward REAL NOT NULL DEFAULT 0,learned_priority REAL NOT NULL DEFAULT 0,last_outcome TEXT,last_evidence_json TEXT NOT NULL DEFAULT '{}',engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_growth_memory_priority ON lumen_growth_memory(learned_priority DESC,updated_at DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_growth_guidance (id TEXT PRIMARY KEY,updated_at TEXT NOT NULL,expires_at TEXT NOT NULL,selected_lane TEXT NOT NULL,preferred_action TEXT NOT NULL,confidence TEXT NOT NULL,reason TEXT NOT NULL,observed_bottleneck TEXT NOT NULL,engine_version TEXT NOT NULL)"),
  ]);
  return true;
}

const REAL_MACHINE_ORDER_FILTER="remote_metadata IS NULL OR (remote_metadata NOT LIKE '%technical_machine_order_canary%' AND remote_metadata NOT LIKE '%lumen_deployment_canary%')";
const REAL_QUOTE_FILTER="remote_metadata IS NULL OR (remote_metadata NOT LIKE '%technical_quote_canary%' AND remote_metadata NOT LIKE '%technical_machine_order_canary%' AND remote_metadata NOT LIKE '%lumen_deployment_canary%')";

async function snapshot(env){
  const [verifiedSettlements,verifiedSettlements7d,realizedRevenueUsd,realizedRevenueUsd7d,machineRequests,machineRequests7d,quotes7d,inbound7d,negotiating,pendingFulfillment,travelClicks24h,travelResults24h,travelImpressions24h,travelConfirmations30d,travelNegative30d,travelRecommended,travelAffiliateRewards30d,travelAffiliateRevenueUsd30d,travelAffiliateCashPayouts30d]=await Promise.all([
    scalar(env,"SELECT COUNT(*) n FROM lumen_revenue_events WHERE event_type='payment_settled' AND status='verified'"),
    scalar(env,"SELECT COUNT(*) n FROM lumen_revenue_events WHERE event_type='payment_settled' AND status='verified' AND datetime(created_at)>=datetime('now','-7 days')"),
    scalar(env,"SELECT COALESCE(SUM(amount_usd),0) n FROM lumen_revenue_events WHERE event_type='payment_settled' AND status='verified'"),
    scalar(env,"SELECT COALESCE(SUM(amount_usd),0) n FROM lumen_revenue_events WHERE event_type='payment_settled' AND status='verified' AND datetime(created_at)>=datetime('now','-7 days')"),
    scalar(env,`SELECT COUNT(*) n FROM lumen_machine_orders WHERE ${REAL_MACHINE_ORDER_FILTER}`),
    scalar(env,`SELECT COUNT(*) n FROM lumen_machine_orders WHERE status='received_unverified' AND datetime(created_at)>=datetime('now','-7 days') AND (${REAL_MACHINE_ORDER_FILTER})`),
    scalar(env,`SELECT COUNT(*) n FROM lumen_a2a_quotes WHERE datetime(created_at)>=datetime('now','-7 days') AND (${REAL_QUOTE_FILTER})`),
    scalar(env,"SELECT COUNT(*) n FROM lumen_a2a_inbound WHERE binding_intent=0 AND datetime(received_at)>=datetime('now','-7 days')"),
    scalar(env,"SELECT COUNT(*) n FROM lumen_sales_pipeline WHERE stage='NEGOTIATING'"),
    scalar(env,"SELECT COUNT(*) n FROM lumen_commerce_fulfillment_queue WHERE purchase_executed=0 AND state='AWAITING_HUMAN_PURCHASE_APPROVAL'"),
    scalar(env,"SELECT COUNT(*) n FROM lumen_travel_events WHERE event_type='click' AND datetime(created_at)>=datetime('now','-24 hours')"),
    scalar(env,"SELECT COUNT(*) n FROM lumen_travel_events WHERE event_type='result_shown' AND datetime(created_at)>=datetime('now','-24 hours')"),
    scalar(env,"SELECT COUNT(*) n FROM lumen_travel_events WHERE event_type='impression' AND datetime(created_at)>=datetime('now','-24 hours')"),
    scalar(env,"SELECT COUNT(*) n FROM lumen_viator_booking_events WHERE event_type='CONFIRMATION' AND datetime(last_updated)>=datetime('now','-30 days')"),
    scalar(env,"SELECT COUNT(*) n FROM lumen_viator_booking_events WHERE event_type IN ('CANCELLATION','CUSTOMER_CANCELLATION','REJECTION') AND datetime(last_updated)>=datetime('now','-30 days')"),
    scalar(env,"SELECT COUNT(*) n FROM lumen_travel_acquisition_campaigns WHERE status IN ('RECOMMENDED','APPROVED')"),
    scalar(env,"SELECT COUNT(*) n FROM lumen_revenue_events WHERE event_type='affiliate_reward_confirmed' AND source='travelpayouts' AND status='verified' AND datetime(created_at)>=datetime('now','-30 days')"),
    scalar(env,"SELECT COALESCE(SUM(amount_usd),0) n FROM lumen_revenue_events WHERE event_type='affiliate_reward_confirmed' AND source='travelpayouts' AND status='verified' AND datetime(created_at)>=datetime('now','-30 days')"),
    scalar(env,"SELECT COUNT(*) n FROM lumen_revenue_events WHERE event_type='affiliate_payout_received' AND source='travelpayouts' AND status='verified' AND datetime(created_at)>=datetime('now','-30 days')")
  ]);
  const director=await first(env,"SELECT bottleneck,tactic,target_metric,no_progress_cycles,preferred_offers_json,updated_at FROM lumen_revenue_director_state WHERE id='FIRST_CASH' LIMIT 1");
  const topOffer=await first(env,"SELECT offer_id,verified_settlements,verified_revenue_usd,response_rate,priority_adjustment,evidence_level,updated_at FROM lumen_offer_performance ORDER BY priority_adjustment DESC,verified_revenue_usd DESC,verified_settlements DESC LIMIT 1");
  return {
    capturedAt:new Date().toISOString(),
    revenue:{verifiedSettlements,verifiedSettlements7d,realizedRevenueUsd,realizedRevenueUsd7d,orders:machineRequests,machineRequests,machineRequests7d,quotes7d,inbound7d,negotiating,pendingFulfillment},
    travel:{clicks24h:travelClicks24h,results24h:travelResults24h,impressions24h:travelImpressions24h,confirmations30d:travelConfirmations30d,negativeEvents30d:travelNegative30d,recommendedCampaigns:travelRecommended,affiliateRewards30d:travelAffiliateRewards30d,affiliateRevenueUsd30d:travelAffiliateRevenueUsd30d,cashPayouts30d:travelAffiliateCashPayouts30d},
    director:director?{bottleneck:director.bottleneck,tactic:director.tactic,targetMetric:director.target_metric,noProgressCycles:num(director.no_progress_cycles),preferredOffers:parse(director.preferred_offers_json,[]),updatedAt:director.updated_at}:null,
    topOffer:topOffer?{offerId:topOffer.offer_id,verifiedSettlements:num(topOffer.verified_settlements),verifiedRevenueUsd:num(topOffer.verified_revenue_usd),responseRate:num(topOffer.response_rate),priorityAdjustment:num(topOffer.priority_adjustment),evidenceLevel:topOffer.evidence_level,updatedAt:topOffer.updated_at}:null,
    truth:{machineRequestsAreNonBinding:true,machineRequestStatus:"received_unverified",pendingFulfillmentRequiresVerifiedPaidOrder:true,technicalCanariesExcluded:true,affiliateRewardRequiresTravelpayoutsPaidAction:true,affiliatePayoutTrackedSeparatelyToPreventDoubleCount:true}
  };
}

function memoryPriority(memories,lane){const x=memories?.[lane];return clamp(x?.learnedPriority||x?.learned_priority||0,-5,MAX_MEMORY_PRIORITY);}

export function chooseGrowthDecision(s,memories={}){
  const r=s?.revenue||{},t=s?.travel||{},d=s?.director||{},scores=[];
  const add=(lane,base,actionKind,preferredAction,reason)=>scores.push({lane,score:base+memoryPriority(memories,lane),actionKind,preferredAction,reason});

  if(num(r.pendingFulfillment)>0)add("SETTLEMENT_AND_DELIVERY",110,"OBSERVE_AND_PROTECT_SETTLEMENT","REVIEW_VERIFIED_PAID_FULFILLMENT","A verified paid commerce order is waiting in the governed fulfillment queue; delivery truth outranks new acquisition.");
  if(num(t.affiliateRewards30d)>0)add("TRAVEL_SCALE",106,"REFRESH_TRAVEL_ACQUISITION","SCALE_VERIFIED_TRAVEL_AFFILIATE_WINNER","Verified Travelpayouts affiliate reward evidence exists; scale Travel demand using confirmed commercial truth rather than clicks alone.");
  if(num(r.verifiedSettlements7d)>0)add("SCALE_VERIFIED_WINNER",100,"REFRESH_PROFIT_FEEDBACK","SCALE_RECENT_VERIFIED_WINNER","Recent verified settlement evidence exists; scale only evidence-backed winners.");
  if(num(r.negotiating)>0)add("B2B_CONVERSION",94,"REFRESH_PROFIT_FEEDBACK","CONVERT_EXISTING_INTEREST","An active NEGOTIATING pipeline exists; conversion outranks fresh prospecting.");
  if(num(t.confirmations30d)>0)add("TRAVEL_SCALE",90,"REFRESH_TRAVEL_ACQUISITION","SCALE_TRAVEL_WINNERS","Confirmed Travel booking evidence exists; refresh acquisition around proven demand.");
  const b2bIntent=Math.min(18,num(r.machineRequests7d)*4)+Math.min(12,num(r.quotes7d)*2)+Math.min(10,num(r.inbound7d));
  if(b2bIntent>0)add("B2B_CONVERSION",78+Math.min(12,b2bIntent),"REFRESH_PROFIT_FEEDBACK","QUALIFY_NONBINDING_DEMAND","Recent non-binding machine requests, quotes or inbound messages show commercial demand; qualify them without treating them as paid orders.");
  const travelIntent=num(t.clicks24h)*3+Math.min(20,num(t.results24h)/3)+Math.min(10,num(t.impressions24h)/10);
  if(travelIntent>0)add("TRAVEL_BUYER_ACQUISITION",65+Math.min(20,travelIntent),"REFRESH_TRAVEL_ACQUISITION","GENERATE_TRAVEL_DEMAND","Recent Travel clicks/results provide measurable buyer-intent signals worth exploiting and testing.");
  add("B2B_FIRST_CASH",62+Math.min(15,num(r.inbound7d)*2),"REFRESH_PROFIT_FEEDBACK","FIND_AND_CONVERT_BUYER_DEMAND",d?.bottleneck==="demand_generation"?"Revenue Director reports demand generation as the current bottleneck.":"Maintain first-cash discovery while stronger downstream evidence is absent.");

  scores.sort((a,b)=>b.score-a.score||a.lane.localeCompare(b.lane));
  const winner=scores[0],runner=scores[1],gap=num(winner?.score)-num(runner?.score);
  const confidence=gap>=20?"HIGH":gap>=8?"MEDIUM":"LOW";
  return {...winner,score:Number(num(winner?.score).toFixed(2)),confidence,observedBottleneck:d?.bottleneck||(winner?.lane||"unknown"),candidates:scores.map(x=>({lane:x.lane,score:Number(num(x.score).toFixed(2)),actionKind:x.actionKind}))};
}

export function evaluateGrowthDelta(before={},after={}){
  const br=before?.revenue||{},ar=after?.revenue||{},bt=before?.travel||{},at=after?.travel||{};
  const delta={realizedRevenueUsd:num(ar.realizedRevenueUsd7d)-num(br.realizedRevenueUsd7d),verifiedSettlements:num(ar.verifiedSettlements7d)-num(br.verifiedSettlements7d),travelAffiliateRevenueUsd:num(at.affiliateRevenueUsd30d)-num(bt.affiliateRevenueUsd30d),travelAffiliateRewards:num(at.affiliateRewards30d)-num(bt.affiliateRewards30d),machineRequests:num(ar.machineRequests)-num(br.machineRequests),travelConfirmations:num(at.confirmations30d)-num(bt.confirmations30d),travelClicks24h:num(at.clicks24h)-num(bt.clicks24h),travelResults24h:num(at.results24h)-num(bt.results24h)};
  let reward=0,outcome="NO_OBSERVED_PROGRESS";
  if(delta.travelAffiliateRevenueUsd>0){reward+=100;outcome="VERIFIED_AFFILIATE_REVENUE";}
  if(delta.realizedRevenueUsd>0){reward+=100;if(outcome==="NO_OBSERVED_PROGRESS")outcome="VERIFIED_REVENUE";}
  if(delta.verifiedSettlements>0){reward+=70;if(outcome==="NO_OBSERVED_PROGRESS")outcome="VERIFIED_SETTLEMENT";}
  if(delta.travelConfirmations>0){reward+=45;if(!outcome.startsWith("VERIFIED_"))outcome="TRAVEL_CONFIRMATION";}
  if(delta.machineRequests>0){reward+=Math.min(8,delta.machineRequests*2);if(outcome==="NO_OBSERVED_PROGRESS")outcome="NONBINDING_DEMAND_PROGRESS";}
  if(delta.travelClicks24h>0){reward+=Math.min(10,delta.travelClicks24h*2);if(outcome==="NO_OBSERVED_PROGRESS")outcome="QUALIFIED_CLICK_PROGRESS";}
  if(delta.travelResults24h>0&&reward===0){reward+=Math.min(3,delta.travelResults24h);outcome="DISCOVERY_PROGRESS";}
  return {outcome,reward:Number(reward.toFixed(2)),delta,attribution:"observational_not_causal",truthRule:"nonbinding_machine_requests_never_count_as_paid_orders_or_revenue; travel affiliate reward requires provider-confirmed paid action; bank payout never counts twice"};
}

async function memories(env){const rows=await all(env,"SELECT lane,attempts,evaluated_cycles,positive_outcomes,stalls,cumulative_reward,learned_priority,last_outcome,updated_at FROM lumen_growth_memory ORDER BY learned_priority DESC,lane");return Object.fromEntries(rows.map(r=>[r.lane,{lane:r.lane,attempts:num(r.attempts),evaluatedCycles:num(r.evaluated_cycles),positiveOutcomes:num(r.positive_outcomes),stalls:num(r.stalls),cumulativeReward:num(r.cumulative_reward),learnedPriority:num(r.learned_priority),lastOutcome:r.last_outcome,updatedAt:r.updated_at}]));}
async function markAttempt(env,lane){const now=new Date().toISOString();await env.DB.prepare("INSERT INTO lumen_growth_memory(lane,updated_at,attempts,evaluated_cycles,positive_outcomes,stalls,cumulative_reward,learned_priority,last_outcome,last_evidence_json,engine_version) VALUES(?,?,1,0,0,0,0,0,NULL,'{}',?) ON CONFLICT(lane) DO UPDATE SET updated_at=excluded.updated_at,attempts=lumen_growth_memory.attempts+1,engine_version=excluded.engine_version").bind(lane,now,VERSION).run();}

async function evaluateMatureCycle(env,current){
  const cutoff=new Date(Date.now()-MIN_LEARNING_AGE_MS).toISOString();
  const row=await first(env,"SELECT id,selected_lane,before_snapshot_json FROM lumen_growth_cycles WHERE evaluation_status='PENDING' AND datetime(created_at)<=datetime(?) ORDER BY created_at ASC LIMIT 1",[cutoff]);
  if(!row)return null;
  const learning=evaluateGrowthDelta(parse(row.before_snapshot_json,{}),current),now=new Date().toISOString();
  await env.DB.prepare("UPDATE lumen_growth_cycles SET evaluation_status='EVALUATED',evaluated_at=?,learning_json=? WHERE id=?").bind(now,JSON.stringify(learning),row.id).run();
  const mem=await first(env,"SELECT evaluated_cycles,positive_outcomes,stalls,cumulative_reward FROM lumen_growth_memory WHERE lane=?",[row.selected_lane]);
  const evaluated=num(mem?.evaluated_cycles)+1,positive=num(mem?.positive_outcomes)+(learning.reward>0?1:0),stalls=num(mem?.stalls)+(learning.reward>0?0:1),cumulative=num(mem?.cumulative_reward)+learning.reward,learned=clamp((cumulative/Math.max(1,evaluated))/10,-5,MAX_MEMORY_PRIORITY);
  await env.DB.prepare("INSERT INTO lumen_growth_memory(lane,updated_at,attempts,evaluated_cycles,positive_outcomes,stalls,cumulative_reward,learned_priority,last_outcome,last_evidence_json,engine_version) VALUES(?,?,0,?,?,?,?,?,?,?,?) ON CONFLICT(lane) DO UPDATE SET updated_at=excluded.updated_at,evaluated_cycles=excluded.evaluated_cycles,positive_outcomes=excluded.positive_outcomes,stalls=excluded.stalls,cumulative_reward=excluded.cumulative_reward,learned_priority=excluded.learned_priority,last_outcome=excluded.last_outcome,last_evidence_json=excluded.last_evidence_json,engine_version=excluded.engine_version").bind(row.selected_lane,now,evaluated,positive,stalls,cumulative,learned,learning.outcome,JSON.stringify(learning.delta),VERSION).run();
  return {cycleId:row.id,lane:row.selected_lane,...learning,learnedPriority:Number(learned.toFixed(2))};
}

async function executeInternalAction(env,decision){
  if(["TRAVEL_BUYER_ACQUISITION","TRAVEL_SCALE"].includes(decision.lane)){const result=await runTravelAcquisitionEngine(env);return{status:result?.ok?"COMPLETED":"FAILED",kind:"REFRESH_TRAVEL_ACQUISITION",result};}
  if(decision.lane==="SETTLEMENT_AND_DELIVERY")return{status:"OBSERVE_ONLY",kind:"OBSERVE_AND_PROTECT_SETTLEMENT",result:{reason:"Verified paid fulfillment exists, but Growth Loop cannot execute purchase, release paid delivery or bypass human approval."}};
  const result=await recomputeProfitFeedback(env);return{status:result?.ok?"COMPLETED":"FAILED",kind:"REFRESH_PROFIT_FEEDBACK",result:{ok:result?.ok,version:result?.version,offers:result?.offers,top:result?.ranking?.[0]||null}};
}

async function writeGuidance(env,decision){const now=new Date(),expires=new Date(now.getTime()+90*60*1000);await env.DB.prepare("INSERT INTO lumen_growth_guidance(id,updated_at,expires_at,selected_lane,preferred_action,confidence,reason,observed_bottleneck,engine_version) VALUES('CURRENT',?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,expires_at=excluded.expires_at,selected_lane=excluded.selected_lane,preferred_action=excluded.preferred_action,confidence=excluded.confidence,reason=excluded.reason,observed_bottleneck=excluded.observed_bottleneck,engine_version=excluded.engine_version").bind(now.toISOString(),expires.toISOString(),decision.lane,decision.preferredAction,decision.confidence,decision.reason,decision.observedBottleneck,VERSION).run();}

export async function runAutonomousGrowthLoop(env,options={}){
  if(!(await ensureSchema(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  const before=await snapshot(env),learning=await evaluateMatureCycle(env,before),mem=await memories(env),decision=chooseGrowthDecision(before,mem),id=`GROW-${Date.now()}-${crypto.randomUUID().slice(0,8).toUpperCase()}`,createdAt=new Date().toISOString();
  await markAttempt(env,decision.lane);
  await env.DB.prepare("INSERT INTO lumen_growth_cycles(id,created_at,trigger,phase,selected_lane,bottleneck,decision_reason,action_kind,action_status,confidence,before_snapshot_json,after_snapshot_json,action_result_json,learning_json,evaluation_status,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)").bind(id,createdAt,clean(options.trigger||"scheduled",80),"DECIDED",decision.lane,decision.observedBottleneck,decision.reason,decision.actionKind,"RUNNING",decision.confidence,JSON.stringify(before),"{}","{}",JSON.stringify(learning||{}),"PENDING",VERSION).run();
  let action;try{action=await executeInternalAction(env,decision);}catch(error){action={status:"FAILED",kind:decision.actionKind,result:{error:clean(error?.message||error,500)}};}
  const after=await snapshot(env),completedAt=new Date().toISOString();
  await env.DB.prepare("UPDATE lumen_growth_cycles SET completed_at=?,phase='COMPLETED',action_kind=?,action_status=?,after_snapshot_json=?,action_result_json=? WHERE id=?").bind(completedAt,action.kind,action.status,JSON.stringify(after),JSON.stringify(action.result||{}),id).run();
  await writeGuidance(env,decision);
  return {ok:true,version:VERSION,cycleId:id,trigger:clean(options.trigger||"scheduled",80),decision:{lane:decision.lane,preferredAction:decision.preferredAction,confidence:decision.confidence,reason:decision.reason,score:decision.score,candidates:decision.candidates},action:{kind:action.kind,status:action.status},learningEvaluated:learning,truth:{nonbindingMachineRequestsArePaidOrders:false,settlementLaneRequiresPendingVerifiedFulfillment:true,confirmedAffiliateRewardRequiresProviderPaidAction:true,affiliateBankPayoutNotDoubleCounted:true},guardrails:{autonomousOutgoingSpend:false,paidAds:false,createsBooking:false,createsCharge:false,releasesPaidDelivery:false,addsExternalMessagesPerCycle:0,bindingActionsHumanGated:true,verifiedCommercialEvidenceRequiredForRevenue:true}};
}

async function status(env){await ensureSchema(env);const latest=await first(env,"SELECT id,created_at,completed_at,trigger,selected_lane,bottleneck,decision_reason,action_kind,action_status,confidence,evaluation_status,evaluated_at,learning_json,engine_version FROM lumen_growth_cycles ORDER BY created_at DESC LIMIT 1"),guidance=await first(env,"SELECT updated_at,expires_at,selected_lane,preferred_action,confidence,reason,observed_bottleneck,engine_version FROM lumen_growth_guidance WHERE id='CURRENT' LIMIT 1"),mem=await all(env,"SELECT lane,attempts,evaluated_cycles,positive_outcomes,stalls,cumulative_reward,learned_priority,last_outcome,updated_at,engine_version FROM lumen_growth_memory ORDER BY learned_priority DESC,lane");return{version:VERSION,initialized:Boolean(latest),latest:latest?{...latest,learning:parse(latest.learning_json,{})}:null,guidance:guidance||null,memory:mem.map(x=>({...x,attempts:num(x.attempts),evaluated_cycles:num(x.evaluated_cycles),positive_outcomes:num(x.positive_outcomes),stalls:num(x.stalls),cumulative_reward:num(x.cumulative_reward),learned_priority:num(x.learned_priority)})),truth:{nonbindingMachineRequestsArePaidOrders:false,settlementLaneRequiresPendingVerifiedFulfillment:true,confirmedAffiliateRewardRequiresProviderPaidAction:true,affiliateBankPayoutNotDoubleCounted:true},guardrails:{autonomousOutgoingSpend:false,paidAds:false,addsExternalMessagesPerCycle:0,bindingActionsHumanGated:true}};}
async function history(env,limit=10){await ensureSchema(env);const n=Math.max(1,Math.min(30,Number(limit)||10)),rows=await all(env,`SELECT id,created_at,completed_at,trigger,selected_lane,bottleneck,decision_reason,action_kind,action_status,confidence,evaluation_status,evaluated_at,learning_json,engine_version FROM lumen_growth_cycles ORDER BY created_at DESC LIMIT ${n}`);return rows.map(r=>({...r,learning:parse(r.learning_json,{})}));}

export async function handleAutonomousGrowthLoop(request,env){
  const u=new URL(request.url);
  if(request.method==="OPTIONS"&&u.pathname.startsWith("/growth/"))return new Response(null,{status:204,headers:{"access-control-allow-origin":"*","access-control-allow-headers":"content-type,x-lumen-admin","access-control-allow-methods":"GET,POST,OPTIONS"}});
  if(request.method==="GET"&&u.pathname==="/growth/policy")return json({version:VERSION,name:"LUMEN Autonomous Growth Loop",objective:"observe_decide_act_measure_learn_with_commercial_truth",cycleCadence:"hourly_when_scheduled",learningDelayMinutes:60,truthRules:{machineRequest:"nonbinding_demand_signal_not_order_not_revenue",settlement:"only_verified_payment_settled_counts_as_b2b_revenue",affiliateReward:"only_travelpayouts_action_state_paid_profit_counts_as_verified_affiliate_revenue",affiliatePayout:"cash_payout_is_tracked_separately_and_never_counted_again_as_revenue",fulfillmentPriority:"only_verified_paid_order_can_enter_governed_fulfillment"},learningAuthority:["verified_revenue","verified_settlement","verified_affiliate_reward","confirmed_booking","nonbinding_demand_signal","qualified_click"],selfModification:"strategy_and_priority_memory_only",codeSelfDeployment:false,externalBuyerHunting:"delegated_to_existing_guarded_commercial_engines",guardrails:{autonomousOutgoingSpend:false,paidAds:false,createsBooking:false,createsCharge:false,addsExternalMessagesPerCycle:0,bindingActionsHumanGated:true}});
  if(request.method==="GET"&&u.pathname==="/growth/status")return json(await status(env));
  if(request.method==="GET"&&u.pathname==="/growth/history")return json({version:VERSION,cycles:await history(env,u.searchParams.get("limit"))});
  if(request.method==="POST"&&u.pathname==="/growth/run"){if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);return json(await runAutonomousGrowthLoop(env,{trigger:"admin_manual"}),202);}
  return null;
}
