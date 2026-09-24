const VERSION="1.0-negotiator-terms-runtime";
const MAX_MESSAGES_PER_CASE=2;
const TIMEOUT_MS=15000;

function json(d,s=200){return Response.json(d,{status:s,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function clean(v,n=6000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}
function authorized(r,e){const a=clean(e?.OPPORTUNITY_ADMIN_TOKEN,500),b=clean(r.headers.get("x-lumen-admin"),500);return Boolean(a&&b&&a===b);}
function isHttps(v){try{return new URL(v).protocol==="https:";}catch{return false;}}
function baseUrl(v){const u=new URL(v);u.hash="";u.search="";return u.toString().replace(/\/$/,"");}
function timer(){const c=new AbortController(),t=setTimeout(()=>c.abort("timeout"),TIMEOUT_MS);return{signal:c.signal,done:()=>clearTimeout(t)};}
async function hash(s){const d=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(String(s)));return[...new Uint8Array(d)].map(b=>b.toString(16).padStart(2,"0")).join("");}

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
  const t=clean(text,9000);
  for(const p of [/(?:price|pricing|fee|cost|rate|charge|quote)[^\d$]{0,35}(?:usd|usdc|\$)\s*([0-9]+(?:[.,][0-9]{1,2})?)/i,/(?:usd|usdc|\$)\s*([0-9]+(?:[.,][0-9]{1,2})?)/i,/([0-9]+(?:[.,][0-9]{1,2})?)\s*(?:usd|usdc)\b/i]){
    const m=t.match(p);if(m){const n=Number(m[1].replace(",","."));if(Number.isFinite(n)&&n>=0&&n<=1e6)return n;}
  }
  return null;
}
function etaFromText(text){
  const t=clean(text,9000);
  let m=t.match(/(?:eta|turnaround|delivery(?: time)?|ready in|within)[^0-9]{0,25}([0-9]+(?:\.[0-9]+)?)\s*(hours?|hrs?|h)\b/i);
  if(m){const n=Number(m[1]);if(Number.isFinite(n)&&n>0&&n<=8760)return n;}
  m=t.match(/(?:eta|turnaround|delivery(?: time)?|ready in|within)[^0-9]{0,25}([0-9]+(?:\.[0-9]+)?)\s*(days?|d)\b/i);
  if(m){const n=Number(m[1])*24;if(Number.isFinite(n)&&n>0&&n<=8760)return n;}
  return null;
}
function authRequired(card){return(Array.isArray(card?.securityRequirements)&&card.securityRequirements.length>0)||(Array.isArray(card?.security)&&card.security.length>0);}
function selectInterface(card){
  const xs=Array.isArray(card?.supportedInterfaces)?card.supportedInterfaces:Array.isArray(card?.supported_interfaces)?card.supported_interfaces:[];
  for(const x of xs){const b=clean(x?.protocolBinding||x?.binding||x?.transport,80).toUpperCase();if(isHttps(x?.url)&&["JSONRPC","JSON-RPC","HTTP+JSON"].includes(b))return{url:baseUrl(x.url),binding:b==="HTTP+JSON"?"HTTP+JSON":"JSONRPC",version:clean(x?.protocolVersion||x?.protocol_version||card?.protocolVersion||"1.0",20),tenant:clean(x?.tenant,200)||null};}
  if(isHttps(card?.url)){const b=clean(card?.preferredTransport||card?.transport||"JSONRPC",80).toUpperCase();if(["JSONRPC","JSON-RPC","HTTP+JSON"].includes(b))return{url:baseUrl(card.url),binding:b==="HTTP+JSON"?"HTTP+JSON":"JSONRPC",version:clean(card?.protocolVersion||"0.3",20),tenant:null};}
  return null;
}
async function probe(url){
  if(!isHttps(url))return{ok:false,status:"INCOMPATIBLE",error:"card_url_not_https"};
  const t=timer();
  try{const r=await fetch(url,{headers:{accept:"application/json, application/a2a+json"},signal:t.signal}),raw=await r.text();if(!r.ok)return{ok:false,status:"CARD_FETCH_FAILED",error:`card_http_${r.status}`};let card;try{card=JSON.parse(raw);}catch{return{ok:false,status:"CARD_FETCH_FAILED",error:"card_invalid_json"};}if(authRequired(card))return{ok:false,status:"AUTH_REQUIRED",error:"agent_requires_authentication"};const iface=selectInterface(card);if(!iface)return{ok:false,status:"INCOMPATIBLE",error:"no_supported_public_a2a_interface"};return{ok:true,iface};}catch(e){return{ok:false,status:"CARD_FETCH_FAILED",error:clean(e?.message||e,300)};}finally{t.done();}
}
function envelope(row,iface){
  const id=`lumen-terms-${crypto.randomUUID()}`,v1=String(iface.version||"").startsWith("1.");
  const message={messageId:id,role:v1?"ROLE_USER":"user",parts:[{text:row.request_text}]};
  const metadata={lumen:{type:"negotiation_terms_request",requestId:row.request_id,caseId:row.case_id,opportunityId:row.opportunity_id,nonBinding:true,exploratory:true,spendAllowed:false,purchaseAllowed:false,contractAllowed:false}};
  if(iface.binding==="HTTP+JSON"){const payload={message,metadata};if(iface.tenant)payload.tenant=iface.tenant;return{url:`${iface.url}/message:send`,headers:{"content-type":"application/a2a+json",accept:"application/a2a+json, application/json","a2a-version":iface.version||"1.0"},payload};}
  const params={message,metadata};if(iface.tenant)params.tenant=iface.tenant;
  return{url:iface.url,headers:{"content-type":"application/json",accept:"application/json","a2a-version":iface.version||(v1?"1.0":"0.3")},payload:{jsonrpc:"2.0",id,method:v1?"SendMessage":"message/send",params}};
}
function extract(body){
  const v=body?.result||body||{},task=v?.task||(v?.id&&v?.status?v:null),msg=v?.message||(Array.isArray(v?.parts)&&v?.role?v:null);
  const parts=msg?.parts||task?.status?.message?.parts||task?.artifacts?.flatMap?.(a=>a?.parts||[])||[],arr=Array.isArray(parts)?parts:[];
  return{taskId:clean(task?.id,300)||null,contextId:clean(task?.contextId,300)||clean(msg?.contextId,300)||null,state:clean(task?.status?.state,100)||null,responseText:clean(arr.map(p=>p?.text||p?.data?.text||"").filter(Boolean).join(" "),6000)||null};
}
async function storeTerms(env,row,text){
  const price=priceFromText(text),eta=etaFromText(text);if(price==null&&eta==null)return{stored:false,priceUsd:null,etaHours:null};
  const now=new Date().toISOString(),id=`NGT-${(await hash(`${row.partner_id}|${row.opportunity_id}|negotiator_response`)).slice(0,18).toUpperCase()}`;
  await env.DB.prepare("INSERT INTO lumen_negotiation_terms(id,partner_id,opportunity_id,source,created_at,updated_at,price_usd,eta_hours,scope,terms_text,evidence,status,binding_allowed,spend_allowed) VALUES(?,?,?,'negotiator_response',?,?,?,?,?,?,?,'DECLARED_UNVERIFIED',0,0) ON CONFLICT(partner_id,opportunity_id,source) DO UPDATE SET updated_at=excluded.updated_at,price_usd=COALESCE(excluded.price_usd,lumen_negotiation_terms.price_usd),eta_hours=COALESCE(excluded.eta_hours,lumen_negotiation_terms.eta_hours),terms_text=excluded.terms_text,evidence=excluded.evidence,status='DECLARED_UNVERIFIED',binding_allowed=0,spend_allowed=0")
    .bind(id,row.partner_id,row.opportunity_id,now,now,price,eta,clean(row.title,1000)||null,clean(text,4500),`a2a_nonbinding_terms_request:${row.request_id}`).run();
  return{stored:true,priceUsd:price,etaHours:eta};
}
async function ready(env,limit){
  const r=await env.DB.prepare("SELECT q.id request_id,q.case_id,q.partner_id,q.partner_name,q.request_text,q.target_card_url,q.target_endpoint,c.opportunity_id,c.title FROM lumen_negotiation_requests q JOIN lumen_negotiation_cases c ON c.id=q.case_id JOIN lumen_negotiation_candidates n ON n.case_id=q.case_id AND n.partner_id=q.partner_id WHERE q.status='DRAFT' AND q.external_message_sent=0 AND c.status='RANKED_INCOMPLETE_TERMS' AND (n.declared_price_usd IS NULL OR n.eta_hours IS NULL) AND q.trust_level IN ('ALLOW','CAUTION') AND (SELECT COALESCE(SUM(q2.external_message_sent),0) FROM lumen_negotiation_requests q2 WHERE q2.case_id=q.case_id) < ? ORDER BY c.commercial_score DESC,n.total_score DESC,n.data_completeness DESC LIMIT ?").bind(MAX_MESSAGES_PER_CASE,Math.min(MAX_MESSAGES_PER_CASE,Math.max(1,Number(limit)||1))).all();
  return r.results||[];
}
async function saveExchange(env,row,data){
  const now=new Date().toISOString(),id=`NEX-${(await hash(row.request_id)).slice(0,18).toUpperCase()}`;
  await env.DB.prepare("INSERT INTO lumen_negotiation_exchanges(id,request_id,case_id,opportunity_id,partner_id,partner_name,created_at,updated_at,status,protocol_binding,protocol_version,agent_url,task_id,context_id,request_json,response_json,response_text,price_usd,eta_hours,http_status,error,external_message_sent,sent_at,polled_at,binding_allowed,spend_allowed,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0,?) ON CONFLICT(request_id) DO UPDATE SET updated_at=excluded.updated_at,status=excluded.status,protocol_binding=COALESCE(excluded.protocol_binding,lumen_negotiation_exchanges.protocol_binding),protocol_version=COALESCE(excluded.protocol_version,lumen_negotiation_exchanges.protocol_version),agent_url=COALESCE(excluded.agent_url,lumen_negotiation_exchanges.agent_url),task_id=COALESCE(excluded.task_id,lumen_negotiation_exchanges.task_id),context_id=COALESCE(excluded.context_id,lumen_negotiation_exchanges.context_id),request_json=COALESCE(excluded.request_json,lumen_negotiation_exchanges.request_json),response_json=COALESCE(excluded.response_json,lumen_negotiation_exchanges.response_json),response_text=COALESCE(excluded.response_text,lumen_negotiation_exchanges.response_text),price_usd=COALESCE(excluded.price_usd,lumen_negotiation_exchanges.price_usd),eta_hours=COALESCE(excluded.eta_hours,lumen_negotiation_exchanges.eta_hours),http_status=COALESCE(excluded.http_status,lumen_negotiation_exchanges.http_status),error=excluded.error,external_message_sent=MAX(lumen_negotiation_exchanges.external_message_sent,excluded.external_message_sent),sent_at=COALESCE(lumen_negotiation_exchanges.sent_at,excluded.sent_at),polled_at=COALESCE(excluded.polled_at,lumen_negotiation_exchanges.polled_at),binding_allowed=0,spend_allowed=0,engine_version=excluded.engine_version")
    .bind(id,row.request_id,row.case_id,row.opportunity_id,row.partner_id,row.partner_name,data.createdAt||now,now,data.status,data.binding||null,data.version||null,data.agentUrl||null,data.taskId||null,data.contextId||null,data.requestJson||null,data.responseJson||null,data.responseText||null,data.priceUsd??null,data.etaHours??null,data.httpStatus||null,data.error||null,data.sent?1:0,data.sentAt||null,data.polledAt||null,VERSION).run();
}
async function sendOne(env,row){
  const p=await probe(row.target_card_url||row.target_endpoint);
  if(!p.ok){await saveExchange(env,row,{status:p.status,error:p.error,sent:false});await env.DB.prepare("UPDATE lumen_negotiation_requests SET updated_at=?,status=? WHERE id=? AND external_message_sent=0").bind(new Date().toISOString(),p.status,row.request_id).run();return{sent:false,target:row.partner_name,status:p.status,error:p.error};}
  const e=envelope(row,p.iface),t=timer(),sentAt=new Date().toISOString();let raw="",http=0;
  try{const resp=await fetch(e.url,{method:"POST",headers:e.headers,body:JSON.stringify(e.payload),signal:t.signal});http=resp.status;raw=await resp.text();if(!resp.ok)throw new Error(`send_http_${resp.status}`);let body={};try{body=JSON.parse(raw);}catch{}const info=extract(body),terms=info.responseText?await storeTerms(env,row,info.responseText):{stored:false,priceUsd:null,etaHours:null};const status=info.responseText?(terms.stored?"RESPONDED_TERMS":"RESPONDED_INCOMPLETE"):info.taskId?"SENT_TASK":"SENT";await saveExchange(env,row,{status,binding:p.iface.binding,version:p.iface.version,agentUrl:p.iface.url,taskId:info.taskId,contextId:info.contextId,requestJson:JSON.stringify(e.payload),responseJson:clean(raw,12000),responseText:info.responseText,priceUsd:terms.priceUsd,etaHours:terms.etaHours,httpStatus:http,error:null,sent:true,sentAt});await env.DB.prepare("UPDATE lumen_negotiation_requests SET updated_at=?,status=?,external_message_sent=1,binding_allowed=0,spend_allowed=0 WHERE id=?").bind(new Date().toISOString(),status,row.request_id).run();return{sent:true,requestId:row.request_id,caseId:row.case_id,target:row.partner_name,status,taskId:info.taskId,priceUsd:terms.priceUsd,etaHours:terms.etaHours};}
  catch(e2){const msg=clean(e2?.message||e2,500);await saveExchange(env,row,{status:"SEND_FAILED",binding:p.iface.binding,version:p.iface.version,agentUrl:p.iface.url,requestJson:JSON.stringify(e.payload),responseJson:clean(raw,12000),httpStatus:http,error:`${msg}${http?`;http=${http}`:""}`,sent:false});await env.DB.prepare("UPDATE lumen_negotiation_requests SET updated_at=?,status='SEND_FAILED' WHERE id=? AND external_message_sent=0").bind(new Date().toISOString(),row.request_id).run();return{sent:false,requestId:row.request_id,target:row.partner_name,status:"SEND_FAILED",error:msg};}
  finally{t.done();}
}
export async function sendNegotiationTermRequests(env,{force=false,limit=1}={}){
  if(!(await ensure(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  const enabled=String(env?.A2A_AUTONOMOUS_NEGOTIATION_TERMS||"false").toLowerCase()==="true";
  if(!force&&!enabled)return{ok:true,version:VERSION,sent:0,reason:"autonomous_negotiation_terms_disabled",guardrails:{maxMessagesPerCase:MAX_MESSAGES_PER_CASE,autonomousNegotiationMessages:false,autonomousSpend:false,bindingActionsHumanGated:true}};
  const rs=await ready(env,limit),results=[];for(const r of rs)results.push(await sendOne(env,r));
  return{ok:true,version:VERSION,attempted:rs.length,sent:results.filter(x=>x.sent).length,results,guardrails:{maxMessagesPerCase:MAX_MESSAGES_PER_CASE,nonBindingOnly:true,autonomousSpend:false,autonomousPurchase:false,autonomousContract:false,bindingActionsHumanGated:true}};
}
async function pollOne(env,row){
  const t=timer(),v1=String(row.protocol_version||"").startsWith("1.");let raw="",http=0;
  try{let resp;if(row.protocol_binding==="HTTP+JSON")resp=await fetch(`${baseUrl(row.agent_url)}/tasks/${encodeURIComponent(row.task_id)}`,{headers:{accept:"application/a2a+json, application/json","a2a-version":row.protocol_version||"1.0"},signal:t.signal});else resp=await fetch(row.agent_url,{method:"POST",headers:{"content-type":"application/json",accept:"application/json","a2a-version":row.protocol_version||(v1?"1.0":"0.3")},body:JSON.stringify({jsonrpc:"2.0",id:`lumen-terms-poll-${crypto.randomUUID()}`,method:v1?"GetTask":"tasks/get",params:{id:row.task_id}}),signal:t.signal});http=resp.status;raw=await resp.text();if(!resp.ok)throw new Error(`poll_http_${resp.status}`);let body={};try{body=JSON.parse(raw);}catch{}const info=extract(body),terms=info.responseText?await storeTerms(env,row,info.responseText):{stored:false,priceUsd:null,etaHours:null};let status=info.responseText?(terms.stored?"RESPONDED_TERMS":"RESPONDED_INCOMPLETE"):"WORKING";if(!info.responseText&&["completed","failed","canceled","cancelled","rejected"].includes(clean(info.state,50).toLowerCase()))status=`TASK_${clean(info.state,50).toUpperCase()}`;await saveExchange(env,row,{status,responseJson:clean(raw,12000),responseText:info.responseText,priceUsd:terms.priceUsd,etaHours:terms.etaHours,httpStatus:http,error:null,sent:true,polledAt:new Date().toISOString()});await env.DB.prepare("UPDATE lumen_negotiation_requests SET updated_at=?,status=? WHERE id=?").bind(new Date().toISOString(),status,row.request_id).run();return{polled:true,requestId:row.request_id,target:row.partner_name,status,priceUsd:terms.priceUsd,etaHours:terms.etaHours};}
  catch(e){return{polled:true,requestId:row.request_id,target:row.partner_name,status:"POLL_FAILED",error:clean(e?.message||e,500)};}finally{t.done();}
}
export async function pollNegotiationTermResponses(env){
  if(!(await ensure(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  const r=await env.DB.prepare("SELECT e.request_id,e.case_id,e.opportunity_id,e.partner_id,e.partner_name,e.protocol_binding,e.protocol_version,e.agent_url,e.task_id,c.title FROM lumen_negotiation_exchanges e JOIN lumen_negotiation_cases c ON c.id=e.case_id WHERE e.external_message_sent=1 AND e.task_id IS NOT NULL AND e.status IN ('SENT_TASK','WORKING') ORDER BY e.updated_at ASC LIMIT 8").all(),results=[];
  for(const row of r.results||[])results.push(await pollOne(env,row));
  return{ok:true,version:VERSION,polled:results.length,results};
}
async function stats(env){
  await ensure(env);const r=await env.DB.prepare("SELECT COUNT(*) total,COALESCE(SUM(external_message_sent),0) sent,SUM(CASE WHEN status='RESPONDED_TERMS' THEN 1 ELSE 0 END) responded_terms,SUM(CASE WHEN price_usd IS NOT NULL THEN 1 ELSE 0 END) priced,SUM(CASE WHEN eta_hours IS NOT NULL THEN 1 ELSE 0 END) timed,SUM(CASE WHEN status IN ('SENT_TASK','WORKING') THEN 1 ELSE 0 END) pending FROM lumen_negotiation_exchanges").first();
  return json({version:VERSION,total:Number(r?.total||0),externalMessagesSent:Number(r?.sent||0),responsesWithTerms:Number(r?.responded_terms||0),pricedResponses:Number(r?.priced||0),timedResponses:Number(r?.timed||0),pendingTasks:Number(r?.pending||0),maxMessagesPerCase:MAX_MESSAGES_PER_CASE,autonomousNegotiationMessages:String(env?.A2A_AUTONOMOUS_NEGOTIATION_TERMS||"false").toLowerCase()==="true",autonomousSpend:false,autonomousPurchase:false,autonomousContract:false,bindingActionsHumanGated:true});
}
export async function handleNegotiatorTermsRuntime(request,env){
  const u=new URL(request.url);
  if(request.method==="GET"&&u.pathname==="/negotiator/terms-runtime/stats")return stats(env);
  if(request.method==="POST"&&u.pathname==="/negotiator/terms-runtime/send"){if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);let b={};try{b=await request.json();}catch{}if(b?.confirmNonBinding!==true)return json({ok:false,error:"confirmNonBinding_required"},400);return json(await sendNegotiationTermRequests(env,{force:true,limit:b?.limit||1}),202);}
  if(request.method==="POST"&&u.pathname==="/negotiator/terms-runtime/poll"){if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);return json(await pollNegotiationTermResponses(env),202);}
  if(request.method==="GET"&&u.pathname==="/negotiator/terms-runtime/exchanges"){if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);await ensure(env);const r=await env.DB.prepare("SELECT request_id,case_id,partner_id,partner_name,status,protocol_binding,protocol_version,task_id,response_text,price_usd,eta_hours,http_status,error,external_message_sent,sent_at,polled_at,updated_at FROM lumen_negotiation_exchanges ORDER BY updated_at DESC LIMIT 100").all();return json({version:VERSION,exchanges:r.results||[]});}
  return null;
}
