import { classifyCommercialResponse } from "./response-qualification.js";

const VERSION = "1.0-commercial-reply-engine";
const SEND_TIMEOUT_MS = 15000;

const OFFER_SCOPES = {
  "MP-SUPPLIER-SNAPSHOT": "a compact supplier verification snapshot",
  "MP-QUOTE-SANITY": "a quick sanity check of pricing and quotation structure",
  "MP-TENDER-SCAN": "a focused scan of tender fit, deadlines and commercial relevance",
  "MP-SOURCING-5": "a shortlist of five relevant suppliers with evidence",
  "MP-BUYER-SIGNALS": "an evidence-backed scan of buyer intent and demand signals",
  "MP-EXPORT-PULSE": "a compact export-market demand and channel pulse"
};

function json(data, status=200){return Response.json(data,{status,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function clean(value,limit=6000){return String(value??"").trim().replace(/\s+/g," ").slice(0,limit);}
function boolVar(value,fallback=false){const v=clean(value,20).toLowerCase();if(!v)return fallback;return ["1","true","yes","on"].includes(v);}
function authorized(request,env){const a=clean(env?.OPPORTUNITY_ADMIN_TOKEN,500),b=clean(request.headers.get("x-lumen-admin"),500);return Boolean(a&&b&&a===b);}
function isHttps(value){try{return new URL(value).protocol==="https:";}catch{return false;}}
function withTimeout(ms){const controller=new AbortController();const timer=setTimeout(()=>controller.abort("timeout"),ms);return{signal:controller.signal,clear:()=>clearTimeout(timer)};}

async function ensureSchema(env){
  if(!env?.DB)return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_commercial_replies (proposal_id TEXT PRIMARY KEY,opportunity_id TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,status TEXT NOT NULL,response_class TEXT NOT NULL,question_text TEXT,reply_text TEXT,task_id TEXT,context_id TEXT,response_text TEXT,error TEXT,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_commercial_replies_status ON lumen_commercial_replies(status,updated_at)")
  ]);
  return true;
}

async function candidateRows(env){
  const sql=`SELECT p.proposal_id,p.opportunity_id,p.offer_id,p.offer_name,p.amount_usd,p.message,o.name AS target,
    x.agent_url,x.protocol_binding,x.protocol_version,x.context_id,
    COALESCE((SELECT f.response_text FROM lumen_followups f WHERE f.proposal_id=p.proposal_id AND f.response_text IS NOT NULL AND TRIM(f.response_text)<>'' ORDER BY COALESCE(f.sent_at,f.updated_at) DESC LIMIT 1),x.response_text) AS response_text
    FROM lumen_proposal_drafts p
    JOIN lumen_opportunities o ON o.id=p.opportunity_id
    JOIN lumen_outreach_attempts x ON x.proposal_id=p.proposal_id
    LEFT JOIN lumen_commercial_replies r ON r.proposal_id=p.proposal_id
    WHERE p.quality_gate_status='PASS' AND r.proposal_id IS NULL AND x.agent_url IS NOT NULL
      AND (x.response_text IS NOT NULL OR EXISTS(SELECT 1 FROM lumen_followups f2 WHERE f2.proposal_id=p.proposal_id AND f2.response_text IS NOT NULL AND TRIM(f2.response_text)<>''))
    ORDER BY x.updated_at DESC LIMIT 100`;
  try{const r=await env.DB.prepare(sql).all();return r.results||[];}catch{return[];}
}

function questionType(text){
  const t=clean(text,8000).toLowerCase();
  if(["what is the price","what's the price","whats the price","how much","price?"].some(x=>t.includes(x)))return"PRICE";
  if(["what does it include","what is included","what's included","whats included","what is the scope","what's the scope","whats the scope"].some(x=>t.includes(x)))return"SCOPE";
  if(["how long","eta","turnaround","delivery time","when will","when can"].some(x=>t.includes(x)))return"ETA";
  if(["what do you need","what information","what info","requirements","from us","from me"].some(x=>t.includes(x)))return"INPUTS";
  if(["how does it work","how do you work","process","what happens next"].some(x=>t.includes(x)))return"PROCESS";
  return"GENERAL";
}

function replyFor(row){
  const type=questionType(row.response_text);
  const offer=clean(row.offer_name,160)||"this LUMEN service";
  const price=Number(row.amount_usd||0);
  const scope=OFFER_SCOPES[row.offer_id]||"the deliverable described in LUMEN's proposal";
  let answer;
  if(type==="PRICE") answer=`The price for ${offer} is USD ${price.toFixed(2)} per request.`;
  else if(type==="SCOPE") answer=`${offer} includes ${scope}.`;
  else if(type==="ETA") answer=`LUMEN does not promise a fixed turnaround before the exact scope is confirmed. Once you send the requirement, LUMEN can confirm the deliverable and timing before checkout.`;
  else if(type==="INPUTS") answer=`Please send the requirement you want checked plus any constraints that materially affect the result (for example target market, product/specification, supplier context, quotation or tender details). LUMEN will confirm the exact deliverable before checkout.`;
  else if(type==="PROCESS") answer=`The flow is: you send the requirement, LUMEN confirms the exact deliverable, then provides the exact x402 checkout for ${offer}. Work is treated as purchased only after payment settlement succeeds.`;
  else answer=`${offer} is USD ${price.toFixed(2)} per request and delivers ${scope}. If you send the exact requirement, LUMEN can confirm whether it fits and clarify the deliverable before checkout.`;
  return clean(`${answer}\n\nThis reply is informational and non-binding. It does not create an order, payment, contract, exclusivity or commitment.`,2200);
}

async function findCandidate(env){
  for(const row of await candidateRows(env)){
    const c=classifyCommercialResponse(row.response_text,row.message);
    if(c.responseClass!=="COMMERCIAL_QUESTION")continue;
    if(!isHttps(row.agent_url))continue;
    return{...row,classification:c,replyText:replyFor(row)};
  }
  return null;
}

function envelope(row,text){
  const id=`lumen-commercial-reply-${crypto.randomUUID()}`;
  const version=clean(row.protocol_version,20)||"0.3.0";
  const isV1=version.startsWith("1.");
  const message={messageId:id,role:isV1?"ROLE_USER":"user",parts:[{text}]};
  const metadata={lumen:{proposalId:row.proposal_id,opportunityId:row.opportunity_id,offerId:row.offer_id,amountUsd:Number(row.amount_usd||0),stage:"commercial_question_reply",responseClass:"COMMERCIAL_QUESTION"}};
  if(clean(row.protocol_binding,40).toUpperCase()==="HTTP+JSON")return{url:`${clean(row.agent_url,1000).replace(/\/$/,"")}/message:send`,headers:{"content-type":"application/a2a+json","accept":"application/a2a+json, application/json","a2a-version":version},payload:{message,metadata}};
  return{url:row.agent_url,headers:{"content-type":"application/json","accept":"application/json","a2a-version":version},payload:{jsonrpc:"2.0",id,method:isV1?"SendMessage":"message/send",params:{message,metadata}}};
}

function extractResponse(body,binding){
  const value=clean(binding,40).toUpperCase()==="JSONRPC"?(body?.result||body||{}):(body||{});
  const task=value?.task||(value?.id&&value?.status?value:null);const message=value?.message||null;
  const parts=message?.parts||task?.status?.message?.parts||task?.artifacts?.flatMap?.(a=>a?.parts||[])||[];
  return{taskId:clean(task?.id,300)||null,contextId:clean(task?.contextId,300)||clean(message?.contextId,300)||null,responseText:clean((Array.isArray(parts)?parts:[]).map(p=>p?.text||"").filter(Boolean).join(" "),5000)||null};
}

async function record(env,row,values){
  const now=new Date().toISOString();
  await env.DB.prepare("INSERT INTO lumen_commercial_replies(proposal_id,opportunity_id,created_at,updated_at,status,response_class,question_text,reply_text,task_id,context_id,response_text,error,engine_version) VALUES(?,?,?,?,?,'COMMERCIAL_QUESTION',?,?,?,?,?,?,?) ON CONFLICT(proposal_id) DO UPDATE SET updated_at=excluded.updated_at,status=excluded.status,reply_text=excluded.reply_text,task_id=excluded.task_id,context_id=excluded.context_id,response_text=excluded.response_text,error=excluded.error,engine_version=excluded.engine_version")
    .bind(row.proposal_id,row.opportunity_id,now,now,values.status,clean(row.response_text,5000),row.replyText,values.taskId||null,values.contextId||null,values.responseText||null,values.error||null,VERSION).run();
}

export async function runCommercialReplyEngine(env,{force=false}={}){
  if(!(await ensureSchema(env)))return{ok:false,sent:false,error:"persistence_unavailable",version:VERSION};
  const candidate=await findCandidate(env);
  if(!candidate)return{ok:true,sent:false,reason:"no_commercial_question_waiting",version:VERSION};
  const enabled=boolVar(env?.A2A_AUTONOMOUS_OUTREACH,false)&&boolVar(env?.A2A_AUTONOMOUS_COMMERCIAL_REPLY,false);
  if(!force&&!enabled)return{ok:true,sent:false,ready:true,proposalId:candidate.proposal_id,reason:"autonomous_commercial_reply_disabled",version:VERSION};
  const req=envelope(candidate,candidate.replyText);const timeout=withTimeout(SEND_TIMEOUT_MS);let raw="";
  try{
    const response=await fetch(req.url,{method:"POST",headers:req.headers,body:JSON.stringify(req.payload),signal:timeout.signal});raw=await response.text();
    if(!response.ok)throw new Error(`commercial_reply_http_${response.status}`);
    let body={};try{body=JSON.parse(raw);}catch{}
    const info=extractResponse(body,candidate.protocol_binding);const status=info.responseText?"RESPONDED":info.taskId?"SENT_TASK":"SENT";
    await record(env,candidate,{status,...info});
    return{ok:true,sent:true,version:VERSION,proposalId:candidate.proposal_id,opportunityId:candidate.opportunity_id,offerId:candidate.offer_id,status,taskId:info.taskId,questionType:questionType(candidate.response_text),guardrails:{commercialQuestionOnly:true,oneReplyPerProposal:true,knownOfferFactsOnly:true,unknownEtaNotInvented:true,autonomousDiscounting:false,autonomousSpend:false,autonomousContract:false,bindingActionsHumanGated:true}};
  }catch(error){const err=clean(error?.message||error,500);await record(env,candidate,{status:"SEND_FAILED",error:err});return{ok:false,sent:false,version:VERSION,proposalId:candidate.proposal_id,status:"SEND_FAILED",error:err};}
  finally{timeout.clear();}
}

async function statsData(env){
  await ensureSchema(env);let row=null;try{row=await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN status IN ('SENT','SENT_TASK','RESPONDED') THEN 1 ELSE 0 END) sent,SUM(CASE WHEN status='RESPONDED' THEN 1 ELSE 0 END) responded,SUM(CASE WHEN status='SEND_FAILED' THEN 1 ELSE 0 END) failed FROM lumen_commercial_replies").first();}catch{}
  const candidate=await findCandidate(env);
  return{total:Number(row?.total||0),sent:Number(row?.sent||0),responded:Number(row?.responded||0),failed:Number(row?.failed||0),readyToReply:Boolean(candidate),readyProposalId:candidate?.proposal_id||null,autonomousEnabled:boolVar(env?.A2A_AUTONOMOUS_OUTREACH,false)&&boolVar(env?.A2A_AUTONOMOUS_COMMERCIAL_REPLY,false)};
}

export async function handleCommercialReplyEngine(request,env){
  const url=new URL(request.url);
  if(request.method==="GET"&&url.pathname==="/commercial-reply/policy")return json({version:VERSION,name:"LUMEN Commercial Reply Engine",handles:["COMMERCIAL_QUESTION"],purchaseIntentHandledBy:"First Cash Closer",knownOfferFactsOnly:true,unknownEtaNotInvented:true,maxExternalMessagesPerRun:1,oneReplyPerProposal:true,autonomousDiscounting:false,autonomousSpend:false,autonomousContract:false,bindingActionsHumanGated:true});
  if(request.method==="GET"&&url.pathname==="/commercial-reply/stats")return json({version:VERSION,...await statsData(env)});
  if(request.method==="POST"&&url.pathname==="/commercial-reply/run"){if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);return json(await runCommercialReplyEngine(env,{force:false}),202);}
  return null;
}
