const VERSION = "1.0-venture-peer-review";

function json(data,status=200){return Response.json(data,{status,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function clean(v,n=8000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}
function clamp(n,min=0,max=100){return Math.max(min,Math.min(max,Number(n)||0));}
function authorized(r,e){const a=clean(e?.OPPORTUNITY_ADMIN_TOKEN,500),b=clean(r.headers.get("x-lumen-admin"),500);return Boolean(a&&b&&a===b);}
async function bodyJson(r){try{return await r.json();}catch{return{};}}

async function ensureSchema(env){
  if(!env?.DB)return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_venture_review_assignments (id TEXT PRIMARY KEY,venture_case_id TEXT NOT NULL,reviewer_partner_id TEXT,reviewer_name TEXT NOT NULL,reviewer_role TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,external_contact_sent INTEGER NOT NULL DEFAULT 0,UNIQUE(venture_case_id,reviewer_partner_id))"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_venture_review_assignments ON lumen_venture_review_assignments(venture_case_id,status,updated_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_venture_peer_reviews (id TEXT PRIMARY KEY,venture_case_id TEXT NOT NULL,reviewer_partner_id TEXT,reviewer_name TEXT NOT NULL,created_at TEXT NOT NULL,market_score INTEGER NOT NULL,evidence_score INTEGER NOT NULL,execution_score INTEGER NOT NULL,monetization_score INTEGER NOT NULL,risk_score INTEGER NOT NULL,total_score INTEGER NOT NULL,verdict TEXT NOT NULL,critique TEXT NOT NULL,recommendation TEXT NOT NULL,evidence TEXT,raw_json TEXT)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_venture_peer_reviews_case ON lumen_venture_peer_reviews(venture_case_id,created_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_venture_review_summary (venture_case_id TEXT PRIMARY KEY,review_count INTEGER NOT NULL,pass_count INTEGER NOT NULL,reject_count INTEGER NOT NULL,average_score INTEGER NOT NULL,status TEXT NOT NULL,updated_at TEXT NOT NULL,reason TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_venture_review_summary_status ON lumen_venture_review_summary(status,updated_at)")
  ]);
  return true;
}

async function reviewerCandidates(env,ventureCase){
  let caps=[];try{caps=JSON.parse(ventureCase.required_capabilities_json||"[]");}catch{}
  const rows=[];
  for(const cap of caps.slice(0,5)){
    try{
      const needle=`%\"${clean(cap,80).toLowerCase()}\"%`;
      const r=await env.DB.prepare("SELECT p.id,p.name,p.reputation_score,p.compatibility_score,o.score observed_score,o.confidence observed_confidence FROM lumen_partner_agents p LEFT JOIN lumen_partner_observed_reputation o ON o.partner_id=p.id WHERE LOWER(p.capabilities_json) LIKE ? AND p.status IN ('candidate','strong_candidate') ORDER BY CASE WHEN COALESCE(o.confidence,0)>=30 THEN COALESCE(o.score,0) ELSE p.reputation_score END DESC,p.compatibility_score DESC LIMIT 8").bind(needle).all();
      for(const x of r.results||[])rows.push({...x,capability:cap});
    }catch{}
  }
  const unique=[];const used=new Set();
  for(const x of rows){if(used.has(x.id))continue;used.add(x.id);unique.push(x);}
  return unique.sort((a,b)=>{
    const ar=Number(a.observed_confidence||0)>=30?Number(a.observed_score||0):Number(a.reputation_score||0);
    const br=Number(b.observed_confidence||0)>=30?Number(b.observed_score||0):Number(b.reputation_score||0);
    return br-ar||Number(b.compatibility_score||0)-Number(a.compatibility_score||0);
  });
}

