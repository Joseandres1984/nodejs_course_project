import { buildDynamicTeams } from "./dynamic-team-engine.js";
import { dispatchNextDelegationTask, pollDelegationTasks } from "./delegation-runtime.js";

const VERSION = "3.0-four-engine-superautonomy";
const MAX_PLAN_STEPS = 7;
const MAX_EXPERIMENT_HISTORY = 80;

function num(v, fallback = 0) { const n = Number(v); return Number.isFinite(n) ? n : fallback; }
function clean(v, n = 320) { return String(v ?? "").replace(/[\r\n\t]+/g, " ").replace(/\s+/g, " ").trim().slice(0, n); }
function clamp(v, min, max) { return Math.max(min, Math.min(max, num(v))); }
function parse(v, fallback = {}) { try { return JSON.parse(String(v || "")); } catch { return fallback; } }
function now() { return new Date().toISOString(); }
function bool(v) { return String(v ?? "false").toLowerCase() === "true"; }
function json(data, status = 200) { return Response.json(data, { status, headers: { "cache-control":"no-store", "x-content-type-options":"nosniff", "access-control-allow-origin":"*", "access-control-allow-headers":"content-type,x-lumen-admin", "access-control-allow-methods":"GET,POST,OPTIONS" } }); }
function authorized(request, env) { const expected = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500), supplied = clean(request.headers.get("x-lumen-admin"), 500); return Boolean(expected && supplied && expected === supplied); }

