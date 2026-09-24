const VERSION = "1.0-dynamic-team-engine";

const OFFER_NEEDS={
  "MP-SUPPLIER-SNAPSHOT":["verification","sourcing","research"],
  "MP-QUOTE-SANITY":["pricing","research","verification"],
  "MP-TENDER-SCAN":["tender","research"],
  "MP-SOURCING-5":["sourcing","verification","pricing"],
  "MP-BUYER-SIGNALS":["sales","research"],
  "MP-EXPORT-PULSE":["export","logistics","research"]
};

function json(data,status=200){return Response.json(data,{status,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function clean(v,n=8000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}
function authorized(r,e){const a=clean(e?.OPPORTUNITY_ADMIN_TOKEN,500),b=clean(r.headers.get("x-lumen-admin"),500);return Boolean(a&&b&&a===b);}
function parseArray(v){try{const x=JSON.parse(v||"[]");return Array.isArray(x)?x:[];}catch{return[];}}
function clamp(n,min=0,max=100){return Math.max(min,Math.min(max,Number(n)||0));}

async function ensureSchema(env){
  if(!env?.DB)return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_dynamic_teams (id TEXT PRIMARY KEY,opportunity_id TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,status TEXT NOT NULL,team_score INTEGER NOT NULL,coverage_score INTEGER NOT NULL,member_quality_score INTEGER NOT NULL,graph_affinity_score INTEGER NOT NULL,risk_penalty INTEGER NOT NULL,needs_json TEXT NOT NULL,members_json TEXT NOT NULL,rationale_json TEXT NOT NULL,binding_allowed INTEGER NOT NULL DEFAULT 0,spend_allowed INTEGER NOT NULL DEFAULT 0,external_invites_sent INTEGER NOT NULL DEFAULT 0,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_dynamic_teams_rank ON lumen_dynamic_teams(opportunity_id,status,team_score DESC,updated_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_dynamic_team_runs (id TEXT PRIMARY KEY,started_at TEXT NOT NULL,finished_at TEXT,status TEXT NOT NULL,opportunities_evaluated INTEGER NOT NULL DEFAULT 0,teams_built INTEGER NOT NULL DEFAULT 0,details TEXT)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_dynamic_team_runs ON lumen_dynamic_team_runs(started_at DESC)")
  ]);
  return true;
}

async function safeAll(env,sql,bind=[]){try{const s=env.DB.prepare(sql);const r=bind.length?await s.bind(...bind).all():await s.all();return r.results||[];}catch{return[];}}
async function safeFirst(env,sql,bind=[]){try{const s=env.DB.prepare(sql);return bind.length?await s.bind(...bind).first():await s.first();}catch{return null;}}

async function activeOpportunities(env,limit=8){
  return safeAll(env,"SELECT o.id,o.name,o.revenue_offer_id,a.commercial_score,a.evidence_strength FROM lumen_opportunities o JOIN lumen_opportunity_assessments a ON a.opportunity_id=o.id WHERE a.commercially_actionable=1 AND a.synthetic_or_test_only=0 ORDER BY a.commercial_score DESC,o.updated_at DESC LIMIT ?",[limit]);
}

function needsFor(opp){return OFFER_NEEDS[clean(opp?.revenue_offer_id,100)]||["research"];}

async function runtimeBlocked(env,partnerId){
  const rows=await safeAll(env,"SELECT status,capability FROM lumen_partner_runtime_observations WHERE partner_id=? ORDER BY observed_at DESC LIMIT 10",[partnerId]);
  const bad=rows.find(x=>['unsupported','failed','incompatible','partial_discovery_only'].includes(String(x.status||'').toLowerCase()));
  return bad?{blocked:true,reason:`runtime_${clean(bad.status,80).toLowerCase()}`,capability:clean(bad.capability,120)}:{blocked:false};
}

async function roomPenalty(env,partnerId){
  const rows=await safeAll(env,"SELECT room_status FROM lumen_council_room_members WHERE partner_id=? ORDER BY COALESCE(last_response_at,last_message_at) DESC LIMIT 6",[partnerId]);
  const bad=rows.filter(x=>['FAILED','REPLACED','LOW_QUALITY_REPLACED'].includes(String(x.room_status||''))).length;
  return Math.min(30,bad*10);
}

async function candidatesForRole(env,opp,role){
  const needle=`%\"${clean(role,80).toLowerCase()}\"%`;
  const rows=await safeAll(env,"SELECT p.id,p.name,p.endpoint,p.protocol_version,p.capabilities_json,p.reputation_score,p.compatibility_score,o.score AS observed_score,o.confidence AS observed_confidence,o.reliability_score,o.responsiveness_score,m.match_score FROM lumen_partner_agents p LEFT JOIN lumen_partner_observed_reputation o ON o.partner_id=p.id LEFT JOIN lumen_partner_matches m ON m.partner_id=p.id AND m.opportunity_id=? WHERE LOWER(p.capabilities_json) LIKE ? AND p.status IN ('candidate','strong_candidate') ORDER BY COALESCE(m.match_score,0) DESC,p.reputation_score DESC,p.compatibility_score DESC LIMIT 40",[opp.id,needle]);
  const out=[];
  for(const p of rows){
    if(!clean(p.endpoint,1000).startsWith('https://'))continue;
    const rt=await runtimeBlocked(env,p.id);if(rt.blocked)continue;
    const failurePenalty=await roomPenalty(env,p.id);
    const confidence=Number(p.observed_confidence||0);
    const observed=Number(p.observed_score||0);
    const declared=Number(p.reputation_score||0);
    const effectiveRep=confidence>=30?Math.round(declared*.65+observed*.35):declared;
    const match=Number(p.match_score||0)||Math.round(declared*.45+Number(p.compatibility_score||0)*.35+20);
    const quality=Math.round(clamp(match*.42+effectiveRep*.23+Number(p.compatibility_score||0)*.20+(confidence>=30?observed:50)*.15-failurePenalty));
    out.push({partnerId:p.id,name:p.name,role,endpoint:p.endpoint,protocolVersion:p.protocol_version,capabilities:parseArray(p.capabilities_json),matchScore:match,declaredReputation:declared,observedScore:confidence?observed:null,observedConfidence:confidence,compatibility:Number(p.compatibility_score||0),operationalPenalty:failurePenalty,memberQuality:quality});
  }
  out.sort((a,b)=>b.memberQuality-a.memberQuality||b.matchScore-a.matchScore);
  return out.slice(0,8);
}

async function pairAffinity(env,a,b){
  const s=a<b?a:b,t=a<b?b:a;
  const rows=await safeAll(env,"SELECT affinity_score,contexts,successes,failures,relation_type FROM lumen_agent_graph_edges WHERE source_partner_id=? AND target_partner_id=? ORDER BY contexts DESC,affinity_score DESC",[s,t]);
  if(!rows.length)return{score:50,evidence:false,contexts:0,successes:0,failures:0,reason:"no_pair_history_neutral"};
  const contexts=rows.reduce((n,x)=>n+Number(x.contexts||0),0);
  const successes=rows.reduce((n,x)=>n+Number(x.successes||0),0);
  const failures=rows.reduce((n,x)=>n+Number(x.failures||0),0);
  const weighted=rows.reduce((n,x)=>n+Number(x.affinity_score||50)*Math.max(1,Number(x.contexts||1)),0)/rows.reduce((n,x)=>n+Math.max(1,Number(x.contexts||1)),0);
  return{score:Math.round(clamp(weighted)),evidence:true,contexts,successes,failures,reason:failures>successes?"pair_history_risky":successes>failures?"pair_history_positive":"pair_history_mixed"};
}

function combinations(roleLists,idx=0,chosen=[],out=[]){
  if(idx>=roleLists.length){out.push([...chosen]);return out;}
  for(const c of roleLists[idx]){
    if(chosen.some(x=>x.partnerId===c.partnerId))continue;
    chosen.push(c);combinations(roleLists,idx+1,chosen,out);chosen.pop();
    if(out.length>=180)break;
  }
  return out;
}

async function scoreTeam(env,opp,needs,members){
  const covered=new Set(members.map(x=>x.role));
  const coverage=Math.round((covered.size/Math.max(1,needs.length))*100);
  const memberQuality=Math.round(members.reduce((n,x)=>n+x.memberQuality,0)/Math.max(1,members.length));
  const pairScores=[];let riskPenalty=0;const pairEvidence=[];
  for(let i=0;i<members.length;i++)for(let j=i+1;j<members.length;j++){
    const p=await pairAffinity(env,members[i].partnerId,members[j].partnerId);pairScores.push(p.score);pairEvidence.push({a:members[i].name,b:members[j].name,...p});
    if(p.evidence&&p.score<40)riskPenalty+=Math.min(18,40-p.score);
  }
  const graphAffinity=pairScores.length?Math.round(pairScores.reduce((a,b)=>a+b,0)/pairScores.length):50;
  const score=Math.round(clamp(coverage*.32+memberQuality*.48+graphAffinity*.20-riskPenalty));
  return{teamScore:score,coverageScore:coverage,memberQualityScore:memberQuality,graphAffinityScore:graphAffinity,riskPenalty,pairEvidence};
}

async function buildForOpportunity(env,opp){
  const needs=needsFor(opp).slice(0,3);
  const lists=[];
  for(const role of needs){const candidates=await candidatesForRole(env,opp,role);if(!candidates.length)return{opportunityId:opp.id,built:false,reason:`no_executable_candidate_for_${role}`,needs};lists.push(candidates);}
  const combos=combinations(lists);
  const scored=[];
  for(const members of combos){const s=await scoreTeam(env,opp,needs,members);scored.push({members,...s});}
  scored.sort((a,b)=>b.teamScore-a.teamScore||b.memberQualityScore-a.memberQualityScore||b.graphAffinityScore-a.graphAffinityScore);
  const best=scored[0];if(!best)return{opportunityId:opp.id,built:false,reason:"no_unique_team_combination",needs};
  const now=new Date().toISOString();
  await env.DB.prepare("UPDATE lumen_dynamic_teams SET status='SUPERSEDED',updated_at=? WHERE opportunity_id=? AND status='DRAFT_TEAM'").bind(now,opp.id).run();
  const id=`TEAM-${crypto.randomUUID().replaceAll('-','').slice(0,14).toUpperCase()}`;
  const rationale={commercialScore:Number(opp.commercial_score||0),evidenceStrength:opp.evidence_strength||null,pairEvidence:best.pairEvidence,selectionPolicy:"role_coverage_plus_member_quality_plus_observed_graph_affinity",runtimeFailedAgentsExcluded:true,observedReputationConfidenceGate:30};
  await env.DB.prepare("INSERT INTO lumen_dynamic_teams(id,opportunity_id,created_at,updated_at,status,team_score,coverage_score,member_quality_score,graph_affinity_score,risk_penalty,needs_json,members_json,rationale_json,binding_allowed,spend_allowed,external_invites_sent,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,0,0,0,?)")
    .bind(id,opp.id,now,now,"DRAFT_TEAM",best.teamScore,best.coverageScore,best.memberQualityScore,best.graphAffinityScore,best.riskPenalty,JSON.stringify(needs),JSON.stringify(best.members),JSON.stringify(rationale),VERSION).run();
  return{opportunityId:opp.id,opportunityName:opp.name,offerId:opp.revenue_offer_id,built:true,teamId:id,teamScore:best.teamScore,coverageScore:best.coverageScore,memberQualityScore:best.memberQualityScore,graphAffinityScore:best.graphAffinityScore,riskPenalty:best.riskPenalty,needs,members:best.members.map(x=>({partnerId:x.partnerId,name:x.name,role:x.role,memberQuality:x.memberQuality,observedConfidence:x.observedConfidence})),pairEvidence:best.pairEvidence};
}

export async function buildDynamicTeams(env){
  if(!(await ensureSchema(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  const runId=`DTR-${crypto.randomUUID().replaceAll('-','').slice(0,18).toUpperCase()}`;const started=new Date().toISOString();
  await env.DB.prepare("INSERT INTO lumen_dynamic_team_runs(id,started_at,status,details) VALUES(?,?,'RUNNING',NULL)").bind(runId,started).run();
  const opps=await activeOpportunities(env,8);const results=[];
  for(const opp of opps)results.push(await buildForOpportunity(env,opp));
  const built=results.filter(x=>x.built).length;const finished=new Date().toISOString();
  await env.DB.prepare("UPDATE lumen_dynamic_team_runs SET finished_at=?,status='SUCCESS',opportunities_evaluated=?,teams_built=?,details=? WHERE id=?").bind(finished,opps.length,built,JSON.stringify(results).slice(0,16000),runId).run();
  return{ok:true,version:VERSION,runId,opportunitiesEvaluated:opps.length,teamsBuilt:built,results,guardrails:{internalDraftOnly:true,externalInvitesSent:false,autonomousHiring:false,autonomousSpend:false,bindingAllowed:false}};
}

async function stats(env){
  await ensureSchema(env);const r=await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN status='DRAFT_TEAM' THEN 1 ELSE 0 END) active,COALESCE(MAX(CASE WHEN status='DRAFT_TEAM' THEN team_score ELSE 0 END),0) best_score,COALESCE(AVG(CASE WHEN status='DRAFT_TEAM' THEN graph_affinity_score END),0) avg_affinity FROM lumen_dynamic_teams").first();
  return json({version:VERSION,total:Number(r?.total||0),activeDraftTeams:Number(r?.active||0),bestTeamScore:Number(r?.best_score||0),averageGraphAffinity:Math.round(Number(r?.avg_affinity||0)),internalDraftOnly:true,externalInvitesSent:false,autonomousSpend:false,bindingActionsHumanGated:true});
}

export async function handleDynamicTeamEngine(request,env){
  const url=new URL(request.url);
  if(request.method==="GET"&&url.pathname==="/dynamic-teams/stats")return stats(env);
  if(request.method==="POST"&&url.pathname==="/dynamic-teams/build"){
    if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);return json(await buildDynamicTeams(env),202);
  }
  if(request.method==="GET"&&url.pathname==="/dynamic-teams"){
    if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);await ensureSchema(env);
    const r=await env.DB.prepare("SELECT * FROM lumen_dynamic_teams WHERE status='DRAFT_TEAM' ORDER BY team_score DESC,updated_at DESC LIMIT 50").all();
    return json({version:VERSION,teams:(r.results||[]).map(x=>({...x,needs:parseArray(x.needs_json),members:parseArray(x.members_json),rationale:(()=>{try{return JSON.parse(x.rationale_json||'{}');}catch{return{};}})()}))});
  }
  return null;
}
