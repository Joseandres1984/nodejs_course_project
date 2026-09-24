const VERSION="1.0-revenue-attribution";

function json(d,s=200){return Response.json(d,{status:s,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function clean(v,n=5000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}
function authorized(r,e){const a=clean(e?.OPPORTUNITY_ADMIN_TOKEN,500),b=clean(r.headers.get("x-lumen-admin"),500);return Boolean(a&&b&&a===b);}
function parseObject(v){try{const x=typeof v==='string'?JSON.parse(v||'{}'):(v||{});return x&&typeof x==='object'&&!Array.isArray(x)?x:{};}catch{return{};}}
async function sha256(text){const d=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(String(text)));return[...new Uint8Array(d)].map(b=>b.toString(16).padStart(2,"0")).join("");}

async function ensure(env){
  if(!env?.DB)return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_revenue_attributions (id TEXT PRIMARY KEY,revenue_event_id TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,amount_usd REAL NOT NULL,item_id TEXT,source TEXT,attribution_status TEXT NOT NULL,confidence INTEGER NOT NULL DEFAULT 0,proposal_id TEXT,opportunity_id TEXT,offer_id TEXT,referral_id TEXT,origin_partner_id TEXT,origin_partner_name TEXT,evidence_json TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_revenue_attr_status ON lumen_revenue_attributions(attribution_status,created_at)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_revenue_attr_partner ON lumen_revenue_attributions(origin_partner_id,created_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_partner_commercial_value (partner_id TEXT PRIMARY KEY,partner_name TEXT,updated_at TEXT NOT NULL,verified_revenue_influenced_usd REAL NOT NULL DEFAULT 0,verified_settlements INTEGER NOT NULL DEFAULT 0,verified_referral_settlements INTEGER NOT NULL DEFAULT 0,commercial_value_score INTEGER NOT NULL DEFAULT 0,last_revenue_event_id TEXT,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_partner_commercial_value_score ON lumen_partner_commercial_value(commercial_value_score DESC,verified_revenue_influenced_usd DESC)")
  ]);
  return true;
}

async function safeFirst(env,sql,bind=[]){try{const s=env.DB.prepare(sql);return bind.length?await s.bind(...bind).first():await s.first();}catch{return null;}}
async function safeAll(env,sql,bind=[]){try{const s=env.DB.prepare(sql),r=bind.length?await s.bind(...bind).all():await s.all();return r.results||[];}catch{return[];}}

function metadataIds(meta){
  const m=parseObject(meta);
  const candidates=[m,m.lumen,m.attribution,m.commercial,m.checkout,m.payment].filter(x=>x&&typeof x==='object');
  const pick=(...keys)=>{for(const o of candidates)for(const k of keys){const v=clean(o?.[k],180);if(v)return v;}return null;};
  return{
    proposalId:pick('proposalId','proposal_id'),
    opportunityId:pick('opportunityId','opportunity_id'),
    offerId:pick('offerId','offer_id','itemId','item_id'),
    referralId:pick('referralId','referral_id')
  };
}

async function resolveAttribution(env,event){
  const item=clean(event.item_id,180)||null,ids=metadataIds(event.metadata);
  let proposal=null,referral=null,opportunity=null,offerId=ids.offerId||null;
  let confidence=0;const evidence=[];

  if(ids.proposalId) proposal=await safeFirst(env,"SELECT proposal_id,opportunity_id,offer_id FROM lumen_proposal_drafts WHERE proposal_id=? LIMIT 1",[ids.proposalId]);
  if(!proposal&&item) proposal=await safeFirst(env,"SELECT proposal_id,opportunity_id,offer_id FROM lumen_proposal_drafts WHERE proposal_id=? LIMIT 1",[item]);
  if(proposal){confidence=Math.max(confidence,100);evidence.push(`proposal_exact:${proposal.proposal_id}`);offerId=offerId||proposal.offer_id||null;}

  const referralId=ids.referralId||null;
  if(referralId) referral=await safeFirst(env,"SELECT id,opportunity_id,origin_partner_id,origin_partner_name,settlement_event_id,status FROM lumen_referrals WHERE id=? LIMIT 1",[referralId]);
  if(!referral&&item) referral=await safeFirst(env,"SELECT id,opportunity_id,origin_partner_id,origin_partner_name,settlement_event_id,status FROM lumen_referrals WHERE id=? LIMIT 1",[item]);
  if(!referral) referral=await safeFirst(env,"SELECT id,opportunity_id,origin_partner_id,origin_partner_name,settlement_event_id,status FROM lumen_referrals WHERE settlement_event_id=? LIMIT 1",[event.id]);
  if(referral){confidence=Math.max(confidence,100);evidence.push(`referral_exact:${referral.id}`);}

  const oppId=ids.opportunityId||proposal?.opportunity_id||referral?.opportunity_id||null;
  if(oppId) opportunity=await safeFirst(env,"SELECT id,revenue_offer_id FROM lumen_opportunities WHERE id=? LIMIT 1",[oppId]);
  if(!opportunity&&item) opportunity=await safeFirst(env,"SELECT id,revenue_offer_id FROM lumen_opportunities WHERE id=? LIMIT 1",[item]);
  if(opportunity){confidence=Math.max(confidence,proposal||referral?100:95);evidence.push(`opportunity_exact:${opportunity.id}`);offerId=offerId||opportunity.revenue_offer_id||null;}

  if(!offerId&&item&&/^MP-|^REV-/.test(item)){offerId=item;confidence=Math.max(confidence,85);evidence.push(`offer_item_exact:${item}`);}
  if(offerId&&ids.offerId){confidence=Math.max(confidence,90);evidence.push(`offer_metadata_exact:${offerId}`);}

  const partnerId=referral?.origin_partner_id||null;
  const partnerName=referral?.origin_partner_name||null;
  const status=partnerId?'PARTNER_ATTRIBUTED':(proposal||opportunity||offerId||referral?'SOURCE_ATTRIBUTED':'UNATTRIBUTED');
  return{status,confidence,proposalId:proposal?.proposal_id||ids.proposalId||null,opportunityId:opportunity?.id||proposal?.opportunity_id||referral?.opportunity_id||ids.opportunityId||null,offerId:offerId||null,referralId:referral?.id||ids.referralId||null,originPartnerId:partnerId,originPartnerName:partnerName,evidence};
}

async function recomputePartnerCommercialValue(env){
  const partners=await safeAll(env,"SELECT origin_partner_id partner_id,MAX(origin_partner_name) partner_name,COALESCE(SUM(amount_usd),0) revenue,COUNT(*) settlements,SUM(CASE WHEN referral_id IS NOT NULL THEN 1 ELSE 0 END) referral_settlements,MAX(revenue_event_id) last_event FROM lumen_revenue_attributions WHERE attribution_status='PARTNER_ATTRIBUTED' AND origin_partner_id IS NOT NULL GROUP BY origin_partner_id");
  const now=new Date().toISOString();let updated=0;
  for(const p of partners){
    const revenue=Math.max(0,Number(p.revenue||0)),settlements=Math.max(0,Number(p.settlements||0)),refs=Math.max(0,Number(p.referral_settlements||0));
    const score=Math.min(100,Math.round(Math.min(60,revenue*4)+Math.min(25,settlements*10)+Math.min(15,refs*8)));
    await env.DB.prepare("INSERT INTO lumen_partner_commercial_value(partner_id,partner_name,updated_at,verified_revenue_influenced_usd,verified_settlements,verified_referral_settlements,commercial_value_score,last_revenue_event_id,engine_version) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(partner_id) DO UPDATE SET partner_name=excluded.partner_name,updated_at=excluded.updated_at,verified_revenue_influenced_usd=excluded.verified_revenue_influenced_usd,verified_settlements=excluded.verified_settlements,verified_referral_settlements=excluded.verified_referral_settlements,commercial_value_score=excluded.commercial_value_score,last_revenue_event_id=excluded.last_revenue_event_id,engine_version=excluded.engine_version")
      .bind(p.partner_id,p.partner_name||null,now,revenue,settlements,refs,score,p.last_event||null,VERSION).run();updated++;
  }
  return updated;
}

export async function recomputeRevenueAttribution(env){
  if(!(await ensure(env)))return{ok:false,error:'persistence_unavailable',version:VERSION};
  const events=await safeAll(env,"SELECT e.id,e.created_at,e.source,e.item_id,e.amount_usd,e.evidence,e.metadata FROM lumen_revenue_events e LEFT JOIN lumen_revenue_attributions a ON a.revenue_event_id=e.id WHERE e.event_type='payment_settled' AND e.status='verified' AND a.revenue_event_id IS NULL ORDER BY e.created_at ASC LIMIT 500");
  const now=new Date().toISOString(),results=[];
  for(const e of events){
    const a=await resolveAttribution(env,e),id=`RATTR-${(await sha256(e.id)).slice(0,18).toUpperCase()}`;
    await env.DB.prepare("INSERT INTO lumen_revenue_attributions(id,revenue_event_id,created_at,updated_at,amount_usd,item_id,source,attribution_status,confidence,proposal_id,opportunity_id,offer_id,referral_id,origin_partner_id,origin_partner_name,evidence_json,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
      .bind(id,e.id,e.created_at||now,now,Math.max(0,Number(e.amount_usd||0)),e.item_id||null,e.source||null,a.status,a.confidence,a.proposalId,a.opportunityId,a.offerId,a.referralId,a.originPartnerId,a.originPartnerName,JSON.stringify({rules:'direct_identifiers_only',matches:a.evidence,eventEvidence:clean(e.evidence,1000)||null}),VERSION).run();
    results.push({revenueEventId:e.id,amountUsd:Number(e.amount_usd||0),status:a.status,confidence:a.confidence,proposalId:a.proposalId,opportunityId:a.opportunityId,offerId:a.offerId,referralId:a.referralId,originPartnerId:a.originPartnerId,originPartnerName:a.originPartnerName});
  }
  const partnerValuesUpdated=await recomputePartnerCommercialValue(env);
  const s=await statsData(env);
  return{ok:true,version:VERSION,processed:results.length,results:results.slice(0,50),partnerValuesUpdated,state:s,guardrails:{verifiedSettlementsOnly:true,directEvidenceOnly:true,noInferredTeamCredit:true,autonomousSpend:false,bindingActionsHumanGated:true}};
}

async function statsData(env){
  await ensure(env);
  const r=await safeFirst(env,"SELECT COUNT(*) total,COALESCE(SUM(amount_usd),0) revenue,SUM(CASE WHEN attribution_status='PARTNER_ATTRIBUTED' THEN 1 ELSE 0 END) partner_attributed,SUM(CASE WHEN attribution_status='SOURCE_ATTRIBUTED' THEN 1 ELSE 0 END) source_attributed,SUM(CASE WHEN attribution_status='UNATTRIBUTED' THEN 1 ELSE 0 END) unattributed,COALESCE(SUM(CASE WHEN attribution_status='PARTNER_ATTRIBUTED' THEN amount_usd ELSE 0 END),0) partner_revenue FROM lumen_revenue_attributions");
  const p=await safeFirst(env,"SELECT COUNT(*) partners,COALESCE(MAX(commercial_value_score),0) best_score,COALESCE(MAX(verified_revenue_influenced_usd),0) max_partner_revenue FROM lumen_partner_commercial_value");
  return{attributedSettlements:Number(r?.total||0),attributedRevenueUsd:Number(r?.revenue||0),partnerAttributedSettlements:Number(r?.partner_attributed||0),sourceAttributedSettlements:Number(r?.source_attributed||0),unattributedSettlements:Number(r?.unattributed||0),partnerAttributedRevenueUsd:Number(r?.partner_revenue||0),revenueProducingPartners:Number(p?.partners||0),bestPartnerCommercialValueScore:Number(p?.best_score||0),maxPartnerInfluencedRevenueUsd:Number(p?.max_partner_revenue||0)};
}

async function policy(){return json({version:VERSION,name:'LUMEN Revenue Attribution',truthRule:'only_verified_payment_settled_events_are_attributed',partnerCreditRule:'partner_credit_requires_direct_referral_or_explicit_partner_identifier_evidence',teamCreditRule:'draft_or_planned_team_membership_does_not_receive_revenue_credit',autonomousSpend:false,bindingActionsHumanGated:true});}

export async function handleRevenueAttribution(request,env){
  const u=new URL(request.url);
  if(request.method==='GET'&&u.pathname==='/revenue-attribution/policy')return policy();
  if(request.method==='GET'&&u.pathname==='/revenue-attribution/stats')return json({version:VERSION,...await statsData(env),verifiedSettlementsOnly:true,directEvidenceOnly:true});
  if(request.method==='POST'&&u.pathname==='/revenue-attribution/recompute'){if(!authorized(request,env))return json({ok:false,error:'admin_token_required'},403);return json(await recomputeRevenueAttribution(env),202);}
  if(request.method==='GET'&&u.pathname==='/revenue-attribution/events'){if(!authorized(request,env))return json({ok:false,error:'admin_token_required'},403);await ensure(env);const r=await env.DB.prepare("SELECT * FROM lumen_revenue_attributions ORDER BY created_at DESC LIMIT 200").all();return json({version:VERSION,events:r.results||[]});}
  if(request.method==='GET'&&u.pathname==='/revenue-attribution/partners'){if(!authorized(request,env))return json({ok:false,error:'admin_token_required'},403);await ensure(env);const r=await env.DB.prepare("SELECT * FROM lumen_partner_commercial_value ORDER BY commercial_value_score DESC,verified_revenue_influenced_usd DESC LIMIT 200").all();return json({version:VERSION,partners:r.results||[]});}
  return null;
}
