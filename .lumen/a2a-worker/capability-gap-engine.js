const VERSION = "1.0-capability-gap-engine";

const OFFER_NEEDS={
  "MP-SUPPLIER-SNAPSHOT":["verification","sourcing","research"],
  "MP-QUOTE-SANITY":["pricing","research","verification"],
  "MP-TENDER-SCAN":["tender","research"],
  "MP-SOURCING-5":["sourcing","verification","pricing"],
  "MP-BUYER-SIGNALS":["sales","research"],
  "MP-EXPORT-PULSE":["export","logistics","research"]
};

function json(data,status=200){return Response.json(data,{status,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function clean(v,n=6000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}
function authorized(r,e){const a=clean(e?.OPPORTUNITY_ADMIN_TOKEN,500),b=clean(r.headers.get("x-lumen-admin"),500);return Boolean(a&&b&&a===b);}
function parseArray(v){try{const x=JSON.parse(v||"[]");return Array.isArray(x)?x:[];}catch{return[];}}
function clamp(n,min=0,max=100){return Math.max(min,Math.min(max,Number(n)||0));}

async function ensureSchema(env){
  if(!env?.DB)return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_capability_gap_queue (id TEXT PRIMARY KEY,source_type TEXT NOT NULL,source_id TEXT NOT NULL,capability TEXT NOT NULL,priority INTEGER NOT NULL,status TEXT NOT NULL,current_candidates INTEGER NOT NULL,strong_candidates INTEGER NOT NULL,observed_confident_candidates INTEGER NOT NULL,best_partner_id TEXT,best_partner_name TEXT,suggested_search TEXT NOT NULL,reason TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,engine_version TEXT NOT NULL,UNIQUE(source_type,source_id,capability))"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_capability_gap_priority ON lumen_capability_gap_queue(status,priority DESC,updated_at)")
  ]);
  return true;
}

async function coverage(env,capability){
  const needle=`%\"${clean(capability,80).toLowerCase()}\"%`;
  let rows=[];
  try{
    const r=await env.DB.prepare("SELECT p.id,p.name,p.reputation_score,p.compatibility_score,p.status,o.score AS observed_score,o.confidence AS observed_confidence FROM lumen_partner_agents p LEFT JOIN lumen_partner_observed_reputation o ON o.partner_id=p.id WHERE LOWER(p.capabilities_json) LIKE ? AND p.status IN ('candidate','strong_candidate') ORDER BY CASE WHEN COALESCE(o.confidence,0)>=30 THEN COALESCE(o.score,0) ELSE p.reputation_score END DESC,p.compatibility_score DESC LIMIT 100").bind(needle).all();
    rows=r.results||[];
  }catch{}
  const strong=rows.filter(x=>Number(x.reputation_score||0)>=75&&Number(x.compatibility_score||0)>=85);
  const observed=rows.filter(x=>Number(x.observed_confidence||0)>=30&&Number(x.observed_score||0)>=60&&Number(x.compatibility_score||0)>=80);
  const best=observed[0]||strong[0]||rows[0]||null;
  let status="OPEN";
  let reason="no_partner_for_capability";
  if(observed.length){status="COVERED";reason="observed_confident_partner_available";}
  else if(strong.length){status="WEAK_COVERAGE";reason="declared_strong_partner_without_observed_confidence";}
  else if(rows.length){status="WEAK_COVERAGE";reason="partner_available_but_fit_or_confidence_is_weak";}
  return{rows,strong,observed,best,status,reason};
}

function searchPhrase(cap){
  const map={
    verification:"verification evidence trust due diligence agent",
    sourcing:"supplier sourcing procurement vendor agent",
    research:"research intelligence analysis data agent",
    pricing:"pricing quote benchmark market agent",
    tender:"tender rfq bid procurement agent",
    sales:"buyer intent sales prospect demand agent",
    export:"export import trade distributor agent",
    logistics:"logistics shipping freight delivery agent",
    payments:"x402 payment settlement commerce agent",
    automation:"workflow automation orchestration agent"
  };
  return map[cap]||`${cap} specialist agent`;
}

async function upsertGap(env,{sourceType,sourceId,capability,priority,sourceReason}){
  const cov=await coverage(env,capability);
  const id=`CGAP-${sourceType}-${sourceId}-${capability}`.slice(0,230);
  const now=new Date().toISOString();
  await env.DB.prepare("INSERT INTO lumen_capability_gap_queue(id,source_type,source_id,capability,priority,status,current_candidates,strong_candidates,observed_confident_candidates,best_partner_id,best_partner_name,suggested_search,reason,created_at,updated_at,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source_type,source_id,capability) DO UPDATE SET priority=excluded.priority,status=excluded.status,current_candidates=excluded.current_candidates,strong_candidates=excluded.strong_candidates,observed_confident_candidates=excluded.observed_confident_candidates,best_partner_id=excluded.best_partner_id,best_partner_name=excluded.best_partner_name,suggested_search=excluded.suggested_search,reason=excluded.reason,updated_at=excluded.updated_at,engine_version=excluded.engine_version")
    .bind(id,sourceType,sourceId,capability,priority,cov.status,cov.rows.length,cov.strong.length,cov.observed.length,cov.best?.id||null,cov.best?.name||null,searchPhrase(capability),`${sourceReason};${cov.reason}`,now,now,VERSION).run();
  return{id,sourceType,sourceId,capability,priority,status:cov.status,currentCandidates:cov.rows.length,strongCandidates:cov.strong.length,observedConfidentCandidates:cov.observed.length,bestPartner:cov.best?.name||null,suggestedSearch:searchPhrase(capability),reason:`${sourceReason};${cov.reason}`};
}

