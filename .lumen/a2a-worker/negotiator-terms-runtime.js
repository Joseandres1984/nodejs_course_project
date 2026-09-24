const VERSION = "1.0-negotiator-terms-runtime";
const CARD_TIMEOUT_MS = 8000;
const SEND_TIMEOUT_MS = 15000;
const MAX_MESSAGES_PER_CASE = 2;

function json(data,status=200){return Response.json(data,{status,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function clean(v,n=6000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}
function authorized(request,env){const a=clean(env?.OPPORTUNITY_ADMIN_TOKEN,500),b=clean(request.headers.get("x-lumen-admin"),500);return Boolean(a&&b&&a===b);}
function isHttps(v){try{return new URL(v).protocol==="https:";}catch{return false;}}
function normalizeBaseUrl(v){const u=new URL(v);u.hash="";u.search="";return u.toString().replace(/\/$/,"");}
function timeout(ms){const c=new AbortController();const t=setTimeout(()=>c.abort("timeout"),ms);return{signal:c.signal,clear:()=>clearTimeout(t)};}
async function sha256(text){const d=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(String(text)));return[...new Uint8Array(d)].map(b=>b.toString(16).padStart(2,"0")).join("");}

async function ensure(env){
  if(!env?.DB)return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_negotiation_terms (id TEXT PRIMARY KEY,partner_id TEXT NOT NULL,opportunity_id TEXT,source TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,price_usd REAL,eta_hours REAL,scope TEXT,terms_text TEXT,evidence TEXT,status TEXT NOT NULL DEFAULT 'DECLARED_UNVERIFIED',binding_allowed INTEGER NOT NULL DEFAULT 0,spend_allowed INTEGER NOT NULL DEFAULT 0,UNIQUE(partner_id,opportunity_id,source))"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_negotiation_exchanges (id TEXT PRIMARY KEY,request_id TEXT NOT NULL UNIQUE,case_id TEXT NOT NULL,opportunity_id TEXT NOT NULL,partner_id TEXT NOT NULL,partner_name TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,status TEXT NOT NULL,protocol_binding TEXT,protocol_version TEXT,agent_url TEXT,task_id TEXT,context_id TEXT,request_json TEXT,response_json TEXT,response_text TEXT,price_usd REAL,eta_hours REAL,http_status INTEGER,error TEXT,external_message_sent INTEGER NOT NULL DEFAULT 0,sent_at TEXT,polled_at TEXT,binding_allowed INTEGER NOT NULL DEFAULT 0,spend_allowed INTEGER NOT NULL DEFAULT 0,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_negotiation_exchanges_status ON lumen_negotiation_exchanges(status,updated_at)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_negotiation_exchanges_case ON lumen_negotiation_exchanges(case_id,external_message_sent,updated_at)")
  ]);
  return true;
}

function priceFromText(text){
  const t=clean(text,9000);if(!t)return null;
  const patterns=[/(?:price|pricing|fee|cost|rate|charge|quote)[^\d$]{0,35}(?:usd|usdc|\$)\s*([0-9]+(?:[.,][0-9]{1,2})?)/i,/(?:usd|usdc|\$)\s*([0-9]+(?:[.,][0-9]{1,2})?)/i,/([0-9]+(?:[.,][0-9]{1,2})?)\s*(?:usd|usdc)\b/i];
  for(const p of patterns){const m=t.match(p);if(m){const n=Number(String(m[1]).replace(",","."));if(Number.isFinite(n)&&n>=0&&n<=1000000)return n;}}
  return null;
}
function etaFromText(text){
  const t=clean(text,9000);if(!t)return null;
  let m=t.match(/(?:eta|turnaround|delivery(?: time)?|deliver(?:y|ed)?|ready in|within)[^0-9]{0,25}([0-9]+(?:\.[0-9]+)?)\s*(hours?|hrs?|h)\b/i);if(m){const n=Number(m[1]);if(Number.isFinite(n)&&n>0&&n<=8760)return n;}
  m=t.match(/(?:eta|turnaround|delivery(?: time)?|deliver(?:y|ed)?|ready in|within)[^0-9]{0,25}([0-9]+(?:\.[0-9]+)?)\s*(days?|d)\b/i);if(m){const n=Number(m[1])*24;if(Number.isFinite(n)&&n>0&&n<=8760)return n;}
  return null;
}

