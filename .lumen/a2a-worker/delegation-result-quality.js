const VERSION = "1.0-delegation-result-quality";

const ROLE_TERMS = {
  verification:["verify","verified","evidence","trust","certification","assurance","risk","provenance"],
  research:["research","evidence","analysis","source","finding","data","context"],
  sourcing:["supplier","vendor","source","sourcing","procurement","option","provider"],
  pricing:["price","pricing","quote","cost","benchmark","range","market"],
  tender:["tender","rfq","requirement","deadline","qualification","bid"],
  logistics:["logistics","shipping","freight","delivery","transport","route"],
  sales:["buyer","customer","intent","objection","qualification","commercial"],
  payments:["payment","settlement","rail","checkout","receipt","wallet"],
  automation:["workflow","step","input","output","failure","control","gate"]
};

function json(data,status=200){return Response.json(data,{status,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function clean(v,n=16000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}
function authorized(r,e){const a=clean(e?.OPPORTUNITY_ADMIN_TOKEN,500),b=clean(r.headers.get("x-lumen-admin"),500);return Boolean(a&&b&&a===b);}
function countHits(text,terms){const t=clean(text,24000).toLowerCase();return terms.filter(x=>t.includes(x)).length;}
function tokens(text){const stop=new Set(["this","that","with","from","your","have","will","into","agent","lumen","task","please","return","only","work","relevant","expected","output"]);return new Set((clean(text,24000).toLowerCase().match(/[a-z0-9][a-z0-9_-]{3,}/g)||[]).filter(x=>!stop.has(x)));}
function overlap(a,b){const A=tokens(a),B=tokens(b);if(!A.size||!B.size)return 0;let hit=0;for(const x of A)if(B.has(x))hit++;return hit/Math.min(A.size,B.size);}

async function ensureSchema(env){
  if(!env?.DB)return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_delegation_result_quality (task_id TEXT PRIMARY KEY,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,score INTEGER NOT NULL,status TEXT NOT NULL,relevance_score INTEGER NOT NULL,evidence_score INTEGER NOT NULL,action_score INTEGER NOT NULL,role_score INTEGER NOT NULL,fabrication_penalty INTEGER NOT NULL,echo_penalty INTEGER NOT NULL,reasons_json TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_delegation_result_quality_status ON lumen_delegation_result_quality(status,score)")
  ]);
  return true;
}

function scoreResult(task){
  const result=clean(task.response_text,20000);const lower=result.toLowerCase();const scope=clean(`${task.title||""} ${task.objective||""} ${task.expected_output||""}`,16000);const reasons=[];
  const rel=Math.min(30,Math.round(overlap(result,scope)*60));if(rel>=15)reasons.push("scope_relevant");
  const roleTerms=ROLE_TERMS[clean(task.role,80).toLowerCase()]||[clean(task.role,80).toLowerCase()];
  const role=Math.min(20,countHits(result,roleTerms)*4);if(role>=8)reasons.push("role_specific");
  const evidence=Math.min(25,countHits(result,["evidence","source","observed","verified","reference","http://","https://","record","receipt","profile","data","unknown","assumption"])*3);if(evidence>=9)reasons.push("evidence_or_uncertainty_signals");
  const action=Math.min(15,countHits(result,["recommend","next","should","check","verify","confirm","compare","contact","use ","avoid"])*3);if(action>=6)reasons.push("actionable");

  let fabrication=0;
  const riskyClaims=["guaranteed","definitely purchased","payment completed","contract signed","order placed","authorized by lumen","confirmed customer","confirmed buyer"];
  const riskyHits=countHits(result,riskyClaims);if(riskyHits){fabrication=Math.min(50,riskyHits*20);reasons.push(`unsupported_binding_claim_penalty:${fabrication}`);}

  let echo=0;const ov=overlap(result,scope);if(ov>0.72&&result.length>500)echo=20;else if(ov>0.58&&result.length>500)echo=10;if(echo)reasons.push(`task_echo_penalty:${echo}`);

  if(result.length<80){reasons.push("result_too_short");}
  let score=Math.max(0,Math.min(100,20+rel+role+evidence+action-fabrication-echo));
  if(result.length<80)score=Math.min(score,49);
  if(fabrication>=40)score=0;
  const status=score>=70?"PASS":score>=50?"WEAK":"REJECT";
  return{score,status,relevance_score:rel,evidence_score:evidence,action_score:action,role_score:role,fabrication_penalty:fabrication,echo_penalty:echo,reasons};
}

export async function reviewDelegationResults(env){
  if(!(await ensureSchema(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  const r=await env.DB.prepare("SELECT * FROM lumen_delegation_tasks WHERE status='RESULT_RECEIVED' AND response_text IS NOT NULL AND TRIM(response_text)<>'' ORDER BY completed_at ASC LIMIT 30").all();
  const out=[];
  for(const task of r.results||[]){
    const q=scoreResult(task);const now=new Date().toISOString();
    await env.DB.prepare("INSERT INTO lumen_delegation_result_quality(task_id,created_at,updated_at,score,status,relevance_score,evidence_score,action_score,role_score,fabrication_penalty,echo_penalty,reasons_json,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET updated_at=excluded.updated_at,score=excluded.score,status=excluded.status,relevance_score=excluded.relevance_score,evidence_score=excluded.evidence_score,action_score=excluded.action_score,role_score=excluded.role_score,fabrication_penalty=excluded.fabrication_penalty,echo_penalty=excluded.echo_penalty,reasons_json=excluded.reasons_json,engine_version=excluded.engine_version")
      .bind(task.id,now,now,q.score,q.status,q.relevance_score,q.evidence_score,q.action_score,q.role_score,q.fabrication_penalty,q.echo_penalty,JSON.stringify(q.reasons),VERSION).run();
    const next=q.status==="PASS"?"RESULT_PASS":q.status==="WEAK"?"RESULT_WEAK":"RESULT_REJECTED";
    await env.DB.prepare("UPDATE lumen_delegation_tasks SET status=?,updated_at=?,quality_score=? WHERE id=? AND status='RESULT_RECEIVED'").bind(next,now,q.score,task.id).run();
    out.push({taskId:task.id,partnerId:task.partner_id,partnerName:task.partner_name,role:task.role,...q,nextStatus:next});
  }
  return{ok:true,version:VERSION,reviewed:out.length,pass:out.filter(x=>x.status==='PASS').length,weak:out.filter(x=>x.status==='WEAK').length,reject:out.filter(x=>x.status==='REJECT').length,results:out};
}

async function stats(env){
  await ensureSchema(env);const x=await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN status='PASS' THEN 1 ELSE 0 END) pass,SUM(CASE WHEN status='WEAK' THEN 1 ELSE 0 END) weak,SUM(CASE WHEN status='REJECT' THEN 1 ELSE 0 END) reject FROM lumen_delegation_result_quality").first();
  return json({version:VERSION,total:Number(x?.total||0),pass:Number(x?.pass||0),weak:Number(x?.weak||0),reject:Number(x?.reject||0),integrationRequires:"RESULT_PASS",autonomousOutgoingSpend:false,bindingActionsHumanGated:true});
}

export async function handleDelegationResultQuality(request,env){
  const url=new URL(request.url);
  if(request.method==="GET"&&url.pathname==="/delegation/result-quality-stats")return stats(env);
  if(request.method==="POST"&&url.pathname==="/delegation/review-results"){
    if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);return json(await reviewDelegationResults(env),202);
  }
  if(request.method==="GET"&&url.pathname==="/delegation/result-quality"){
    if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);await ensureSchema(env);
    const r=await env.DB.prepare("SELECT q.*,d.room_id,d.partner_name,d.role,d.title,d.status AS task_status FROM lumen_delegation_result_quality q JOIN lumen_delegation_tasks d ON d.id=q.task_id ORDER BY q.updated_at DESC LIMIT 50").all();
    return json({version:VERSION,results:(r.results||[]).map(x=>({...x,reasons:(()=>{try{return JSON.parse(x.reasons_json||'[]');}catch{return[];}})()}))});
  }
  return null;
}
