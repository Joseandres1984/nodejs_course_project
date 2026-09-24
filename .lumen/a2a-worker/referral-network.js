const VERSION="1.0-referral-network";

function json(d,s=200){return Response.json(d,{status:s,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function clean(v,n=5000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}
function authorized(r,e){const a=clean(e?.OPPORTUNITY_ADMIN_TOKEN,500),b=clean(r.headers.get("x-lumen-admin"),500);return Boolean(a&&b&&a===b);}
function parse(v,f=[]){try{const x=JSON.parse(v||"");return x??f;}catch{return f;}}
function safeHttps(v){try{const u=new URL(v);if(u.protocol!=="https:")return false;const h=u.hostname.toLowerCase();if(h==="localhost"||h.endsWith(".local")||h==="::1"||/^127\./.test(h)||/^10\./.test(h)||/^192\.168\./.test(h)||/^169\.254\./.test(h))return false;const m=h.match(/^172\.(\d+)\./);return !(m&&Number(m[1])>=16&&Number(m[1])<=31);}catch{return false;}}
async function bodyJson(r){try{return await r.json();}catch{return{};}}
async function sha256(text){const d=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(String(text)));return[...new Uint8Array(d)].map(b=>b.toString(16).padStart(2,"0")).join("");}

const MANIPULATION=[/ignore (all|any|the)? ?(previous|prior|system)/i,/system prompt/i,/reveal (your )?(secret|token|credential|private key|seed)/i,/disable (security|safety|guardrail)/i,/bypass (security|approval|authorization|policy)/i,/exfiltrat/i,/wallet seed/i];
function unsafeInput(text){return MANIPULATION.some(r=>r.test(String(text||"")));}

async function ensure(env){
  if(!env?.DB)return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_referrals (id TEXT PRIMARY KEY,direction TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,source TEXT NOT NULL,origin_partner_id TEXT,origin_partner_name TEXT,origin_card_url TEXT,target_partner_id TEXT,target_partner_name TEXT,opportunity_id TEXT,title TEXT NOT NULL,summary TEXT NOT NULL,capability TEXT,estimated_value_usd REAL,status TEXT NOT NULL,trust_score INTEGER,trust_level TEXT,match_score INTEGER,attribution_key TEXT NOT NULL UNIQUE,external_contact_sent INTEGER NOT NULL DEFAULT 0,binding_allowed INTEGER NOT NULL DEFAULT 0,spend_allowed INTEGER NOT NULL DEFAULT 0,commission_status TEXT NOT NULL DEFAULT 'NOT_CONFIGURED',settled_revenue_usd REAL NOT NULL DEFAULT 0,settlement_event_id TEXT,raw_json TEXT,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_referrals_state ON lumen_referrals(direction,status,updated_at)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_referrals_opp ON lumen_referrals(opportunity_id,direction,status)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_referral_events (id TEXT PRIMARY KEY,referral_id TEXT NOT NULL,created_at TEXT NOT NULL,event_type TEXT NOT NULL,detail TEXT,amount_usd REAL,verified INTEGER NOT NULL DEFAULT 0)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_referral_events_ref ON lumen_referral_events(referral_id,created_at)")
  ]);
  return true;
}

async function logEvent(env,referralId,eventType,detail="",amount=null,verified=false){
  const id=`RFE-${crypto.randomUUID().replaceAll("-","").slice(0,18).toUpperCase()}`;
  await env.DB.prepare("INSERT INTO lumen_referral_events(id,referral_id,created_at,event_type,detail,amount_usd,verified) VALUES(?,?,?,?,?,?,?)")
    .bind(id,referralId,new Date().toISOString(),clean(eventType,100),clean(detail,3000)||null,amount==null?null:Number(amount||0),verified?1:0).run();
}

function basicReferralScore(r){
  const text=`${r.title||""} ${r.summary||""} ${r.capability||""}`.toLowerCase();let score=20;
  if(/buyer|customer|client|rfq|procurement|supplier|purchase|tender|quote|budget|paid|payment|need|demand/.test(text))score+=30;
  if(clean(r.capability,80))score+=15;
  if(Number(r.estimatedValueUsd||0)>0)score+=10;
  if(clean(r.summary,4000).length>=100)score+=10;
  return Math.max(0,Math.min(100,score));
}

export async function submitInboundReferral(env,body={}){
  if(!(await ensure(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  const name=clean(body?.referrerName||body?.agentName,220),card=clean(body?.referrerCardUrl||body?.agentCardUrl,2000),title=clean(body?.title,300),summary=clean(body?.summary||body?.opportunity,4500),capability=clean(body?.capability,80).toLowerCase(),evidence=clean(body?.evidence,2500),estimatedValue=Math.max(0,Number(body?.estimatedValueUsd||0)||0);
  if(!name||!card||!title||!summary)return{ok:false,error:"referrerName_referrerCardUrl_title_summary_required",version:VERSION};
  if(!safeHttps(card))return{ok:false,error:"referrer_card_must_be_safe_public_https",version:VERSION};
  if(unsafeInput(`${title} ${summary} ${evidence}`))return{ok:false,error:"unsafe_referral_content_rejected",version:VERSION};
  const key=(await sha256(`INBOUND|${card}|${title.toLowerCase()}|${summary.toLowerCase().slice(0,1200)}`)).slice(0,32).toUpperCase();
  const id=`REF-IN-${key.slice(0,16)}`,now=new Date().toISOString(),score=basicReferralScore({title,summary,capability,estimatedValueUsd:estimatedValue});
  try{
    await env.DB.prepare("INSERT INTO lumen_referrals(id,direction,created_at,updated_at,source,origin_partner_id,origin_partner_name,origin_card_url,target_partner_id,target_partner_name,opportunity_id,title,summary,capability,estimated_value_usd,status,trust_score,trust_level,match_score,attribution_key,external_contact_sent,binding_allowed,spend_allowed,commission_status,settled_revenue_usd,settlement_event_id,raw_json,engine_version) VALUES(?,'INBOUND',?,?,?,?,?,?,NULL,'LUMEN',NULL,?,?,?,?,'PENDING_DISCOVERY',NULL,NULL,?,?,0,0,0,'NOT_CONFIGURED',0,NULL,?,?)")
      .bind(id,now,now,"public_referral",null,name,card,title,summary,capability||null,estimatedValue,score,key,JSON.stringify({evidence,declared:body}).slice(0,12000),VERSION).run();
  }catch(e){if(String(e?.message||e).toLowerCase().includes("unique"))return{ok:true,accepted:false,reason:"duplicate_referral",version:VERSION};return{ok:false,error:"referral_persistence_failed",version:VERSION};}
  await logEvent(env,id,"INBOUND_RECEIVED",`declared_match_score=${score};commission=NOT_CONFIGURED`);
  return{ok:true,accepted:true,version:VERSION,referralId:id,status:"PENDING_DISCOVERY",attributionPreserved:true,declaredMatchScore:score,guardrails:{nonBinding:true,noPaymentPromise:true,commissionConfigured:false,noContract:true,noAutomaticContact:true}};
}

export async function reviewInboundReferrals(env){
  if(!(await ensure(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  const rows=await env.DB.prepare("SELECT * FROM lumen_referrals WHERE direction='INBOUND' AND status IN ('PENDING_DISCOVERY','PENDING_TRUST') ORDER BY created_at ASC LIMIT 60").all();
  const results=[],now=new Date().toISOString();
  for(const r of rows.results||[]){
    let p=null;try{p=await env.DB.prepare("SELECT id,name FROM lumen_partner_agents WHERE card_url=? OR endpoint=? LIMIT 1").bind(r.origin_card_url,r.origin_card_url).first();}catch{}
    if(!p){await env.DB.prepare("UPDATE lumen_referrals SET status='PENDING_DISCOVERY',updated_at=? WHERE id=?").bind(now,r.id).run();results.push({referralId:r.id,status:"PENDING_DISCOVERY"});continue;}
    let t=null;try{t=await env.DB.prepare("SELECT trust_score,trust_level,auth_required,manipulation_hits FROM lumen_partner_trust WHERE partner_id=? LIMIT 1").bind(p.id).first();}catch{}
    if(!t){await env.DB.prepare("UPDATE lumen_referrals SET origin_partner_id=?,origin_partner_name=?,status='PENDING_TRUST',updated_at=? WHERE id=?").bind(p.id,p.name,now,r.id).run();results.push({referralId:r.id,status:"PENDING_TRUST",partnerId:p.id});continue;}
    const level=clean(t.trust_level,40).toUpperCase(),score=Number(t.trust_score||0),hard=Number(t.auth_required||0)===1||Number(t.manipulation_hits||0)>0||["RESTRICTED","QUARANTINE"].includes(level);
    const status=hard?"BLOCKED_TRUST":(["ALLOW","CAUTION"].includes(level)?"INBOUND_TRUSTED":"PENDING_TRUST");
    await env.DB.prepare("UPDATE lumen_referrals SET origin_partner_id=?,origin_partner_name=?,trust_score=?,trust_level=?,status=?,updated_at=? WHERE id=?")
      .bind(p.id,p.name,score,level,status,now,r.id).run();
    await logEvent(env,r.id,status==="INBOUND_TRUSTED"?"TRUST_PASSED":"TRUST_REVIEW",`trust=${level}/${score};status=${status}`);
    results.push({referralId:r.id,status,partnerId:p.id,partnerName:p.name,trustLevel:level,trustScore:score});
  }
  return{ok:true,version:VERSION,reviewed:results.length,results,guardrails:{automaticAcceptance:false,automaticPayment:false,commissionConfigured:false,externalContactSent:false}};
}

export async function planOutboundReferrals(env){
  if(!(await ensure(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  let rows=[];
  try{
    const r=await env.DB.prepare("SELECT o.id opportunity_id,o.name title,o.description summary,o.revenue_offer_id,a.commercial_score,a.evidence_strength,m.partner_id,m.match_score,m.matched_capabilities_json,p.name partner_name,p.card_url,t.trust_score,t.trust_level,t.auth_required,t.manipulation_hits FROM lumen_opportunities o JOIN lumen_opportunity_assessments a ON a.opportunity_id=o.id JOIN lumen_partner_matches m ON m.opportunity_id=o.id AND m.status='candidate' JOIN lumen_partner_agents p ON p.id=m.partner_id JOIN lumen_partner_trust t ON t.partner_id=p.id WHERE a.commercially_actionable=1 AND a.synthetic_or_test_only=0 AND a.commercial_score>=60 AND m.match_score>=70 AND t.trust_level IN ('ALLOW','CAUTION') AND t.auth_required=0 AND t.manipulation_hits=0 ORDER BY a.commercial_score DESC,m.match_score DESC,t.trust_score DESC LIMIT 100").all();rows=r.results||[];
  }catch{return{ok:false,error:"referral_sources_not_ready",version:VERSION};}
  const best=new Map();for(const r of rows){if(!best.has(r.opportunity_id))best.set(r.opportunity_id,r);}
  const planned=[],now=new Date().toISOString();
  for(const r of best.values()){
    const caps=parse(r.matched_capabilities_json,[]),cap=clean(caps?.[0]||"specialist",80).toLowerCase();
    const key=(await sha256(`OUTBOUND|${r.opportunity_id}|${r.partner_id}`)).slice(0,32).toUpperCase(),id=`REF-OUT-${key.slice(0,16)}`;
    await env.DB.prepare("INSERT INTO lumen_referrals(id,direction,created_at,updated_at,source,origin_partner_id,origin_partner_name,origin_card_url,target_partner_id,target_partner_name,opportunity_id,title,summary,capability,estimated_value_usd,status,trust_score,trust_level,match_score,attribution_key,external_contact_sent,binding_allowed,spend_allowed,commission_status,settled_revenue_usd,settlement_event_id,raw_json,engine_version) VALUES(?,'OUTBOUND',?,?,?,NULL,'LUMEN',NULL,?,?,?,?,?,?,NULL,'OUTBOUND_CANDIDATE',?,?,?,?,0,0,0,'NOT_CONFIGURED',0,NULL,?,?) ON CONFLICT(attribution_key) DO UPDATE SET updated_at=excluded.updated_at,trust_score=excluded.trust_score,trust_level=excluded.trust_level,match_score=excluded.match_score,summary=excluded.summary,capability=excluded.capability,engine_version=excluded.engine_version")
      .bind(id,now,now,"commercial_opportunity",r.partner_id,r.partner_name,r.opportunity_id,clean(r.title,300),clean(r.summary,4500),cap,Number(r.trust_score||0),clean(r.trust_level,40),Number(r.match_score||0),key,JSON.stringify({commercialScore:Number(r.commercial_score||0),evidenceStrength:r.evidence_strength,offerId:r.revenue_offer_id}).slice(0,6000),VERSION).run();
    await logEvent(env,id,"OUTBOUND_CANDIDATE_PLANNED",`target=${r.partner_name};match=${Number(r.match_score||0)};trust=${r.trust_level}/${Number(r.trust_score||0)};commission=NOT_CONFIGURED`);
    planned.push({referralId:id,opportunityId:r.opportunity_id,title:r.title,targetPartnerId:r.partner_id,target:r.partner_name,capability:cap,commercialScore:Number(r.commercial_score||0),matchScore:Number(r.match_score||0),trustLevel:r.trust_level,trustScore:Number(r.trust_score||0)});
  }
  return{ok:true,version:VERSION,candidates:planned.length,referrals:planned.slice(0,25),guardrails:{outboundMessagesSent:0,automaticCommission:false,automaticPayment:false,bindingAllowed:false,autonomousSpend:false}};
}

export async function syncReferralSettlements(env){
  if(!(await ensure(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  const refs=await env.DB.prepare("SELECT id FROM lumen_referrals WHERE settled_revenue_usd=0 ORDER BY updated_at DESC LIMIT 200").all();const settled=[];
  for(const r of refs.results||[]){
    let e=null;try{e=await env.DB.prepare("SELECT id,amount_usd,evidence,metadata FROM lumen_revenue_events WHERE event_type='payment_settled' AND status='verified' AND (item_id=? OR metadata LIKE ?) ORDER BY created_at ASC LIMIT 1").bind(r.id,`%${r.id}%`).first();}catch{}
    if(!e)continue;const amount=Math.max(0,Number(e.amount_usd||0));
    await env.DB.prepare("UPDATE lumen_referrals SET status='SETTLED',settled_revenue_usd=?,settlement_event_id=?,updated_at=? WHERE id=?").bind(amount,e.id,new Date().toISOString(),r.id).run();
    await logEvent(env,r.id,"SETTLEMENT_VERIFIED",clean(e.evidence,1000),amount,true);settled.push({referralId:r.id,revenueEventId:e.id,settledRevenueUsd:amount});
  }
  return{ok:true,version:VERSION,settled:settled.length,results:settled,commissionStatus:"NOT_CONFIGURED",guardrails:{verifiedSettlementRequired:true,commissionNotPromised:true,automaticPayout:false}};
}

async function stats(env){
  await ensure(env);const r=await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN direction='INBOUND' THEN 1 ELSE 0 END) inbound,SUM(CASE WHEN direction='OUTBOUND' THEN 1 ELSE 0 END) outbound,SUM(CASE WHEN status='INBOUND_TRUSTED' THEN 1 ELSE 0 END) trustedInbound,SUM(CASE WHEN status='OUTBOUND_CANDIDATE' THEN 1 ELSE 0 END) outboundCandidates,SUM(CASE WHEN status='SETTLED' THEN 1 ELSE 0 END) settled,COALESCE(SUM(CASE WHEN status='SETTLED' THEN settled_revenue_usd ELSE 0 END),0) settledRevenue FROM lumen_referrals").first();
  return json({version:VERSION,total:Number(r?.total||0),inbound:Number(r?.inbound||0),outbound:Number(r?.outbound||0),trustedInbound:Number(r?.trustedInbound||0),outboundCandidates:Number(r?.outboundCandidates||0),settled:Number(r?.settled||0),settledRevenueUsd:Number(r?.settledRevenue||0),bidirectional:true,attributionPreserved:true,commissionStatus:"NOT_CONFIGURED",autonomousReferralMessages:false,autonomousPayout:false,autonomousSpend:false,bindingActionsHumanGated:true});
}

async function policy(){return json({version:VERSION,network:"LUMEN Referral Network",mode:"non_binding_attribution",directions:["INBOUND_TO_LUMEN","OUTBOUND_TO_PARTNER"],inboundEndpoint:"/referrals/inbound",states:["PENDING_DISCOVERY","PENDING_TRUST","INBOUND_TRUSTED","BLOCKED_TRUST","OUTBOUND_CANDIDATE","SETTLED"],rules:["public_https_referrer_card_required","trust_review_required","attribution_is_preserved","no_commission_is_promised","verified_payment_settlement_required_before_revenue_credit","no_contract_or_payment_created_by_referral"],commissionStatus:"NOT_CONFIGURED",autonomousReferralMessages:false,autonomousPayout:false,autonomousSpend:false,bindingActionsHumanGated:true});}

export async function handleReferralNetwork(request,env){
  const u=new URL(request.url);
  if(request.method==="GET"&&u.pathname==="/referrals/policy")return policy();
  if(request.method==="GET"&&u.pathname==="/referrals/stats")return stats(env);
  if(request.method==="POST"&&u.pathname==="/referrals/inbound")return json(await submitInboundReferral(env,await bodyJson(request)),202);
  if(request.method==="POST"&&u.pathname==="/referrals/review"){if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);return json(await reviewInboundReferrals(env),202);}
  if(request.method==="POST"&&u.pathname==="/referrals/plan-outbound"){if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);return json(await planOutboundReferrals(env),202);}
  if(request.method==="POST"&&u.pathname==="/referrals/settlements/sync"){if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);return json(await syncReferralSettlements(env),202);}
  if(request.method==="GET"&&u.pathname==="/referrals/ledger"){if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);await ensure(env);const r=await env.DB.prepare("SELECT * FROM lumen_referrals ORDER BY updated_at DESC LIMIT 150").all();return json({version:VERSION,referrals:r.results||[]});}
  return null;
}
