const VERSION = "1.0-delegation-runtime";
const CARD_TIMEOUT_MS = 8000;
const SEND_TIMEOUT_MS = 15000;

function json(data,status=200){return Response.json(data,{status,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function clean(v,n=12000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}
function bool(v){return String(v??"false").toLowerCase()==="true";}
function authorized(r,e){const a=clean(e?.OPPORTUNITY_ADMIN_TOKEN,500),b=clean(r.headers.get("x-lumen-admin"),500);return Boolean(a&&b&&a===b);}
function isHttps(v){try{return new URL(v).protocol==="https:";}catch{return false;}}
function normalizeBaseUrl(v){const u=new URL(v);u.hash="";u.search="";return u.toString().replace(/\/$/,"");}
function timeout(ms){const c=new AbortController();const t=setTimeout(()=>c.abort("timeout"),ms);return{signal:c.signal,clear:()=>clearTimeout(t)};}

async function ensureSchema(env){
  if(!env?.DB)return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_delegation_tasks (id TEXT PRIMARY KEY,room_id TEXT NOT NULL,opportunity_id TEXT NOT NULL,partner_id TEXT NOT NULL,partner_name TEXT NOT NULL,role TEXT NOT NULL,title TEXT NOT NULL,objective TEXT NOT NULL,expected_output TEXT NOT NULL,evidence_required TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,dispatched_at TEXT,completed_at TEXT,remote_task_id TEXT,context_id TEXT,response_text TEXT,quality_score INTEGER,error TEXT,binding_allowed INTEGER NOT NULL DEFAULT 0,spend_allowed INTEGER NOT NULL DEFAULT 0,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_delegation_events (id TEXT PRIMARY KEY,task_id TEXT NOT NULL,created_at TEXT NOT NULL,event_type TEXT NOT NULL,detail TEXT)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_delegation_runtime_status ON lumen_delegation_tasks(status,updated_at)")
  ]);
  return true;
}

async function logEvent(env,taskId,eventType,detail=""){
  const id=`DRE-${crypto.randomUUID().replaceAll("-","").slice(0,20).toUpperCase()}`;
  await env.DB.prepare("INSERT INTO lumen_delegation_events(id,task_id,created_at,event_type,detail) VALUES(?,?,?,?,?)")
    .bind(id,taskId,new Date().toISOString(),clean(eventType,100),clean(detail,5000)||null).run();
}

function hasRequiredAuth(card){
  if(Array.isArray(card?.securityRequirements)&&card.securityRequirements.length)return true;
  if(Array.isArray(card?.security)&&card.security.length)return true;
  return false;
}

function selectInterface(card){
  const interfaces=Array.isArray(card?.supportedInterfaces)?card.supportedInterfaces:Array.isArray(card?.supported_interfaces)?card.supported_interfaces:[];
  for(const x of interfaces){
    const binding=clean(x?.protocolBinding||x?.binding||x?.transport,80).toUpperCase();
    if(!isHttps(x?.url))continue;
    if(["JSONRPC","JSON-RPC","HTTP+JSON"].includes(binding))return{url:normalizeBaseUrl(x.url),binding:binding==="HTTP+JSON"?"HTTP+JSON":"JSONRPC",version:clean(x?.protocolVersion||x?.protocol_version||card?.protocolVersion||"1.0",20),tenant:clean(x?.tenant,200)||null};
  }
  if(isHttps(card?.url)){
    const binding=clean(card?.preferredTransport||card?.transport||"JSONRPC",80).toUpperCase();
    if(["JSONRPC","JSON-RPC","HTTP+JSON"].includes(binding))return{url:normalizeBaseUrl(card.url),binding:binding==="HTTP+JSON"?"HTTP+JSON":"JSONRPC",version:clean(card?.protocolVersion||"0.3",20),tenant:null};
  }
  return null;
}

async function fetchCard(url){
  if(!isHttps(url))return{ok:false,status:"INCOMPATIBLE",error:"card_url_not_https"};
  const t=timeout(CARD_TIMEOUT_MS);
  try{
    const r=await fetch(url,{headers:{accept:"application/json, application/a2a+json"},signal:t.signal});
    const raw=await r.text();
    if(!r.ok)return{ok:false,status:"CARD_FETCH_FAILED",error:`card_http_${r.status}`};
    let card;try{card=JSON.parse(raw);}catch{return{ok:false,status:"CARD_FETCH_FAILED",error:"card_invalid_json"};}
    if(hasRequiredAuth(card))return{ok:false,status:"AUTH_REQUIRED",error:"agent_requires_authentication"};
    const selected=selectInterface(card);if(!selected)return{ok:false,status:"INCOMPATIBLE",error:"no_supported_public_a2a_interface"};
    return{ok:true,card,selected};
  }catch(e){return{ok:false,status:"CARD_FETCH_FAILED",error:clean(e?.message||e,300)};}finally{t.clear();}
}

function extract(body){
  const value=body?.result||body||{};
  const task=value?.task||(value?.id&&value?.status?value:null);
  const msg=value?.message||(Array.isArray(value?.parts)&&value?.role?value:null);
  const parts=msg?.parts||task?.status?.message?.parts||task?.artifacts?.flatMap?.(a=>a?.parts||[])||[];
  return{
    taskId:clean(task?.id,300)||null,
    contextId:clean(task?.contextId,300)||clean(msg?.contextId,300)||null,
    state:clean(task?.status?.state,100)||null,
    responseText:clean((Array.isArray(parts)?parts:[]).map(p=>p?.text||p?.data?.text||"").filter(Boolean).join(" "),12000)||null
  };
}

async function nextPlanned(env){
  return env.DB.prepare("SELECT * FROM lumen_delegation_tasks WHERE status='PLANNED' AND binding_allowed=0 AND spend_allowed=0 ORDER BY created_at ASC LIMIT 1").first();
}

async function partner(env,partnerId){
  return env.DB.prepare("SELECT id,name,endpoint,card_url,protocol_version FROM lumen_partner_agents WHERE id=? LIMIT 1").bind(partnerId).first();
}

function taskPrompt(task){
  return clean(`LUMEN is delegating a zero-spend, non-binding specialist task that was produced only after a quality-gated multi-agent council synthesis. Task ID: ${task.id}. Role: ${task.role}. Title: ${task.title}. Objective: ${task.objective}. Expected output: ${task.expected_output}. Evidence requirement: ${task.evidence_required}. Return only work relevant to this task. Separate observed evidence from assumptions. Do not place orders, spend funds, sign contracts, create debt, promise payment, or assume authority to bind LUMEN. If the task cannot be completed without payment, authentication, or a binding action, stop and report that requirement instead of proceeding.`,7000);
}

function envelope(task,iface,text){
  const messageId=`lumen-delegation-${crypto.randomUUID()}`;
  const v1=String(iface.version||"").startsWith("1.");
  const message={messageId,role:v1?"ROLE_USER":"user",parts:[{text}]};
  const metadata={lumen:{type:"delegated_task",delegationTaskId:task.id,roomId:task.room_id,opportunityId:task.opportunity_id,role:task.role,nonBinding:true,spendAllowed:false,contractAllowed:false}};
  if(iface.binding==="HTTP+JSON"){
    const payload={message,metadata};if(iface.tenant)payload.tenant=iface.tenant;
    return{url:`${iface.url}/message:send`,headers:{"content-type":"application/a2a+json",accept:"application/a2a+json, application/json","a2a-version":iface.version||"1.0"},payload};
  }
  const params={message,metadata};if(iface.tenant)params.tenant=iface.tenant;
  return{url:iface.url,headers:{"content-type":"application/json",accept:"application/json","a2a-version":iface.version||(v1?"1.0":"0.3")},payload:{jsonrpc:"2.0",id:messageId,method:v1?"SendMessage":"message/send",params}};
}

export async function dispatchNextDelegationTask(env,{force=false}={}){
  if(!(await ensureSchema(env)))return{ok:false,sent:false,error:"persistence_unavailable",version:VERSION};
  const enabled=bool(env?.A2A_AUTONOMOUS_DELEGATION);
  if(!enabled&&!force)return{ok:true,sent:false,reason:"autonomous_delegation_disabled",version:VERSION,autonomousDelegation:false};

  const task=await nextPlanned(env);
  if(!task)return{ok:true,sent:false,reason:"no_planned_task",version:VERSION};
  if(Number(task.binding_allowed)!==0||Number(task.spend_allowed)!==0)return{ok:false,sent:false,error:"unsafe_task_guardrail_violation",taskId:task.id,version:VERSION};

  const p=await partner(env,task.partner_id);
  if(!p)return{ok:false,sent:false,error:"partner_not_found",taskId:task.id,version:VERSION};
  const probe=await fetchCard(p.card_url||p.endpoint);
  if(!probe.ok){
    await env.DB.prepare("UPDATE lumen_delegation_tasks SET status='FAILED',updated_at=?,error=? WHERE id=?").bind(new Date().toISOString(),probe.error,task.id).run();
    await logEvent(env,task.id,"DISPATCH_BLOCKED",probe.error);
    return{ok:false,sent:false,status:probe.status,error:probe.error,taskId:task.id,target:p.name,version:VERSION};
  }

  const text=taskPrompt(task);const e=envelope(task,probe.selected,text);const t=timeout(SEND_TIMEOUT_MS);let raw="";let http=0;
  try{
    const resp=await fetch(e.url,{method:"POST",headers:e.headers,body:JSON.stringify(e.payload),signal:t.signal});http=resp.status;raw=await resp.text();
    if(!resp.ok)throw new Error(`send_http_${resp.status}`);
    let body={};try{body=JSON.parse(raw);}catch{}
    const info=extract(body);const now=new Date().toISOString();
    const status=info.responseText?"RESULT_RECEIVED":info.taskId?"DISPATCHED":"DISPATCHED_ACK";
    await env.DB.prepare("UPDATE lumen_delegation_tasks SET status=?,updated_at=?,dispatched_at=?,completed_at=?,remote_task_id=?,context_id=?,response_text=?,error=NULL WHERE id=?")
      .bind(status,now,now,info.responseText?now:null,info.taskId,info.contextId,info.responseText,task.id).run();
    await logEvent(env,task.id,"TASK_DISPATCHED",`target=${p.name}; status=${status}; remoteTaskId=${info.taskId||"none"}`);
    if(info.responseText)await logEvent(env,task.id,"RESULT_RECEIVED",info.responseText);
    return{ok:true,sent:true,version:VERSION,taskId:task.id,target:p.name,status,remoteTaskId:info.taskId,responseText:info.responseText,guardrails:{bindingAllowed:false,spendAllowed:false,contractAllowed:false}};
  }catch(e2){
    const msg=clean(e2?.message||e2,500);await env.DB.prepare("UPDATE lumen_delegation_tasks SET status='FAILED',updated_at=?,error=? WHERE id=?").bind(new Date().toISOString(),`${msg}${http?`;http=${http}`:""}`,task.id).run();
    await logEvent(env,task.id,"DISPATCH_FAILED",`${msg}${http?`;http=${http}`:""}`);
    return{ok:false,sent:false,status:"SEND_FAILED",error:msg,taskId:task.id,target:p.name,version:VERSION};
  }finally{t.clear();}
}

async function pollOne(env,task){
  const p=await partner(env,task.partner_id);if(!p)return{polled:false,error:"partner_not_found"};
  const probe=await fetchCard(p.card_url||p.endpoint);if(!probe.ok)return{polled:false,error:probe.error};
  const iface=probe.selected;const v1=String(iface.version||"").startsWith("1.");const t=timeout(SEND_TIMEOUT_MS);
  try{
    let resp;
    if(iface.binding==="HTTP+JSON")resp=await fetch(`${normalizeBaseUrl(iface.url)}/tasks/${encodeURIComponent(task.remote_task_id)}`,{headers:{accept:"application/a2a+json, application/json","a2a-version":iface.version||"1.0"},signal:t.signal});
    else resp=await fetch(iface.url,{method:"POST",headers:{"content-type":"application/json",accept:"application/json","a2a-version":iface.version||(v1?"1.0":"0.3")},body:JSON.stringify({jsonrpc:"2.0",id:`lumen-delegation-poll-${crypto.randomUUID()}`,method:v1?"GetTask":"tasks/get",params:{id:task.remote_task_id}}),signal:t.signal});
    const raw=await resp.text();if(!resp.ok)throw new Error(`poll_http_${resp.status}`);let body={};try{body=JSON.parse(raw);}catch{}
    const info=extract(body);if(!info.responseText)return{polled:true,responded:false,state:info.state};
    const now=new Date().toISOString();await env.DB.prepare("UPDATE lumen_delegation_tasks SET status='RESULT_RECEIVED',updated_at=?,completed_at=?,response_text=?,error=NULL WHERE id=?").bind(now,now,info.responseText,task.id).run();
    await logEvent(env,task.id,"RESULT_RECEIVED",info.responseText);
    return{polled:true,responded:true,taskId:task.id,responseText:info.responseText};
  }catch(e){return{polled:true,responded:false,error:clean(e?.message||e,400)};}finally{t.clear();}
}

export async function pollDelegationTasks(env){
  if(!(await ensureSchema(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  const rows=await env.DB.prepare("SELECT * FROM lumen_delegation_tasks WHERE status='DISPATCHED' AND remote_task_id IS NOT NULL ORDER BY dispatched_at ASC LIMIT 6").all();
  const results=[];for(const task of rows.results||[])results.push(await pollOne(env,task));
  return{ok:true,version:VERSION,polled:results.length,results};
}

async function stats(env){
  await ensureSchema(env);const r=await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN status='PLANNED' THEN 1 ELSE 0 END) planned,SUM(CASE WHEN status IN ('DISPATCHED','DISPATCHED_ACK') THEN 1 ELSE 0 END) active,SUM(CASE WHEN status='RESULT_RECEIVED' THEN 1 ELSE 0 END) results,SUM(CASE WHEN status='FAILED' THEN 1 ELSE 0 END) failed FROM lumen_delegation_tasks").first();
  return json({version:VERSION,total:Number(r?.total||0),planned:Number(r?.planned||0),active:Number(r?.active||0),results:Number(r?.results||0),failed:Number(r?.failed||0),autonomousDelegation:bool(env?.A2A_AUTONOMOUS_DELEGATION),autonomousOutgoingSpend:false,bindingActionsHumanGated:true});
}

export async function handleDelegationRuntime(request,env){
  const url=new URL(request.url);
  if(request.method==="GET"&&url.pathname==="/delegation/runtime-stats")return stats(env);
  if(request.method==="POST"&&url.pathname==="/delegation/dispatch-next"){
    if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);let b={};try{b=await request.json();}catch{}return json(await dispatchNextDelegationTask(env,{force:Boolean(b?.force)}),202);
  }
  if(request.method==="POST"&&url.pathname==="/delegation/poll"){
    if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);return json(await pollDelegationTasks(env),202);
  }
  return null;
}