function hasRequiredAuth(card){const req=card?.securityRequirements;if(Array.isArray(req)&&req.length)return true;const legacy=card?.security;return Array.isArray(legacy)&&legacy.length>0;}
function selectInterface(card){
  const interfaces=Array.isArray(card?.supportedInterfaces)?card.supportedInterfaces:Array.isArray(card?.supported_interfaces)?card.supported_interfaces:[];
  for(const x of interfaces){const binding=clean(x?.protocolBinding||x?.binding||x?.transport,80).toUpperCase();if(!isHttps(x?.url))continue;if(["JSONRPC","JSON-RPC","HTTP+JSON"].includes(binding))return{url:normalizeBaseUrl(x.url),binding:binding==="HTTP+JSON"?"HTTP+JSON":"JSONRPC",version:clean(x?.protocolVersion||x?.protocol_version||card?.protocolVersion||"1.0",20),tenant:clean(x?.tenant,200)||null};}
  if(isHttps(card?.url)){const binding=clean(card?.preferredTransport||card?.transport||"JSONRPC",80).toUpperCase();if(["JSONRPC","JSON-RPC","HTTP+JSON"].includes(binding))return{url:normalizeBaseUrl(card.url),binding:binding==="HTTP+JSON"?"HTTP+JSON":"JSONRPC",version:clean(card?.protocolVersion||"0.3",20),tenant:null};}
  return null;
}
async function fetchCard(url){
  if(!isHttps(url))return{ok:false,status:"INCOMPATIBLE",error:"card_url_not_https"};
  const t=timeout(CARD_TIMEOUT_MS);
  try{const r=await fetch(url,{headers:{accept:"application/json, application/a2a+json"},signal:t.signal});const text=await r.text();if(!r.ok)return{ok:false,status:"CARD_FETCH_FAILED",error:`card_http_${r.status}`,raw:clean(text,2000)};let card;try{card=JSON.parse(text);}catch{return{ok:false,status:"CARD_FETCH_FAILED",error:"card_invalid_json"};}if(hasRequiredAuth(card))return{ok:false,status:"AUTH_REQUIRED",error:"agent_requires_authentication",card};const selected=selectInterface(card);if(!selected)return{ok:false,status:"INCOMPATIBLE",error:"no_supported_public_a2a_interface",card};return{ok:true,status:"READY",card,selected};}catch(e){return{ok:false,status:"CARD_FETCH_FAILED",error:clean(e?.message||e,300)};}finally{t.clear();}
}

