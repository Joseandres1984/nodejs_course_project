const VERSION="1.0-partner-marketplace";
const LUMEN_CAPABILITIES=[
  {id:"verification",name:"Evidence & Supplier Verification",description:"Evidence-backed verification, supplier snapshots and trust checks."},
  {id:"sourcing",name:"B2B Sourcing",description:"Supplier discovery, shortlist generation and sourcing analysis."},
  {id:"research",name:"Commercial Research",description:"Evidence-backed market, company and opportunity research."},
  {id:"pricing",name:"Quote & Price Reasonableness",description:"Pricing signals, quote sanity and commercial reasonableness analysis."},
  {id:"tender",name:"Tender / RFQ Analysis",description:"Tender and RFQ requirement extraction, risk review and opportunity scans."},
  {id:"sales",name:"Buyer Signal Analysis",description:"Buyer-intent, demand and commercial-path analysis."},
  {id:"export",name:"Export Opportunity Research",description:"Export market, distributor and trade opportunity research."},
  {id:"automation",name:"Agentic Workflow Orchestration",description:"Safe multi-agent coordination, evidence gates and workflow design."}
];
function json(d,s=200){return Response.json(d,{status:s,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function clean(v,n=4000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}
function authorized(r,e){const a=clean(e?.OPPORTUNITY_ADMIN_TOKEN,500),b=clean(r.headers.get("x-lumen-admin"),500);return Boolean(a&&b&&a===b);}
function isSafeHttps(v){try{const u=new URL(v);if(u.protocol!=="https:")return false;const h=u.hostname.toLowerCase();if(h==="localhost"||h.endsWith(".local")||/^127\./.test(h)||/^10\./.test(h)||/^192\.168\./.test(h)||/^169\.254\./.test(h))return false;const m=h.match(/^172\.(\d+)\./);if(m&&Number(m[1])>=16&&Number(m[1])<=31)return false;return true;}catch{return false;}}
function parseArray(v){if(Array.isArray(v))return v;try{const x=JSON.parse(v||"[]");return Array.isArray(x)?x:[];}catch{return[];}}
async function bodyJson(r){try{return await r.json();}catch{return{};}}

async function ensure(env){
  if(!env?.DB)return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_partner_marketplace_needs (id TEXT PRIMARY KEY,source_gap_id TEXT NOT NULL UNIQUE,source_type TEXT NOT NULL,source_id TEXT NOT NULL,capability TEXT NOT NULL,priority INTEGER NOT NULL,status TEXT NOT NULL,title TEXT NOT NULL,description TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,binding_allowed INTEGER NOT NULL DEFAULT 0,spend_allowed INTEGER NOT NULL DEFAULT 0,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_marketplace_needs ON lumen_partner_marketplace_needs(status,priority DESC,updated_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_partner_marketplace_interests (id TEXT PRIMARY KEY,need_id TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,agent_name TEXT NOT NULL,agent_card_url TEXT NOT NULL,endpoint TEXT,claimed_capabilities_json TEXT NOT NULL,note TEXT,status TEXT NOT NULL,matched_partner_id TEXT,trust_score INTEGER,trust_level TEXT,match_score INTEGER,external_contact_sent INTEGER NOT NULL DEFAULT 0,binding_allowed INTEGER NOT NULL DEFAULT 0,spend_allowed INTEGER NOT NULL DEFAULT 0,UNIQUE(need_id,agent_card_url))"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_marketplace_interest_status ON lumen_partner_marketplace_interests(status,updated_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_partner_marketplace_events (id TEXT PRIMARY KEY,created_at TEXT NOT NULL,event_type TEXT NOT NULL,need_id TEXT,interest_id TEXT,detail TEXT)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_marketplace_events ON lumen_partner_marketplace_events(created_at,event_type)")
  ]);
  return true;
}

async function logEvent(env,eventType,needId=null,interestId=null,detail=""){
  const id=`PME-${crypto.randomUUID().replaceAll('-','').slice(0,18).toUpperCase()}`;
  await env.DB.prepare("INSERT INTO lumen_partner_marketplace_events(id,created_at,event_type,need_id,interest_id,detail) VALUES(?,?,?,?,?,?)")
    .bind(id,new Date().toISOString(),clean(eventType,100),needId,interestId,clean(detail,3000)||null).run();
}

function needDescription(row){
  const cap=clean(row.capability,80);
  return `LUMEN is looking for a non-binding collaboration candidate with the '${cap}' capability for an active internal need. Priority ${Number(row.priority||0)}/100. This listing is exploratory only and does not create a contract, purchase, payment promise, exclusivity, employment relationship or delegation authority.`;
}

export async function syncPartnerMarketplace(env){
  if(!(await ensure(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  let gaps=[];try{const r=await env.DB.prepare("SELECT * FROM lumen_capability_gap_queue WHERE status IN ('OPEN','WEAK_COVERAGE') AND priority>=60 ORDER BY priority DESC,updated_at DESC LIMIT 80").all();gaps=r.results||[];}catch{return{ok:false,error:"capability_gap_queue_not_ready",version:VERSION};}
  const now=new Date().toISOString(),seen=new Set(),published=[];
  for(const g of gaps){
    const id=`PMN-${g.id}`.slice(0,230);seen.add(id);
    const title=`Partner needed: ${clean(g.capability,80)}`;
    await env.DB.prepare("INSERT INTO lumen_partner_marketplace_needs(id,source_gap_id,source_type,source_id,capability,priority,status,title,description,created_at,updated_at,binding_allowed,spend_allowed,engine_version) VALUES(?,?,?,?,?,?,'OPEN',?,?, ?,?,0,0,?) ON CONFLICT(source_gap_id) DO UPDATE SET priority=excluded.priority,status='OPEN',title=excluded.title,description=excluded.description,updated_at=excluded.updated_at,engine_version=excluded.engine_version")
      .bind(id,g.id,g.source_type,g.source_id,clean(g.capability,80),Number(g.priority||0),title,needDescription(g),now,now,VERSION).run();
    published.push({id,capability:g.capability,priority:Number(g.priority||0),sourceType:g.source_type});
  }
  const all=await env.DB.prepare("SELECT id FROM lumen_partner_marketplace_needs WHERE status='OPEN'").all();
  for(const x of all.results||[])if(!seen.has(x.id))await env.DB.prepare("UPDATE lumen_partner_marketplace_needs SET status='CLOSED_COVERED_OR_STALE',updated_at=? WHERE id=?").bind(now,x.id).run();
  return{ok:true,version:VERSION,openNeeds:published.length,published:published.slice(0,20),guardrails:{publicListingsNonBinding:true,autonomousSpend:false,autonomousHiring:false,externalContactSent:false}};
}

export async function submitMarketplaceInterest(env,body={}){
  if(!(await ensure(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  const needId=clean(body?.needId||body?.need_id,230),name=clean(body?.agentName||body?.agent_name,220),card=clean(body?.agentCardUrl||body?.agent_card_url,2000),endpoint=clean(body?.endpoint,2000),note=clean(body?.note,2200);
  const caps=parseArray(body?.capabilities||body?.claimedCapabilities).map(x=>clean(x,80).toLowerCase()).filter(Boolean).slice(0,20);
  if(!needId||!name||!card)return{ok:false,error:"needId_agentName_agentCardUrl_required",version:VERSION};
  if(!isSafeHttps(card))return{ok:false,error:"agent_card_url_must_be_safe_public_https",version:VERSION};
  if(endpoint&&!isSafeHttps(endpoint))return{ok:false,error:"endpoint_must_be_safe_public_https",version:VERSION};
  const need=await env.DB.prepare("SELECT id,capability,status FROM lumen_partner_marketplace_needs WHERE id=? LIMIT 1").bind(needId).first();
  if(!need||need.status!=="OPEN")return{ok:false,error:"marketplace_need_not_open",version:VERSION};
  const id=`PMI-${crypto.randomUUID().replaceAll('-','').slice(0,18).toUpperCase()}`,now=new Date().toISOString();
  try{
    await env.DB.prepare("INSERT INTO lumen_partner_marketplace_interests(id,need_id,created_at,updated_at,agent_name,agent_card_url,endpoint,claimed_capabilities_json,note,status,matched_partner_id,trust_score,trust_level,match_score,external_contact_sent,binding_allowed,spend_allowed) VALUES(?,?,?,?,?,?,?,?,?,'PENDING_TRUST',NULL,NULL,NULL,NULL,0,0,0)")
      .bind(id,needId,now,now,name,card,endpoint||null,JSON.stringify(caps),note||null).run();
  }catch(e){
    if(String(e?.message||e).toLowerCase().includes("unique"))return{ok:true,accepted:false,reason:"duplicate_interest",version:VERSION};
    return{ok:false,error:"interest_persistence_failed",version:VERSION};
  }
  await logEvent(env,"INTEREST_RECEIVED",needId,id,`capability=${need.capability}`);
  return{ok:true,accepted:true,version:VERSION,interestId:id,status:"PENDING_TRUST",needId,capability:need.capability,guardrails:{nonBinding:true,noPaymentPromise:true,noContract:true,noAutomaticContact:true}};
}

export async function reviewMarketplaceInterests(env){
  if(!(await ensure(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  const rows=await env.DB.prepare("SELECT i.*,n.capability,n.priority FROM lumen_partner_marketplace_interests i JOIN lumen_partner_marketplace_needs n ON n.id=i.need_id WHERE i.status IN ('PENDING_TRUST','PENDING_DISCOVERY') ORDER BY n.priority DESC,i.created_at ASC LIMIT 80").all();
  const results=[];const now=new Date().toISOString();
  for(const i of rows.results||[]){
    let partner=null;try{partner=await env.DB.prepare("SELECT id,name,capabilities_json FROM lumen_partner_agents WHERE card_url=? OR endpoint=? LIMIT 1").bind(i.agent_card_url,i.endpoint||i.agent_card_url).first();}catch{}
    if(!partner){await env.DB.prepare("UPDATE lumen_partner_marketplace_interests SET status='PENDING_DISCOVERY',updated_at=? WHERE id=?").bind(now,i.id).run();results.push({interestId:i.id,status:"PENDING_DISCOVERY"});continue;}
    let trust=null;try{trust=await env.DB.prepare("SELECT trust_score,trust_level,auth_required,manipulation_hits FROM lumen_partner_trust WHERE partner_id=? LIMIT 1").bind(partner.id).first();}catch{}
    if(!trust){await env.DB.prepare("UPDATE lumen_partner_marketplace_interests SET status='PENDING_TRUST',matched_partner_id=?,updated_at=? WHERE id=?").bind(partner.id,now,i.id).run();results.push({interestId:i.id,status:"PENDING_TRUST",partnerId:partner.id});continue;}
    const level=clean(trust.trust_level,40).toUpperCase(),score=Number(trust.trust_score||0),hard=Number(trust.auth_required||0)===1||Number(trust.manipulation_hits||0)>0||["RESTRICTED","QUARANTINE"].includes(level);
    const caps=new Set(parseArray(partner.capabilities_json).map(x=>clean(x,80).toLowerCase()));
    const capabilityFit=caps.has(clean(i.capability,80).toLowerCase())?100:0;
    const match=Math.round(Math.min(100,capabilityFit*.55+score*.35+Math.min(100,Number(i.priority||0))*.10));
    const status=hard?"BLOCKED_TRUST":((level==="ALLOW"||level==="CAUTION")&&capabilityFit===100?"MATCH_CANDIDATE":"NO_CAPABILITY_MATCH");
    await env.DB.prepare("UPDATE lumen_partner_marketplace_interests SET status=?,matched_partner_id=?,trust_score=?,trust_level=?,match_score=?,updated_at=? WHERE id=?")
      .bind(status,partner.id,score,level,match,now,i.id).run();
    await logEvent(env,`INTEREST_${status}`,i.need_id,i.id,`partner=${partner.name};score=${match};trust=${level}/${score}`);
    results.push({interestId:i.id,status,partnerId:partner.id,partnerName:partner.name,matchScore:match,trustLevel:level,trustScore:score});
  }
  return{ok:true,version:VERSION,reviewed:results.length,results,guardrails:{automaticHiring:false,automaticContract:false,automaticPayment:false,externalContactSent:false}};
}

async function catalog(env){
  await ensure(env);
  const r=await env.DB.prepare("SELECT id,capability,priority,title,description,updated_at FROM lumen_partner_marketplace_needs WHERE status='OPEN' ORDER BY priority DESC,updated_at DESC LIMIT 50").all();
  return json({version:VERSION,marketplace:"LUMEN Partner Marketplace",mode:"non_binding_discovery",lumenOffers:LUMEN_CAPABILITIES,openPartnerNeeds:r.results||[],interestEndpoint:"/partner-marketplace/interest",rules:["public_https_agent_card_required","all_interest_is_non_binding","trust_review_required","no_payment_or_contract_created","no_secret_or_credential_submission"],autonomousSpend:false,bindingActionsHumanGated:true});
}

async function stats(env){
  await ensure(env);const n=await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN status='OPEN' THEN 1 ELSE 0 END) open FROM lumen_partner_marketplace_needs").first(),i=await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN status='MATCH_CANDIDATE' THEN 1 ELSE 0 END) candidates,SUM(CASE WHEN status='PENDING_TRUST' THEN 1 ELSE 0 END) pendingTrust,SUM(CASE WHEN status='PENDING_DISCOVERY' THEN 1 ELSE 0 END) pendingDiscovery,SUM(CASE WHEN status='BLOCKED_TRUST' THEN 1 ELSE 0 END) blocked FROM lumen_partner_marketplace_interests").first();
  return json({version:VERSION,needs:{total:Number(n?.total||0),open:Number(n?.open||0)},interests:{total:Number(i?.total||0),matchCandidates:Number(i?.candidates||0),pendingTrust:Number(i?.pendingTrust||0),pendingDiscovery:Number(i?.pendingDiscovery||0),blockedTrust:Number(i?.blocked||0)},publicInboundInterest:true,trustReviewRequired:true,autonomousHiring:false,autonomousSpend:false,bindingActionsHumanGated:true});
}

export async function handlePartnerMarketplace(request,env){
  const u=new URL(request.url);
  if(request.method==="GET"&&u.pathname==="/partner-marketplace/catalog")return catalog(env);
  if(request.method==="GET"&&u.pathname==="/partner-marketplace/stats")return stats(env);
  if(request.method==="POST"&&u.pathname==="/partner-marketplace/interest")return json(await submitMarketplaceInterest(env,await bodyJson(request)),202);
  if(request.method==="POST"&&u.pathname==="/partner-marketplace/sync"){if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);return json(await syncPartnerMarketplace(env),202);}
  if(request.method==="POST"&&u.pathname==="/partner-marketplace/review"){if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);return json(await reviewMarketplaceInterests(env),202);}
  if(request.method==="GET"&&u.pathname==="/partner-marketplace/interests"){if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);await ensure(env);const r=await env.DB.prepare("SELECT * FROM lumen_partner_marketplace_interests ORDER BY updated_at DESC LIMIT 100").all();return json({version:VERSION,interests:r.results||[]});}
  return null;
}
