import { recordCommissionAgreement, markCommissionDue } from "./referral-commission-engine.js";

const VERSION = "2.0-commission-autopilot-close-to-cash";
const STANDARD_RATE_PCT = 5;
const MAX_EXTERNAL_MESSAGES_PER_RUN = 1;

function clean(v,n=5000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}
function num(v,f=0){const n=Number(v);return Number.isFinite(n)?n:f;}
function intVar(v,f,min,max){const n=Number.parseInt(String(v??""),10);return Number.isFinite(n)?Math.max(min,Math.min(max,n)):f;}
function json(d,s=200){return Response.json(d,{status:s,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function authorized(r,e){const a=clean(e?.OPPORTUNITY_ADMIN_TOKEN,500),b=clean(r.headers.get("x-lumen-admin"),500);return Boolean(a&&b&&a===b);}
function safeHttps(v){try{const u=new URL(v);if(u.protocol!=="https:")return false;const h=u.hostname.toLowerCase();if(h==="localhost"||h.endsWith(".local")||h==="::1"||/^127\./.test(h)||/^10\./.test(h)||/^192\.168\./.test(h)||/^169\.254\./.test(h))return false;const m=h.match(/^172\.(\d+)\./);return !(m&&Number(m[1])>=16&&Number(m[1])<=31);}catch{return false;}}
function enabled(env){return String(env?.A2A_AUTONOMOUS_OUTREACH||"").toLowerCase()==="true";}
function closeCooldownDays(env){return intVar(env?.COMMISSION_CLOSE_CHECK_COOLDOWN_DAYS,7,1,30);}
function maxCloseChecks(env){return intVar(env?.COMMISSION_CLOSE_CHECK_MAX,6,1,24);}
function paymentCooldownDays(env){return intVar(env?.COMMISSION_PAYMENT_FOLLOWUP_DAYS,3,1,30);}
function maxPaymentFollowups(env){return intVar(env?.COMMISSION_PAYMENT_FOLLOWUP_MAX,2,0,6);}
function olderThan(iso,days){if(!iso)return true;const t=new Date(iso).getTime();return Number.isFinite(t)&&Date.now()-t>=days*86400000;}

async function ensure(env){
  if(!env?.DB)return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_referral_commission_autopilot (referral_id TEXT PRIMARY KEY,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,state TEXT NOT NULL,counterparty_partner_id TEXT,counterparty_name TEXT,endpoint TEXT,proposal_sent_at TEXT,proposal_task_id TEXT,last_response TEXT,last_response_at TEXT,counteroffer_text TEXT,error TEXT,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_referral_commission_autopilot_state ON lumen_referral_commission_autopilot(state,updated_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_referral_commission_messages (id TEXT PRIMARY KEY,referral_id TEXT NOT NULL,kind TEXT NOT NULL,sequence INTEGER NOT NULL,created_at TEXT NOT NULL,sent_at TEXT,endpoint TEXT NOT NULL,task_id TEXT,status TEXT NOT NULL,request_text TEXT NOT NULL,response_text TEXT,response_at TEXT,error TEXT,engine_version TEXT NOT NULL,UNIQUE(referral_id,kind,sequence))"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_referral_commission_messages_poll ON lumen_referral_commission_messages(status,task_id,sent_at)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_referral_commission_messages_ref ON lumen_referral_commission_messages(referral_id,kind,sequence)")
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
  const estimatedText=estimate>0?` Current estimated value: USD ${estimate.toFixed(2)}; this estimate does not determine the fee.`:"";
  return `LUMEN proposes a 5% success fee for brokering and coordinating ${title}, payable only if the referred B2B deal actually closes. The fee is 5% of the final confirmed deal value, not an estimate.${estimatedText} No fee is due if the deal does not close. This message does not sign a contract or authorize LUMEN to spend funds. To explicitly accept the commission arrangement, reply exactly: ACCEPT LUMEN 5% SUCCESS FEE ${ref.id||ref.referral_id}. To propose different commercial terms, reply with COUNTER and your proposal.`;
}
function closeCheckMessage(row){
  return `LUMEN close-status check for referral ${row.referral_id}. If the referred deal has closed, reply exactly: CLOSED LUMEN ${row.referral_id} VALUE USD <final_value> EVIDENCE <reference>. If it is still open, reply exactly: OPEN LUMEN ${row.referral_id}. If it was lost/cancelled, reply exactly: LOST LUMEN ${row.referral_id}. A PAYMENT_DUE is created only from an explicit CLOSED response with final value. This message creates no contract and initiates no payment.`;
}
function paymentMessage(row,followup=false){
  const amount=Math.max(0,num(row.agreed_amount_usd));
  const checkout=clean(row.checkout_url,1200);
  if(followup)return `LUMEN payment follow-up for referral ${row.referral_id}. The agreed 5% success fee remains due: USD ${amount.toFixed(2)}. Exact x402 checkout: ${checkout}. LUMEN recognizes revenue only after verified x402 settlement. If payment is already complete, no further action is needed.`;
  return `PAYMENT_DUE for LUMEN referral ${row.referral_id}. Final confirmed deal value: USD ${num(row.deal_value_usd).toFixed(2)}. Agreed success fee: 5%. Exact amount due: USD ${amount.toFixed(2)}. x402 checkout: ${checkout}. This is a collection request only; LUMEN does not initiate outgoing spend and revenue is recognized only after verified settlement.`;
}

function extractText(payload){
  if(!payload)return"";
  if(typeof payload==="string")return clean(payload,6000);
  const c=[payload.text,payload.message,payload.response,payload.result?.text,payload.result?.message,payload.result?.response,payload.artifacts?.[0]?.parts?.[0]?.text,payload.result?.artifacts?.[0]?.parts?.[0]?.text,payload.result?.task?.status?.message?.parts?.map?.(p=>p?.text||"").join(" ")];
  for(const x of c)if(typeof x==="string"&&clean(x,6000))return clean(x,6000);
  return"";
}
function extractTaskId(payload){return clean(payload?.task_id||payload?.taskId||payload?.id||payload?.result?.id||payload?.result?.task_id||payload?.result?.taskId||payload?.result?.task?.id,200);}

async function sendA2A(endpoint,message,referralId,kind){
  const payload={jsonrpc:"2.0",id:`lumen-${Date.now()}`,method:"message/send",params:{message:{role:"user",parts:[{kind:"text",text:message}],messageId:`lumen-commission-${kind.toLowerCase()}-${referralId}-${Date.now()}`}}};
  const r=await fetch(endpoint,{method:"POST",headers:{"content-type":"application/json","accept":"application/json"},body:JSON.stringify(payload)});
  const raw=await r.text();let body=null;try{body=JSON.parse(raw);}catch{body={text:raw};}
  if(!r.ok)return{ok:false,error:clean(raw||`http_${r.status}`,1000),status:r.status,responseText:extractText(body)};
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
function classifyProposal(text,referralId){
  const t=clean(text,6000);
  if(new RegExp(`\\bACCEPT\\s+LUMEN\\s+5%\\s+SUCCESS\\s+FEE\\s+${esc(referralId)}\\b`,`i`).test(t))return"ACCEPT";
  if(/\bCOUNTER\b/i.test(t))return"COUNTER";
  if(/\b(DECLINE|DECLINED|NOT INTERESTED|NO THANKS)\b/i.test(t))return"DECLINE";
  return"OTHER";
}
function classifyClose(text,referralId){
  const t=clean(text,6000);
  const closed=t.match(new RegExp(`\\bCLOSED\\s+LUMEN\\s+${esc(referralId)}\\s+VALUE\\s+USD\\s+([0-9][0-9,]*(?:\\.[0-9]{1,2})?)\\s+EVIDENCE\\s+(.+)$`,`i`));
  if(closed){const finalValue=Number(String(closed[1]).replaceAll(",",""));const evidence=clean(closed[2],2500);if(finalValue>0&&evidence.length>=3)return{type:"CLOSED",finalValue,evidence};}
  if(new RegExp(`\\bOPEN\\s+LUMEN\\s+${esc(referralId)}\\b`,`i`).test(t))return{type:"OPEN"};
  if(new RegExp(`\\bLOST\\s+LUMEN\\s+${esc(referralId)}\\b`,`i`).test(t))return{type:"LOST"};
  return{type:"OTHER"};
}

async function upsertAutopilot(env,row,p,state,send=null){
  const now=new Date().toISOString();
  await env.DB.prepare("INSERT INTO lumen_referral_commission_autopilot(referral_id,created_at,updated_at,state,counterparty_partner_id,counterparty_name,endpoint,proposal_sent_at,proposal_task_id,error,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(referral_id) DO UPDATE SET updated_at=excluded.updated_at,state=excluded.state,counterparty_partner_id=COALESCE(excluded.counterparty_partner_id,lumen_referral_commission_autopilot.counterparty_partner_id),counterparty_name=COALESCE(excluded.counterparty_name,lumen_referral_commission_autopilot.counterparty_name),endpoint=COALESCE(excluded.endpoint,lumen_referral_commission_autopilot.endpoint),proposal_sent_at=COALESCE(excluded.proposal_sent_at,lumen_referral_commission_autopilot.proposal_sent_at),proposal_task_id=COALESCE(excluded.proposal_task_id,lumen_referral_commission_autopilot.proposal_task_id),error=excluded.error,engine_version=excluded.engine_version")
    .bind(row.referral_id||row.id,now,now,state,p?.id||null,p?.name||null,p?.endpoint||null,send?.ok&&state==="PROPOSAL_SENT"?now:null,send?.taskId||null,send?.ok?null:send?.error||null,VERSION).run();
}
async function logMessage(env,{referralId,kind,sequence,endpoint,message,send}){
  const now=new Date().toISOString();
  const id=`RCMSG-${crypto.randomUUID().replaceAll("-","").slice(0,18).toUpperCase()}`;
  await env.DB.prepare("INSERT OR IGNORE INTO lumen_referral_commission_messages(id,referral_id,kind,sequence,created_at,sent_at,endpoint,task_id,status,request_text,response_text,response_at,error,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
    .bind(id,referralId,kind,sequence,now,send.ok?now:null,endpoint,send.taskId||null,send.ok?(send.responseText?"RESPONDED_IMMEDIATE":"SENT"):"SEND_FAILED",message,send.responseText||null,send.responseText?now:null,send.ok?null:send.error||null,VERSION).run();
  return{id,referral_id:referralId,kind,sequence,endpoint,task_id:send.taskId||null,status:send.ok?(send.responseText?"RESPONDED_IMMEDIATE":"SENT"):"SEND_FAILED",response_text:send.responseText||null};
}

async function recordAcceptance(env,row,evidence){
  const result=await recordCommissionAgreement(env,{referralId:row.referral_id,agreementEvidence:evidence,agreementSource:"a2a_explicit_acceptance",agreedRatePct:STANDARD_RATE_PCT});
  if(!result.ok)return result;
  const now=new Date().toISOString();
  await env.DB.prepare("UPDATE lumen_referral_commission_autopilot SET state='AGREED_PENDING_CLOSE',last_response=?,last_response_at=?,updated_at=?,engine_version=? WHERE referral_id=?").bind(evidence,now,now,VERSION,row.referral_id).run();
  return result;
}
async function markLost(env,referralId,evidence){
  const now=new Date().toISOString();
  await env.DB.prepare("UPDATE lumen_referral_commissions SET status='CLOSED_LOST',completion_evidence=?,updated_at=?,engine_version=? WHERE referral_id=? AND status='AGREED_PENDING_CLOSE'").bind(clean(evidence,4000),now,VERSION,referralId).run();
  await env.DB.prepare("UPDATE lumen_referrals SET commission_status='CLOSED_LOST',updated_at=? WHERE id=?").bind(now,referralId).run();
  await env.DB.prepare("UPDATE lumen_referral_commission_autopilot SET state='CLOSED_LOST',last_response=?,last_response_at=?,updated_at=?,engine_version=? WHERE referral_id=?").bind(clean(evidence,6000),now,now,VERSION,referralId).run();
  try{await env.DB.prepare("INSERT INTO lumen_referral_events(id,referral_id,created_at,event_type,detail,amount_usd,verified) VALUES(?,?,?,?,?,?,0)").bind(`RFAP-${crypto.randomUUID().replaceAll("-","").slice(0,18).toUpperCase()}`,referralId,now,"COMMISSION_CLOSED_LOST","Counterparty explicitly reported referred deal lost/cancelled; no success fee due",null).run();}catch{}
}

async function processMessageResponse(env,msg,text){
  const response=clean(text,6000);if(!response)return{handled:false};
  const now=new Date().toISOString();
  if(msg.id)await env.DB.prepare("UPDATE lumen_referral_commission_messages SET status='RESPONDED',response_text=?,response_at=?,error=NULL WHERE id=?").bind(response,now,msg.id).run();
  const row=await env.DB.prepare("SELECT a.*,c.status commission_status,c.agreed_amount_usd,c.checkout_url FROM lumen_referral_commission_autopilot a JOIN lumen_referral_commissions c ON c.referral_id=a.referral_id WHERE a.referral_id=? LIMIT 1").bind(msg.referral_id).first();
  if(!row)return{handled:false};
  if(msg.kind==="COMMISSION_PROPOSAL"){
    const cls=classifyProposal(response,msg.referral_id);
    if(cls==="ACCEPT"){const r=await recordAcceptance(env,row,response);return{handled:r.ok,type:"ACCEPT",result:r};}
    if(cls==="COUNTER"){await env.DB.prepare("UPDATE lumen_referral_commission_autopilot SET state='COUNTEROFFER_REVIEW',counteroffer_text=?,last_response=?,last_response_at=?,updated_at=? WHERE referral_id=?").bind(response,response,now,now,msg.referral_id).run();return{handled:true,type:"COUNTER"};}
    if(cls==="DECLINE"){await env.DB.prepare("UPDATE lumen_referral_commission_autopilot SET state='DECLINED',last_response=?,last_response_at=?,updated_at=? WHERE referral_id=?").bind(response,now,now,msg.referral_id).run();return{handled:true,type:"DECLINE"};}
    return{handled:false,type:"OTHER"};
  }
  if(msg.kind==="CLOSE_CHECK"){
    const cls=classifyClose(response,msg.referral_id);
    if(cls.type==="CLOSED"){
      const evidence=`a2a_close_report:${msg.id||msg.task_id||"immediate"};reference=${cls.evidence};response=${response}`;
      const due=await markCommissionDue(env,{referralId:msg.referral_id,finalDealValueUsd:cls.finalValue,completionEvidence:evidence});
      if(due.ok)await env.DB.prepare("UPDATE lumen_referral_commission_autopilot SET state='PAYMENT_DUE',last_response=?,last_response_at=?,updated_at=?,engine_version=? WHERE referral_id=?").bind(response,now,now,VERSION,msg.referral_id).run();
      return{handled:due.ok,type:"CLOSED",result:due};
    }
    if(cls.type==="OPEN"){await env.DB.prepare("UPDATE lumen_referral_commission_autopilot SET state='AGREED_PENDING_CLOSE',last_response=?,last_response_at=?,updated_at=? WHERE referral_id=?").bind(response,now,now,msg.referral_id).run();return{handled:true,type:"OPEN"};}
    if(cls.type==="LOST"){await markLost(env,msg.referral_id,response);return{handled:true,type:"LOST"};}
    return{handled:false,type:"OTHER"};
  }
  return{handled:true,type:"COLLECTION_RESPONSE"};
}

export async function pollReferralCommissionAutopilot(env){
  if(!(await ensure(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  const results=[];
  const legacy=await env.DB.prepare("SELECT * FROM lumen_referral_commission_autopilot WHERE state='PROPOSAL_SENT' AND proposal_task_id IS NOT NULL ORDER BY updated_at ASC LIMIT 20").all();
  for(const row of legacy.results||[]){
    if(!safeHttps(row.endpoint))continue;
    const already=await env.DB.prepare("SELECT id FROM lumen_referral_commission_messages WHERE referral_id=? AND kind='COMMISSION_PROPOSAL' LIMIT 1").bind(row.referral_id).first();
    if(already)continue;
    const p=await pollA2A(row.endpoint,row.proposal_task_id);if(!p.ok||!clean(p.responseText,6000))continue;
    const msg={id:null,referral_id:row.referral_id,kind:"COMMISSION_PROPOSAL",endpoint:row.endpoint,task_id:row.proposal_task_id};
    const r=await processMessageResponse(env,msg,p.responseText);results.push({referralId:row.referral_id,kind:"COMMISSION_PROPOSAL",responseClass:r.type||"OTHER",legacy:true});
  }
  const rows=await env.DB.prepare("SELECT * FROM lumen_referral_commission_messages WHERE status='SENT' AND task_id IS NOT NULL ORDER BY sent_at ASC LIMIT 40").all();
  for(const msg of rows.results||[]){
    if(!safeHttps(msg.endpoint))continue;
    const p=await pollA2A(msg.endpoint,msg.task_id);if(!p.ok)continue;
    const text=clean(p.responseText,6000);if(!text)continue;
    const r=await processMessageResponse(env,msg,text);
    results.push({referralId:msg.referral_id,kind:msg.kind,responseClass:r.type||"OTHER"});
  }
  return{ok:true,version:VERSION,polled:results.length,results};
}

async function messageSummary(env,referralId,kind){
  const r=await env.DB.prepare("SELECT COUNT(*) n,MAX(sent_at) last_sent FROM lumen_referral_commission_messages WHERE referral_id=? AND kind=? AND status NOT IN ('SEND_FAILED')").bind(referralId,kind).first();
  return{count:Number(r?.n||0),lastSent:r?.last_sent||null};
}
async function sendTracked(env,{row,p,kind,sequence,message,state}){
  const send=await sendA2A(p.endpoint,message,row.referral_id,kind);
  const msg=await logMessage(env,{referralId:row.referral_id,kind,sequence,endpoint:p.endpoint,message,send});
  if(kind==="COMMISSION_PROPOSAL")await upsertAutopilot(env,row,p,send.ok?"PROPOSAL_SENT":"PROPOSAL_READY",send);
  else if(send.ok)await env.DB.prepare("UPDATE lumen_referral_commission_autopilot SET state=?,updated_at=?,error=NULL,engine_version=? WHERE referral_id=?").bind(state||row.commission_status||"TRACKING",new Date().toISOString(),VERSION,row.referral_id).run();
  if(send.responseText)await processMessageResponse(env,msg,send.responseText);
  return{ok:send.ok,sent:send.ok,externalAttempted:true,version:VERSION,referralId:row.referral_id,type:kind,sequence,maxExternalMessagesPerRun:MAX_EXTERNAL_MESSAGES_PER_RUN,error:send.ok?null:send.error};
}

async function chooseCollectionAction(env){
  const rows=await env.DB.prepare("SELECT r.id referral_id,r.direction,r.target_partner_id,r.origin_partner_id,r.title,c.status commission_status,c.deal_value_usd,c.agreed_amount_usd,c.checkout_url,a.endpoint,a.counterparty_partner_id,a.counterparty_name FROM lumen_referrals r JOIN lumen_referral_commissions c ON c.referral_id=r.id LEFT JOIN lumen_referral_commission_autopilot a ON a.referral_id=r.id WHERE c.status='PAYMENT_DUE' AND c.agreed_amount_usd>0 AND c.checkout_url IS NOT NULL ORDER BY c.payment_due_at ASC LIMIT 30").all();
  for(const row of rows.results||[]){
    const p=row.endpoint&&safeHttps(row.endpoint)?{id:row.counterparty_partner_id,name:row.counterparty_name,endpoint:row.endpoint}:await counterparty(env,row);
    if(!p)continue;
    const initial=await messageSummary(env,row.referral_id,"PAYMENT_REQUEST");
    if(initial.count===0)return{row,p,kind:"PAYMENT_REQUEST",sequence:1,message:paymentMessage(row,false),state:"PAYMENT_DUE"};
    const follow=await messageSummary(env,row.referral_id,"PAYMENT_FOLLOWUP");
    const last=follow.lastSent||initial.lastSent;
    if(follow.count<maxPaymentFollowups(env)&&olderThan(last,paymentCooldownDays(env)))return{row,p,kind:"PAYMENT_FOLLOWUP",sequence:follow.count+1,message:paymentMessage(row,true),state:"PAYMENT_DUE"};
  }
  return null;
}
async function chooseCloseAction(env){
  const rows=await env.DB.prepare("SELECT r.id referral_id,r.direction,r.target_partner_id,r.origin_partner_id,r.title,c.status commission_status,c.agreement_at,a.endpoint,a.counterparty_partner_id,a.counterparty_name,a.state autopilot_state FROM lumen_referrals r JOIN lumen_referral_commissions c ON c.referral_id=r.id LEFT JOIN lumen_referral_commission_autopilot a ON a.referral_id=r.id WHERE c.status='AGREED_PENDING_CLOSE' AND COALESCE(a.state,'AGREED_PENDING_CLOSE') NOT IN ('CLOSED_LOST','DECLINED','COUNTEROFFER_REVIEW') ORDER BY c.agreement_at ASC LIMIT 30").all();
  for(const row of rows.results||[]){
    const s=await messageSummary(env,row.referral_id,"CLOSE_CHECK");
    if(s.count>=maxCloseChecks(env))continue;
    if(s.count>0&&!olderThan(s.lastSent,closeCooldownDays(env)))continue;
    const p=row.endpoint&&safeHttps(row.endpoint)?{id:row.counterparty_partner_id,name:row.counterparty_name,endpoint:row.endpoint}:await counterparty(env,row);
    if(!p)continue;
    return{row,p,kind:"CLOSE_CHECK",sequence:s.count+1,message:closeCheckMessage(row),state:"AGREED_PENDING_CLOSE"};
  }
  return null;
}
async function chooseProposalAction(env){
  let row=null;
  try{row=await env.DB.prepare("SELECT r.id referral_id,r.direction,r.target_partner_id,r.origin_partner_id,r.title,r.estimated_value_usd,r.match_score,c.deal_value_usd,c.proposed_rate_pct,c.status commission_status FROM lumen_referrals r JOIN lumen_referral_commissions c ON c.referral_id=r.id LEFT JOIN lumen_referral_commission_autopilot a ON a.referral_id=r.id WHERE r.direction='OUTBOUND' AND c.status='PROPOSAL_READY' AND c.proposed_rate_pct=5 AND a.referral_id IS NULL AND r.trust_level IN ('ALLOW','CAUTION') ORDER BY r.match_score DESC,r.updated_at ASC LIMIT 1").first();}catch{}
  if(!row)return null;
  const p=await counterparty(env,row);if(!p)return null;
  return{row,p,kind:"COMMISSION_PROPOSAL",sequence:1,message:proposalMessage(row),state:"PROPOSAL_SENT"};
}

export async function runReferralCommissionAutopilot(env,{force=false}={}){
  if(!(await ensure(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  await pollReferralCommissionAutopilot(env);
  if(!force&&!enabled(env))return{ok:true,version:VERSION,sent:false,reason:"autonomous_outreach_disabled"};
  const action=await chooseCollectionAction(env)||await chooseCloseAction(env)||await chooseProposalAction(env);
  if(!action)return{ok:true,version:VERSION,sent:false,reason:"no_commission_action_due",standardRatePct:STANDARD_RATE_PCT};
  return sendTracked(env,action);
}

async function stats(env){
  await ensure(env);
  const r=await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN state='PROPOSAL_SENT' THEN 1 ELSE 0 END) proposal_sent,SUM(CASE WHEN state='AGREED_PENDING_CLOSE' THEN 1 ELSE 0 END) agreed,SUM(CASE WHEN state='PAYMENT_DUE' THEN 1 ELSE 0 END) payment_due,SUM(CASE WHEN state='CLOSED_LOST' THEN 1 ELSE 0 END) closed_lost,SUM(CASE WHEN state='COUNTEROFFER_REVIEW' THEN 1 ELSE 0 END) counteroffers,SUM(CASE WHEN state='DECLINED' THEN 1 ELSE 0 END) declined FROM lumen_referral_commission_autopilot").first();
  const m=await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN kind='COMMISSION_PROPOSAL' THEN 1 ELSE 0 END) proposals,SUM(CASE WHEN kind='CLOSE_CHECK' THEN 1 ELSE 0 END) close_checks,SUM(CASE WHEN kind='PAYMENT_REQUEST' THEN 1 ELSE 0 END) payment_requests,SUM(CASE WHEN kind='PAYMENT_FOLLOWUP' THEN 1 ELSE 0 END) payment_followups FROM lumen_referral_commission_messages").first();
  return{total:num(r?.total),proposalSent:num(r?.proposal_sent),agreedPendingClose:num(r?.agreed),paymentDue:num(r?.payment_due),closedLost:num(r?.closed_lost),counteroffersPendingReview:num(r?.counteroffers),declined:num(r?.declined),messages:{total:num(m?.total),proposals:num(m?.proposals),closeChecks:num(m?.close_checks),paymentRequests:num(m?.payment_requests),paymentFollowups:num(m?.payment_followups)}};
}

export async function handleReferralCommissionAutopilot(request,env){
  const u=new URL(request.url);
  if(request.method==="GET"&&u.pathname==="/referrals/commissions/autopilot/policy")return json({version:VERSION,standardSuccessFeePct:STANDARD_RATE_PCT,percentageFeeBasis:"final_confirmed_deal_value",estimatedDealValueRequiredForProposal:false,explicitAcceptanceRequired:true,exactAcceptancePhrase:true,closeEvidenceRequired:true,closeReportRequiresFinalValue:true,checkoutRail:"x402",exactAmountCheckout:true,revenueOnlyAfterVerifiedSettlement:true,counteroffersAutoAccepted:false,maxExternalMessagesPerRun:MAX_EXTERNAL_MESSAGES_PER_RUN,closeCheckCooldownDays:closeCooldownDays(env),maxCloseChecks:maxCloseChecks(env),paymentFollowupDays:paymentCooldownDays(env),maxPaymentFollowups:maxPaymentFollowups(env),autonomousSpend:false,automaticContract:false,priority:["PAYMENT_DUE_COLLECTION","CLOSE_TRACKING","NEW_COMMISSION_PROPOSAL"]});
  if(request.method==="GET"&&u.pathname==="/referrals/commissions/autopilot/stats")return json({version:VERSION,...await stats(env),autonomousEnabled:enabled(env)});
  if(request.method==="POST"&&u.pathname==="/referrals/commissions/autopilot/run"){if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);return json(await runReferralCommissionAutopilot(env,{force:false}),202);}
  if(request.method==="POST"&&u.pathname==="/referrals/commissions/autopilot/poll"){if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);return json(await pollReferralCommissionAutopilot(env),202);}
  return null;
}