function envelope(row,iface){
  const messageId=`lumen-terms-${crypto.randomUUID()}`;const v1=String(iface.version||"").startsWith("1.");
  const message={messageId,role:v1?"ROLE_USER":"user",parts:[{text:row.request_text}]};
  const metadata={lumen:{type:"negotiation_terms_request",requestId:row.request_id,caseId:row.case_id,opportunityId:row.opportunity_id,nonBinding:true,exploratory:true,spendAllowed:false,purchaseAllowed:false,contractAllowed:false}};
  if(iface.binding==="HTTP+JSON"){const payload={message,metadata};if(iface.tenant)payload.tenant=iface.tenant;return{messageId,url:`${iface.url}/message:send`,headers:{"content-type":"application/a2a+json",accept:"application/a2a+json, application/json","a2a-version":iface.version||"1.0"},payload};}
  const params={message,metadata};if(iface.tenant)params.tenant=iface.tenant;
  return{messageId,url:iface.url,headers:{"content-type":"application/json",accept:"application/json","a2a-version":iface.version||(v1?"1.0":"0.3")},payload:{jsonrpc:"2.0",id:messageId,method:v1?"SendMessage":"message/send",params}};
}
function extract(body){
  const value=body?.result||body||{};const task=value?.task||(value?.id&&value?.status?value:null);const msg=value?.message||(Array.isArray(value?.parts)&&value?.role?value:null);
  const taskId=clean(task?.id,300)||null;const contextId=clean(task?.contextId,300)||clean(msg?.contextId,300)||null;const state=clean(task?.status?.state,100)||null;
  const parts=msg?.parts||task?.status?.message?.parts||task?.artifacts?.flatMap?.(a=>a?.parts||[])||[];const responseText=clean((Array.isArray(parts)?parts:[]).map(p=>p?.text||p?.data?.text||"").filter(Boolean).join(" "),6000)||null;
  return{taskId,contextId,state,responseText};
}
async function upsertTerms(env,row,text,source="negotiator_response"){
  const price=priceFromText(text),eta=etaFromText(text);if(price==null&&eta==null)return{stored:false,priceUsd:null,etaHours:null};
  const now=new Date().toISOString();const id=`NGT-${(await sha256(`${row.partner_id}|${row.opportunity_id}|${source}`)).slice(0,18).toUpperCase()}`;
  await env.DB.prepare("INSERT INTO lumen_negotiation_terms(id,partner_id,opportunity_id,source,created_at,updated_at,price_usd,eta_hours,scope,terms_text,evidence,status,binding_allowed,spend_allowed) VALUES(?,?,?,?,?,?,?,?,?,?,?,'DECLARED_UNVERIFIED',0,0) ON CONFLICT(partner_id,opportunity_id,source) DO UPDATE SET updated_at=excluded.updated_at,price_usd=COALESCE(excluded.price_usd,lumen_negotiation_terms.price_usd),eta_hours=COALESCE(excluded.eta_hours,lumen_negotiation_terms.eta_hours),terms_text=excluded.terms_text,evidence=excluded.evidence,status='DECLARED_UNVERIFIED',binding_allowed=0,spend_allowed=0")
    .bind(id,row.partner_id,row.opportunity_id,source,now,now,price,eta,clean(row.title,1000)||null,clean(text,4500),`a2a_nonbinding_terms_request:${row.request_id}`).run();
  return{stored:true,priceUsd:price,etaHours:eta};
}

async function readyRequests(env,limit){
  const r=await env.DB.prepare("SELECT q.id request_id,q.case_id,q.partner_id,q.partner_name,q.request_text,q.target_card_url,q.target_endpoint,q.trust_level,q.trust_score,c.opportunity_id,c.title,n.total_score,n.declared_price_usd,n.eta_hours FROM lumen_negotiation_requests q JOIN lumen_negotiation_cases c ON c.id=q.case_id JOIN lumen_negotiation_candidates n ON n.case_id=q.case_id AND n.partner_id=q.partner_id WHERE q.status='DRAFT' AND q.external_message_sent=0 AND c.status='RANKED_INCOMPLETE_TERMS' AND (n.declared_price_usd IS NULL OR n.eta_hours IS NULL) AND q.trust_level IN ('ALLOW','CAUTION') AND (SELECT COALESCE(SUM(q2.external_message_sent),0) FROM lumen_negotiation_requests q2 WHERE q2.case_id=q.case_id) < ? ORDER BY c.commercial_score DESC,n.total_score DESC,n.data_completeness DESC LIMIT ?").bind(MAX_MESSAGES_PER_CASE,Math.min(MAX_MESSAGES_PER_CASE,Math.max(1,Number(limit)||1))).all();
  return r.results||[];
}
async function recordProbeFailure(env,row,probe){const now=new Date().toISOString(),id=`NEX-${(await sha256(row.request_id)).slice(0,18).toUpperCase()}`;await env.DB.prepare("INSERT INTO lumen_negotiation_exchanges(id,request_id,case_id,opportunity_id,partner_id,partner_name,created_at,updated_at,status,error,external_message_sent,binding_allowed,spend_allowed,engine_version) VALUES(?,?,?,?,?,?,?, ?,?,?,0,0,0,?) ON CONFLICT(request_id) DO UPDATE SET updated_at=excluded.updated_at,status=excluded.status,error=excluded.error,engine_version=excluded.engine_version").bind(id,row.request_id,row.case_id,row.opportunity_id,row.partner_id,row.partner_name,now,now,probe.status,probe.error,VERSION).run();await env.DB.prepare("UPDATE lumen_negotiation_requests SET updated_at=?,status=? WHERE id=? AND external_message_sent=0").bind(now,probe.status,row.request_id).run();}