async function first(env, sql, bind = []) { try { const q = env.DB.prepare(sql); return bind.length ? await q.bind(...bind).first() : await q.first(); } catch { return null; } }
async function all(env, sql, bind = []) { try { const q = env.DB.prepare(sql), r = bind.length ? await q.bind(...bind).all() : await q.all(); return r.results || []; } catch { return []; } }
async function isolated(step, fallback = { ok:false }) { try { return await step(); } catch (error) { return { ...fallback, isolatedFailure:true, error:clean(error?.message || error, 220) }; } }

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_v3_self_model (capability_key TEXT PRIMARY KEY,updated_at TEXT NOT NULL,score REAL NOT NULL DEFAULT 0,level INTEGER NOT NULL DEFAULT 0,evidence_count INTEGER NOT NULL DEFAULT 0,successes INTEGER NOT NULL DEFAULT 0,failures INTEGER NOT NULL DEFAULT 0,autonomy_mode TEXT NOT NULL,reason TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_v3_self_model_level ON lumen_v3_self_model(level DESC,score DESC,updated_at DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_v3_plans (plan_id TEXT PRIMARY KEY,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,cycle INTEGER NOT NULL DEFAULT 0,context_key TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,status TEXT NOT NULL,replan_reason TEXT NOT NULL,target_metric TEXT,plan_json TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_v3_plans_current ON lumen_v3_plans(status,updated_at DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_v3_strategy_experiments (experiment_id TEXT PRIMARY KEY,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,context_key TEXT NOT NULL,target_metric TEXT,champion_action TEXT,challenger_action TEXT,recommended_arm TEXT NOT NULL,baseline_value REAL NOT NULL DEFAULT 0,latest_value REAL NOT NULL DEFAULT 0,evidence_count INTEGER NOT NULL DEFAULT 0,exploration_share REAL NOT NULL DEFAULT 0,status TEXT NOT NULL,result TEXT,experiment_json TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_v3_experiments_context ON lumen_v3_strategy_experiments(context_key,status,updated_at DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_v3_swarm_state (id TEXT PRIMARY KEY,updated_at TEXT NOT NULL,teams_built INTEGER NOT NULL DEFAULT 0,prepared_tasks INTEGER NOT NULL DEFAULT 0,active_tasks INTEGER NOT NULL DEFAULT 0,result_tasks INTEGER NOT NULL DEFAULT 0,failed_tasks INTEGER NOT NULL DEFAULT 0,dispatch_enabled INTEGER NOT NULL DEFAULT 0,state_json TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_v3_state (id TEXT PRIMARY KEY,updated_at TEXT NOT NULL,cycle INTEGER NOT NULL DEFAULT 0,context_key TEXT NOT NULL,state_json TEXT NOT NULL,engine_version TEXT NOT NULL)")
  ]);
  return true;
}

async function loadContext(env) {
  const [sa, goals, actionMemory, meta, contextMemory, delegation, teams, learning, postmortems] = await Promise.all([
    first(env, "SELECT cycle,phase,bottleneck,next_action,target_metric,stall_cycles,recovery_level,autonomy_ratio,state_json,updated_at FROM lumen_superautonomy_state WHERE id='GLOBAL' LIMIT 1"),
    all(env, "SELECT goal_id,priority,objective,target_metric,current_value,target_value,status,owner,reason FROM lumen_superautonomy_goals WHERE status IN ('active','active_scale') ORDER BY priority DESC LIMIT 8"),
    all(env, "SELECT action_key,attempts,wins,stalls,score,last_outcome,last_metric,last_delta,updated_at FROM lumen_superautonomy_action_memory ORDER BY score DESC,updated_at DESC LIMIT 60"),
    first(env, "SELECT cycle,context_key,mode,preferred_action,challenger_action,confidence,recommendation_json,updated_at FROM lumen_meta_controller_state WHERE id='GLOBAL' LIMIT 1"),
    all(env, "SELECT context_key,action_key,attempts,wins,stalls,score,last_outcome,last_delta,updated_at FROM lumen_meta_context_memory ORDER BY updated_at DESC LIMIT 100"),
    first(env, "SELECT COUNT(*) total,SUM(CASE WHEN status='PLANNED' THEN 1 ELSE 0 END) planned,SUM(CASE WHEN status='APPROVED_FOR_DISPATCH' THEN 1 ELSE 0 END) approved,SUM(CASE WHEN status IN ('DISPATCHED','DISPATCHED_ACK') THEN 1 ELSE 0 END) active,SUM(CASE WHEN status='RESULT_RECEIVED' THEN 1 ELSE 0 END) results,SUM(CASE WHEN status='FAILED' THEN 1 ELSE 0 END) failed,COALESCE(AVG(CASE WHEN quality_score IS NOT NULL THEN quality_score END),0) avg_quality FROM lumen_delegation_tasks"),
    first(env, "SELECT COUNT(*) total,SUM(CASE WHEN status='DRAFT_TEAM' THEN 1 ELSE 0 END) active,COALESCE(MAX(CASE WHEN status='DRAFT_TEAM' THEN team_score ELSE 0 END),0) best_score FROM lumen_dynamic_teams"),
    first(env, "SELECT COUNT(*) total,SUM(CASE WHEN signal_strength>0 THEN 1 ELSE 0 END) positive,SUM(CASE WHEN signal_strength<=0 THEN 1 ELSE 0 END) nonpositive FROM lumen_self_learning_events"),
    first(env, "SELECT COUNT(*) total,SUM(CASE WHEN outcome='VERIFIED_PROGRESS' THEN 1 ELSE 0 END) progress FROM lumen_superautonomy_postmortems")
  ]);
  const state = parse(sa?.state_json, {});
  const phase = clean(sa?.phase || state?.phase || "UNKNOWN", 80);
  const bottleneck = clean(sa?.bottleneck || state?.bottleneck || "unknown", 120);
  const contextKey = clean(meta?.context_key || `${phase}:${bottleneck}`, 180);
  return {
    cycle:num(sa?.cycle), phase, bottleneck, contextKey,
    nextAction:clean(sa?.next_action || state?.nextAction, 180) || null,
    selectedTactic:clean(state?.selectedTactic || "", 180) || null,
    targetMetric:clean(sa?.target_metric || state?.targetMetric, 140) || null,
    currentValue:num(state?.currentValue), baselineValue:num(state?.baselineValue),
    stallCycles:num(sa?.stall_cycles), recoveryLevel:num(sa?.recovery_level), autonomyRatio:num(sa?.autonomy_ratio),
    superState:state, goals, actionMemory,
    meta:meta ? { ...meta, recommendation:parse(meta.recommendation_json,{}) } : null,
    contextMemory,
    delegation:{total:num(delegation?.total),planned:num(delegation?.planned),approved:num(delegation?.approved),active:num(delegation?.active),results:num(delegation?.results),failed:num(delegation?.failed),avgQuality:num(delegation?.avg_quality)},
    teams:{total:num(teams?.total),active:num(teams?.active),bestScore:num(teams?.best_score)},
    learning:{total:num(learning?.total),positive:num(learning?.positive),nonpositive:num(learning?.nonpositive)},
    postmortems:{total:num(postmortems?.total),progress:num(postmortems?.progress)}
  };
}

function capabilityLevel(score, evidence) {
  if (evidence <= 0) return 0;
  if (score < 40) return 1;
  if (score < 60 || evidence < 3) return 2;
  if (score < 78 || evidence < 8) return 3;
  return 4;
}
function autonomyMode(level) {
  return ["OBSERVE_ONLY","ASSIST_ONLY","RECOMMEND_AND_PREPARE","AUTONOMOUS_REVERSIBLE","TRUSTED_AUTONOMOUS_REVERSIBLE"][clamp(level,0,4)];
}
function scoreFromEvidence(attempts, wins, quality = 0) {
  attempts = Math.max(0, num(attempts)); wins = clamp(wins,0,attempts || 0); quality = clamp(quality,0,100);
  if (!attempts) return 25;
  const successRate = wins / Math.max(1, attempts);
  const confidence = Math.min(1, Math.log1p(attempts) / Math.log(10));
  const qualityTerm = quality > 0 ? (quality - 50) * 0.18 : 0;
  return clamp(30 + 50 * successRate * confidence + 18 * confidence + qualityTerm, 0, 100);
}
function rowsFor(memory, needles) {
  return memory.filter(r => needles.some(n => String(r.action_key || "").toLowerCase().includes(n)));
}
function summarizeMemory(rows) {
  return rows.reduce((a,r)=>({attempts:a.attempts+num(r.attempts),wins:a.wins+num(r.wins),stalls:a.stalls+num(r.stalls)}),{attempts:0,wins:0,stalls:0});
}

export function deriveSelfModel(context) {
  const specs = [
    ["commercial_reasoning", context.actionMemory, context.postmortems.progress, context.postmortems.total, 0, "choosing and revising commercial tactics"],
    ["opportunity_qualification", rowsFor(context.actionMemory,["qualify","candidate","evidence"]), null, null, 0, "turning candidate evidence into actionable opportunities"],
    ["outbound_followup", rowsFor(context.actionMemory,["followup","message","outbound","send"]), null, null, 0, "reversible commercial follow-up and message preparation"],
    ["conversion", rowsFor(context.actionMemory,["close","reply","proposal","objection"]), null, null, 0, "moving verified demand toward close-ready states"],
    ["delegation", [], context.delegation.results, context.delegation.results + context.delegation.failed, context.delegation.avgQuality, "delegating bounded zero-spend specialist work"],
    ["recovery", rowsFor(context.actionMemory,["rotate","reframe","mine","audit"]), null, null, 0, "recovering from repeated verified stagnation"],
    ["learning", [], context.learning.positive, context.learning.total, 0, "changing future preferences from observed outcomes"],
    ["multiagent_orchestration", [], context.teams.active, context.teams.total, context.teams.bestScore, "assembling specialist teams with trust and quality gates"]
  ];
  return specs.map(([key, rows, explicitWins, explicitAttempts, quality, reason]) => {
    const m = rows.length ? summarizeMemory(rows) : {attempts:num(explicitAttempts),wins:num(explicitWins),stalls:Math.max(0,num(explicitAttempts)-num(explicitWins))};
    const score = Number(scoreFromEvidence(m.attempts,m.wins,quality).toFixed(1));
    const level = capabilityLevel(score,m.attempts);
    return { capability:key, score, level, evidenceCount:m.attempts, successes:m.wins, failures:m.stalls, autonomyMode:autonomyMode(level), reason };
  });
}

async function persistSelfModel(env, model) {
  const ts = now();
  for (const row of model) {
    await env.DB.prepare("INSERT INTO lumen_v3_self_model(capability_key,updated_at,score,level,evidence_count,successes,failures,autonomy_mode,reason,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(capability_key) DO UPDATE SET updated_at=excluded.updated_at,score=excluded.score,level=excluded.level,evidence_count=excluded.evidence_count,successes=excluded.successes,failures=excluded.failures,autonomy_mode=excluded.autonomy_mode,reason=excluded.reason,engine_version=excluded.engine_version")
      .bind(row.capability,ts,row.score,row.level,row.evidenceCount,row.successes,row.failures,row.autonomyMode,row.reason,VERSION).run();
  }
}

function competence(model,key) { return model.find(x => x.capability === key) || {score:0,level:0,evidenceCount:0,autonomyMode:"OBSERVE_ONLY"}; }
function requiredCapability(context) {
  const b = context.bottleneck.toLowerCase();
  if (b.includes("followup") || b.includes("unsent")) return "outbound_followup";
  if (b.includes("close") || b.includes("reply") || b.includes("conversion")) return "conversion";
  if (b.includes("candidate") || b.includes("demand") || b.includes("actionable")) return "opportunity_qualification";
  return "commercial_reasoning";
}

function experimentCandidates(context) {
  const contextual = context.contextMemory.filter(x => x.context_key === context.contextKey && num(x.attempts) > 0)
    .map(x => ({action:clean(x.action_key,160),score:num(x.score),attempts:num(x.attempts),wins:num(x.wins),stalls:num(x.stalls),source:"context"}))
    .sort((a,b)=>b.score-a.score||b.wins-a.wins||a.stalls-b.stalls);
  const global = context.actionMemory.map(x=>({action:clean(x.action_key,160),score:num(x.score),attempts:num(x.attempts),wins:num(x.wins),stalls:num(x.stalls),source:"global"}));
  const seen = new Set();
  return [...contextual,...global].filter(x=>x.action&&!seen.has(x.action)&&(seen.add(x.action),true));
}

export function chooseStrategyExperiment(context) {
  const candidates = experimentCandidates(context);
  const metaPreferred = clean(context.meta?.preferred_action || context.meta?.recommendation?.preferredAction || "",160) || null;
  const metaChallenger = clean(context.meta?.challenger_action || context.meta?.recommendation?.challengerAction || "",160) || null;
  const champion = metaPreferred || candidates[0]?.action || context.selectedTactic || context.nextAction || null;
  let challenger = metaChallenger || candidates.find(x=>x.action!==champion)?.action || null;
  if (challenger === champion) challenger = null;
  const evidence = candidates.slice(0,2).reduce((n,x)=>n+x.attempts,0);
  const lowEvidence = evidence < 6;
  const explore = context.stallCycles >= 3 || lowEvidence;
  const recommendedArm = explore && challenger ? "CHALLENGER" : "CHAMPION";
  const recommendedAction = recommendedArm === "CHALLENGER" ? challenger : champion;
  const explorationShare = context.stallCycles >= 6 ? 0.50 : lowEvidence ? 0.40 : context.stallCycles >= 3 ? 0.35 : 0.20;
  return {
    contextKey:context.contextKey,targetMetric:context.targetMetric,champion,challenger,recommendedArm,recommendedAction,
    baselineValue:context.currentValue,evidenceCount:evidence,explorationShare,
    hypothesis:challenger ? `${champion} remains the working champion while ${challenger} receives bounded exploration when evidence is weak or progress stalls.` : "Keep learning until a comparable challenger has enough evidence to test.",
    falsificationRule:context.meta?.recommendation?.whatWouldChangeMyMind || `Change preference if the chosen action repeatedly fails to improve ${context.targetMetric || "the target metric"} under comparable conditions.`,
    attributionPolicy:"observational_only_until_repeated_comparable_evidence"
  };
}

async function persistExperiment(env, context, experiment) {
  const previous = await first(env,"SELECT experiment_id,target_metric,baseline_value,latest_value,status FROM lumen_v3_strategy_experiments WHERE context_key=? AND status='ACTIVE' ORDER BY updated_at DESC LIMIT 1",[context.contextKey]);
  if (previous) {
    const comparable = clean(previous.target_metric,140) === clean(context.targetMetric,140);
    const result = comparable && context.currentValue > num(previous.baseline_value) ? "PROGRESS_OBSERVED_IN_CONTEXT" : comparable ? "NO_PROGRESS_OBSERVED_YET" : "CONTEXT_CHANGED";
    await env.DB.prepare("UPDATE lumen_v3_strategy_experiments SET updated_at=?,latest_value=?,status='OBSERVED',result=? WHERE experiment_id=?")
      .bind(now(),context.currentValue,result,previous.experiment_id).run();
  }
  const id = `EXP-${String(context.cycle).padStart(8,"0")}-${crypto.randomUUID().slice(0,8)}`;
  const payload = { ...experiment, createdForCycle:context.cycle, guardrails:{zeroSpend:true,nonBinding:true,reversiblePreferenceExperiment:true,selfModifyingCode:false} };
  await env.DB.prepare("INSERT INTO lumen_v3_strategy_experiments(experiment_id,created_at,updated_at,context_key,target_metric,champion_action,challenger_action,recommended_arm,baseline_value,latest_value,evidence_count,exploration_share,status,result,experiment_json,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
    .bind(id,now(),now(),context.contextKey,context.targetMetric,experiment.champion,experiment.challenger,experiment.recommendedArm,context.currentValue,context.currentValue,experiment.evidenceCount,experiment.explorationShare,"ACTIVE",null,JSON.stringify(payload),VERSION).run();
  await env.DB.prepare("DELETE FROM lumen_v3_strategy_experiments WHERE experiment_id NOT IN (SELECT experiment_id FROM lumen_v3_strategy_experiments ORDER BY updated_at DESC LIMIT ?)").bind(MAX_EXPERIMENT_HISTORY).run();
  return {id,...payload};
}

export function buildAutonomousPlan(context, model, experiment, previousPlan = null) {
  const skillKey = requiredCapability(context);
  const skill = competence(model,skillKey);
  const canExecuteReversible = skill.level >= 3;
  const contextChanged = Boolean(previousPlan && clean(previousPlan.context_key,180) !== context.contextKey);
  const replanReason = contextChanged ? "CONTEXT_CHANGED" : context.recoveryLevel > 0 ? `RECOVERY_LEVEL_${context.recoveryLevel}` : context.stallCycles >= 3 ? "STALL_TRIGGERED_REPLAN" : "CONTINUOUS_REPLAN";
  const action = experiment.recommendedAction || context.selectedTactic || context.nextAction || "OBSERVE_AND_GATHER_EVIDENCE";
  const multiAgentUseful = ["opportunity_qualification","conversion","commercial_reasoning"].includes(skillKey) && (context.stallCycles >= 2 || context.recoveryLevel >= 2);
  const steps = [
    {id:"S1",kind:"VERIFY_CONTEXT",action:`VERIFY_${context.bottleneck.toUpperCase()}`,authority:"AUTO",reversible:true,expectedEvidence:`Current ${context.targetMetric || "target metric"} and bottleneck evidence`},
    {id:"S2",kind:"EXECUTE_TACTIC",action,authority:canExecuteReversible?"AUTO_REVERSIBLE":"PREPARE_ONLY",reversible:true,requiresCapability:skillKey,competenceLevel:skill.level,expectedEvidence:`Observable movement in ${context.targetMetric || "target metric"}`},
    {id:"S3",kind:"MEASURE",action:`MEASURE_${clean(context.targetMetric || "OUTCOME",80).toUpperCase()}`,authority:"AUTO",reversible:true,expectedEvidence:"Verified before/after metric comparison"},
    {id:"S4",kind:"LEARN",action:"UPDATE_CONTEXTUAL_MEMORY_AND_POSTMORTEM",authority:"AUTO",reversible:true,expectedEvidence:"Observed outcome recorded without causal overclaim"},
    {id:"S5",kind:"REPLAN",action:context.stallCycles>=3&&experiment.challenger?`TEST_CHALLENGER_${experiment.challenger}`:"KEEP_OR_ROTATE_BY_EVIDENCE",authority:"AUTO_REVERSIBLE",reversible:true,expectedEvidence:experiment.falsificationRule}
  ];
  if (multiAgentUseful) steps.push({id:"S6",kind:"SWARM",action:"ASSEMBLE_AND_DELEGATE_ZERO_SPEND_SPECIALIST_SUPPORT",authority:"AUTO_IF_ALREADY_QUALITY_APPROVED",reversible:true,requiresCapability:"multiagent_orchestration",expectedEvidence:"Team quality, task quality, and returned specialist evidence"});
  steps.push({id:`S${steps.length+1}`,kind:"ESCALATE_ONLY_IF_REQUIRED",action:"ASK_HUMAN_ONLY_FOR_BINDING_AUTHORITY",authority:"HUMAN_GATE",reversible:false,expectedEvidence:"Explicit financial/legal/contractual/connector/deploy gate"});
  return {
    contextKey:context.contextKey,cycle:context.cycle,targetMetric:context.targetMetric,replanReason,
    primaryObjective:context.goals[0]?.objective || `Advance ${context.bottleneck}`,
    selectedAction:action,requiredCapability:skillKey,competence:skill,
    steps:steps.slice(0,MAX_PLAN_STEPS),needsSwarm:multiAgentUseful,
    accelerateGrowthLoop:context.stallCycles>=3 || context.recoveryLevel>=2,
    authority:{autonomousSpendUsd:0,bindingActionsHumanGated:true,productionDeploy:false,newExternalConnectors:false,autonomousDebt:false,autonomousContract:false},
    policy:"plan continuously; execute reversible zero-spend work at earned competence; measure; learn; replan; never broaden binding authority automatically"
  };
}

async function persistPlan(env, context, plan) {
  const prev = await first(env,"SELECT plan_id,revision,context_key FROM lumen_v3_plans WHERE status='ACTIVE' ORDER BY updated_at DESC LIMIT 1");
  const revision = prev ? num(prev.revision)+1 : 1;
  if (prev) await env.DB.prepare("UPDATE lumen_v3_plans SET status='SUPERSEDED',updated_at=? WHERE plan_id=?").bind(now(),prev.plan_id).run();
  const id = `PLAN-${String(context.cycle).padStart(8,"0")}-${revision}`;
  await env.DB.prepare("INSERT INTO lumen_v3_plans(plan_id,created_at,updated_at,cycle,context_key,revision,status,replan_reason,target_metric,plan_json,engine_version) VALUES(?,?,?,?,?,?, 'ACTIVE',?,?,?,?)")
    .bind(id,now(),now(),context.cycle,context.contextKey,revision,plan.replanReason,context.targetMetric,JSON.stringify({...plan,planId:id,revision}),VERSION).run();
  return {...plan,planId:id,revision};
}

async function runSwarm(env, context, model, plan) {
  const teamSkill = competence(model,"multiagent_orchestration");
  const delegationSkill = competence(model,"delegation");
  const shouldBuild = plan.needsSwarm || context.teams.active === 0;
  const built = shouldBuild ? await isolated(()=>buildDynamicTeams(env),{ok:false,teamsBuilt:0}) : {ok:true,skipped:true,teamsBuilt:0};
  const polled = context.delegation.active > 0 ? await isolated(()=>pollDelegationTasks(env),{ok:false,polled:0}) : {ok:true,skipped:true,polled:0};
  const dispatchEligible = bool(env?.A2A_AUTONOMOUS_DELEGATION) && delegationSkill.level >= 3 && teamSkill.level >= 2 && context.delegation.approved > 0;
  const dispatch = dispatchEligible ? await isolated(()=>dispatchNextDelegationTask(env),{ok:false,sent:false}) : {ok:true,sent:false,reason:bool(env?.A2A_AUTONOMOUS_DELEGATION)?"competence_or_approved_task_gate":"autonomous_delegation_disabled"};
  const stats = await first(env,"SELECT COUNT(*) total,SUM(CASE WHEN status='PLANNED' THEN 1 ELSE 0 END) planned,SUM(CASE WHEN status='APPROVED_FOR_DISPATCH' THEN 1 ELSE 0 END) approved,SUM(CASE WHEN status IN ('DISPATCHED','DISPATCHED_ACK') THEN 1 ELSE 0 END) active,SUM(CASE WHEN status='RESULT_RECEIVED' THEN 1 ELSE 0 END) results,SUM(CASE WHEN status='FAILED' THEN 1 ELSE 0 END) failed FROM lumen_delegation_tasks");
  const teamStats = await first(env,"SELECT COUNT(*) total,SUM(CASE WHEN status='DRAFT_TEAM' THEN 1 ELSE 0 END) active FROM lumen_dynamic_teams");
  const state = {
    built,polled,dispatch,
    teamsBuilt:num(teamStats?.active),preparedTasks:num(stats?.planned)+num(stats?.approved),activeTasks:num(stats?.active),resultTasks:num(stats?.results),failedTasks:num(stats?.failed),
    dispatchEnabled:bool(env?.A2A_AUTONOMOUS_DELEGATION),dispatchEligible,
    competence:{delegation:delegationSkill,multiagentOrchestration:teamSkill},
    policy:"assemble specialist teams autonomously; dispatch only pre-quality-approved zero-spend non-binding tasks when explicit autonomous-delegation configuration and earned competence both allow it"
  };
  await env.DB.prepare("INSERT INTO lumen_v3_swarm_state(id,updated_at,teams_built,prepared_tasks,active_tasks,result_tasks,failed_tasks,dispatch_enabled,state_json,engine_version) VALUES('GLOBAL',?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,teams_built=excluded.teams_built,prepared_tasks=excluded.prepared_tasks,active_tasks=excluded.active_tasks,result_tasks=excluded.result_tasks,failed_tasks=excluded.failed_tasks,dispatch_enabled=excluded.dispatch_enabled,state_json=excluded.state_json,engine_version=excluded.engine_version")
    .bind(now(),state.teamsBuilt,state.preparedTasks,state.activeTasks,state.resultTasks,state.failedTasks,state.dispatchEnabled?1:0,JSON.stringify(state),VERSION).run();
  return state;
}

export async function runSuperautonomyV3Cycle(env,{trigger="scheduled"}={}) {
  if (!(await ensureSchema(env))) return {ok:false,error:"db_unavailable",version:VERSION};
  const context = await loadContext(env);
  const model = deriveSelfModel(context);
  await persistSelfModel(env,model);
  const experimentDraft = chooseStrategyExperiment(context);
  const experiment = await persistExperiment(env,context,experimentDraft);
  const previousPlan = await first(env,"SELECT plan_id,revision,context_key,plan_json FROM lumen_v3_plans WHERE status='ACTIVE' ORDER BY updated_at DESC LIMIT 1");
  const planDraft = buildAutonomousPlan(context,model,experimentDraft,previousPlan);
  const plan = await persistPlan(env,context,planDraft);
  const swarm = await runSwarm(env,context,model,plan);
  const state = {
    ok:true,version:VERSION,trigger,updatedAt:now(),cycle:context.cycle,contextKey:context.contextKey,
    fourEngines:{selfModel:true,autonomousPlanner:true,strategyLab:true,swarmOrchestrator:true},
    selfModel:model,plan,experiment,swarm,
    autonomy:{boundedRatio:context.autonomyRatio,earnedPerCompetence:true,zeroSpend:true,bindingActionsHumanGated:true},
    accelerateGrowthLoop:Boolean(plan.accelerateGrowthLoop),
    principle:"know what LUMEN can do, plan continuously, test strategies against evidence, delegate bounded work to the best available specialists, and earn more reversible autonomy through demonstrated competence"
  };
  await env.DB.prepare("INSERT INTO lumen_v3_state(id,updated_at,cycle,context_key,state_json,engine_version) VALUES('GLOBAL',?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,cycle=excluded.cycle,context_key=excluded.context_key,state_json=excluded.state_json,engine_version=excluded.engine_version")
    .bind(state.updatedAt,context.cycle,context.contextKey,JSON.stringify(state),VERSION).run();
  return state;
}

export async function superautonomyV3Status(env) {
  await ensureSchema(env);
  const [state,skills,plan,experiments,swarm] = await Promise.all([
    first(env,"SELECT updated_at,cycle,context_key,state_json,engine_version FROM lumen_v3_state WHERE id='GLOBAL' LIMIT 1"),
    all(env,"SELECT capability_key,updated_at,score,level,evidence_count,successes,failures,autonomy_mode,reason FROM lumen_v3_self_model ORDER BY level DESC,score DESC"),
    first(env,"SELECT plan_id,updated_at,cycle,context_key,revision,status,replan_reason,target_metric,plan_json FROM lumen_v3_plans WHERE status='ACTIVE' ORDER BY updated_at DESC LIMIT 1"),
    all(env,"SELECT experiment_id,updated_at,context_key,target_metric,champion_action,challenger_action,recommended_arm,baseline_value,latest_value,evidence_count,exploration_share,status,result FROM lumen_v3_strategy_experiments ORDER BY updated_at DESC LIMIT 12"),
    first(env,"SELECT updated_at,teams_built,prepared_tasks,active_tasks,result_tasks,failed_tasks,dispatch_enabled,state_json FROM lumen_v3_swarm_state WHERE id='GLOBAL' LIMIT 1")
  ]);
  return {ok:true,version:VERSION,state:state?parse(state.state_json,{}):null,selfModel:skills,activePlan:plan?{...plan,plan:parse(plan.plan_json,{})}:null,experiments,swarm:swarm?{...swarm,state:parse(swarm.state_json,{})}:null};
}

export async function handleSuperautonomyV3(request,env) {
  const url = new URL(request.url);
  if (request.method === "OPTIONS" && ["/superautonomy-v3","/self-model","/autonomous-planner","/strategy-lab","/lumen-swarm"].some(p=>url.pathname.startsWith(p))) return new Response(null,{status:204,headers:{"access-control-allow-origin":"*","access-control-allow-headers":"content-type,x-lumen-admin","access-control-allow-methods":"GET,POST,OPTIONS"}});
  if (request.method === "GET" && url.pathname === "/superautonomy-v3/policy") return json({ok:true,version:VERSION,engines:["Self-Model + Autonomía por Competencia","Motor de Planificación, Priorización y Replanificación Autónoma","Laboratorio Autónomo de Experimentos + Evolución de Estrategias","LUMEN Swarm: Delegación Multiagente + Auto-Orquestación de Capacidades"],earnedAutonomy:true,selfModifyingCode:false,autonomousSpendUsd:0,bindingActionsHumanGated:true,productionDeploy:false,newExternalConnectors:false});
  if (request.method === "GET" && url.pathname === "/superautonomy-v3/status") { if(!authorized(request,env)) return json({ok:false,error:"unauthorized"},401); return json(await superautonomyV3Status(env)); }
  if (request.method === "GET" && url.pathname === "/self-model/status") { if(!authorized(request,env)) return json({ok:false,error:"unauthorized"},401); await ensureSchema(env); return json({ok:true,version:VERSION,capabilities:await all(env,"SELECT capability_key,updated_at,score,level,evidence_count,successes,failures,autonomy_mode,reason FROM lumen_v3_self_model ORDER BY level DESC,score DESC")}); }
  if (request.method === "GET" && url.pathname === "/autonomous-planner/status") { if(!authorized(request,env)) return json({ok:false,error:"unauthorized"},401); await ensureSchema(env); const p=await first(env,"SELECT * FROM lumen_v3_plans WHERE status='ACTIVE' ORDER BY updated_at DESC LIMIT 1"); return json({ok:true,version:VERSION,activePlan:p?{...p,plan:parse(p.plan_json,{})}:null}); }
  if (request.method === "GET" && url.pathname === "/strategy-lab/status") { if(!authorized(request,env)) return json({ok:false,error:"unauthorized"},401); await ensureSchema(env); return json({ok:true,version:VERSION,experiments:await all(env,"SELECT experiment_id,updated_at,context_key,target_metric,champion_action,challenger_action,recommended_arm,baseline_value,latest_value,evidence_count,exploration_share,status,result FROM lumen_v3_strategy_experiments ORDER BY updated_at DESC LIMIT 30")}); }
  if (request.method === "GET" && url.pathname === "/lumen-swarm/status") { if(!authorized(request,env)) return json({ok:false,error:"unauthorized"},401); await ensureSchema(env); const s=await first(env,"SELECT * FROM lumen_v3_swarm_state WHERE id='GLOBAL' LIMIT 1"); return json({ok:true,version:VERSION,swarm:s?{...s,state:parse(s.state_json,{})}:null}); }
  if (request.method === "POST" && url.pathname === "/superautonomy-v3/run") { if(!authorized(request,env)) return json({ok:false,error:"unauthorized"},401); return json(await runSuperautonomyV3Cycle(env,{trigger:"admin_run"}),202); }
  return null;
}

export { VERSION as SUPER_AUTONOMY_V3_VERSION, capabilityLevel, autonomyMode, requiredCapability };
