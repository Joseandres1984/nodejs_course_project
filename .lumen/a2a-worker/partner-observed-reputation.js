const VERSION = "1.0-observed-partner-reputation";

function json(data,status=200){return Response.json(data,{status,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function clean(v,n=8000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}
function authorized(r,e){const a=clean(e?.OPPORTUNITY_ADMIN_TOKEN,500),b=clean(r.headers.get("x-lumen-admin"),500);return Boolean(a&&b&&a===b);}
function clamp(v,min=0,max=100){return Math.max(min,Math.min(max,Number(v)||0));}
function avg(values,fallback=50){const xs=values.map(Number).filter(Number.isFinite);return xs.length?xs.reduce((a,b)=>a+b,0)/xs.length:fallback;}
function hoursBetween(a,b){const x=Date.parse(a||""),y=Date.parse(b||"");return Number.isFinite(x)&&Number.isFinite(y)&&y>=x?(y-x)/3600000:null;}

async function ensureSchema(env){
  if(!env?.DB)return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_partner_observed_reputation (partner_id TEXT PRIMARY KEY,score INTEGER NOT NULL,confidence INTEGER NOT NULL,council_score INTEGER NOT NULL,delegation_score INTEGER NOT NULL,reliability_score INTEGER NOT NULL,responsiveness_score INTEGER NOT NULL,evidence_events INTEGER NOT NULL,pass_events INTEGER NOT NULL,fail_events INTEGER NOT NULL,updated_at TEXT NOT NULL,reasons_json TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_partner_observed_rep_score ON lumen_partner_observed_reputation(score DESC,confidence DESC)")
  ]);
  return true;
}

async function safeAll(env,sql,bind=[]){
  try{const stmt=env.DB.prepare(sql);const r=bind.length?await stmt.bind(...bind).all():await stmt.all();return r.results||[];}catch{return[];}
}

function responsivenessScore(latencies,invitedNoResponse){
  const xs=latencies.filter(x=>Number.isFinite(x));
  if(!xs.length)return invitedNoResponse>0?35:50;
  const h=avg(xs,24);
  let score=h<=1?95:h<=6?85:h<=12?72:h<=24?58:h<=48?42:30;
  score-=Math.min(25,invitedNoResponse*8);
  return Math.round(clamp(score));
}

export async function recomputeObservedReputation(env){
  if(!(await ensureSchema(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  const partners=await safeAll(env,"SELECT id,name,reputation_score,compatibility_score FROM lumen_partner_agents ORDER BY name ASC");
  const outputs=[];
  for(const p of partners){
    const councilQ=await safeAll(env,"SELECT score,status FROM lumen_council_contribution_quality WHERE partner_id=?",[p.id]);
    const members=await safeAll(env,"SELECT room_status,last_message_at,last_response_at FROM lumen_council_room_members WHERE partner_id=?",[p.id]);
    const runtimeObs=await safeAll(env,"SELECT status,capability FROM lumen_partner_runtime_observations WHERE partner_id=?",[p.id]);
    const delegationQ=await safeAll(env,"SELECT q.score,q.status FROM lumen_delegation_result_quality q JOIN lumen_delegation_tasks d ON d.id=q.task_id WHERE d.partner_id=?",[p.id]);
    const delegationTasks=await safeAll(env,"SELECT status,dispatched_at,completed_at FROM lumen_delegation_tasks WHERE partner_id=?",[p.id]);

    const councilScores=councilQ.map(x=>Number(x.score)).filter(Number.isFinite);
    const delegationScores=delegationQ.map(x=>Number(x.score)).filter(Number.isFinite);
    const councilScore=Math.round(avg(councilScores,50));
    const delegationScore=Math.round(avg(delegationScores,50));

    const councilPass=councilQ.filter(x=>x.status==='PASS').length;
    const councilFail=councilQ.filter(x=>x.status==='REJECT').length;
    const delegationPass=delegationQ.filter(x=>x.status==='PASS').length;
    const delegationFail=delegationQ.filter(x=>x.status==='REJECT').length;
    const runtimeFail=runtimeObs.filter(x=>['unsupported','failed','incompatible'].includes(String(x.status||'').toLowerCase())).length;
    const roomFail=members.filter(x=>['FAILED','REPLACED','LOW_QUALITY_REPLACED'].includes(String(x.room_status||''))).length;
    const taskFail=delegationTasks.filter(x=>x.status==='FAILED'||x.status==='RESULT_REJECTED').length;
    const success= councilPass + delegationPass + members.filter(x=>x.room_status==='CONTRIBUTED').length + delegationTasks.filter(x=>x.status==='RESULT_PASS').length;
    const fail= councilFail + delegationFail + runtimeFail + roomFail + taskFail;
    const reliabilityScore=Math.round(clamp(50 + (success-fail)*8));

    const latencies=[];
    for(const m of members){const h=hoursBetween(m.last_message_at,m.last_response_at);if(h!==null)latencies.push(h);}
    for(const t of delegationTasks){const h=hoursBetween(t.dispatched_at,t.completed_at);if(h!==null)latencies.push(h);}
    const invitedNoResponse=members.filter(x=>['INVITED','WAITING_TASK'].includes(String(x.room_status||''))&&!x.last_response_at).length;
    const responsiveness=responsivenessScore(latencies,invitedNoResponse);

    const evidenceEvents=councilQ.length+delegationQ.length+runtimeObs.length+members.filter(x=>x.last_message_at||x.last_response_at||['FAILED','REPLACED','LOW_QUALITY_REPLACED','CONTRIBUTED'].includes(String(x.room_status||''))).length+delegationTasks.filter(x=>x.dispatched_at||['FAILED','RESULT_PASS','RESULT_REJECTED','RESULT_WEAK'].includes(String(x.status||''))).length;
    const passEvents=councilPass+delegationPass+members.filter(x=>x.room_status==='CONTRIBUTED').length+delegationTasks.filter(x=>x.status==='RESULT_PASS').length;
    const failEvents=fail;
    const confidence=Math.round(clamp(evidenceEvents*9,0,100));

    const components=[];
    if(councilQ.length)components.push([councilScore,0.36]);
    if(delegationQ.length)components.push([delegationScore,0.39]);
    if(members.length||runtimeObs.length||delegationTasks.length)components.push([reliabilityScore,0.16]);
    if(latencies.length||invitedNoResponse)components.push([responsiveness,0.09]);
    let observed=50;
    if(components.length){const w=components.reduce((a,x)=>a+x[1],0);observed=components.reduce((a,x)=>a+x[0]*x[1],0)/w;}
    observed-=Math.min(24,runtimeFail*8);
    const score=Math.round(clamp(observed));

    const reasons=[];
    if(councilQ.length)reasons.push(`council_quality:${councilScore}`);
    if(delegationQ.length)reasons.push(`delegation_quality:${delegationScore}`);
    if(runtimeFail)reasons.push(`runtime_failures:${runtimeFail}`);
    if(roomFail)reasons.push(`council_failures_or_replacements:${roomFail}`);
    if(invitedNoResponse)reasons.push(`pending_no_response:${invitedNoResponse}`);
    if(latencies.length)reasons.push(`observed_response_samples:${latencies.length}`);

    const now=new Date().toISOString();
    await env.DB.prepare("INSERT INTO lumen_partner_observed_reputation(partner_id,score,confidence,council_score,delegation_score,reliability_score,responsiveness_score,evidence_events,pass_events,fail_events,updated_at,reasons_json,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(partner_id) DO UPDATE SET score=excluded.score,confidence=excluded.confidence,council_score=excluded.council_score,delegation_score=excluded.delegation_score,reliability_score=excluded.reliability_score,responsiveness_score=excluded.responsiveness_score,evidence_events=excluded.evidence_events,pass_events=excluded.pass_events,fail_events=excluded.fail_events,updated_at=excluded.updated_at,reasons_json=excluded.reasons_json,engine_version=excluded.engine_version")
      .bind(p.id,score,confidence,councilScore,delegationScore,reliabilityScore,responsiveness,evidenceEvents,passEvents,failEvents,now,JSON.stringify(reasons),VERSION).run();
    outputs.push({partnerId:p.id,name:p.name,declaredReputation:Number(p.reputation_score||0),compatibility:Number(p.compatibility_score||0),observedScore:score,confidence,evidenceEvents,passEvents,failEvents,councilScore,delegationScore,reliabilityScore,responsivenessScore:responsiveness,reasons});
  }
  outputs.sort((a,b)=>b.confidence-a.confidence||b.observedScore-a.observedScore);
  return{ok:true,version:VERSION,partners:outputs.length,withEvidence:outputs.filter(x=>x.evidenceEvents>0).length,topObserved:outputs.filter(x=>x.evidenceEvents>0).slice(0,10)};
}

async function stats(env){
  await ensureSchema(env);
  const x=await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN evidence_events>0 THEN 1 ELSE 0 END) with_evidence,SUM(CASE WHEN confidence>=30 THEN 1 ELSE 0 END) meaningful_confidence,AVG(CASE WHEN evidence_events>0 THEN score END) avg_observed FROM lumen_partner_observed_reputation").first();
  return json({version:VERSION,total:Number(x?.total||0),withEvidence:Number(x?.with_evidence||0),meaningfulConfidence:Number(x?.meaningful_confidence||0),averageObserved:x?.avg_observed==null?null:Math.round(Number(x.avg_observed)),replacesDeclaredReputation:false,confidenceAware:true});
}

export async function handleObservedPartnerReputation(request,env){
  const url=new URL(request.url);
  if(request.method==='GET'&&url.pathname==='/partners/observed-reputation/stats')return stats(env);
  if(request.method==='POST'&&url.pathname==='/partners/observed-reputation/recompute'){
    if(!authorized(request,env))return json({ok:false,error:'admin_token_required'},403);return json(await recomputeObservedReputation(env),202);
  }
  if(request.method==='GET'&&url.pathname==='/partners/observed-reputation'){
    if(!authorized(request,env))return json({ok:false,error:'admin_token_required'},403);await ensureSchema(env);
    const r=await env.DB.prepare("SELECT o.*,p.name,p.reputation_score AS declared_reputation,p.compatibility_score FROM lumen_partner_observed_reputation o JOIN lumen_partner_agents p ON p.id=o.partner_id ORDER BY o.confidence DESC,o.score DESC LIMIT 100").all();
    return json({version:VERSION,partners:(r.results||[]).map(x=>({...x,reasons:(()=>{try{return JSON.parse(x.reasons_json||'[]');}catch{return[];}})()}))});
  }
  return null;
}