async function sendOne(env,row){
  const probe=await fetchCard(row.target_card_url||row.target_endpoint);if(!probe.ok){await recordProbeFailure(env,row,probe);return{ok:false,sent:false,requestId:row.request_id,target:row.partner_name,status:probe.status,error:probe.error};}
  const e=envelope(row,probe.selected),t=timeout(SEND_TIMEOUT_MS);let raw="",http=0;
  try{
    const resp=await fetch(e.url,{method:"POST",headers:e.headers,body:JSON.stringify(e.payload),signal:t.signal});http=resp.status;raw=await resp.text();if(!resp.ok)throw new Error(`send_http_${resp.status}`);
    let body={};try{body=JSON.parse(raw);}catch{}const info=extract(body),now=new Date().toISOString();const terms=info.responseText?await upsertTerms(env,row,info.responseText):{stored:false,priceUsd:null,etaHours:null};
    const status=info.responseText?(terms.stored?"RESPONDED_TERMS":"RESPONDED_INCOMPLETE"):info.taskId?"SENT_TASK":"SENT";const id=`NEX-${(await sha256(row.request_id)).slice(0,18).toUpperCase()}`;
    await env.DB.prepare("INSERT INTO lumen_negotiation_exchanges(id,request_id,case_id,opportunity_id,partner_id,partner_name,created_at,updated_at,status,protocol_binding,protocol_version,agent_url,task_id,context_id,request_json,response_json,response_text,price_usd,eta_hours,http_status,error,external_message_sent,sent_at,polled_at,binding_allowed,spend_allowed,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,NULL,0,0,?) ON CONFLICT(request_id) DO UPDATE SET updated_at=excluded.updated_at,status=excluded.status,protocol_binding=excluded.protocol_binding,protocol_version=excluded.protocol_version,agent_url=excluded.agent_url,task_id=excluded.task_id,context_id=excluded.context_id,request_json=excluded.request_json,response_json=excluded.response_json,response_text=excluded.response_text,price_usd=excluded.price_usd,eta_hours=excluded.eta_hours,http_status=excluded.http_status,error=NULL,external_message_sent=1,sent_at=excluded.sent_at,binding_allowed=0,spend_allowed=0,engine_version=excluded.engine_version")
      .bind(id,row.request_id,row.case_id,row.opportunity_id,row.partner_id,row.partner_name,now,now,status,probe.selected.binding,probe.selected.version,probe.selected.url,info.taskId,info.contextId,JSON.stringify(e.payload),clean(raw,12000),info.responseText,terms.priceUsd,terms.etaHours,http,null,now,VERSION).run();
    await env.DB.prepare("UPDATE lumen_negotiation_requests SET updated_at=?,status=?,external_message_sent=1,binding_allowed=0,spend_allowed=0 WHERE id=?").bind(now,status,row.request_id).run();
    return{ok:true,sent:true,requestId:row.request_id,caseId:row.case_id,target:row.partner_name,status,taskId:info.taskId,responseText:info.responseText,priceUsd:terms.priceUsd,etaHours:terms.etaHours,guardrails:{nonBinding:true,spendAllowed:false,purchaseAllowed:false,contractAllowed:false}};
  }catch(err){const now=new Date().toISOString(),msg=clean(err?.message||err,500),id=`NEX-${(await sha256(row.request_id)).slice(0,18).toUpperCase()}`;await env.DB.prepare("INSERT INTO lumen_negotiation_exchanges(id,request_id,case_id,opportunity_id,partner_id,partner_name,created_at,updated_at,status,response_json,http_status,error,external_message_sent,binding_allowed,spend_allowed,engine_version) VALUES(?,?,?,?,?,?,?,?,'SEND_FAILED',?,?,?,0,0,0,?) ON CONFLICT(request_id) DO UPDATE SET updated_at=excluded.updated_at,status='SEND_FAILED',response_json=excluded.response_json,http_status=excluded.http_status,error=excluded.error,engine_version=excluded.engine_version").bind(id,row.request_id,row.case_id,row.opportunity_id,row.partner_id,row.partner_name,now,now,clean(raw,12000),http,`${msg}${http?`;http=${http}:""}`,VERSION).run();await env.DB.prepare("UPDATE lumen_negotiation_requests SET updated_at=?,status='SEND_FAILED' WHERE id=? AND external_message_sent=0").bind(now,row.request_id).run();return{ok:false,sent:false,requestId:row.request_id,target:row.partner_name,status:"SEND_FAILED",error:msg};}finally{t.clear();}
}

export async function sendNegotiationTermRequests(env,{force=false,limit=1}={}){
  if(!(await ensure(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};const enabled=String(env?.A2A_AUTONOMOUS_NEGOTIATION_TERMS||"false").toLowerCase()==="true";
  if(!force&&!enabled)return{ok:true,sent:0,reason:"autonomous_negotiation_terms_disabled",version:VERSION,guardrails:{maxMessagesPerCase:MAX_MESSAGES_PER_CASE,autonomousNegotiationMessages:false,autonomousSpend:false,bindingActionsHumanGated:true}};
  const rows=await readyRequests(env,limit),results=[];for(const row of rows)results.push(await sendOne(env,row));
  return{ok:true,version:VERSION,attempted:rows.length,sent:results.filter(x=>x.sent).length,results,guardrails:{maxMessagesPerCase:MAX_MESSAGES_PER_CASE,nonBindingOnly:true,autonomousSpend:false,autonomousPurchase:false,autonomousContract:false,bindingActionsHumanGated:true}};
}

async function pollOne(env,row){
  if(!row.task_id||!row.agent_url)return{polled:false,requestId:row.request_id};const v1=String(row.protocol_version||"").startsWith("1."),t=timeout(SEND_TIMEOUT_MS);let raw="",http=0;
  try{let resp;if(row.protocol_binding==="HTTP+JSON")resp=await fetch(`${normalizeBaseUrl(row.agent_url)}/tasks/${encodeURIComponent(row.task_id)}`,{headers:{accept:"application/a2a+json, application/json","a2a-version":row.protocol_version||"1.0"},signal:t.signal});else{const payload={jsonrpc:"2.0",id:`lumen-terms-poll-${crypto.randomUUID()}`,method:v1?"GetTask":"tasks/get",params:{id:row.task_id}};resp=await fetch(row.agent_url,{method:"POST",headers:{"content-type":"application/json",accept:"application/json","a2a-version":row.protocol_version||(v1?"1.0":"0.3")},body:JSON.stringify(payload),signal:t.signal});}http=resp.status;raw=await resp.text();if(!resp.ok)throw new Error(`poll_http_${resp.status}`);let body={};try{body=JSON.parse(raw);}catch{}const info=extract(body),now=new Date().toISOString();let status="WORKING",terms={stored:false,priceUsd:null,etaHours:null};if(info.responseText){terms=await upsertTerms(env,row,info.responseText);status=terms.stored?"RESPONDED_TERMS":"RESPONDED_INCOMPLETE";}else if(["completed","failed","canceled","cancelled","rejected"].includes(clean(info.state,40).toLowerCase()))status=`TASK_${clean(info.state,40).toUpperCase()}`;await env.DB.prepare("UPDATE lumen_negotiation_exchanges SET updated_at=?,status=?,response_json=?,response_text=COALESCE(?,response_text),price_usd=COALESCE(?,price_usd),eta_hours=COALESCE(?,eta_hours),http_status=?,error=NULL,polled_at=?,engine_version=? WHERE request_id=?").bind(now,status,clean(raw,12000),info.responseText,terms.priceUsd,terms.etaHours,http,now,VERSION,row.request_id).run();await env.DB.prepare("UPDATE lumen_negotiation_requests SET updated_at=?,status=? WHERE id=?").bind(now,status,row.request_id).run();return{polled:true,requestId:row.request_id,target:row.partner_name,status,responseText:info.responseText,priceUsd:terms.priceUsd,etaHours:terms.etaHours};}catch(err){const now=new Date().toISOString(),msg=clean(err?.message||err,500);await env.DB.prepare("UPDATE lumen_negotiation_exchanges SET updated_at=?,error=?,http_status=?,polled_at=?,engine_version=? WHERE request_id=?").bind(now,msg,http,now,VERSION,row.request_id).run();return{polled:true,requestId:row.request_id,target:row.partner_name,status:"POLL_FAILED",error:msg};}finally{t.clear();}
}
export async function pollNegotiationTermResponses(env){
  if(!(await ensure(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};const r=await env.DB.prepare("SELECT e.request_id,e.case_id,e.opportunity_id,e.partner_id,e.partner_name,e.protocol_binding,e.protocol_version,e.agent_url,e.task_id,c.title FROM lumen_negotiation_exchanges e JOIN lumen_negotiation_cases c ON c.id=e.case_id WHERE e.external_message_sent=1 AND e.task_id IS NOT NULL AND e.status IN ('SENT_TASK','WORKING') ORDER BY e.updated_at ASC LIMIT 8").all();const results=[];for(const row of r.results||[])results.push(await pollOne(env,row));return{ok:true,version:VERSION,polled:results.length,results};
}

async function stats(env){
  await ensure(env);const r=await env.DB.prepare("SELECT COUNT(*) total,COALESCE(SUM(external_message_sent),0) sent,SUM(CASE WHEN status='RESPONDED_TERMS' THEN 1 ELSE 0 END) responded_terms,SUM(CASE WHEN price_usd IS NOT NULL THEN 1 ELSE 0 END) priced,SUM(CASE WHEN eta_hours IS NOT NULL THEN 1 ELSE 0 END) timed,SUM(CASE WHEN status='SENT_TASK' OR status='WORKING' THEN 1 ELSE 0 END) pending_tasks FROM lumen_negotiation_exchanges").first();return json({version:VERSION,total:Number(r?.total||0),externalMessagesSent:Number(r?.sent||0),responsesWithTerms:Number(r?.responded_terms||0),pricedResponses:Number(r?.priced||0),timedResponses:Number(r?.timed||0),pendingTasks:Number(r?.pending_tasks||0),maxMessagesPerCase:MAX_MESSAGES_PER_CASE,autonomousNegotiationMessages:String(env?.A2A_AUTONOMOUS_NEGOTIATION_TERMS||"false").toLowerCase()==="true",autonomousSpend:false,autonomousPurchase:false,autonomousContract:false,bindingActionsHumanGated:true});
}

export async function handleNegotiatorTermsRuntime(request,env){
  const u=new URL(request.url);if(request.method==='GET'&&u.pathname==='/negotiator/terms-runtime/stats')return stats(env);
  if(request.method==='POST'&&u.pathname==='/negotiator/terms-runtime/send'){if(!authorized(request,env))return json({ok:false,error:'admin_token_required'},403);let body={};try{body=await request.json();}catch{}if(body?.confirmNonBinding!==true)return json({ok:false,error:'confirmNonBinding_required'},400);return json(await sendNegotiationTermRequests(env,{force:true,limit:Math.min(MAX_MESSAGES_PER_CASE,Math.max(1,Number(body?.limit)||1))}),202);}
  if(request.method==='POST'&&u.pathname==='/negotiator/terms-runtime/poll'){if(!authorized(request,env))return json({ok:false,error:'admin_token_required'},403);return json(await pollNegotiationTermResponses(env),202);}
  if(request.method==='GET'&&u.pathname==='/negotiator/terms-runtime/exchanges'){if(!authorized(request,env))return json({ok:false,error:'admin_token_required'},403);await ensure(env);const r=await env.DB.prepare("SELECT request_id,case_id,partner_id,partner_name,status,protocol_binding,protocol_version,task_id,response_text,price_usd,eta_hours,http_status,error,external_message_sent,sent_at,polled_at,updated_at FROM lumen_negotiation_exchanges ORDER BY updated_at DESC LIMIT 100").all();return json({version:VERSION,exchanges:r.results||[]});}
  return null;
}
