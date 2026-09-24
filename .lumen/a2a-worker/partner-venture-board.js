const VERSION = "1.0-partner-venture-board";

function json(data,status=200){return Response.json(data,{status,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function clean(v,n=4000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}
function arr(v){return Array.isArray(v)?v:v==null?[]:[v];}
function clamp(n,min=0,max=100){return Math.max(min,Math.min(max,Number(n)||0));}
function authorized(request,env){const a=clean(env?.OPPORTUNITY_ADMIN_TOKEN,500),b=clean(request.headers.get("x-lumen-admin"),500);return Boolean(a&&b&&a===b);}
async function bodyJson(request){try{return await request.json();}catch{return{};}}

async function ensureSchema(env){
  if(!env?.DB)return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_partner_ideas (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, partner_id TEXT, council_id TEXT, opportunity_id TEXT, title TEXT NOT NULL, summary TEXT NOT NULL, customer_signal TEXT, revenue_model TEXT, evidence TEXT, required_capabilities_json TEXT NOT NULL, estimated_revenue_usd REAL, estimated_cost_usd REAL, revenue_confidence TEXT NOT NULL DEFAULT 'unverified', commercial_score INTEGER NOT NULL, feasibility_score INTEGER NOT NULL, network_synergy_score INTEGER NOT NULL, evidence_score INTEGER NOT NULL, total_score INTEGER NOT NULL, status TEXT NOT NULL, binding_allowed INTEGER NOT NULL DEFAULT 0, spend_allowed INTEGER NOT NULL DEFAULT 0, raw_json TEXT)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_partner_ideas_rank ON lumen_partner_ideas(status,total_score,created_at)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_partner_ideas_partner ON lumen_partner_ideas(partner_id,created_at)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_partner_ideas_council ON lumen_partner_ideas(council_id,created_at)")
  ]);
  return true;
}

function scoreIdea(body){
  const title=clean(body?.title,220);
  const summary=clean(body?.summary||body?.idea,3000);
  const customer=clean(body?.customerSignal||body?.customer_signal,1600);
  const revenue=clean(body?.revenueModel||body?.revenue_model,1600);
  const evidence=clean(body?.evidence,2400);
  const caps=arr(body?.requiredCapabilities||body?.required_capabilities).map(x=>clean(x,80)).filter(Boolean).slice(0,12);
  const estimatedRevenue=Number(body?.estimatedRevenueUsd??body?.estimated_revenue_usd??0)||0;
  const estimatedCost=Number(body?.estimatedCostUsd??body?.estimated_cost_usd??0)||0;

  let commercial=15;
  if(customer)commercial+=20;
  if(revenue)commercial+=20;
  if(/buyer|customer|client|demand|rfq|procurement|need|purchase|paid|subscription|commission|fee|revenue/i.test(`${customer} ${revenue} ${summary}`))commercial+=20;
  if(estimatedRevenue>0)commercial+=10;
  if(title&&summary.length>=80)commercial+=10;
  commercial=clamp(commercial);

  let feasibility=20;
  if(caps.length)feasibility+=20;
  if(caps.length<=5)feasibility+=10;
  if(estimatedCost===0)feasibility+=15;
  else if(estimatedRevenue>0&&estimatedCost<estimatedRevenue)feasibility+=10;
  if(/api|a2a|agent|automation|data|research|sourcing|verification|pricing|sales/i.test(summary))feasibility+=15;
  feasibility=clamp(feasibility);

  let synergy=15;
  const known=["sourcing","verification","pricing","research","logistics","export","sales","tender","payments","automation"];
  const knownHits=caps.filter(x=>known.includes(x.toLowerCase())).length;
  synergy+=Math.min(45,knownHits*10);
  if(caps.length>=2)synergy+=15;
  if(clean(body?.partnerId||body?.partner_id,120))synergy+=10;
  synergy=clamp(synergy);

  let evidenceScore=10;
  if(evidence)evidenceScore+=30;
  if(/https?:\/\//i.test(evidence))evidenceScore+=20;
  if(customer)evidenceScore+=15;
  if(/observed|verified|source|registry|request|signal|lead|inquiry/i.test(`${evidence} ${customer}`))evidenceScore+=15;
  evidenceScore=clamp(evidenceScore);

  const total=Math.round(commercial*.35+feasibility*.25+synergy*.20+evidenceScore*.20);
  const status=total>=78?"HIGH_POTENTIAL":total>=60?"REVIEW":total>=45?"WATCH":"LOW_SIGNAL";
  return {title,summary,customer,revenue,evidence,caps,estimatedRevenue,estimatedCost,commercial,feasibility,synergy,evidenceScore,total,status};
}

async function latestCouncil(env,councilId=""){
  if(councilId)return env.DB.prepare("SELECT * FROM lumen_partner_councils WHERE id=? LIMIT 1").bind(councilId).first();
  return env.DB.prepare("SELECT * FROM lumen_partner_councils WHERE status='DRAFT_COUNCIL' ORDER BY created_at DESC LIMIT 1").first();
}

export async function ventureAgenda(env,councilId=""){
  await ensureSchema(env);
  const council=await latestCouncil(env,councilId);
  if(!council)return{ok:false,error:"council_not_found",version:VERSION};
  let members=[];try{members=JSON.parse(council.members_json||"[]");}catch{}
  const contributors=members.filter(x=>x?.id&&x.id!=="LUMEN");
  return{
    ok:true,version:VERSION,councilId:council.id,opportunityId:council.opportunity_id,
    agenda:{
      section:"opportunity_round",
      purpose:"Ask every partner to contribute business ideas, unmet demand, market opportunities, new services, referrals, or useful agent combinations.",
      prompt:"Propose up to 2 concrete non-binding business opportunities. For each: problem/customer signal, proposed solution, revenue model, evidence, capabilities/agents needed, estimated upside if known, and main risks. Distinguish observed evidence from assumptions.",
      rules:["non_binding_only","no_spend_commitment","no_contract_commitment","evidence_over_hype","estimates_marked_unverified","human_gate_for_hiring_or_spend"]
    },
    contributors:contributors.map(x=>({partnerId:x.id,name:x.name,role:x.role}))
  };
}

export async function submitPartnerIdea(env,body={}){
  if(!(await ensureSchema(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  const scored=scoreIdea(body);
  if(!scored.title||!scored.summary)return{ok:false,error:"title_and_summary_required",version:VERSION};
  const now=new Date().toISOString();
  const id=`IDEA-${crypto.randomUUID().replaceAll("-","").slice(0,14).toUpperCase()}`;
  const partnerId=clean(body?.partnerId||body?.partner_id,180);
  const councilId=clean(body?.councilId||body?.council_id,180);
  const opportunityId=clean(body?.opportunityId||body?.opportunity_id,180);
  await env.DB.prepare("INSERT INTO lumen_partner_ideas(id,created_at,updated_at,partner_id,council_id,opportunity_id,title,summary,customer_signal,revenue_model,evidence,required_capabilities_json,estimated_revenue_usd,estimated_cost_usd,revenue_confidence,commercial_score,feasibility_score,network_synergy_score,evidence_score,total_score,status,binding_allowed,spend_allowed,raw_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0,?)")
    .bind(id,now,now,partnerId,councilId,opportunityId,scored.title,scored.summary,scored.customer,scored.revenue,scored.evidence,JSON.stringify(scored.caps),scored.estimatedRevenue,scored.estimatedCost,"unverified",scored.commercial,scored.feasibility,scored.synergy,scored.evidenceScore,scored.total,scored.status,JSON.stringify(body).slice(0,12000)).run();
  return{ok:true,version:VERSION,ideaId:id,status:scored.status,totalScore:scored.total,scores:{commercial:scored.commercial,feasibility:scored.feasibility,networkSynergy:scored.synergy,evidence:scored.evidenceScore},guardrails:{bindingAllowed:false,spendAllowed:false,estimatesVerified:false}};
}

async function topIdeas(env){
  if(!(await ensureSchema(env)))return{version:VERSION,ideas:[]};
  const r=await env.DB.prepare("SELECT id,partner_id,council_id,opportunity_id,title,summary,customer_signal,revenue_model,evidence,required_capabilities_json,estimated_revenue_usd,estimated_cost_usd,revenue_confidence,total_score,status,created_at FROM lumen_partner_ideas ORDER BY total_score DESC,created_at DESC LIMIT 25").all();
  return{version:VERSION,ideas:(r.results||[]).map(x=>{let caps=[];try{caps=JSON.parse(x.required_capabilities_json||"[]");}catch{}return{...x,requiredCapabilities:caps};})};
}

async function stats(env){
  if(!(await ensureSchema(env)))return{version:VERSION,total:0,highPotential:0,review:0};
  const row=await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN status='HIGH_POTENTIAL' THEN 1 ELSE 0 END) highPotential,SUM(CASE WHEN status='REVIEW' THEN 1 ELSE 0 END) review,COALESCE(MAX(total_score),0) bestScore FROM lumen_partner_ideas").first();
  return{version:VERSION,total:Number(row?.total||0),highPotential:Number(row?.highPotential||0),review:Number(row?.review||0),bestScore:Number(row?.bestScore||0),autonomousHiring:false,autonomousOutgoingSpend:false,bindingActionsHumanGated:true};
}

export async function handlePartnerVentureBoard(request,env){
  const url=new URL(request.url);
  if(request.method==="GET"&&url.pathname==="/partners/ideas/stats")return json(await stats(env));
  if(request.method==="GET"&&url.pathname==="/partners/ideas/top")return json(await topIdeas(env));
  if(request.method==="GET"&&url.pathname==="/partners/ideas/agenda")return json(await ventureAgenda(env,clean(url.searchParams.get("councilId"),180)));
  if(request.method==="POST"&&url.pathname==="/partners/ideas/submit"){
    if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);
    return json(await submitPartnerIdea(env,await bodyJson(request)),202);
  }
  return null;
}
