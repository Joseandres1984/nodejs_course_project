const VERSION="1.0-partner-negotiator";

function json(d,s=200){return Response.json(d,{status:s,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function clean(v,n=5000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}
function authorized(r,e){const a=clean(e?.OPPORTUNITY_ADMIN_TOKEN,500),b=clean(r.headers.get("x-lumen-admin"),500);return Boolean(a&&b&&a===b);}
function clamp(v,min=0,max=100){return Math.max(min,Math.min(max,Number(v)||0));}
function parseJson(v,f=[]){try{const x=JSON.parse(v||"");return x??f;}catch{return f;}}
async function sha256(text){const d=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(String(text)));return[...new Uint8Array(d)].map(b=>b.toString(16).padStart(2,"0")).join("");}

async function ensure(env){
  if(!env?.DB)return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_negotiation_cases (id TEXT PRIMARY KEY,opportunity_id TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,status TEXT NOT NULL,title TEXT NOT NULL,commercial_score INTEGER NOT NULL,offer_id TEXT,required_capabilities_json TEXT NOT NULL,candidate_count INTEGER NOT NULL DEFAULT 0,priced_candidate_count INTEGER NOT NULL DEFAULT 0,timed_candidate_count INTEGER NOT NULL DEFAULT 0,recommended_partner_id TEXT,recommended_partner_name TEXT,recommendation_score INTEGER,recommendation_confidence INTEGER NOT NULL DEFAULT 0,decision_mode TEXT NOT NULL,binding_allowed INTEGER NOT NULL DEFAULT 0,spend_allowed INTEGER NOT NULL DEFAULT 0,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_negotiation_case_status ON lumen_negotiation_cases(status,commercial_score DESC,updated_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_negotiation_candidates (id TEXT PRIMARY KEY,case_id TEXT NOT NULL,partner_id TEXT NOT NULL,partner_name TEXT NOT NULL,capabilities_json TEXT NOT NULL,match_score INTEGER NOT NULL,trust_score INTEGER NOT NULL,trust_level TEXT NOT NULL,declared_reputation INTEGER NOT NULL,compatibility_score INTEGER NOT NULL,observed_score INTEGER,observed_confidence INTEGER NOT NULL DEFAULT 0,reliability_score INTEGER,responsiveness_score INTEGER,declared_price_usd REAL,price_source TEXT,eta_hours REAL,terms_text TEXT,quality_score INTEGER NOT NULL,price_score INTEGER NOT NULL,time_score INTEGER NOT NULL,risk_penalty INTEGER NOT NULL,total_score INTEGER NOT NULL,data_completeness INTEGER NOT NULL,status TEXT NOT NULL,updated_at TEXT NOT NULL,raw_json TEXT,UNIQUE(case_id,partner_id))"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_negotiation_candidate_rank ON lumen_negotiation_candidates(case_id,total_score DESC,data_completeness DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_negotiation_terms (id TEXT PRIMARY KEY,partner_id TEXT NOT NULL,opportunity_id TEXT,source TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,price_usd REAL,eta_hours REAL,scope TEXT,terms_text TEXT,evidence TEXT,status TEXT NOT NULL DEFAULT 'DECLARED_UNVERIFIED',binding_allowed INTEGER NOT NULL DEFAULT 0,spend_allowed INTEGER NOT NULL DEFAULT 0,UNIQUE(partner_id,opportunity_id,source))")
  ]);
  return true;
}

function priceFromText(text){
  const t=clean(text,9000);
  if(!t)return null;
  const patterns=[/(?:price|pricing|fee|cost|rate|charge)[^\d$]{0,30}(?:usd|usdc|\$)\s*([0-9]+(?:[.,][0-9]{1,2})?)/i,/(?:usd|usdc|\$)\s*([0-9]+(?:[.,][0-9]{1,2})?)/i,/([0-9]+(?:[.,][0-9]{1,2})?)\s*(?:usd|usdc)\b/i];
  for(const p of patterns){const m=t.match(p);if(m){const n=Number(String(m[1]).replace(",","."));if(Number.isFinite(n)&&n>=0&&n<=1000000)return n;}}
  return null;
}
function etaFromText(text){
  const t=clean(text,9000);if(!t)return null;
  let m=t.match(/(?:within|eta|delivery|deliver|turnaround|ready in|available in)?[^0-9]{0,20}([0-9]+(?:\.[0-9]+)?)\s*(hours?|hrs?|h)\b/i);if(m){const n=Number(m[1]);if(Number.isFinite(n)&&n>0&&n<=8760)return n;}
  m=t.match(/(?:within|eta|delivery|deliver|turnaround|ready in|available in)?[^0-9]{0,20}([0-9]+(?:\.[0-9]+)?)\s*(days?|d)\b/i);if(m){const n=Number(m[1])*24;if(Number.isFinite(n)&&n>0&&n<=8760)return n;}
  return null;
}

async function ingestRecruitmentTerms(env){
  if(!(await ensure(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  let rows=[];try{const r=await env.DB.prepare("SELECT partner_id,response_text,response_class,stage,updated_at FROM lumen_partner_recruitment WHERE response_text IS NOT NULL AND TRIM(response_text)<>'' ORDER BY updated_at DESC LIMIT 100").all();rows=r.results||[];}catch{return{ok:true,version:VERSION,ingested:0,reason:"recruitment_table_unavailable"};}
  let ingested=0;const now=new Date().toISOString();
  for(const r of rows){const price=priceFromText(r.response_text),eta=etaFromText(r.response_text);if(price==null&&eta==null)continue;const id=`NGT-${(await sha256(`${r.partner_id}|recruitment`)).slice(0,18).toUpperCase()}`;
    await env.DB.prepare("INSERT INTO lumen_negotiation_terms(id,partner_id,opportunity_id,source,created_at,updated_at,price_usd,eta_hours,scope,terms_text,evidence,status,binding_allowed,spend_allowed) VALUES(?,?,NULL,'recruitment_response',?,?,?,?,NULL,?,?,'DECLARED_UNVERIFIED',0,0) ON CONFLICT(partner_id,opportunity_id,source) DO UPDATE SET updated_at=excluded.updated_at,price_usd=COALESCE(excluded.price_usd,lumen_negotiation_terms.price_usd),eta_hours=COALESCE(excluded.eta_hours,lumen_negotiation_terms.eta_hours),terms_text=excluded.terms_text,evidence=excluded.evidence,status='DECLARED_UNVERIFIED',binding_allowed=0,spend_allowed=0")
      .bind(id,r.partner_id,now,now,price,eta,clean(r.response_text,4500),`recruitment:${r.stage||"unknown"}/${r.response_class||"unknown"}`).run();ingested++;}
  return{ok:true,version:VERSION,ingested};
}

function blendQuality(row){
  const declared=clamp(row.declared_reputation||0),obs=clamp(row.observed_score||50),conf=clamp(row.observed_confidence||0);
  const observedWeight=conf>=30?Math.min(.6,.15+(conf/100)*.45):Math.min(.12,(conf/30)*.12);
  return Math.round(clamp(declared*(1-observedWeight)+obs*observedWeight));
}
function riskPenalty(row){let p=0;const level=clean(row.trust_level,30).toUpperCase();if(level==="CAUTION")p+=10;if(Number(row.trust_score||0)<70)p+=Math.round((70-Number(row.trust_score||0))*.25);if(Number(row.observed_confidence||0)>=30&&Number(row.observed_score||0)<45)p+=8;return Math.round(clamp(p,0,30));}
function relativeScore(value,min,max){if(value==null||!Number.isFinite(Number(value)))return 50;if(max<=min)return 80;return Math.round(clamp(100-((Number(value)-min)/(max-min))*70,30,100));}

async function sourceRows(env){
  const sql="SELECT o.id opportunity_id,o.name title,o.revenue_offer_id,a.commercial_score,m.partner_id,m.match_score,m.matched_capabilities_json,p.name partner_name,p.reputation_score declared_reputation,p.compatibility_score,t.trust_score,t.trust_level,t.auth_required,t.manipulation_hits,orx.score observed_score,COALESCE(orx.confidence,0) observed_confidence,orx.reliability_score,orx.responsiveness_score,nt.price_usd term_price_usd,nt.eta_hours term_eta_hours,nt.terms_text term_text,nt.source term_source FROM lumen_opportunities o JOIN lumen_opportunity_assessments a ON a.opportunity_id=o.id JOIN lumen_partner_matches m ON m.opportunity_id=o.id AND m.status IN ('candidate','quality_candidate') JOIN lumen_partner_agents p ON p.id=m.partner_id JOIN lumen_partner_trust t ON t.partner_id=p.id LEFT JOIN lumen_partner_observed_reputation orx ON orx.partner_id=p.id LEFT JOIN lumen_negotiation_terms nt ON nt.partner_id=p.id AND (nt.opportunity_id=o.id OR nt.opportunity_id IS NULL) WHERE a.commercially_actionable=1 AND a.synthetic_or_test_only=0 AND a.commercial_score>=60 AND m.match_score>=55 AND t.trust_level IN ('ALLOW','CAUTION') AND t.auth_required=0 AND t.manipulation_hits=0 ORDER BY a.commercial_score DESC,o.updated_at DESC,m.match_score DESC,t.trust_score DESC";
  try{const r=await env.DB.prepare(sql).all();return r.results||[];}catch{return[];}
}

export async function recomputeNegotiator(env){
  if(!(await ensure(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  await ingestRecruitmentTerms(env);
  const rows=await sourceRows(env);const grouped=new Map();for(const r of rows){if(!grouped.has(r.opportunity_id))grouped.set(r.opportunity_id,[]);const list=grouped.get(r.opportunity_id);if(!list.some(x=>x.partner_id===r.partner_id))list.push(r);}
  const outputs=[];const now=new Date().toISOString();
  for(const [oppId,candidates0] of [...grouped.entries()].slice(0,12)){
    const candidates=candidates0.slice(0,12);if(!candidates.length)continue;
    const caseId=`NEG-${(await sha256(oppId)).slice(0,18).toUpperCase()}`;
    const prices=candidates.map(x=>x.term_price_usd==null?null:Number(x.term_price_usd)).filter(Number.isFinite);const etas=candidates.map(x=>x.term_eta_hours==null?null:Number(x.term_eta_hours)).filter(x=>Number.isFinite(x)&&x>0);
    const minPrice=prices.length?Math.min(...prices):0,maxPrice=prices.length?Math.max(...prices):0,minEta=etas.length?Math.min(...etas):0,maxEta=etas.length?Math.max(...etas):0;
    const ranked=[];
    for(const c of candidates){const quality=blendQuality(c),priceScore=relativeScore(c.term_price_usd==null?null:Number(c.term_price_usd),minPrice,maxPrice),timeScore=relativeScore(c.term_eta_hours==null?null:Number(c.term_eta_hours),minEta,maxEta),risk=riskPenalty(c);
      const reliability=c.reliability_score==null?50:clamp(c.reliability_score),responsiveness=c.responsiveness_score==null?50:clamp(c.responsiveness_score);
      const total=Math.round(clamp(Number(c.match_score||0)*.25+Number(c.trust_score||0)*.18+quality*.22+reliability*.10+responsiveness*.08+priceScore*.10+timeScore*.07-risk));
      let completeness=45;if(c.term_price_usd!=null)completeness+=18;if(c.term_eta_hours!=null)completeness+=10;if(Number(c.observed_confidence||0)>=30)completeness+=15;if(Number(c.trust_score||0)>=70)completeness+=7;if(clean(c.term_text,200))completeness+=5;completeness=Math.round(clamp(completeness));
      const cid=`NEGC-${(await sha256(`${caseId}|${c.partner_id}`)).slice(0,18).toUpperCase()}`;const caps=parseJson(c.matched_capabilities_json,[]);
      await env.DB.prepare("INSERT INTO lumen_negotiation_candidates(id,case_id,partner_id,partner_name,capabilities_json,match_score,trust_score,trust_level,declared_reputation,compatibility_score,observed_score,observed_confidence,reliability_score,responsiveness_score,declared_price_usd,price_source,eta_hours,terms_text,quality_score,price_score,time_score,risk_penalty,total_score,data_completeness,status,updated_at,raw_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(case_id,partner_id) DO UPDATE SET partner_name=excluded.partner_name,capabilities_json=excluded.capabilities_json,match_score=excluded.match_score,trust_score=excluded.trust_score,trust_level=excluded.trust_level,declared_reputation=excluded.declared_reputation,compatibility_score=excluded.compatibility_score,observed_score=excluded.observed_score,observed_confidence=excluded.observed_confidence,reliability_score=excluded.reliability_score,responsiveness_score=excluded.responsiveness_score,declared_price_usd=excluded.declared_price_usd,price_source=excluded.price_source,eta_hours=excluded.eta_hours,terms_text=excluded.terms_text,quality_score=excluded.quality_score,price_score=excluded.price_score,time_score=excluded.time_score,risk_penalty=excluded.risk_penalty,total_score=excluded.total_score,data_completeness=excluded.data_completeness,status=excluded.status,updated_at=excluded.updated_at,raw_json=excluded.raw_json")
        .bind(cid,caseId,c.partner_id,c.partner_name,JSON.stringify(caps),Number(c.match_score||0),Number(c.trust_score||0),clean(c.trust_level,30),Number(c.declared_reputation||0),Number(c.compatibility_score||0),c.observed_score==null?null:Number(c.observed_score),Number(c.observed_confidence||0),c.reliability_score==null?null:Number(c.reliability_score),c.responsiveness_score==null?null:Number(c.responsiveness_score),c.term_price_usd==null?null:Number(c.term_price_usd),c.term_source||null,c.term_eta_hours==null?null:Number(c.term_eta_hours),clean(c.term_text,4000)||null,quality,priceScore,timeScore,risk,total,completeness,"RANKED",now,JSON.stringify({priceVerified:false,termsBinding:false}).slice(0,2000)).run();
      ranked.push({partnerId:c.partner_id,name:c.partner_name,totalScore:total,dataCompleteness:completeness,matchScore:Number(c.match_score||0),trust:{level:c.trust_level,score:Number(c.trust_score||0)},qualityScore:quality,observedConfidence:Number(c.observed_confidence||0),declaredPriceUsd:c.term_price_usd==null?null:Number(c.term_price_usd),etaHours:c.term_eta_hours==null?null:Number(c.term_eta_hours),priceVerified:false,riskPenalty:risk});
    }
    ranked.sort((a,b)=>b.totalScore-a.totalScore||b.dataCompleteness-a.dataCompleteness);
    const top=ranked[0],priced=ranked.filter(x=>x.declaredPriceUsd!=null).length,timed=ranked.filter(x=>x.etaHours!=null).length;
    const commercialComparable=ranked.length>=2&&priced>=2;const confidence=Math.round(clamp((ranked.length>=2?25:8)+(priced>=2?30:priced===1?12:0)+(timed>=2?12:timed===1?5:0)+Math.min(25,ranked.reduce((a,x)=>a+x.dataCompleteness,0)/Math.max(1,ranked.length)*.25)+(top?.trust?.level==="ALLOW"?8:3)));
    const status=commercialComparable&&top.totalScore>=65?"READY_FOR_HUMAN_REVIEW":ranked.length>=2?"RANKED_INCOMPLETE_TERMS":"INSUFFICIENT_COMPETITION";
    const mode=commercialComparable?"COMMERCIAL_COMPARISON":"TECHNICAL_RANKING_ONLY";
    const required=[...new Set(ranked.flatMap(x=>{const src=candidates.find(c=>c.partner_id===x.partnerId);return parseJson(src?.matched_capabilities_json,[]);} ))];
    await env.DB.prepare("INSERT INTO lumen_negotiation_cases(id,opportunity_id,created_at,updated_at,status,title,commercial_score,offer_id,required_capabilities_json,candidate_count,priced_candidate_count,timed_candidate_count,recommended_partner_id,recommended_partner_name,recommendation_score,recommendation_confidence,decision_mode,binding_allowed,spend_allowed,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0,?) ON CONFLICT(opportunity_id) DO UPDATE SET updated_at=excluded.updated_at,status=excluded.status,title=excluded.title,commercial_score=excluded.commercial_score,offer_id=excluded.offer_id,required_capabilities_json=excluded.required_capabilities_json,candidate_count=excluded.candidate_count,priced_candidate_count=excluded.priced_candidate_count,timed_candidate_count=excluded.timed_candidate_count,recommended_partner_id=excluded.recommended_partner_id,recommended_partner_name=excluded.recommended_partner_name,recommendation_score=excluded.recommendation_score,recommendation_confidence=excluded.recommendation_confidence,decision_mode=excluded.decision_mode,binding_allowed=0,spend_allowed=0,engine_version=excluded.engine_version")
      .bind(caseId,oppId,now,now,status,clean(candidates[0].title,300),Number(candidates[0].commercial_score||0),candidates[0].revenue_offer_id||null,JSON.stringify(required),ranked.length,priced,timed,top?.partnerId||null,top?.name||null,top?.totalScore||null,confidence,mode,VERSION).run();
    outputs.push({caseId,opportunityId:oppId,title:candidates[0].title,status,decisionMode:mode,candidates:ranked.length,pricedCandidates:priced,timedCandidates:timed,recommendationConfidence:confidence,recommended:top||null,ranking:ranked.slice(0,5)});
  }
  return{ok:true,version:VERSION,cases:outputs.length,readyForHumanReview:outputs.filter(x=>x.status==="READY_FOR_HUMAN_REVIEW").length,incompleteTerms:outputs.filter(x=>x.status==="RANKED_INCOMPLETE_TERMS").length,insufficientCompetition:outputs.filter(x=>x.status==="INSUFFICIENT_COMPETITION").length,topCases:outputs.slice(0,8),guardrails:{recommendationOnly:true,pricesDeclaredNotVerified:true,autonomousNegotiationMessages:false,autonomousHiring:false,autonomousSpend:false,bindingActionsHumanGated:true}};
}

async function stats(env){await ensure(env);const r=await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN status='READY_FOR_HUMAN_REVIEW' THEN 1 ELSE 0 END) ready,SUM(CASE WHEN status='RANKED_INCOMPLETE_TERMS' THEN 1 ELSE 0 END) incomplete,SUM(CASE WHEN status='INSUFFICIENT_COMPETITION' THEN 1 ELSE 0 END) insufficient,SUM(candidate_count) candidates,SUM(priced_candidate_count) priced,MAX(recommendation_confidence) max_confidence FROM lumen_negotiation_cases").first();return json({version:VERSION,totalCases:Number(r?.total||0),readyForHumanReview:Number(r?.ready||0),incompleteTerms:Number(r?.incomplete||0),insufficientCompetition:Number(r?.insufficient||0),rankedCandidates:Number(r?.candidates||0),pricedCandidates:Number(r?.priced||0),maxRecommendationConfidence:Number(r?.max_confidence||0),recommendationOnly:true,autonomousNegotiationMessages:false,autonomousHiring:false,autonomousSpend:false,bindingActionsHumanGated:true});}

async function policy(){return json({version:VERSION,name:"LUMEN Partner Negotiator",mode:"non_binding_recommendation",weights:{match:25,trust:18,quality:22,reliability:10,responsiveness:8,price:10,time:7,riskPenalty:"0..30"},pricePolicy:"declared_terms_are_unverified_until_independently_confirmed",unknownPricePolicy:"unknown_price_is_neutral_not_invented_and_prevents_full_commercial_confidence",recommendationGate:"commercial recommendation needs >=2 candidates and >=2 comparable declared prices; any hire/spend/contract remains human-gated",autonomousNegotiationMessages:false,autonomousHiring:false,autonomousSpend:false,bindingActionsHumanGated:true});}

export async function handlePartnerNegotiator(request,env){const u=new URL(request.url);if(request.method==="GET"&&u.pathname==="/negotiator/policy")return policy();if(request.method==="GET"&&u.pathname==="/negotiator/stats")return stats(env);if(request.method==="POST"&&u.pathname==="/negotiator/recompute"){if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);return json(await recomputeNegotiator(env),202);}if(request.method==="GET"&&u.pathname==="/negotiator/cases"){if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);await ensure(env);const c=await env.DB.prepare("SELECT * FROM lumen_negotiation_cases ORDER BY commercial_score DESC,updated_at DESC LIMIT 50").all();const out=[];for(const x of c.results||[]){const r=await env.DB.prepare("SELECT partner_id,partner_name,capabilities_json,match_score,trust_score,trust_level,declared_reputation,compatibility_score,observed_score,observed_confidence,reliability_score,responsiveness_score,declared_price_usd,price_source,eta_hours,quality_score,price_score,time_score,risk_penalty,total_score,data_completeness,status FROM lumen_negotiation_candidates WHERE case_id=? ORDER BY total_score DESC,data_completeness DESC LIMIT 20").bind(x.id).all();out.push({...x,candidates:r.results||[]});}return json({version:VERSION,cases:out});}return null;}
