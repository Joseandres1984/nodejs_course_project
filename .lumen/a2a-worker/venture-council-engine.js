const VERSION = "1.1-venture-council-engine";

function json(data,status=200){return Response.json(data,{status,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function clean(v,n=8000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}
function authorized(r,e){const a=clean(e?.OPPORTUNITY_ADMIN_TOKEN,500),b=clean(r.headers.get("x-lumen-admin"),500);return Boolean(a&&b&&a===b);}
function clamp(n,min=0,max=100){return Math.max(min,Math.min(max,Number(n)||0));}
function parseArray(v){try{const x=JSON.parse(v||"[]");return Array.isArray(x)?x:[];}catch{return[];}}

async function ensureSchema(env){
  if(!env?.DB)return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_venture_cases (id TEXT PRIMARY KEY,idea_id TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,status TEXT NOT NULL,title TEXT NOT NULL,customer_hypothesis TEXT,revenue_hypothesis TEXT,evidence_summary TEXT,required_capabilities_json TEXT NOT NULL,coverage_score INTEGER NOT NULL,gap_count INTEGER NOT NULL,readiness_score INTEGER NOT NULL,next_experiment TEXT NOT NULL,experiment_cost_usd REAL NOT NULL DEFAULT 0,binding_allowed INTEGER NOT NULL DEFAULT 0,spend_allowed INTEGER NOT NULL DEFAULT 0,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_venture_cases_rank ON lumen_venture_cases(status,readiness_score,updated_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_venture_capability_gaps (id TEXT PRIMARY KEY,venture_case_id TEXT NOT NULL,capability TEXT NOT NULL,status TEXT NOT NULL,best_partner_id TEXT,best_partner_name TEXT,declared_reputation INTEGER,compatibility INTEGER,observed_score INTEGER,observed_confidence INTEGER,updated_at TEXT NOT NULL,reason TEXT NOT NULL,UNIQUE(venture_case_id,capability))"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_venture_gaps_status ON lumen_venture_capability_gaps(status,capability,updated_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_venture_experiments (id TEXT PRIMARY KEY,venture_case_id TEXT NOT NULL,created_at TEXT NOT NULL,status TEXT NOT NULL,experiment_type TEXT NOT NULL,hypothesis TEXT NOT NULL,success_criteria TEXT NOT NULL,method TEXT NOT NULL,cost_limit_usd REAL NOT NULL DEFAULT 0,external_contact_allowed INTEGER NOT NULL DEFAULT 0,binding_allowed INTEGER NOT NULL DEFAULT 0,result_summary TEXT)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_venture_experiments_case ON lumen_venture_experiments(venture_case_id,created_at)")
  ]);
  return true;
}

async function partnerForCapability(env,cap){
  const needle=`%\"${clean(cap,80).toLowerCase()}\"%`;
  let rows=[];
  try{
    const r=await env.DB.prepare("SELECT p.id,p.name,p.reputation_score,p.compatibility_score,o.score AS observed_score,o.confidence AS observed_confidence FROM lumen_partner_agents p LEFT JOIN lumen_partner_observed_reputation o ON o.partner_id=p.id WHERE LOWER(p.capabilities_json) LIKE ? AND p.status IN ('candidate','strong_candidate') ORDER BY CASE WHEN COALESCE(o.confidence,0)>=30 THEN COALESCE(o.score,0) ELSE p.reputation_score END DESC,p.compatibility_score DESC LIMIT 10").bind(needle).all();
    rows=r.results||[];
  }catch{}
  if(!rows.length)return null;
  const strong=rows.find(x=>Number(x.observed_confidence||0)>=30&&Number(x.observed_score||0)>=60&&Number(x.compatibility_score||0)>=80);
  if(strong)return{...strong,coverageStatus:"COVERED",reason:"observed_reputation_confident"};
  const declared=rows.find(x=>Number(x.reputation_score||0)>=75&&Number(x.compatibility_score||0)>=85);
  if(declared)return{...declared,coverageStatus:"WEAK",reason:"declared_fit_without_enough_observed_confidence"};
  return{...rows[0],coverageStatus:"WEAK",reason:"available_but_low_confidence_or_fit"};
}

function experimentForIdea(idea,readiness){
  const customer=clean(idea.customer_signal,1200)||"No validated customer signal yet";
  const revenue=clean(idea.revenue_model,1200)||"Revenue model not validated";
  const hypothesis=`There is a real buyer/problem signal for: ${idea.title}. Customer hypothesis: ${customer}. Revenue hypothesis: ${revenue}.`;
  const success=readiness>=75
    ? "Find at least 2 independent public demand/evidence signals and no blocking capability gap."
    : "Find at least 1 independent demand/evidence signal and reduce the largest evidence or capability gap.";
  const method="Zero-cost evidence validation using public sources, existing LUMEN observations, partner registry data and non-binding internal analysis only. No paid tools, purchases, contracts or outbound commitments.";
  return{type:"ZERO_COST_EVIDENCE_VALIDATION",hypothesis,success,method};
}

async function promoteIdea(env,idea){
  const caps=parseArray(idea.required_capabilities_json).map(x=>clean(x,80).toLowerCase()).filter(Boolean);
  const coverage=[];
  for(const cap of caps){
    const partner=await partnerForCapability(env,cap);
    coverage.push({capability:cap,partner});
  }
  const covered=coverage.filter(x=>x.partner?.coverageStatus==="COVERED").length;
  const weak=coverage.filter(x=>x.partner?.coverageStatus==="WEAK").length;
  const gaps=coverage.filter(x=>!x.partner).length;
  const coverageScore=caps.length?Math.round(((covered+weak*.55)/caps.length)*100):60;
  const readiness=Math.round(clamp(Number(idea.total_score||0)*.58+Number(idea.evidence_score||0)*.22+coverageScore*.20));
  const status=readiness>=78&&gaps===0?"READY_TO_VALIDATE":readiness>=62?"VALIDATION_REQUIRED":"HOLD";
  const id=`VENTURE-${idea.id}`.slice(0,190);
  const now=new Date().toISOString();
  const exp=experimentForIdea(idea,readiness);

  await env.DB.prepare("INSERT INTO lumen_venture_cases(id,idea_id,created_at,updated_at,status,title,customer_hypothesis,revenue_hypothesis,evidence_summary,required_capabilities_json,coverage_score,gap_count,readiness_score,next_experiment,experiment_cost_usd,binding_allowed,spend_allowed,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0,0,?) ON CONFLICT(idea_id) DO UPDATE SET updated_at=excluded.updated_at,status=excluded.status,customer_hypothesis=excluded.customer_hypothesis,revenue_hypothesis=excluded.revenue_hypothesis,evidence_summary=excluded.evidence_summary,required_capabilities_json=excluded.required_capabilities_json,coverage_score=excluded.coverage_score,gap_count=excluded.gap_count,readiness_score=excluded.readiness_score,next_experiment=excluded.next_experiment,engine_version=excluded.engine_version")
    .bind(id,idea.id,now,now,status,idea.title,clean(idea.customer_signal,2000),clean(idea.revenue_model,2000),clean(idea.evidence,3000),JSON.stringify(caps),coverageScore,gaps,readiness,exp.type,VERSION).run();

  for(const item of coverage){
    const gid=`VGAP-${id}-${item.capability}`.slice(0,220);
    const p=item.partner;
    const gapStatus=p?.coverageStatus||"GAP";
    await env.DB.prepare("INSERT INTO lumen_venture_capability_gaps(id,venture_case_id,capability,status,best_partner_id,best_partner_name,declared_reputation,compatibility,observed_score,observed_confidence,updated_at,reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(venture_case_id,capability) DO UPDATE SET status=excluded.status,best_partner_id=excluded.best_partner_id,best_partner_name=excluded.best_partner_name,declared_reputation=excluded.declared_reputation,compatibility=excluded.compatibility,observed_score=excluded.observed_score,observed_confidence=excluded.observed_confidence,updated_at=excluded.updated_at,reason=excluded.reason")
      .bind(gid,id,item.capability,gapStatus,p?.id||null,p?.name||null,p?Number(p.reputation_score||0):null,p?Number(p.compatibility_score||0):null,p?.observed_score==null?null:Number(p.observed_score),p?.observed_confidence==null?null:Number(p.observed_confidence),now,p?.reason||"no_partner_found_for_required_capability").run();
  }

  const experimentId=`VEXP-${idea.id}`.slice(0,190);
  await env.DB.prepare("INSERT OR IGNORE INTO lumen_venture_experiments(id,venture_case_id,created_at,status,experiment_type,hypothesis,success_criteria,method,cost_limit_usd,external_contact_allowed,binding_allowed,result_summary) VALUES(?,?,?,'PLANNED',?,?,?,?,0,0,0,NULL)")
    .bind(experimentId,id,now,exp.type,exp.hypothesis,exp.success,exp.method).run();

  return{id,ideaId:idea.id,title:idea.title,status,readinessScore:readiness,coverageScore,gapCount:gaps,capabilities:coverage.map(x=>({capability:x.capability,status:x.partner?.coverageStatus||"GAP",partner:x.partner?.name||null,observedConfidence:Number(x.partner?.observed_confidence||0)})),experiment:{id:experimentId,type:exp.type,costLimitUsd:0,externalContactAllowed:false}};
}

async function revokeRejectedCases(env){
  try{
    await env.DB.prepare("UPDATE lumen_venture_cases SET status='SOURCE_REJECTED',updated_at=? WHERE idea_id IN (SELECT id FROM lumen_partner_ideas WHERE status='SOURCE_REJECTED') AND status<>'SOURCE_REJECTED'").bind(new Date().toISOString()).run();
    await env.DB.prepare("UPDATE lumen_venture_experiments SET status='CANCELLED_SOURCE_REJECTED' WHERE venture_case_id IN (SELECT id FROM lumen_venture_cases WHERE status='SOURCE_REJECTED') AND status='PLANNED'").run();
  }catch{}
}

export async function runVentureCouncil(env){
  if(!(await ensureSchema(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  await revokeRejectedCases(env);
  let ideas=[];
  try{
    const r=await env.DB.prepare("SELECT i.* FROM lumen_partner_ideas i LEFT JOIN lumen_venture_suggestion_intake v ON v.idea_id=i.id WHERE i.status IN ('HIGH_POTENTIAL','REVIEW') AND i.total_score>=60 AND (v.idea_id IS NULL OR v.status='INGESTED_PASS') ORDER BY i.total_score DESC,i.evidence_score DESC,i.created_at ASC LIMIT 20").all();
    ideas=r.results||[];
  }catch{return{ok:false,error:"venture_board_not_ready",version:VERSION};}
  const cases=[];
  for(const idea of ideas)cases.push(await promoteIdea(env,idea));
  return{ok:true,version:VERSION,ideasEvaluated:ideas.length,cases,sourceQualityGateRequired:true,guardrails:{autonomousSpend:false,autonomousContract:false,autonomousHiring:false,externalValidation:false,experimentsCostLimitUsd:0}};
}

async function stats(env){
  await ensureSchema(env);
  const c=await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN status='READY_TO_VALIDATE' THEN 1 ELSE 0 END) ready,SUM(CASE WHEN status='VALIDATION_REQUIRED' THEN 1 ELSE 0 END) validation_required,SUM(CASE WHEN status='HOLD' THEN 1 ELSE 0 END) hold,SUM(CASE WHEN status='SOURCE_REJECTED' THEN 1 ELSE 0 END) source_rejected,COALESCE(MAX(CASE WHEN status<>'SOURCE_REJECTED' THEN readiness_score ELSE 0 END),0) best_readiness FROM lumen_venture_cases").first();
  const g=await env.DB.prepare("SELECT SUM(CASE WHEN status='GAP' THEN 1 ELSE 0 END) gaps,SUM(CASE WHEN status='WEAK' THEN 1 ELSE 0 END) weak,SUM(CASE WHEN status='COVERED' THEN 1 ELSE 0 END) covered FROM lumen_venture_capability_gaps WHERE venture_case_id NOT IN (SELECT id FROM lumen_venture_cases WHERE status='SOURCE_REJECTED')").first();
  return json({version:VERSION,total:Number(c?.total||0),readyToValidate:Number(c?.ready||0),validationRequired:Number(c?.validation_required||0),hold:Number(c?.hold||0),sourceRejected:Number(c?.source_rejected||0),bestReadiness:Number(c?.best_readiness||0),capabilityCoverage:{covered:Number(g?.covered||0),weak:Number(g?.weak||0),gaps:Number(g?.gaps||0)},sourceQualityGateRequired:true,autonomousSpend:false,externalValidation:false,bindingActionsHumanGated:true});
}

export async function handleVentureCouncil(request,env){
  const url=new URL(request.url);
  if(request.method==="GET"&&url.pathname==="/venture-council/stats")return stats(env);
  if(request.method==="POST"&&url.pathname==="/venture-council/run"){
    if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);
    return json(await runVentureCouncil(env),202);
  }
  if(request.method==="GET"&&url.pathname==="/venture-council/cases"){
    if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);
    await ensureSchema(env);
    const r=await env.DB.prepare("SELECT * FROM lumen_venture_cases ORDER BY CASE WHEN status='SOURCE_REJECTED' THEN 1 ELSE 0 END,readiness_score DESC,updated_at DESC LIMIT 50").all();
    return json({version:VERSION,cases:(r.results||[]).map(x=>({...x,requiredCapabilities:parseArray(x.required_capabilities_json)}))});
  }
  if(request.method==="GET"&&url.pathname==="/venture-council/gaps"){
    if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);
    await ensureSchema(env);
    const r=await env.DB.prepare("SELECT * FROM lumen_venture_capability_gaps WHERE venture_case_id NOT IN (SELECT id FROM lumen_venture_cases WHERE status='SOURCE_REJECTED') ORDER BY CASE status WHEN 'GAP' THEN 0 WHEN 'WEAK' THEN 1 ELSE 2 END,updated_at DESC LIMIT 100").all();
    return json({version:VERSION,gaps:r.results||[]});
  }
  return null;
}
