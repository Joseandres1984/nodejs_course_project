import { computeEconomicOperatorState } from "./revenue-focus-controller.js";

const VERSION = "1.0-superautonomy-live";
const MAX_HISTORY = 80;
const STALL_ACCELERATE_AFTER = 3;
const STALL_CHALLENGE_AFTER = 8;

function num(v){const n=Number(v);return Number.isFinite(n)?n:0;}
function clean(v,n=240){return String(v??"").trim().replace(/[\r\n\t]+/g," ").slice(0,n);}
function clamp(v,min,max){return Math.max(min,Math.min(max,num(v)));}
function parse(v,fallback={}){try{return JSON.parse(v||"");}catch{return fallback;}}
function json(data,status=200){return Response.json(data,{status,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*","access-control-allow-headers":"content-type,x-lumen-admin","access-control-allow-methods":"GET,POST,OPTIONS"}});}
function authorized(request,env){const expected=clean(env?.OPPORTUNITY_ADMIN_TOKEN,500),supplied=clean(request.headers.get("x-lumen-admin"),500);return Boolean(expected&&supplied&&expected===supplied);}

async function first(env,sql,bind=[]){try{const q=env.DB.prepare(sql);return bind.length?await q.bind(...bind).first():await q.first();}catch{return null;}}
async function all(env,sql,bind=[]){try{const q=env.DB.prepare(sql),r=bind.length?await q.bind(...bind).all():await q.all();return r.results||[];}catch{return[];}}

async function ensureSchema(env){
  if(!env?.DB)return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_superautonomy_state (id TEXT PRIMARY KEY,updated_at TEXT NOT NULL,cycle INTEGER NOT NULL DEFAULT 0,phase TEXT NOT NULL,bottleneck TEXT NOT NULL,next_action TEXT NOT NULL,target_metric TEXT,stall_cycles INTEGER NOT NULL DEFAULT 0,recovery_level INTEGER NOT NULL DEFAULT 0,autonomy_ratio REAL NOT NULL DEFAULT 0,state_json TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_superautonomy_history (cycle_id TEXT PRIMARY KEY,created_at TEXT NOT NULL,phase TEXT NOT NULL,bottleneck TEXT NOT NULL,next_action TEXT NOT NULL,target_metric TEXT,baseline_value REAL NOT NULL DEFAULT 0,current_value REAL NOT NULL DEFAULT 0,progress INTEGER NOT NULL DEFAULT 0,human_gate_required INTEGER NOT NULL DEFAULT 0,recovery_level INTEGER NOT NULL DEFAULT 0,decision_json TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_superautonomy_history_created ON lumen_superautonomy_history(created_at DESC)")
  ]);
  return true;
}

function metricValue(state,key){
  const m=state?.metrics||{};
  const b=state?.revenueFocus?.backlog||{};
  const map={
    verifiedRevenueUsd:num(m.verifiedRevenueUsd),
    verifiedSettlements:num(m.verifiedSettlements),
    qualifiedCommercialResponses:num(m.qualifiedCommercialResponses),
    approvedUnsent:num(m.approvedUnsent),
    actionableOpportunities:num(m.actionableOpportunities),
    activeCandidates:num(m.activeCandidates),
    closeIntent:num(b.closeIntent),
    followupsReady:num(b.followupsReady),
    firstCashResponded:num(m.firstCashResponded),
    verifiedPaidCommerceOrders:num(m.verifiedPaidCommerceOrders)
  };
  return num(map[key]);
}

function chooseBottleneck(state){
  const m=state?.metrics||{}, b=state?.revenueFocus?.backlog||{};
  if(num(m.verifiedPaidCommerceOrders)>0) return {phase:"FULFILLMENT",bottleneck:"paid_fulfillment",targetMetric:"verifiedPaidCommerceOrders",nextAction:"PROTECT_VERIFIED_FULFILLMENT",roles:["risk_quality","revops"]};
  if(num(m.verifiedRevenueUsd)>0||num(m.verifiedSettlements)>0) return {phase:"SCALE",bottleneck:"scale_verified_revenue",targetMetric:"verifiedRevenueUsd",nextAction:"SCALE_VERIFIED_WINNER",roles:["revops","research_analyst"]};
  if(num(b.closeIntent)>0||num(m.negotiating)>0) return {phase:"CLOSING",bottleneck:"close_verified_intent",targetMetric:"verifiedRevenueUsd",nextAction:"CLOSE_EXISTING_INTENT",roles:["revops","negotiator","risk_quality"]};
  if(num(m.qualifiedCommercialResponses)>0) return {phase:"CONVERTING",bottleneck:"qualified_reply",targetMetric:"qualifiedCommercialResponses",nextAction:"QUALIFY_AND_REPLY",roles:["revops","negotiator"]};
  if(num(b.followupsReady)>0) return {phase:"FOLLOWUP",bottleneck:"due_followup",targetMetric:"followupsReady",nextAction:"EXECUTE_DUE_FOLLOWUP",roles:["revops"]};
  if(num(m.approvedUnsent)>0) return {phase:"OUTBOUND_READY",bottleneck:"quality_pass_unsent",targetMetric:"approvedUnsent",nextAction:"USE_EXISTING_QUALITY_PASS_INVENTORY",roles:["revops"]};
  if(num(m.actionableOpportunities)>0) return {phase:"PROPOSAL_BUILD",bottleneck:"actionable_without_conversion",targetMetric:"approvedUnsent",nextAction:"ADVANCE_BEST_ACTIONABLE_OPPORTUNITY",roles:["revops","research_analyst"]};
  if(num(m.activeCandidates)>0) return {phase:"QUALIFYING",bottleneck:"candidate_quality",targetMetric:"actionableOpportunities",nextAction:"QUALIFY_STRONGEST_CANDIDATE",roles:["research_analyst","buyer_hunter"]};
  return {phase:"DISCOVERING",bottleneck:"demand_discovery",targetMetric:"activeCandidates",nextAction:"DISCOVER_AND_SCORE_DEMAND",roles:["buyer_hunter","research_analyst"]};
}

function humanGate(state,decision){
  const action=String(state?.nextEconomicAction||decision?.nextAction||"").toUpperCase();
  const explicit=["PAY","PURCHASE","CONTRACT","LEGAL","DEPLOY","CREATE_CONNECTOR","PAID_MEDIA","BINDING"];
  return explicit.some(x=>action.includes(x));
}

function recoveryPlan(stallCycles,decision){
  if(stallCycles>=STALL_CHALLENGE_AFTER) return {level:3,mode:"CHALLENGE_PLAN",accelerateGrowthLoop:true,parallelLane:true,reason:"prolonged_verified_stagnation"};
  if(stallCycles>=STALL_ACCELERATE_AFTER) return {level:2,mode:"ROTATE_AND_ACCELERATE",accelerateGrowthLoop:true,parallelLane:false,reason:"repeated_verified_stagnation"};
  if(stallCycles>=1) return {level:1,mode:"REBALANCE_ATTENTION",accelerateGrowthLoop:false,parallelLane:false,reason:"early_stagnation"};
  return {level:0,mode:"NORMAL",accelerateGrowthLoop:false,parallelLane:false,reason:"verified_progress_or_initial_cycle"};
}

export function decideSuperautonomy(economicState,previous=null){
  const decision=chooseBottleneck(economicState);
  const current=metricValue(economicState,decision.targetMetric);
  const prevState=previous?.state||{};
  const comparable=String(prevState?.targetMetric||previous?.target_metric||"")===decision.targetMetric;
  const baseline=comparable?num(prevState?.currentValue??previous?.current_value):current;
  const progress=current>baseline;
  const stallCycles=progress?0:(comparable?num(previous?.stall_cycles)+1:0);
  const recovery=recoveryPlan(stallCycles,decision);
  const humanGateRequired=humanGate(economicState,decision);
  const autonomousUnits=humanGateRequired?0:1;
  const totalUnits=1;
  const priorRatio=num(previous?.autonomy_ratio);
  const cycle=num(previous?.cycle)+1;
  const boundedAutonomyRatio=cycle<=1?autonomousUnits:clamp(((priorRatio*(cycle-1))+autonomousUnits)/cycle,0,1);
  return {
    version:VERSION,
    cycle,
    phase:decision.phase,
    bottleneck:decision.bottleneck,
    targetMetric:decision.targetMetric,
    nextAction:decision.nextAction,
    roles:decision.roles,
    baselineValue:baseline,
    currentValue:current,
    verifiedProgress:progress,
    stallCycles,
    recovery,
    humanGateRequired,
    boundedAutonomyRatio:Number(boundedAutonomyRatio.toFixed(4)),
    ratioDefinition:"non_binding_superautonomy_cycles_completed_without_human_gate / total_superautonomy_cycles",
    economicOperatorAction:economicState?.nextEconomicAction||null,
    revenueFocus:economicState?.revenueFocus?.mode||null,
    authority:{autonomousSpendUsd:0,autonomousPurchase:false,autonomousContract:false,autonomousDebt:false,paidMedia:false,productionDeploy:false,newExternalConnectors:false,bindingActionsHumanGated:true},
    learningPolicy:"promote only observed verified funnel or revenue progress; never convert activity volume into revenue truth",
    executionPolicy:"continue reversible zero-spend work automatically; escalate only explicit binding or financial authority"
  };
}

async function readState(env){
  const row=await first(env,"SELECT * FROM lumen_superautonomy_state WHERE id='GLOBAL' LIMIT 1");
  if(!row)return null;
  return {...row,state:parse(row.state_json,{})};
}

async function persist(env,decision){
  const now=new Date().toISOString(),cycleId=`SA-${String(decision.cycle).padStart(8,"0")}`;
  const stateJson=JSON.stringify({...decision,updatedAt:now});
  await env.DB.batch([
    env.DB.prepare("INSERT OR REPLACE INTO lumen_superautonomy_state(id,updated_at,cycle,phase,bottleneck,next_action,target_metric,stall_cycles,recovery_level,autonomy_ratio,state_json,engine_version) VALUES('GLOBAL',?,?,?,?,?,?,?,?,?,?,?)").bind(now,decision.cycle,decision.phase,decision.bottleneck,decision.nextAction,decision.targetMetric,decision.stallCycles,decision.recovery.level,decision.boundedAutonomyRatio,stateJson,VERSION),
    env.DB.prepare("INSERT OR REPLACE INTO lumen_superautonomy_history(cycle_id,created_at,phase,bottleneck,next_action,target_metric,baseline_value,current_value,progress,human_gate_required,recovery_level,decision_json,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)").bind(cycleId,now,decision.phase,decision.bottleneck,decision.nextAction,decision.targetMetric,decision.baselineValue,decision.currentValue,decision.verifiedProgress?1:0,decision.humanGateRequired?1:0,decision.recovery.level,stateJson,VERSION)
  ]);
  return {...decision,updatedAt:now};
}

export async function runSuperautonomyCycle(env,{trigger="scheduled"}={}){
  if(!env?.DB)return {ok:false,version:VERSION,error:"db_unavailable",authority:{autonomousSpendUsd:0,bindingActionsHumanGated:true}};
  await ensureSchema(env);
  const [economicState,previous]=await Promise.all([computeEconomicOperatorState(env),readState(env)]);
  const decision=decideSuperautonomy(economicState,previous);
  const persisted=await persist(env,{...decision,trigger});
  return {ok:true,...persisted,trigger};
}

export async function superautonomyStatus(env){
  await ensureSchema(env);
  const [state,history]=await Promise.all([
    readState(env),
    all(env,"SELECT created_at,cycle_id,phase,bottleneck,next_action,target_metric,baseline_value,current_value,progress,human_gate_required,recovery_level FROM lumen_superautonomy_history ORDER BY created_at DESC LIMIT 12")
  ]);
  return {ok:true,version:VERSION,state:state?.state||null,history};
}

export async function handleSuperautonomy(request,env){
  const url=new URL(request.url);
  if(request.method==="OPTIONS"&&url.pathname.startsWith("/superautonomy"))return new Response(null,{status:204,headers:{"access-control-allow-origin":"*","access-control-allow-headers":"content-type,x-lumen-admin","access-control-allow-methods":"GET,POST,OPTIONS"}});
  if(request.method==="GET"&&url.pathname==="/superautonomy/policy")return json({version:VERSION,name:"LUMEN Superautonomy",cycle:"observe_prioritize_act_measure_learn_recover_next",antiStall:true,adaptivePriority:true,learningMemory:true,humanAttentionMinimization:true,autonomousSpendUsd:0,autonomousPurchase:false,autonomousContract:false,paidMedia:false,productionDeploy:false,newExternalConnectors:false,bindingActionsHumanGated:true});
  if(request.method==="GET"&&url.pathname==="/superautonomy/status")return json(await superautonomyStatus(env));
  if(request.method==="POST"&&url.pathname==="/superautonomy/run"){
    if(!authorized(request,env))return json({ok:false,error:"unauthorized"},401);
    return json(await runSuperautonomyCycle(env,{trigger:"admin_run"}),202);
  }
  return null;
}

export { VERSION as SUPER_AUTONOMY_VERSION, MAX_HISTORY };
