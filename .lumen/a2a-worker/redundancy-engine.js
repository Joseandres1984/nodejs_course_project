const VERSION="1.0-redundancy-engine";
function json(d,s=200){return Response.json(d,{status:s,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function clean(v,n=8000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}
function authorized(r,e){const a=clean(e?.OPPORTUNITY_ADMIN_TOKEN,500),b=clean(r.headers.get("x-lumen-admin"),500);return Boolean(a&&b&&a===b);}
function parse(v,f=[]){try{const x=JSON.parse(v||"");return x??f;}catch{return f;}}
function clamp(n,min=0,max=100){return Math.max(min,Math.min(max,Number(n)||0));}
function pairKey(a,b){return a<b?`${a}|${b}`:`${b}|${a}`;}
async function safeAll(env,sql,bind=[]){try{const q=env.DB.prepare(sql),r=bind.length?await q.bind(...bind).all():await q.all();return r.results||[];}catch{return[];}}

async function ensure(env){if(!env?.DB)return false;await env.DB.batch([
 env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_dynamic_team_redundancy (id TEXT PRIMARY KEY,team_id TEXT NOT NULL,opportunity_id TEXT NOT NULL,role TEXT NOT NULL,primary_partner_id TEXT NOT NULL,primary_partner_name TEXT NOT NULL,alternate_rank INTEGER NOT NULL,alternate_partner_id TEXT NOT NULL,alternate_partner_name TEXT NOT NULL,alternate_quality INTEGER NOT NULL,team_affinity INTEGER NOT NULL,status TEXT NOT NULL,reason TEXT NOT NULL,updated_at TEXT NOT NULL,engine_version TEXT NOT NULL,UNIQUE(team_id,role,alternate_rank))"),
 env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_redundancy_ready ON lumen_dynamic_team_redundancy(team_id,status,role,alternate_rank)"),
 env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_replacement_plans (id TEXT PRIMARY KEY,source_type TEXT NOT NULL,source_id TEXT NOT NULL,role TEXT NOT NULL,failed_partner_id TEXT NOT NULL,failed_partner_name TEXT,replacement_partner_id TEXT NOT NULL,replacement_partner_name TEXT NOT NULL,reason TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,external_message_sent INTEGER NOT NULL DEFAULT 0,spend_allowed INTEGER NOT NULL DEFAULT 0,binding_allowed INTEGER NOT NULL DEFAULT 0,engine_version TEXT NOT NULL,UNIQUE(source_type,source_id,failed_partner_id))"),
 env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_replacement_plans_status ON lumen_replacement_plans(status,updated_at)")
]);return true;}

async function context(env){
 const bad=new Set(),fail=new Map(),graph=new Map();
 for(const x of await safeAll(env,"SELECT partner_id,status FROM lumen_partner_runtime_observations ORDER BY observed_at DESC LIMIT 500"))if(['unsupported','failed','incompatible','partial_discovery_only'].includes(String(x.status||'').toLowerCase()))bad.add(x.partner_id);
 for(const x of await safeAll(env,"SELECT partner_id,room_status FROM lumen_council_room_members WHERE partner_id IS NOT NULL"))if(['FAILED','REPLACED','LOW_QUALITY_REPLACED'].includes(String(x.room_status||'')))fail.set(x.partner_id,(fail.get(x.partner_id)||0)+1);
 for(const x of await safeAll(env,"SELECT source_partner_id,target_partner_id,affinity_score,contexts,successes,failures FROM lumen_agent_graph_edges")){
  const k=pairKey(x.source_partner_id,x.target_partner_id),c=graph.get(k)||{w:0,v:0,contexts:0,successes:0,failures:0},w=Math.max(1,Number(x.contexts||1));c.w+=w;c.v+=Number(x.affinity_score||50)*w;c.contexts+=Number(x.contexts||0);c.successes+=Number(x.successes||0);c.failures+=Number(x.failures||0);graph.set(k,c);
 }
 return{bad,fail,graph};
}
function affinity(ctx,a,b){const x=ctx.graph.get(pairKey(a,b));return x?Math.round(clamp(x.v/Math.max(1,x.w))):50;}

async function alternates(env,ctx,opportunityId,role,exclude,remaining){
 const needle=`%\"${clean(role,80).toLowerCase()}\"%`;
 const rows=await safeAll(env,"SELECT p.id,p.name,p.endpoint,p.reputation_score,p.compatibility_score,o.score observed_score,o.confidence observed_confidence,m.match_score FROM lumen_partner_agents p LEFT JOIN lumen_partner_observed_reputation o ON o.partner_id=p.id LEFT JOIN lumen_partner_matches m ON m.partner_id=p.id AND m.opportunity_id=? WHERE LOWER(p.capabilities_json) LIKE ? AND p.status IN ('candidate','strong_candidate') ORDER BY COALESCE(m.match_score,0) DESC,p.reputation_score DESC,p.compatibility_score DESC LIMIT 35",[opportunityId,needle]);
 const out=[];
 for(const p of rows){if(exclude.has(p.id)||ctx.bad.has(p.id)||!clean(p.endpoint,1000).startsWith('https://'))continue;
  const conf=Number(p.observed_confidence||0),obs=Number(p.observed_score||0),decl=Number(p.reputation_score||0),rep=conf>=30?decl*.65+obs*.35:decl,match=Number(p.match_score||0)||decl*.5+Number(p.compatibility_score||0)*.35+15,pen=Math.min(30,(ctx.fail.get(p.id)||0)*10);
  const teamAff=remaining.length?Math.round(remaining.reduce((n,x)=>n+affinity(ctx,p.id,x.partnerId),0)/remaining.length):50;
  const quality=Math.round(clamp(match*.42+rep*.23+Number(p.compatibility_score||0)*.2+(conf>=30?obs:50)*.1+teamAff*.05-pen));
  out.push({partnerId:p.id,name:p.name,quality,teamAffinity:teamAff,observedConfidence:conf,reason:teamAff<40?"risky_pair_history":conf>=30?"observed_confident_alternate":"declared_fit_pending_observed_confidence"});
 }
 out.sort((a,b)=>b.quality-a.quality||b.teamAffinity-a.teamAffinity);return out.slice(0,2);
}

async function buildBenches(env,ctx){
 const teams=await safeAll(env,"SELECT * FROM lumen_dynamic_teams WHERE status='DRAFT_TEAM' ORDER BY team_score DESC LIMIT 30"),built=[];
 for(const team of teams){const members=parse(team.members_json,[]);if(!Array.isArray(members))continue;await env.DB.prepare("DELETE FROM lumen_dynamic_team_redundancy WHERE team_id=?").bind(team.id).run();
  const exclude=new Set(members.map(x=>x.partnerId));
  for(const primary of members){const remaining=members.filter(x=>x.partnerId!==primary.partnerId),alts=await alternates(env,ctx,team.opportunity_id,primary.role,exclude,remaining);let rank=0;
   for(const alt of alts){rank++;const status=alt.quality>=70&&alt.teamAffinity>=40?"READY":"WEAK",id=`BENCH-${team.id}-${primary.role}-${rank}`.slice(0,240),now=new Date().toISOString();
    await env.DB.prepare("INSERT INTO lumen_dynamic_team_redundancy(id,team_id,opportunity_id,role,primary_partner_id,primary_partner_name,alternate_rank,alternate_partner_id,alternate_partner_name,alternate_quality,team_affinity,status,reason,updated_at,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)").bind(id,team.id,team.opportunity_id,primary.role,primary.partnerId,primary.name,rank,alt.partnerId,alt.name,alt.quality,alt.teamAffinity,status,alt.reason,now,VERSION).run();
    built.push({teamId:team.id,role:primary.role,primary:primary.name,rank,alternate:alt.name,quality:alt.quality,teamAffinity:alt.teamAffinity,status});
   }
  }
 }
 return built;
}

async function prepareTeamReplacements(env,ctx){
 const teams=await safeAll(env,"SELECT * FROM lumen_dynamic_teams WHERE status='DRAFT_TEAM' ORDER BY updated_at DESC LIMIT 30"),plans=[];
 for(const team of teams){let members=parse(team.members_json,[]);if(!Array.isArray(members))continue;let changed=false;
  for(let i=0;i<members.length;i++){const m=members[i];if(!ctx.bad.has(m.partnerId))continue;
   const alt=(await safeAll(env,"SELECT * FROM lumen_dynamic_team_redundancy WHERE team_id=? AND role=? AND status='READY' ORDER BY alternate_rank ASC LIMIT 1",[team.id,m.role]))[0];if(!alt)continue;
   const pid=`RPLAN-TEAM-${team.id}-${m.partnerId}`.slice(0,240),now=new Date().toISOString();
   await env.DB.prepare("INSERT OR IGNORE INTO lumen_replacement_plans(id,source_type,source_id,role,failed_partner_id,failed_partner_name,replacement_partner_id,replacement_partner_name,reason,status,created_at,updated_at,external_message_sent,spend_allowed,binding_allowed,engine_version) VALUES(?,?,?,?,?,?,?,?,?,'PREPARED',?,?,0,0,0,?)").bind(pid,"DYNAMIC_TEAM",team.id,m.role,m.partnerId,m.name,alt.alternate_partner_id,alt.alternate_partner_name,"runtime_failure_after_team_selection",now,now,VERSION).run();
   members[i]={...m,partnerId:alt.alternate_partner_id,name:alt.alternate_partner_name,replacedPrimary:{partnerId:m.partnerId,name:m.name},replacementPlanId:pid};changed=true;plans.push({sourceType:"DYNAMIC_TEAM",sourceId:team.id,role:m.role,failed:m.name,replacement:alt.alternate_partner_name,status:"PREPARED_AND_APPLIED_INTERNAL"});
  }
  if(changed)await env.DB.prepare("UPDATE lumen_dynamic_teams SET members_json=?,updated_at=? WHERE id=?").bind(JSON.stringify(members),new Date().toISOString(),team.id).run();
 }
 return plans;
}

async function prepareDelegationFallbacks(env,ctx){
 const tasks=await safeAll(env,"SELECT * FROM lumen_delegation_tasks WHERE status IN ('FAILED','RESULT_REJECTED') ORDER BY updated_at ASC LIMIT 30"),plans=[];
 for(const t of tasks){const exclude=new Set([t.partner_id]),alts=await alternates(env,ctx,t.opportunity_id,t.role,exclude,[]),alt=alts.find(x=>x.quality>=70);if(!alt)continue;
  const id=`RPLAN-TASK-${t.id}-${t.partner_id}`.slice(0,240),now=new Date().toISOString();await env.DB.prepare("INSERT OR IGNORE INTO lumen_replacement_plans(id,source_type,source_id,role,failed_partner_id,failed_partner_name,replacement_partner_id,replacement_partner_name,reason,status,created_at,updated_at,external_message_sent,spend_allowed,binding_allowed,engine_version) VALUES(?,?,?,?,?,?,?,?,?,'PREPARED',?,?,0,0,0,?)").bind(id,"DELEGATION_TASK",t.id,t.role,t.partner_id,t.partner_name,alt.partnerId,alt.name,`task_status=${t.status};replacement_not_dispatched`,now,now,VERSION).run();
  plans.push({sourceType:"DELEGATION_TASK",sourceId:t.id,role:t.role,failed:t.partner_name,replacement:alt.name,status:"PREPARED_NOT_DISPATCHED"});
 }
 return plans;
}

export async function recomputeRedundancy(env){if(!(await ensure(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};const ctx=await context(env),bench=await buildBenches(env,ctx),teamPlans=await prepareTeamReplacements(env,ctx),taskPlans=await prepareDelegationFallbacks(env,ctx);return{ok:true,version:VERSION,benchEntries:bench.length,readyAlternates:bench.filter(x=>x.status==='READY').length,weakAlternates:bench.filter(x=>x.status==='WEAK').length,teamReplacementPlans:teamPlans,delegationReplacementPlans:taskPlans,guardrails:{automaticInternalTeamReplacement:true,automaticExternalRedispatch:false,autonomousSpend:false,bindingAllowed:false,maxAlternatesPerRole:2}};}
async function stats(env){await ensure(env);const b=await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN status='READY' THEN 1 ELSE 0 END) ready,SUM(CASE WHEN status='WEAK' THEN 1 ELSE 0 END) weak FROM lumen_dynamic_team_redundancy").first(),p=await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN status='PREPARED' THEN 1 ELSE 0 END) prepared,SUM(CASE WHEN external_message_sent=1 THEN 1 ELSE 0 END) sent FROM lumen_replacement_plans").first();return json({version:VERSION,benchEntries:Number(b?.total||0),readyAlternates:Number(b?.ready||0),weakAlternates:Number(b?.weak||0),replacementPlans:Number(p?.total||0),preparedPlans:Number(p?.prepared||0),externalRedispatches:Number(p?.sent||0),automaticExternalRedispatch:false,autonomousSpend:false,bindingActionsHumanGated:true});}
export async function handleRedundancyEngine(request,env){const u=new URL(request.url);if(request.method==='GET'&&u.pathname==='/redundancy/stats')return stats(env);if(request.method==='POST'&&u.pathname==='/redundancy/recompute'){if(!authorized(request,env))return json({ok:false,error:'admin_token_required'},403);return json(await recomputeRedundancy(env),202);}if(request.method==='GET'&&u.pathname==='/redundancy/bench'){if(!authorized(request,env))return json({ok:false,error:'admin_token_required'},403);await ensure(env);const r=await env.DB.prepare("SELECT * FROM lumen_dynamic_team_redundancy ORDER BY team_id,role,alternate_rank").all();return json({version:VERSION,bench:r.results||[]});}if(request.method==='GET'&&u.pathname==='/redundancy/plans'){if(!authorized(request,env))return json({ok:false,error:'admin_token_required'},403);await ensure(env);const r=await env.DB.prepare("SELECT * FROM lumen_replacement_plans ORDER BY updated_at DESC LIMIT 100").all();return json({version:VERSION,plans:r.results||[]});}return null;}
