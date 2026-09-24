const VERSION = "1.0-referral-commission-autopilot";
const STANDARD_RATE_PCT = 5;
const MAX_EXTERNAL_MESSAGES_PER_RUN = 1;

function clean(v,n=5000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}
function num(v,f=0){const n=Number(v);return Number.isFinite(n)?n:f;}
function json(d,s=200){return Response.json(d,{status:s,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function authorized(r,e){const a=clean(e?.OPPORTUNITY_ADMIN_TOKEN,500),b=clean(r.headers.get("x-lumen-admin"),500);return Boolean(a&&b&&a===b);}
function safeHttps(v){try{const u=new URL(v);if(u.protocol!=="https:")return false;const h=u.hostname.toLowerCase();if(h==="localhost"||h.endsWith(".local")||h==="::1"||/^127\./.test(h)||/^10\./.test(h)||/^192\.168\./.test(h)||/^169\.254\./.test(h))return false;const m=h.match(/^172\.(\d+)\./);return !(m&&Number(m[1])>=16&&Number(m[1])<=31);}catch{return false;}}
function enabled(env){return String(env?.A2A_AUTONOMOUS_OUTREACH||"").toLowerCase()==="true";}

async function ensure(env){
  if(!env?.DB)return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_referral_commission_autopilot (referral_id TEXT PRIMARY KEY,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,state TEXT NOT NULL,counterparty_partner_id TEXT,counterparty_name TEXT,endpoint TEXT,proposal_sent_at TEXT,proposal_task_id TEXT,last_response TEXT,last_response_at TEXT,counteroffer_text TEXT,error TEXT,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_referral_commission_autopilot_state ON lumen_referral_commission_autopilot(state,updated_at)")
  ]);
  return true;
}

async function counterparty(env,ref){
  const partnerId=ref.direction==="OUTBOUND"?clean(ref.target_partner_id,100):clean(ref.origin_partner_id,100);
  if(!partnerId)return null;
  try{
    const p=await env.DB.prepare("SELECT id,name,endpoint,card_url FROM lumen_partner_agents WHERE id=? LIMIT 1").bind(partnerId).first();
    if(!p)return null;
    const endpoint=clean(p.endpoint||p.card_url,2000);
    if(!safeHttps(endpoint))return null;
    return{id:p.id,name:clean(p.name,220)||partnerId,endpoint};
  }catch{return null;}
}

function proposalMessage(ref){
  const title=clean(ref.title,220)||"the referred opportunity";
  const estimate=Math.max(0,num(ref.deal_value_usd||ref.estimated_value_usd));
  const estimatedText=estimate>0?` Current estimated value: USD ${estimate.toFixed(2)}.`:"";
  return `LUMEN can broker and coordinate ${title} on a 5% success-fee basis, payable only if the referred deal closes. The 5% is calculated on the final confirmed deal value, not the estimate.${estimatedText} No fee is due if the deal does not close. If you accept, reply exactly: ACCEPT LUMEN 5% SUCCESS FEE ${ref.id}. If you want different terms, reply with COUNTER and your proposal.`;
}

function extractText(payload){
  if(!payload)return"";
  if(typeof payload==="string")return clean(payload,6000);
  const c=[payload.text,payload.message,payload.response,payload.result?.text,payload.result?.message,payload.result?.response,payload.artifacts?.[0]?.parts?.[0]?.text,payload.result?.artifacts?.[0]?.parts?.[0]?.text];
  for(const x of c)if(typeof x==="string"&&clean(x,6000))return clean(x,6000);
  return"";
}
function extractTaskId(payload){return clean(payload?.task_id||payload?.taskId||payload?.id||payload?.result?.id||payload?.result?.task_id||payload?.result?.taskId,200);}

async function sendA2A(endpoint,message,referralId){
  const payload={jsonrpc:"2.0",id:`lumen-${Date.now()}`,method:"message/send",params:{message:{role:"user",parts:[{kind:"text",text:message}],messageId:`lumen-commission-${referralId}-${Date.now()}`}}};
  const r=await fetch(endpoint,{method:"POST",headers:{"content-type":"application/json","accept":"application/json"},body:JSON.stringify(payload)});
  const raw=await r.text();let body=null;try{body=JSON.parse(raw);}catch{body={text:raw};}
  if(!r.ok)return{ok:false,error:clean(raw||`http_${r.status}`,1000),status:r.status};
  return{ok:true,status:r.status,taskId:extractTaskId(body),responseText:extractText(body)};
}

async function pollA2A(endpoint,taskId){
  if(!taskId)return{ok:false,error:"task_id_missing"};
  const payload={jsonrpc:"2.0",id:`lumen-poll-${Date.now()}`,method:"tasks/get",params:{id:taskId}};
  const r=await fetch(endpoint,{method:"POST",headers:{"content-type":"application/json","accept":"application/json"},body:JSON.stringify(payload)});
  const raw=await r.text();let body=null;try{body=JSON.parse(raw);}catch{body={text:raw};}
  if(!r.ok)return{ok:false,error:clean(raw,1000),status:r.status};
  return{ok:true,responseText:extractText(body)};
}

function esc(v){return String(v).replace(/[.*+?^${}()|[\]\\]/g,"\\$&");}
function classify(text,referralId){
  const t=clean(text,6000);
  if(new RegExp(`\\bACCEPT\\s+LUMEN\\s+5%\\s+SUCCESS\\s+FEE\\s+${esc(referralId)}\\b`,`i`).test(t))return"ACCEPT";
  if(/\bCOUNTER\b/i.test(t))return"COUNTER";
  if(/\b(DECLINE|DECLINED|NOT INTERESTED|NO THANKS)\b/i.test(t))return"DECLINE";
  return"OTHER";
}

async function recordAcceptance(env,row,evidence){
  const now=new Date().toISOString();
  await env.DB.prepare("UPDATE lumen_referral_commissions SET status='AGREED_PENDING_CLOSE',agreed_rate_pct=5,agreed_amount_usd=NULL,agreement_source='a2a_explicit_acceptance',agreement_evidence=?,agreement_at=?,updated_at=?,engine_version='1.1-referral-commission-engine-rate-based' WHERE referral_id=? AND status='PROPOSAL_READY'").bind(evidence,now,now,row.referral_id).run();
  await env.DB.prepare("UPDATE lumen_referrals SET commission_status='AGREED_PENDING_CLOSE',updated_at=? WHERE id=?").bind(now,row.referral_id).run();
  await env.DB.prepare("UPDATE lumen_referral_commission_autopilot SET state='AGREED_PENDING_CLOSE',last_response=?,last_response_at=?,updated_at=?,engine_version=? WHERE referral_id=?").bind(evidence,now,now,VERSION,row.referral_id).run();
  try{await env.DB.prepare("INSERT INTO lumen_referral_events(id,referral_id,created_at,event_type,detail,amount_usd,verified) VALUES(?,?,?,?,?,?,0)").bind(`RFAP-${crypto.randomUUID().replaceAll("-","").slice(0,18).toUpperCase()}`,row.referral_id,now,"COMMISSION_AGREED_A2A","Explicit counterparty acceptance of 5% success fee on final confirmed deal value",null).run();}catch{}
}

export async function pollReferralCommissionAutopilot(env){
  if(!(await ensure(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  const rows=await env.DB.prepare("SELECT * FROM lumen_referral_commission_autopilot WHERE state='PROPOSAL_SENT' AND proposal_task_id IS NOT NULL ORDER BY updated_at ASC LIMIT 40").all();
  const results=[];
  for(const row of rows.results||[]){
    if(!safeHttps(row.endpoint))continue;
    const p=await pollA2A(row.endpoint,row.proposal_task_id);if(!p.ok)continue;
    const text=clean(p.responseText,6000);if(!text)continue;
    const cls=classify(text,row.referral_id),now=new Date().toISOString();
    if(cls==="ACCEPT")await recordAcceptance(env,row,text);
    else if(cls==="COUNTER")await env.DB.prepare("UPDATE lumen_referral_commission_autopilot SET state='COUNTEROFFER_REVIEW',counteroffer_text=?,last_response=?,last_response_at=?,updated_at=? WHERE referral_id=?").bind(text,text,now,now,row.referral_id).run();
    else if(cls==="DECLINE")await env.DB.prepare("UPDATE lumen_referral_commission_autopilot SET state='DECLINED',last_response=?,last_response_at=?,updated_at=? WHERE referral_id=?").bind(text,now,now,row.referral_id).run();
    results.push({referralId:row.referral_id,responseClass:cls});
  }
  return{ok:true,version:VERSION,polled:results.length,results};
}

export async function runReferralCommissionAutopilot(env,{force=false}={}){
  if(!(await ensure(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  await pollReferralCommissionAutopilot(env);
  if(!force&&!enabled(env))return{ok:true,version:VERSION,sent:false,reason:"autonomous_outreach_disabled"};
  let row=null;
  try{row=await env.DB.prepare("SELECT r.*,c.deal_value_usd,c.proposed_rate_pct,c.status commission_status FROM lumen_referrals r JOIN lumen_referral_commissions c ON c.referral_id=r.id LEFT JOIN lumen_referral_commission_autopilot a ON a.referral_id=r.id WHERE r.direction='OUTBOUND' AND c.status='PROPOSAL_READY' AND c.proposed_rate_pct=5 AND c.deal_value_usd>0 AND a.referral_id IS NULL AND r.trust_level IN ('ALLOW','CAUTION') ORDER BY r.match_score DESC,r.updated_at ASC LIMIT 1").first();}catch{}
  if(!row)return{ok:true,version:VERSION,sent:false,reason:"no_eligible_commission_proposal",standardRatePct:STANDARD_RATE_PCT};
  const p=await counterparty(env,row);if(!p)return{ok:true,version:VERSION,sent:false,reason:"counterparty_endpoint_unavailable",referralId:row.id};
  const send=await sendA2A(p.endpoint,proposalMessage(row),row.id),now=new Date().toISOString();
  await env.DB.prepare("INSERT INTO lumen_referral_commission_autopilot(referral_id,created_at,updated_at,state,counterparty_partner_id,counterparty_name,endpoint,proposal_sent_at,proposal_task_id,error,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?)").bind(row.id,now,now,send.ok?"PROPOSAL_SENT":"PROPOSAL_READY",p.id,p.name,p.endpoint,send.ok?now:null,send.taskId||null,send.ok?null:send.error,VERSION).run();
  return{ok:send.ok,version:VERSION,sent:send.ok,referralId:row.id,type:"COMMISSION_PROPOSAL",standardRatePct:STANDARD_RATE_PCT,maxExternalMessagesPerRun:MAX_EXTERNAL_MESSAGES_PER_RUN,error:send.ok?null:send.error};
}

async function stats(env){
  await ensure(env);const r=await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN state='PROPOSAL_SENT' THEN 1 ELSE 0 END) proposal_sent,SUM(CASE WHEN state='AGREED_PENDING_CLOSE' THEN 1 ELSE 0 END) agreed,SUM(CASE WHEN state='COUNTEROFFER_REVIEW' THEN 1 ELSE 0 END) counteroffers,SUM(CASE WHEN state='DECLINED' THEN 1 ELSE 0 END) declined FROM lumen_referral_commission_autopilot").first();return{total:num(r?.total),proposalSent:num(r?.proposal_sent),agreedPendingClose:num(r?.agreed),counteroffersPendingReview:num(r?.counteroffers),declined:num(r?.declined)};
}

export async function handleReferralCommissionAutopilot(request,env){
  const u=new URL(request.url);
  if(request.method==="GET"&&u.pathname==="/referrals/commissions/autopilot/policy")return json({version:VERSION,standardSuccessFeePct:STANDARD_RATE_PCT,percentageFeeBasis:"final_confirmed_deal_value",explicitAcceptanceRequired:true,exactAcceptancePhrase:true,counteroffersAutoAccepted:false,maxExternalMessagesPerRun:MAX_EXTERNAL_MESSAGES_PER_RUN,autonomousSpend:false,automaticContract:false,revenueOnlyAfterVerifiedSettlement:true});
  if(request.method==="GET"&&u.pathname==="/referrals/commissions/autopilot/stats")return json({version:VERSION,...await stats(env),autonomousEnabled:enabled(env)});
  if(request.method==="POST"&&u.pathname==="/referrals/commissions/autopilot/run"){if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);return json(await runReferralCommissionAutopilot(env,{force:false}),202);}
  if(request.method==="POST"&&u.pathname==="/referrals/commissions/autopilot/poll"){if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);return json(await pollReferralCommissionAutopilot(env),202);}
  return null;
}