export async function planVenturePeerReviews(env,{limit=6}={}){
  if(!(await ensureSchema(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  let cases=[];try{const r=await env.DB.prepare("SELECT * FROM lumen_venture_cases WHERE status IN ('READY_TO_VALIDATE','VALIDATION_REQUIRED') ORDER BY readiness_score DESC,updated_at ASC LIMIT ?").bind(Math.max(1,Math.min(20,Number(limit)||6))).all();cases=r.results||[];}catch{return{ok:false,error:"venture_cases_not_ready",version:VERSION};}
  const planned=[];
  for(const vc of cases){
    const candidates=await reviewerCandidates(env,vc);
    const chosen=candidates.slice(0,2);
    for(const reviewer of chosen){
      const id=`VRA-${vc.id}-${reviewer.id}`.slice(0,220);const now=new Date().toISOString();
      await env.DB.prepare("INSERT OR IGNORE INTO lumen_venture_review_assignments(id,venture_case_id,reviewer_partner_id,reviewer_name,reviewer_role,status,created_at,updated_at,external_contact_sent) VALUES(?,?,?,?,?,'PLANNED',?,?,0)")
        .bind(id,vc.id,reviewer.id,reviewer.name,clean(reviewer.capability,80)||"specialist",now,now).run();
      planned.push({ventureCaseId:vc.id,reviewerPartnerId:reviewer.id,reviewerName:reviewer.name,role:reviewer.capability,status:"PLANNED",externalContactSent:false});
    }
  }
  return{ok:true,version:VERSION,casesConsidered:cases.length,assignmentsPlanned:planned.length,assignments:planned,guardrails:{externalContactSent:false,autonomousSpend:false,bindingAllowed:false}};
}

function scoreReview(body){
  const market=clamp(body?.marketScore??body?.market_score);
  const evidence=clamp(body?.evidenceScore??body?.evidence_score);
  const execution=clamp(body?.executionScore??body?.execution_score);
  const monetization=clamp(body?.monetizationScore??body?.monetization_score);
  const risk=clamp(body?.riskScore??body?.risk_score);
  const total=Math.round(market*.24+evidence*.26+execution*.20+monetization*.20+(100-risk)*.10);
  const verdict=total>=72&&evidence>=60&&risk<=70?"PASS":total>=55?"WEAK":"REJECT";
  return{market,evidence,execution,monetization,risk,total,verdict};
}

async function refreshSummary(env,caseId){
  const r=await env.DB.prepare("SELECT COUNT(*) review_count,SUM(CASE WHEN verdict='PASS' THEN 1 ELSE 0 END) pass_count,SUM(CASE WHEN verdict='REJECT' THEN 1 ELSE 0 END) reject_count,COALESCE(ROUND(AVG(total_score)),0) average_score FROM lumen_venture_peer_reviews WHERE venture_case_id=?").bind(caseId).first();
  const count=Number(r?.review_count||0),pass=Number(r?.pass_count||0),reject=Number(r?.reject_count||0),avg=Number(r?.average_score||0);
  let status="PEER_REVIEW_REQUIRED",reason="minimum_two_independent_reviews_required";
  if(reject>0){status="REVIEW_REJECTED";reason="at_least_one_independent_reject";}
  else if(count>=2&&pass>=2&&avg>=72){status="PEER_REVIEW_PASS";reason="two_independent_pass_reviews";}
  else if(count>=2){status="REVIEW_WEAK";reason="two_reviews_but_consensus_or_quality_below_threshold";}
  const now=new Date().toISOString();
  await env.DB.prepare("INSERT INTO lumen_venture_review_summary(venture_case_id,review_count,pass_count,reject_count,average_score,status,updated_at,reason) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(venture_case_id) DO UPDATE SET review_count=excluded.review_count,pass_count=excluded.pass_count,reject_count=excluded.reject_count,average_score=excluded.average_score,status=excluded.status,updated_at=excluded.updated_at,reason=excluded.reason")
    .bind(caseId,count,pass,reject,avg,status,now,reason).run();
  if(status==="PEER_REVIEW_PASS"){
    await env.DB.prepare("UPDATE lumen_venture_experiments SET status='APPROVED_FOR_ZERO_COST_VALIDATION' WHERE venture_case_id=? AND status='PLANNED' AND cost_limit_usd=0 AND external_contact_allowed=0 AND binding_allowed=0").bind(caseId).run();
  }
  if(status==="REVIEW_REJECTED"){
    await env.DB.prepare("UPDATE lumen_venture_experiments SET status='BLOCKED_BY_PEER_REVIEW' WHERE venture_case_id=? AND status IN ('PLANNED','APPROVED_FOR_ZERO_COST_VALIDATION')").bind(caseId).run();
  }
  return{reviewCount:count,passCount:pass,rejectCount:reject,averageScore:avg,status,reason};
}

export async function submitVenturePeerReview(env,body={}){
  if(!(await ensureSchema(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  const caseId=clean(body?.ventureCaseId||body?.venture_case_id,220);const reviewerId=clean(body?.reviewerPartnerId||body?.reviewer_partner_id,220);const reviewerName=clean(body?.reviewerName||body?.reviewer_name,220);
  const critique=clean(body?.critique,5000);const recommendation=clean(body?.recommendation,4000);const evidenceText=clean(body?.evidence,5000);
  if(!caseId||!reviewerName||!critique||!recommendation)return{ok:false,error:"ventureCaseId_reviewerName_critique_recommendation_required",version:VERSION};
  const vc=await env.DB.prepare("SELECT id FROM lumen_venture_cases WHERE id=? LIMIT 1").bind(caseId).first();if(!vc)return{ok:false,error:"venture_case_not_found",version:VERSION};
  const s=scoreReview(body);const id=`VPR-${crypto.randomUUID().replaceAll('-','').slice(0,18).toUpperCase()}`;const now=new Date().toISOString();
  await env.DB.prepare("INSERT INTO lumen_venture_peer_reviews(id,venture_case_id,reviewer_partner_id,reviewer_name,created_at,market_score,evidence_score,execution_score,monetization_score,risk_score,total_score,verdict,critique,recommendation,evidence,raw_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
    .bind(id,caseId,reviewerId||null,reviewerName,now,s.market,s.evidence,s.execution,s.monetization,s.risk,s.total,s.verdict,critique,recommendation,evidenceText||null,JSON.stringify(body).slice(0,12000)).run();
  if(reviewerId)await env.DB.prepare("UPDATE lumen_venture_review_assignments SET status='REVIEWED',updated_at=? WHERE venture_case_id=? AND reviewer_partner_id=?").bind(now,caseId,reviewerId).run();
  const summary=await refreshSummary(env,caseId);
  return{ok:true,version:VERSION,reviewId:id,verdict:s.verdict,totalScore:s.total,scores:{market:s.market,evidence:s.evidence,execution:s.execution,monetization:s.monetization,risk:s.risk},summary,guardrails:{bindingAllowed:false,spendAllowed:false}};
}

async function stats(env){
  await ensureSchema(env);
  const a=await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN status='PLANNED' THEN 1 ELSE 0 END) planned,SUM(CASE WHEN status='REVIEWED' THEN 1 ELSE 0 END) reviewed FROM lumen_venture_review_assignments").first();
  const s=await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN status='PEER_REVIEW_PASS' THEN 1 ELSE 0 END) passed,SUM(CASE WHEN status='REVIEW_REJECTED' THEN 1 ELSE 0 END) rejected,SUM(CASE WHEN status='REVIEW_WEAK' THEN 1 ELSE 0 END) weak FROM lumen_venture_review_summary").first();
  return json({version:VERSION,assignments:{total:Number(a?.total||0),planned:Number(a?.planned||0),reviewed:Number(a?.reviewed||0)},cases:{reviewed:Number(s?.total||0),passed:Number(s?.passed||0),rejected:Number(s?.rejected||0),weak:Number(s?.weak||0)},experimentActivationRequires:"PEER_REVIEW_PASS",minimumIndependentReviews:2,autonomousSpend:false,externalReviewInvites:false,bindingActionsHumanGated:true});
}

export async function handleVenturePeerReview(request,env){
  const url=new URL(request.url);
  if(request.method==="GET"&&url.pathname==="/venture-review/stats")return stats(env);
  if(request.method==="POST"&&url.pathname==="/venture-review/plan"){
    if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);let b=await bodyJson(request);return json(await planVenturePeerReviews(env,{limit:b?.limit}),202);
  }
  if(request.method==="POST"&&url.pathname==="/venture-review/submit"){
    if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);return json(await submitVenturePeerReview(env,await bodyJson(request)),202);
  }
  if(request.method==="GET"&&url.pathname==="/venture-review/assignments"){
    if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);await ensureSchema(env);const r=await env.DB.prepare("SELECT * FROM lumen_venture_review_assignments ORDER BY updated_at DESC LIMIT 100").all();return json({version:VERSION,assignments:r.results||[]});
  }
  return null;
}