async function ventureSources(env){
  let rows=[];
  try{
    const r=await env.DB.prepare("SELECT id,status,readiness_score,required_capabilities_json FROM lumen_venture_cases WHERE status IN ('READY_TO_VALIDATE','VALIDATION_REQUIRED','HOLD') ORDER BY readiness_score DESC LIMIT 30").all();
    rows=r.results||[];
  }catch{}
  const out=[];
  for(const row of rows){
    const base=row.status==='READY_TO_VALIDATE'?88:row.status==='VALIDATION_REQUIRED'?75:58;
    for(const cap of parseArray(row.required_capabilities_json).map(x=>clean(x,80).toLowerCase()).filter(Boolean)){
      out.push({sourceType:"VENTURE",sourceId:row.id,capability:cap,priority:Math.round(clamp(base+Number(row.readiness_score||0)*.1,0,100)),sourceReason:`venture_status=${row.status};readiness=${Number(row.readiness_score||0)}`});
    }
  }
  return out;
}

async function opportunitySources(env){
  let rows=[];
  try{
    const r=await env.DB.prepare("SELECT o.id,o.revenue_offer_id,a.commercial_score FROM lumen_opportunities o JOIN lumen_opportunity_assessments a ON a.opportunity_id=o.id WHERE a.commercially_actionable=1 AND a.synthetic_or_test_only=0 ORDER BY a.commercial_score DESC,o.updated_at DESC LIMIT 20").all();
    rows=r.results||[];
  }catch{}
  const out=[];
  for(const row of rows){
    const needs=OFFER_NEEDS[clean(row.revenue_offer_id,100)]||[];
    for(const cap of needs){
      out.push({sourceType:"OPPORTUNITY",sourceId:row.id,capability:cap,priority:Math.round(clamp(45+Number(row.commercial_score||0)*.5,0,100)),sourceReason:`commercial_score=${Number(row.commercial_score||0)};offer=${row.revenue_offer_id||"unknown"}`});
    }
  }
  return out;
}

export async function recomputeCapabilityGaps(env){
  if(!(await ensureSchema(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  const sources=[...(await ventureSources(env)),...(await opportunitySources(env))];
  const results=[];
  for(const source of sources)results.push(await upsertGap(env,source));
  const open=results.filter(x=>x.status==='OPEN').length;
  const weak=results.filter(x=>x.status==='WEAK_COVERAGE').length;
  const covered=results.filter(x=>x.status==='COVERED').length;
  return{ok:true,version:VERSION,evaluated:results.length,open,weakCoverage:weak,covered,topRecruitmentNeeds:results.filter(x=>x.status!=='COVERED').sort((a,b)=>b.priority-a.priority).slice(0,12),guardrails:{autonomousRecruitmentContact:false,autonomousSpend:false,bindingActionsHumanGated:true}};
}

async function stats(env){
  await ensureSchema(env);
  const r=await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN status='OPEN' THEN 1 ELSE 0 END) open,SUM(CASE WHEN status='WEAK_COVERAGE' THEN 1 ELSE 0 END) weak,SUM(CASE WHEN status='COVERED' THEN 1 ELSE 0 END) covered,COALESCE(MAX(CASE WHEN status<>'COVERED' THEN priority ELSE 0 END),0) top_priority FROM lumen_capability_gap_queue").first();
  return json({version:VERSION,total:Number(r?.total||0),open:Number(r?.open||0),weakCoverage:Number(r?.weak||0),covered:Number(r?.covered||0),highestRecruitmentPriority:Number(r?.top_priority||0),autonomousRecruitmentContact:false,autonomousSpend:false,bindingActionsHumanGated:true});
}

export async function handleCapabilityGapEngine(request,env){
  const url=new URL(request.url);
  if(request.method==="GET"&&url.pathname==="/capability-gaps/stats")return stats(env);
  if(request.method==="POST"&&url.pathname==="/capability-gaps/recompute"){
    if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);
    return json(await recomputeCapabilityGaps(env),202);
  }
  if(request.method==="GET"&&url.pathname==="/capability-gaps/queue"){
    if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);
    await ensureSchema(env);
    const r=await env.DB.prepare("SELECT * FROM lumen_capability_gap_queue WHERE status<>'COVERED' ORDER BY priority DESC,updated_at DESC LIMIT 100").all();
    return json({version:VERSION,queue:r.results||[]});
  }
  return null;
}
