import { computeEconomicOperatorState } from "./revenue-focus-controller.js";
import { runOpportunityFactory } from "./opportunity-factory.js";
import { recomputePortfolioGovernor } from "./portfolio-governor.js";

const VERSION = "2.0-superautonomy-live";
const MAX_HISTORY = 120;
const STALL_REBALANCE_AFTER = 1;
const STALL_ROTATE_AFTER = 3;
const STALL_PARALLEL_AFTER = 6;
const STALL_CHALLENGE_AFTER = 10;
const MAX_PORTFOLIO = 12;
const MAX_GOALS = 5;

function num(v){const n=Number(v);return Number.isFinite(n)?n:0;}
function clean(v,n=240){return String(v??"").trim().replace(/[\r\n\t]+/g," ").slice(0,n);}
function clamp(v,min,max){return Math.max(min,Math.min(max,num(v)));}
function parse(v,fallback={}){try{return JSON.parse(v||"");}catch{return fallback;}}
function json(data,status=200){return Response.json(data,{status,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*","access-control-allow-headers":"content-type,x-lumen-admin","access-control-allow-methods":"GET,POST,OPTIONS"}});}
function authorized(request,env){const expected=clean(env?.OPPORTUNITY_ADMIN_TOKEN,500),supplied=clean(request.headers.get("x-lumen-admin"),500);return Boolean(expected&&supplied&&expected===supplied);}
function now(){return new Date().toISOString();}

async function first(env,sql,bind=[]){try{const q=env.DB.prepare(sql);return bind.length?await q.bind(...bind).first():await q.first();}catch{return null;}}
async function all(env,sql,bind=[]){try{const q=env.DB.prepare(sql),r=bind.length?await q.bind(...bind).all():await q.all();return r.results||[];}catch{return[];}}
async function runSafe(step,fallback={ok:false}){try{return await step();}catch(error){return {...fallback,isolatedFailure:true,error:clean(error?.message||error,220)};}}

async function ensureSchema(env){
  if(!env?.DB)return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_superautonomy_state (id TEXT PRIMARY KEY,updated_at TEXT NOT NULL,cycle INTEGER NOT NULL DEFAULT 0,phase TEXT NOT NULL,bottleneck TEXT NOT NULL,next_action TEXT NOT NULL,target_metric TEXT,stall_cycles INTEGER NOT NULL DEFAULT 0,recovery_level INTEGER NOT NULL DEFAULT 0,autonomy_ratio REAL NOT NULL DEFAULT 0,state_json TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_superautonomy_history (cycle_id TEXT PRIMARY KEY,created_at TEXT NOT NULL,phase TEXT NOT NULL,bottleneck TEXT NOT NULL,next_action TEXT NOT NULL,target_metric TEXT,baseline_value REAL NOT NULL DEFAULT 0,current_value REAL NOT NULL DEFAULT 0,progress INTEGER NOT NULL DEFAULT 0,human_gate_required INTEGER NOT NULL DEFAULT 0,recovery_level INTEGER NOT NULL DEFAULT 0,decision_json TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_superautonomy_history_created ON lumen_superautonomy_history(created_at DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_superautonomy_action_memory (action_key TEXT PRIMARY KEY,updated_at TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,wins INTEGER NOT NULL DEFAULT 0,stalls INTEGER NOT NULL DEFAULT 0,score REAL NOT NULL DEFAULT 1,last_outcome TEXT,last_metric TEXT,last_delta REAL NOT NULL DEFAULT 0,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_superautonomy_action_memory_score ON lumen_superautonomy_action_memory(score DESC,updated_at DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_superautonomy_goals (goal_id TEXT PRIMARY KEY,updated_at TEXT NOT NULL,priority INTEGER NOT NULL,objective TEXT NOT NULL,target_metric TEXT,current_value REAL NOT NULL DEFAULT 0,target_value REAL NOT NULL DEFAULT 0,status TEXT NOT NULL,owner TEXT NOT NULL,reason TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_superautonomy_goals_priority ON lumen_superautonomy_goals(status,priority DESC,updated_at DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_superautonomy_human_debt (debt_id TEXT PRIMARY KEY,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,category TEXT NOT NULL,reason TEXT NOT NULL,hits INTEGER NOT NULL DEFAULT 1,avoidable INTEGER NOT NULL DEFAULT 0,mitigation TEXT NOT NULL,status TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_superautonomy_human_debt_status ON lumen_superautonomy_human_debt(status,hits DESC,updated_at DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_superautonomy_postmortems (postmortem_id TEXT PRIMARY KEY,created_at TEXT NOT NULL,cycle INTEGER NOT NULL,outcome TEXT NOT NULL,action_key TEXT NOT NULL,target_metric TEXT,delta REAL NOT NULL DEFAULT 0,observation TEXT NOT NULL,lesson TEXT NOT NULL,promotion TEXT NOT NULL,confidence TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_superautonomy_postmortems_cycle ON lumen_superautonomy_postmortems(cycle DESC,created_at DESC)")
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
  const m=state?.metrics||{},b=state?.revenueFocus?.backlog||{};
  if(num(m.verifiedPaidCommerceOrders)>0)return {phase:"FULFILLMENT",bottleneck:"paid_fulfillment",targetMetric:"verifiedPaidCommerceOrders",roles:["risk_quality","revops"]};
  if(num(m.verifiedRevenueUsd)>0||num(m.verifiedSettlements)>0)return {phase:"SCALE",bottleneck:"scale_verified_revenue",targetMetric:"verifiedRevenueUsd",roles:["revops","research_analyst"]};
  if(num(b.closeIntent)>0||num(m.negotiating)>0)return {phase:"CLOSING",bottleneck:"close_verified_intent",targetMetric:"verifiedRevenueUsd",roles:["revops","negotiator","risk_quality"]};
  if(num(m.qualifiedCommercialResponses)>0)return {phase:"CONVERTING",bottleneck:"qualified_reply",targetMetric:"qualifiedCommercialResponses",roles:["revops","negotiator"]};
  if(num(b.followupsReady)>0)return {phase:"FOLLOWUP",bottleneck:"due_followup",targetMetric:"followupsReady",roles:["revops"]};
  if(num(m.approvedUnsent)>0)return {phase:"OUTBOUND_READY",bottleneck:"quality_pass_unsent",targetMetric:"approvedUnsent",roles:["revops"]};
  if(num(m.actionableOpportunities)>0)return {phase:"PROPOSAL_BUILD",bottleneck:"actionable_without_conversion",targetMetric:"approvedUnsent",roles:["revops","research_analyst"]};
  if(num(m.activeCandidates)>0)return {phase:"QUALIFYING",bottleneck:"candidate_quality",targetMetric:"actionableOpportunities",roles:["research_analyst","buyer_hunter"]};
  return {phase:"DISCOVERING",bottleneck:"demand_discovery",targetMetric:"activeCandidates",roles:["buyer_hunter","research_analyst"]};
}

const TACTICS={
  paid_fulfillment:[
    {id:"protect_fulfillment",action:"PROTECT_VERIFIED_FULFILLMENT",roles:["risk_quality","revops"],needsSearch:false},
    {id:"audit_fulfillment_truth",action:"AUDIT_FULFILLMENT_TRUTH",roles:["risk_quality"],needsSearch:false}
  ],
  scale_verified_revenue:[
    {id:"scale_verified_winner",action:"SCALE_VERIFIED_WINNER",roles:["revops","research_analyst"],needsSearch:false},
    {id:"replicate_proven_lane",action:"REPLICATE_PROVEN_LANE",roles:["revops"],needsSearch:false}
  ],
  close_verified_intent:[
    {id:"close_existing_intent",action:"CLOSE_EXISTING_INTENT",roles:["revops","negotiator"],needsSearch:false},
    {id:"prepare_close_packet",action:"PREPARE_COMPLETE_CLOSE_PACKET",roles:["revops","risk_quality"],needsSearch:false}
  ],
  qualified_reply:[
    {id:"qualify_and_reply",action:"QUALIFY_AND_REPLY",roles:["revops","negotiator"],needsSearch:false},
    {id:"objection_response",action:"PREPARE_OBJECTION_RESPONSE",roles:["negotiator","risk_quality"],needsSearch:false}
  ],
  due_followup:[
    {id:"due_followup",action:"EXECUTE_DUE_FOLLOWUP",roles:["revops"],needsSearch:false},
    {id:"followup_reframe",action:"REFRAME_FOLLOWUP_AROUND_BUYER_VALUE",roles:["revops","negotiator"],needsSearch:false}
  ],
  quality_pass_unsent:[
    {id:"quality_pass_inventory",action:"USE_EXISTING_QUALITY_PASS_INVENTORY",roles:["revops"],needsSearch:false},
    {id:"message_fit_review",action:"REVIEW_MESSAGE_PRODUCT_FIT_BEFORE_SEND",roles:["revops","risk_quality"],needsSearch:false}
  ],
  actionable_without_conversion:[
    {id:"advance_best_actionable",action:"ADVANCE_BEST_ACTIONABLE_OPPORTUNITY",roles:["revops","research_analyst"],needsSearch:false},
    {id:"low_friction_offer",action:"PREPARE_LOW_FRICTION_OFFER",roles:["revops","negotiator"],needsSearch:false}
  ],
  candidate_quality:[
    {id:"qualify_strongest",action:"QUALIFY_STRONGEST_CANDIDATE",roles:["research_analyst","buyer_hunter"],needsSearch:false},
    {id:"rotate_candidate",action:"ROTATE_TO_NEXT_EVIDENCE_BACKED_CANDIDATE",roles:["research_analyst"],needsSearch:false}
  ],
  demand_discovery:[
    {id:"discover_score_demand",action:"DISCOVER_AND_SCORE_DEMAND",roles:["buyer_hunter","research_analyst"],needsSearch:true},
    {id:"mine_existing_signals",action:"MINE_EXISTING_SIGNAL_INVENTORY",roles:["research_analyst"],needsSearch:false}
  ]
};

function memoryRow(actionMemory,id){return actionMemory?.[id]||{score:1,attempts:0,wins:0,stalls:0};}
function chooseTactic(bottleneck,actionMemory={},stallCycles=0){
  const choices=[...(TACTICS[bottleneck]||TACTICS.demand_discovery)];
  const ranked=choices.map((row,index)=>{
    const mem=memoryRow(actionMemory,row.id);
    const rotateBonus=stallCycles>=STALL_ROTATE_AFTER&&index>0?0.35:0;
    const noveltyBonus=num(mem.attempts)===0?0.15:0;
    return {...row,selectionScore:clamp(num(mem.score)||1,0.2,2)+rotateBonus+noveltyBonus,memory:mem};
  }).sort((a,b)=>b.selectionScore-a.selectionScore||num(a.memory.attempts)-num(b.memory.attempts)||a.id.localeCompare(b.id));
  return ranked[0];
}

function gateCategory(action){
  const value=String(action||"").toUpperCase();
  if(value.includes("PURCHASE"))return "PURCHASE";
  if(value.includes("PAY"))return "PAYMENT";
  if(value.includes("CONTRACT")||value.includes("BINDING"))return "BINDING_TERMS";
  if(value.includes("LEGAL"))return "LEGAL";
  if(value.includes("DEPLOY"))return "PRODUCTION_DEPLOY";
  if(value.includes("CONNECTOR"))return "NEW_CONNECTOR";
  if(value.includes("PAID_MEDIA"))return "PAID_MEDIA";
  return null;
}
function humanGate(state,tactic){return Boolean(gateCategory(state?.nextEconomicAction||tactic?.action));}

function recoveryPlan(stallCycles){
  if(stallCycles>=STALL_CHALLENGE_AFTER)return {level:4,mode:"CHALLENGE_ASSUMPTIONS",accelerateGrowthLoop:true,parallelLane:true,refreshPortfolio:true,reason:"prolonged_verified_stagnation"};
  if(stallCycles>=STALL_PARALLEL_AFTER)return {level:3,mode:"PARALLEL_ZERO_COST_LANE",accelerateGrowthLoop:true,parallelLane:true,refreshPortfolio:true,reason:"persistent_verified_stagnation"};
  if(stallCycles>=STALL_ROTATE_AFTER)return {level:2,mode:"ROTATE_TACTIC",accelerateGrowthLoop:true,parallelLane:false,refreshPortfolio:true,reason:"repeated_verified_stagnation"};
  if(stallCycles>=STALL_REBALANCE_AFTER)return {level:1,mode:"REBALANCE_ATTENTION",accelerateGrowthLoop:false,parallelLane:false,refreshPortfolio:false,reason:"early_stagnation"};
  return {level:0,mode:"NORMAL",accelerateGrowthLoop:false,parallelLane:false,refreshPortfolio:false,reason:"verified_progress_or_initial_cycle"};
}

function portfolioPlan(rows=[],stallCycles=0){
  const normalized=(rows||[]).slice(0,MAX_PORTFOLIO).map(row=>({
    id:row.id,
    sourceType:row.source_type,
    sourceId:row.source_id,
    lane:row.lane,
    stage:row.stage,
    title:row.title||null,
    estimatedValueUsd:num(row.estimated_value_usd),
    probability:num(row.probability),
    evidenceScore:num(row.evidence_score),
    signalScore:num(row.signal_score),
    economicScore:num(row.economic_score),
    actionKind:row.action_kind,
    actionRef:row.action_ref||null,
    rationale:row.rationale||null
  }));
  const primary=normalized[0]||null;
  const backups=[];
  const lanes=new Set(primary?.lane?[primary.lane]:[]);
  for(const row of normalized.slice(1)){
    if(backups.length>=3)break;
    if(!lanes.has(row.lane)||stallCycles>=STALL_ROTATE_AFTER){backups.push(row);lanes.add(row.lane);}
  }
  return {
    primary,
    backups,
    tracked:normalized.length,
    lanes:[...new Set(normalized.map(x=>x.lane).filter(Boolean))],
    rotationReady:backups.length>0,
    parkingPolicy:"do_not_delete; temporarily deprioritize repeated low-yield candidates while preserving evidence",
    abandonmentPolicy:"never mark lost solely from inactivity; require explicit evidence or downstream terminal status"
  };
}

function goalManager(state,decision,portfolio,openDebt=[]){
  const goals=[];
  const m=state?.metrics||{};
  goals.push({id:"GOAL-VERIFIED-REVENUE",priority:100,objective:"Reach and then scale verified realized revenue.",targetMetric:"verifiedRevenueUsd",current:num(m.verifiedRevenueUsd),target:Math.max(1,num(m.verifiedRevenueUsd)+1),status:num(m.verifiedRevenueUsd)>0?"active_scale":"active",owner:"revops",reason:"verified_revenue_is_the_terminal_truth_metric"});
  goals.push({id:`GOAL-BOTTLENECK-${decision.bottleneck.toUpperCase()}`,priority:96,objective:`Advance current bottleneck: ${decision.bottleneck}.`,targetMetric:decision.targetMetric,current:num(decision.currentValue),target:Math.max(1,num(decision.currentValue)+1),status:"active",owner:decision.roles?.[0]||"revops",reason:"current_verified_funnel_bottleneck"});
  if(portfolio?.primary)goals.push({id:"GOAL-PORTFOLIO-PRIMARY",priority:88,objective:`Advance highest-ranked evidence-backed candidate ${portfolio.primary.id}.`,targetMetric:"portfolio_primary_progress",current:0,target:1,status:"active",owner:"revops",reason:`lane_${portfolio.primary.lane||"unknown"}_economic_score_${portfolio.primary.economicScore}`});
  goals.push({id:"GOAL-HUMAN-ATTENTION",priority:84,objective:"Minimize avoidable human attention while preserving mandatory approval gates.",targetMetric:"openHumanAttentionDebt",current:openDebt.length,target:0,status:openDebt.length?"active":"achieved",owner:"system",reason:"prepare_complete_decision_packets_and_keep_reversible_work_running"});
  goals.push({id:"GOAL-RELIABILITY",priority:80,objective:"Keep the autonomous cycle recoverable, evidence-backed and non-blocking.",targetMetric:"stallCycles",current:num(decision.stallCycles),target:0,status:num(decision.stallCycles)>0?"active":"achieved",owner:"risk_quality",reason:"self_recovery_without_widening_authority"});
  return goals.sort((a,b)=>b.priority-a.priority).slice(0,MAX_GOALS);
}

function attentionPlan(decision,goals){
  const primaryRoles=decision.roles||[];
  const weights={revops:0,research_analyst:0,buyer_hunter:0,negotiator:0,risk_quality:0};
  primaryRoles.forEach((role,index)=>{if(role in weights)weights[role]+=index===0?0.12:0.07;});
  if(decision.recovery.level>=2)weights.research_analyst+=0.05;
  if(decision.humanGateRequired)weights.risk_quality+=0.08;
  const capped=Object.fromEntries(Object.entries(weights).filter(([,v])=>v>0).map(([k,v])=>[k,Number(Math.min(0.15,v).toFixed(3))]));
  return {roleBoosts:capped,capPerRole:0.15,goalCount:goals.length,authorityChange:false,budgetChange:false};
}

function preflightForGate(category){
  const map={
    PAYMENT:"PREPARE_PAYMENT_APPROVAL_PACKET",
    PURCHASE:"PREPARE_PURCHASE_APPROVAL_PACKET",
    BINDING_TERMS:"PREPARE_CONTRACT_APPROVAL_PACKET",
    LEGAL:"PREPARE_LEGAL_REVIEW_PACKET",
    PRODUCTION_DEPLOY:"PREPARE_DEPLOY_APPROVAL_PACKET",
    NEW_CONNECTOR:"PREPARE_CONNECTOR_APPROVAL_PACKET",
    PAID_MEDIA:"PREPARE_PAID_MEDIA_APPROVAL_PACKET"
  };
  return map[category]||"PREPARE_HUMAN_DECISION_PACKET";
}

export function decideSuperautonomy(economicState,previous=null,context={}){
  const bottleneck=chooseBottleneck(economicState);
  const current=metricValue(economicState,bottleneck.targetMetric);
  const prevState=previous?.state||{};
  const previousTarget=clean(prevState?.targetMetric||previous?.target_metric,120);
  const previousValue=num(prevState?.currentValue??previous?.current_value);
  const currentPreviousMetric=previousTarget?metricValue(economicState,previousTarget):0;
  const learningDelta=previousTarget?currentPreviousMetric-previousValue:0;
  const progress=Boolean(previousTarget&&learningDelta>0);
  const comparable=previousTarget===bottleneck.targetMetric;
  const baseline=comparable?previousValue:current;
  const stallCycles=progress?0:(comparable?num(previous?.stall_cycles)+1:0);
  const tactic=chooseTactic(bottleneck.bottleneck,context.actionMemory||{},stallCycles);
  const recovery=recoveryPlan(stallCycles);
  const humanGateRequired=humanGate(economicState,tactic);
  const category=humanGateRequired?gateCategory(economicState?.nextEconomicAction||tactic.action):null;
  const autonomousUnits=humanGateRequired?0:1;
  const priorRatio=num(previous?.autonomy_ratio);
  const cycle=num(previous?.cycle)+1;
  const boundedAutonomyRatio=cycle<=1?autonomousUnits:clamp(((priorRatio*(cycle-1))+autonomousUnits)/cycle,0,1);
  const portfolio=portfolioPlan(context.portfolioRows||[],stallCycles);
  const attentionDebt=context.openDebt||[];
  const goals=goalManager(economicState,{...bottleneck,currentValue:current,stallCycles,roles:tactic.roles},portfolio,attentionDebt);
  const attention=attentionPlan({...bottleneck,roles:tactic.roles,recovery,humanGateRequired},goals);
  return {
    version:VERSION,
    cycle,
    phase:bottleneck.phase,
    bottleneck:bottleneck.bottleneck,
    targetMetric:bottleneck.targetMetric,
    selectedTactic:tactic.id,
    nextAction:tactic.action,
    roles:tactic.roles,
    baselineValue:baseline,
    currentValue:current,
    progressMetric:previousTarget||bottleneck.targetMetric,
    progressBaseline:previousTarget?previousValue:current,
    progressCurrent:previousTarget?currentPreviousMetric:current,
    metricDelta:Number(learningDelta.toFixed(4)),
    verifiedProgress:progress,
    bottleneckAdvanced:Boolean(previousTarget&&previousTarget!==bottleneck.targetMetric&&progress),
    stallCycles,
    recovery,
    portfolio,
    goals,
    attention,
    humanGateRequired,
    humanGateCategory:category,
    humanPreflightAction:humanGateRequired?preflightForGate(category):null,
    boundedAutonomyRatio:Number(boundedAutonomyRatio.toFixed(4)),
    ratioDefinition:"non_binding_superautonomy_cycles_completed_without_human_gate / total_superautonomy_cycles",
    humanAttentionDebt:{open:attentionDebt.length,policy:"reduce preparation burden; never bypass mandatory financial, legal, contractual, connector, paid-media or production approvals"},
    economicOperatorAction:economicState?.nextEconomicAction||null,
    revenueFocus:economicState?.revenueFocus?.mode||null,
    authority:{autonomousSpendUsd:0,autonomousPurchase:false,autonomousContract:false,autonomousDebt:false,paidMedia:false,productionDeploy:false,newExternalConnectors:false,bindingActionsHumanGated:true},
    learningPolicy:"promote tactics only after observed verified funnel or revenue progress; demote repeated stalls; treat attribution as observational unless explicit evidence proves causality",
    executionPolicy:"refresh internal opportunity portfolio and continue reversible zero-spend work automatically; escalate only explicit binding or financial authority",
    v2Capabilities:{goalManager:true,opportunityPortfolio:true,actionMemory:true,humanAttentionOptimizer:true,postmortems:true,recoveryEngine:true,antiStall:true,adaptivePriority:true}
  };
}

async function readState(env){
  const row=await first(env,"SELECT * FROM lumen_superautonomy_state WHERE id='GLOBAL' LIMIT 1");
  if(!row)return null;
  return {...row,state:parse(row.state_json,{})};
}

async function readActionMemory(env){
  const rows=await all(env,"SELECT action_key,attempts,wins,stalls,score,last_outcome,last_metric,last_delta,updated_at FROM lumen_superautonomy_action_memory");
  return Object.fromEntries(rows.map(row=>[row.action_key,{...row,attempts:num(row.attempts),wins:num(row.wins),stalls:num(row.stalls),score:num(row.score)||1,last_delta:num(row.last_delta)}]));
}

async function readPortfolioRows(env){
  return all(env,"SELECT id,source_type,source_id,lane,stage,title,estimated_value_usd,probability,urgency,evidence_score,signal_score,economic_score,action_kind,action_ref,rationale,updated_at FROM lumen_opportunity_factory_candidates WHERE active=1 ORDER BY CASE lane WHEN 'COLLECTION' THEN 0 WHEN 'CLOSE' THEN 1 WHEN 'INBOUND' THEN 2 WHEN 'FOLLOW_UP' THEN 3 WHEN 'NEW_BUSINESS' THEN 4 ELSE 5 END,economic_score DESC,updated_at DESC LIMIT 12");
}

async function readOpenDebt(env){
  return all(env,"SELECT debt_id,created_at,updated_at,category,reason,hits,avoidable,mitigation,status FROM lumen_superautonomy_human_debt WHERE status='OPEN' ORDER BY hits DESC,updated_at DESC LIMIT 20");
}

async function updateActionMemory(env,previous,decision){
  const previousState=previous?.state||{};
  const actionKey=clean(previousState?.selectedTactic,120);
  const previousTarget=clean(previousState?.targetMetric,120);
  if(!actionKey||!previousTarget||decision.progressMetric!==previousTarget)return null;
  const delta=num(decision.metricDelta);
  const won=decision.verifiedProgress?1:0;
  const stalled=won?0:1;
  const prior=await first(env,"SELECT attempts,wins,stalls,score FROM lumen_superautonomy_action_memory WHERE action_key=? LIMIT 1",[actionKey]);
  const score=clamp((num(prior?.score)||1)+(won?0.18:-0.10),0.2,2);
  const outcome=won?"VERIFIED_PROGRESS":"NO_VERIFIED_PROGRESS";
  await env.DB.prepare("INSERT INTO lumen_superautonomy_action_memory(action_key,updated_at,attempts,wins,stalls,score,last_outcome,last_metric,last_delta,engine_version) VALUES(?,?,1,?,?,?,?,?,?,?) ON CONFLICT(action_key) DO UPDATE SET updated_at=excluded.updated_at,attempts=lumen_superautonomy_action_memory.attempts+1,wins=lumen_superautonomy_action_memory.wins+?,stalls=lumen_superautonomy_action_memory.stalls+?,score=?,last_outcome=?,last_metric=?,last_delta=?,engine_version=excluded.engine_version")
    .bind(actionKey,now(),won,stalled,score,outcome,previousTarget,delta,VERSION,won,stalled,score,outcome,previousTarget,delta).run();
  return {actionKey,outcome,metric:previousTarget,delta,score};
}

async function persistGoals(env,goals){
  const ts=now();
  await env.DB.prepare("UPDATE lumen_superautonomy_goals SET status='SUPERSEDED',updated_at=? WHERE status IN ('active','active_scale')").bind(ts).run();
  for(const goal of goals){
    await env.DB.prepare("INSERT OR REPLACE INTO lumen_superautonomy_goals(goal_id,updated_at,priority,objective,target_metric,current_value,target_value,status,owner,reason,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?)")
      .bind(goal.id,ts,goal.priority,goal.objective,goal.targetMetric,num(goal.current),num(goal.target),goal.status,goal.owner,goal.reason,VERSION).run();
  }
}

async function recordHumanDebt(env,decision){
  if(!decision.humanGateRequired)return null;
  const category=decision.humanGateCategory||"HUMAN_DECISION";
  const debtId=`DEBT-${category}`;
  const ts=now();
  const reason=`Mandatory ${category} approval blocks only the binding step; reversible preparation should continue automatically.`;
  const mitigation=decision.humanPreflightAction||"PREPARE_HUMAN_DECISION_PACKET";
  await env.DB.prepare("INSERT INTO lumen_superautonomy_human_debt(debt_id,created_at,updated_at,category,reason,hits,avoidable,mitigation,status,engine_version) VALUES(?,?,?,?,?,1,0,?,'OPEN',?) ON CONFLICT(debt_id) DO UPDATE SET updated_at=excluded.updated_at,hits=lumen_superautonomy_human_debt.hits+1,reason=excluded.reason,mitigation=excluded.mitigation,status='OPEN',engine_version=excluded.engine_version")
    .bind(debtId,ts,ts,category,reason,mitigation,VERSION).run();
  return {debtId,category,mitigation};
}

async function maybePostmortem(env,previous,decision){
  const prev=previous?.state||{};
  const actionKey=clean(prev?.selectedTactic,120);
  const previousTarget=clean(prev?.targetMetric,120);
  if(!actionKey||!previousTarget||decision.progressMetric!==previousTarget)return null;
  const important=decision.verifiedProgress||decision.stallCycles===STALL_ROTATE_AFTER||decision.stallCycles===STALL_PARALLEL_AFTER||decision.stallCycles===STALL_CHALLENGE_AFTER;
  if(!important)return null;
  const outcome=decision.verifiedProgress?"VERIFIED_PROGRESS":`STALL_LEVEL_${decision.recovery.level}`;
  const observation=decision.verifiedProgress
    ? `Observed ${previousTarget} improvement of ${decision.metricDelta} after tactic ${actionKey}.`
    : `No observed ${previousTarget} improvement across ${decision.stallCycles} comparable cycles after tactic ${actionKey}.`;
  const lesson=decision.verifiedProgress
    ? `Increase preference for ${actionKey} in comparable conditions, while keeping attribution observational.`
    : `Reduce preference for ${actionKey}, rotate tactic, refresh portfolio evidence and preserve authority gates.`;
  const promotion=decision.verifiedProgress?"PROMOTE_TACTIC_WEIGHT":"DEMOTE_AND_ROTATE";
  const confidence=decision.verifiedProgress&&Math.abs(num(decision.metricDelta))>0?"MEDIUM":"LOW";
  const id=`PM-${String(decision.cycle).padStart(8,"0")}-${actionKey.slice(0,40)}`;
  await env.DB.prepare("INSERT OR REPLACE INTO lumen_superautonomy_postmortems(postmortem_id,created_at,cycle,outcome,action_key,target_metric,delta,observation,lesson,promotion,confidence,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)")
    .bind(id,now(),decision.cycle,outcome,actionKey,previousTarget,num(decision.metricDelta),observation,lesson,promotion,confidence,VERSION).run();
  return {id,outcome,actionKey,targetMetric:previousTarget,lesson,promotion,confidence};
}

async function persist(env,decision){
  const ts=now(),cycleId=`SA-${String(decision.cycle).padStart(8,"0")}`;
  const stateJson=JSON.stringify({...decision,updatedAt:ts});
  await env.DB.batch([
    env.DB.prepare("INSERT OR REPLACE INTO lumen_superautonomy_state(id,updated_at,cycle,phase,bottleneck,next_action,target_metric,stall_cycles,recovery_level,autonomy_ratio,state_json,engine_version) VALUES('GLOBAL',?,?,?,?,?,?,?,?,?,?,?)").bind(ts,decision.cycle,decision.phase,decision.bottleneck,decision.nextAction,decision.targetMetric,decision.stallCycles,decision.recovery.level,decision.boundedAutonomyRatio,stateJson,VERSION),
    env.DB.prepare("INSERT OR REPLACE INTO lumen_superautonomy_history(cycle_id,created_at,phase,bottleneck,next_action,target_metric,baseline_value,current_value,progress,human_gate_required,recovery_level,decision_json,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)").bind(cycleId,ts,decision.phase,decision.bottleneck,decision.nextAction,decision.targetMetric,decision.baselineValue,decision.currentValue,decision.verifiedProgress?1:0,decision.humanGateRequired?1:0,decision.recovery.level,stateJson,VERSION)
  ]);
  await env.DB.prepare("DELETE FROM lumen_superautonomy_history WHERE cycle_id NOT IN (SELECT cycle_id FROM lumen_superautonomy_history ORDER BY created_at DESC LIMIT 120)").run();
  return {...decision,updatedAt:ts};
}

async function internalRefresh(env){
  const factory=await runSafe(()=>runOpportunityFactory(env),{ok:false,stage:"opportunity_factory"});
  const governor=await runSafe(()=>recomputePortfolioGovernor(env),{ok:false,stage:"portfolio_governor"});
  return {factory,governor,externalMessagesCreated:false,autonomousSpendUsd:0};
}

export async function runSuperautonomyCycle(env,{trigger="scheduled"}={}){
  if(!env?.DB)return {ok:false,version:VERSION,error:"db_unavailable",authority:{autonomousSpendUsd:0,bindingActionsHumanGated:true}};
  await ensureSchema(env);
  const previous=await readState(env);
  const refresh=await internalRefresh(env);
  const [economicState,actionMemory,portfolioRows,openDebt]=await Promise.all([
    computeEconomicOperatorState(env),
    readActionMemory(env),
    readPortfolioRows(env),
    readOpenDebt(env)
  ]);
  const decision=decideSuperautonomy(economicState,previous,{actionMemory,portfolioRows,openDebt});
  const memoryUpdate=await updateActionMemory(env,previous,decision);
  const humanDebt=await recordHumanDebt(env,decision);
  const postmortem=await maybePostmortem(env,previous,decision);
  await persistGoals(env,decision.goals);
  const persisted=await persist(env,{...decision,trigger,internalRefresh:refresh,memoryUpdate,humanDebt,postmortem});
  return {ok:true,...persisted,trigger};
}

export async function superautonomyStatus(env){
  await ensureSchema(env);
  const [state,history,goals,debt,postmortems,memory]=await Promise.all([
    readState(env),
    all(env,"SELECT created_at,cycle_id,phase,bottleneck,next_action,target_metric,baseline_value,current_value,progress,human_gate_required,recovery_level FROM lumen_superautonomy_history ORDER BY created_at DESC LIMIT 16"),
    all(env,"SELECT goal_id,updated_at,priority,objective,target_metric,current_value,target_value,status,owner,reason FROM lumen_superautonomy_goals ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'active_scale' THEN 0 WHEN 'achieved' THEN 1 ELSE 2 END,priority DESC LIMIT 12"),
    readOpenDebt(env),
    all(env,"SELECT postmortem_id,created_at,cycle,outcome,action_key,target_metric,delta,observation,lesson,promotion,confidence FROM lumen_superautonomy_postmortems ORDER BY cycle DESC LIMIT 12"),
    all(env,"SELECT action_key,updated_at,attempts,wins,stalls,score,last_outcome,last_metric,last_delta FROM lumen_superautonomy_action_memory ORDER BY score DESC,updated_at DESC LIMIT 20")
  ]);
  return {ok:true,version:VERSION,state:state?.state||null,history,goals,humanAttentionDebt:debt,postmortems,actionMemory:memory};
}

export async function handleSuperautonomy(request,env){
  const url=new URL(request.url);
  if(request.method==="OPTIONS"&&url.pathname.startsWith("/superautonomy"))return new Response(null,{status:204,headers:{"access-control-allow-origin":"*","access-control-allow-headers":"content-type,x-lumen-admin","access-control-allow-methods":"GET,POST,OPTIONS"}});
  if(request.method==="GET"&&url.pathname==="/superautonomy/policy")return json({
    version:VERSION,
    name:"LUMEN Superautonomy v2",
    cycle:"observe_prioritize_refresh_portfolio_choose_act_measure_learn_postmortem_recover_next",
    goalManager:true,
    opportunityPortfolio:true,
    actionMemory:true,
    postmortems:true,
    recoveryEngine:true,
    humanAttentionOptimizer:true,
    antiStall:true,
    adaptivePriority:true,
    boundedAutonomyRatio:true,
    autonomousSpendUsd:0,
    autonomousPurchase:false,
    autonomousContract:false,
    autonomousDebt:false,
    paidMedia:false,
    productionDeploy:false,
    newExternalConnectors:false,
    bindingActionsHumanGated:true,
    principle:"maximize verified economic progress while minimizing avoidable human attention without bypassing mandatory authority gates"
  });
  if(request.method==="GET"&&url.pathname==="/superautonomy/status")return json(await superautonomyStatus(env));
  if(request.method==="GET"&&url.pathname==="/superautonomy/goals"){
    await ensureSchema(env);
    return json({ok:true,version:VERSION,goals:await all(env,"SELECT goal_id,updated_at,priority,objective,target_metric,current_value,target_value,status,owner,reason FROM lumen_superautonomy_goals ORDER BY priority DESC LIMIT 20")});
  }
  if(request.method==="GET"&&url.pathname==="/superautonomy/debt"){
    await ensureSchema(env);
    return json({ok:true,version:VERSION,humanAttentionDebt:await readOpenDebt(env)});
  }
  if(request.method==="GET"&&url.pathname==="/superautonomy/postmortems"){
    await ensureSchema(env);
    return json({ok:true,version:VERSION,postmortems:await all(env,"SELECT postmortem_id,created_at,cycle,outcome,action_key,target_metric,delta,observation,lesson,promotion,confidence FROM lumen_superautonomy_postmortems ORDER BY cycle DESC LIMIT 30")});
  }
  if(request.method==="POST"&&url.pathname==="/superautonomy/run"){
    if(!authorized(request,env))return json({ok:false,error:"unauthorized"},401);
    return json(await runSuperautonomyCycle(env,{trigger:"admin_run"}),202);
  }
  return null;
}

export { VERSION as SUPER_AUTONOMY_VERSION, MAX_HISTORY, chooseTactic, portfolioPlan };
