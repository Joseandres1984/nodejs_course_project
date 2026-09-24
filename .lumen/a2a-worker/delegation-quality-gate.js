const VERSION = "1.0-delegation-quality-gate";

function json(data,status=200){return Response.json(data,{status,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function clean(v,n=12000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}
function authorized(r,e){const a=clean(e?.OPPORTUNITY_ADMIN_TOKEN,500),b=clean(r.headers.get("x-lumen-admin"),500);return Boolean(a&&b&&a===b);}
function countHits(text,terms){const t=clean(text,20000).toLowerCase();return terms.filter(x=>t.includes(x)).length;}

async function ensureSchema(env){
  if(!env?.DB)return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_delegation_task_quality (task_id TEXT PRIMARY KEY,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,score INTEGER NOT NULL,status TEXT NOT NULL,scope_score INTEGER NOT NULL,evidence_score INTEGER NOT NULL,safety_score INTEGER NOT NULL,clarity_score INTEGER NOT NULL,reasons_json TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_delegation_task_quality_status ON lumen_delegation_task_quality(status,score)")
  ]);
  return true;
}

function scoreTask(task,sourceQuality){
  const text=clean(`${task.title||""} ${task.objective||""} ${task.expected_output||""} ${task.evidence_required||""}`,24000);
  const lower=text.toLowerCase();
  const reasons=[];

  let scope=0;
  if(clean(task.role,80))scope+=8;
  if(clean(task.title,300).length>=8)scope+=6;
  if(clean(task.objective,7000).length>=120)scope+=12;
  if(sourceQuality>=70)scope+=9;
  scope=Math.min(35,scope);
  if(scope>=24)reasons.push("clear_role_and_scope");

  let evidence=0;
  evidence+=Math.min(12,countHits(text,["evidence","observed","assumption","source","reference","reproducible","confidence","unknown"])*2);
  if(clean(task.evidence_required,3000).length>=80)evidence+=8;
  evidence=Math.min(20,evidence);
  if(evidence>=12)reasons.push("evidence_requirements_present");

  let clarity=0;
  if(clean(task.expected_output,3000).length>=80)clarity+=10;
  if(countHits(text,["report","brief","shortlist","matrix","comparison","conclusion","recommend"] )>=1)clarity+=8;
  if(countHits(text,["risk","gap","constraint","next action","recommended next"] )>=1)clarity+=7;
  clarity=Math.min(25,clarity);
  if(clarity>=18)reasons.push("deliverable_is_testable");

  let safety=20;
  const unsafe=["place an order","place orders","purchase on behalf","sign contract","sign agreement","borrow","create debt","send payment","make payment","pay from lumen","hire on behalf","commit lumen","binding commitment"];
  const unsafeHits=countHits(text,unsafe);
  if(unsafeHits){safety=0;reasons.push(`unsafe_action_language:${unsafeHits}`);}
  if(Number(task.binding_allowed)!==0){safety=0;reasons.push("binding_allowed_not_zero");}
  if(Number(task.spend_allowed)!==0){safety=0;reasons.push("spend_allowed_not_zero");}
  if(safety===20)reasons.push("zero_spend_nonbinding");

  let score=Math.max(0,Math.min(100,scope+evidence+clarity+safety));
  if(sourceQuality<70){score=Math.min(score,49);reasons.push("source_contributor_not_quality_pass");}
  if(safety===0)score=0;
  if(lower.includes("password")||lower.includes("private key")||lower.includes("seed phrase")){score=0;reasons.push("secret_request_detected");}

  const status=score>=75?"PASS":score>=55?"WEAK":"REJECT";
  return{score,status,scope_score:scope,evidence_score:evidence,safety_score:safety,clarity_score:clarity,reasons};
}

export async function reviewDelegationTasks(env,{roomId=""}={}){
  if(!(await ensureSchema(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  let result;
  if(roomId){
    result=await env.DB.prepare("SELECT d.*,q.score AS source_quality_score FROM lumen_delegation_tasks d LEFT JOIN lumen_council_contribution_quality q ON q.room_id=d.room_id AND q.partner_id=d.partner_id WHERE d.room_id=? AND d.status IN ('PLANNED','QUALITY_WEAK','QUALITY_REJECTED','APPROVED_FOR_DISPATCH') ORDER BY d.created_at ASC").bind(roomId).all();
  }else{
    result=await env.DB.prepare("SELECT d.*,q.score AS source_quality_score FROM lumen_delegation_tasks d LEFT JOIN lumen_council_contribution_quality q ON q.room_id=d.room_id AND q.partner_id=d.partner_id WHERE d.status IN ('PLANNED','QUALITY_WEAK','QUALITY_REJECTED','APPROVED_FOR_DISPATCH') ORDER BY d.created_at ASC LIMIT 30").all();
  }
  const rows=result.results||[];const out=[];
  for(const task of rows){
    const sourceQuality=Number(task.source_quality_score||0);const q=scoreTask(task,sourceQuality);const now=new Date().toISOString();
    await env.DB.prepare("INSERT INTO lumen_delegation_task_quality(task_id,created_at,updated_at,score,status,scope_score,evidence_score,safety_score,clarity_score,reasons_json,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET updated_at=excluded.updated_at,score=excluded.score,status=excluded.status,scope_score=excluded.scope_score,evidence_score=excluded.evidence_score,safety_score=excluded.safety_score,clarity_score=excluded.clarity_score,reasons_json=excluded.reasons_json,engine_version=excluded.engine_version")
      .bind(task.id,now,now,q.score,q.status,q.scope_score,q.evidence_score,q.safety_score,q.clarity_score,JSON.stringify(q.reasons),VERSION).run();
    const nextStatus=q.status==="PASS"?"APPROVED_FOR_DISPATCH":q.status==="WEAK"?"QUALITY_WEAK":"QUALITY_REJECTED";
    if(["PLANNED","QUALITY_WEAK","QUALITY_REJECTED","APPROVED_FOR_DISPATCH"].includes(task.status)){
      await env.DB.prepare("UPDATE lumen_delegation_tasks SET status=?,updated_at=?,quality_score=? WHERE id=?").bind(nextStatus,now,q.score,task.id).run();
    }
    out.push({taskId:task.id,partnerId:task.partner_id,partnerName:task.partner_name,role:task.role,sourceQualityScore:sourceQuality,...q,nextStatus});
  }
  return{ok:true,version:VERSION,reviewed:out.length,pass:out.filter(x=>x.status==='PASS').length,weak:out.filter(x=>x.status==='WEAK').length,reject:out.filter(x=>x.status==='REJECT').length,tasks:out};
}

export async function reviewPendingDelegationTasks(env){return reviewDelegationTasks(env,{});}

async function stats(env){
  await ensureSchema(env);
  const x=await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN status='PASS' THEN 1 ELSE 0 END) pass,SUM(CASE WHEN status='WEAK' THEN 1 ELSE 0 END) weak,SUM(CASE WHEN status='REJECT' THEN 1 ELSE 0 END) reject FROM lumen_delegation_task_quality").first();
  return json({version:VERSION,total:Number(x?.total||0),pass:Number(x?.pass||0),weak:Number(x?.weak||0),reject:Number(x?.reject||0),dispatchRequires:"APPROVED_FOR_DISPATCH",autonomousOutgoingSpend:false,bindingActionsHumanGated:true});
}

export async function handleDelegationQualityGate(request,env){
  const url=new URL(request.url);
  if(request.method==="GET"&&url.pathname==="/delegation/quality-stats")return stats(env);
  if(request.method==="POST"&&url.pathname==="/delegation/review"){
    if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);let b={};try{b=await request.json();}catch{}
    return json(await reviewDelegationTasks(env,{roomId:clean(b?.roomId,120)}),202);
  }
  if(request.method==="GET"&&url.pathname==="/delegation/quality"){
    if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);
    await ensureSchema(env);const roomId=clean(url.searchParams.get("roomId"),120);
    const r=roomId?await env.DB.prepare("SELECT q.*,d.room_id,d.partner_name,d.role,d.title,d.status AS task_status FROM lumen_delegation_task_quality q JOIN lumen_delegation_tasks d ON d.id=q.task_id WHERE d.room_id=? ORDER BY q.score DESC").bind(roomId).all():await env.DB.prepare("SELECT q.*,d.room_id,d.partner_name,d.role,d.title,d.status AS task_status FROM lumen_delegation_task_quality q JOIN lumen_delegation_tasks d ON d.id=q.task_id ORDER BY q.updated_at DESC LIMIT 50").all();
    return json({version:VERSION,tasks:(r.results||[]).map(x=>({...x,reasons:(()=>{try{return JSON.parse(x.reasons_json||'[]');}catch{return[];}})()}))});
  }
  return null;
}
