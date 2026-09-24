const VERSION = "1.0-partner-recruitment";
const CARD_TIMEOUT_MS = 8000;
const SEND_TIMEOUT_MS = 15000;

function json(data,status=200){return Response.json(data,{status,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function clean(v,n=6000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}
function parse(v,fallback=[]){try{return JSON.parse(v||"");}catch{return fallback;}}
function authorized(request,env){const a=clean(env?.OPPORTUNITY_ADMIN_TOKEN,500),b=clean(request.headers.get("x-lumen-admin"),500);return Boolean(a&&b&&a===b);}
function isHttps(v){try{return new URL(v).protocol==="https:";}catch{return false;}}
function normalizeBaseUrl(v){const u=new URL(v);u.hash="";u.search="";return u.toString().replace(/\/$/,"");}
function timeout(ms){const c=new AbortController();const t=setTimeout(()=>c.abort("timeout"),ms);return{signal:c.signal,clear:()=>clearTimeout(t)};}

async function ensureSchema(env){
  if(!env?.DB)return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_partner_recruitment (partner_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, stage TEXT NOT NULL, status TEXT NOT NULL, card_url TEXT, agent_url TEXT, protocol_binding TEXT, protocol_version TEXT, task_id TEXT, context_id TEXT, response_text TEXT, response_class TEXT, invite_text TEXT, request_json TEXT, response_json TEXT, error TEXT, contact_count INTEGER NOT NULL DEFAULT 0, last_contact_at TEXT, next_action_at TEXT, engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_partner_recruitment_stage ON lumen_partner_recruitment(stage,updated_at)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_partner_recruitment_next ON lumen_partner_recruitment(next_action_at,stage)")
  ]);
  return true;
}

async function nextCandidate(env){
  await ensureSchema(env);
  const r=await env.DB.prepare("SELECT p.id,p.name,p.card_url,p.endpoint,p.description,p.protocol_version,p.capabilities_json,p.reputation_score,p.compatibility_score,COALESCE(MAX(m.match_score),0) AS best_match FROM lumen_partner_agents p LEFT JOIN lumen_partner_matches m ON m.partner_id=p.id AND m.status='quality_candidate' LEFT JOIN lumen_partner_recruitment r ON r.partner_id=p.id WHERE p.status='strong_candidate' AND p.reputation_score>=80 AND p.compatibility_score>=90 AND r.partner_id IS NULL GROUP BY p.id,p.name,p.card_url,p.endpoint,p.description,p.protocol_version,p.capabilities_json,p.reputation_score,p.compatibility_score ORDER BY best_match DESC,p.reputation_score DESC,p.compatibility_score DESC,p.updated_at DESC LIMIT 1").first();
  return r||null;
}

function hasRequiredAuth(card){
  const req=card?.securityRequirements;
  if(Array.isArray(req)&&req.length)return true;
  const legacy=card?.security;
  return Array.isArray(legacy)&&legacy.length>0;
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
    const text=await r.text();
    if(!r.ok)return{ok:false,status:"CARD_FETCH_FAILED",error:`card_http_${r.status}`,raw:clean(text,2000)};
    let card;try{card=JSON.parse(text);}catch{return{ok:false,status:"CARD_FETCH_FAILED",error:"card_invalid_json"};}
    if(hasRequiredAuth(card))return{ok:false,status:"AUTH_REQUIRED",error:"agent_requires_authentication",card};
    const selected=selectInterface(card);
    if(!selected)return{ok:false,status:"INCOMPATIBLE",error:"no_supported_public_a2a_interface",card};
    return{ok:true,status:"READY",card,selected};
  }catch(e){return{ok:false,status:"CARD_FETCH_FAILED",error:clean(e?.message||e,300)};}finally{t.clear();}
}

function inviteText(row){
  const caps=parse(row.capabilities_json,[]).slice(0,6).join(", ")||"your published capabilities";
  return clean(`Hi ${row.name}, LUMEN is building a non-binding A2A partner network that forms specialist agent teams around real commercial opportunities. Your published capabilities (${caps}) look complementary to our network. We would like to explore whether our agents could collaborate on future work. This message creates no contract, purchase, exclusivity, payment obligation, or other commitment. If you are interested, please reply with: (1) the capabilities you want partners to rely on, (2) your preferred engagement or pricing model if applicable, (3) availability or operating constraints, and (4) up to two concrete business ideas, market opportunities, customer signals, or useful agent combinations you think we could pursue together. Please distinguish observed evidence from assumptions.`,2400);
}

function envelope(row,iface){
  const messageId=`lumen-recruit-${crypto.randomUUID()}`;
  const text=inviteText(row);
  const v1=String(iface.version||"").startsWith("1.");
  const message={messageId,role:v1?"ROLE_USER":"user",parts:[{text}]};
  const metadata={lumen:{type:"partner_recruitment",partnerId:row.id,nonBinding:true,spendAllowed:false,contractAllowed:false,ventureIdeasRequested:true}};
  if(iface.binding==="HTTP+JSON"){
    const payload={message,metadata};if(iface.tenant)payload.tenant=iface.tenant;
    return{messageId,text,url:`${iface.url}/message:send`,headers:{"content-type":"application/a2a+json",accept:"application/a2a+json, application/json","a2a-version":iface.version||"1.0"},payload};
  }
  const params={message,metadata};if(iface.tenant)params.tenant=iface.tenant;
  return{messageId,text,url:iface.url,headers:{"content-type":"application/json",accept:"application/json","a2a-version":iface.version||(v1?"1.0":"0.3")},payload:{jsonrpc:"2.0",id:messageId,method:v1?"SendMessage":"message/send",params}};
}

function extract(body,binding){
  const value=binding==="JSONRPC"?(body?.result||body):body||{};
  const task=value?.task||(value?.id&&value?.status?value:null);
  const msg=value?.message||null;
  const taskId=clean(task?.id,300)||null;
  const contextId=clean(task?.contextId,300)||clean(msg?.contextId,300)||null;
  const state=clean(task?.status?.state,100)||null;
  const parts=msg?.parts||task?.status?.message?.parts||task?.artifacts?.flatMap?.(a=>a?.parts||[])||[];
  const responseText=clean((Array.isArray(parts)?parts:[]).map(p=>p?.text||"").filter(Boolean).join(" "),6000)||null;
  return{taskId,contextId,state,responseText,hasMessage:Boolean(msg||responseText)};
}

function classify(text){
  const t=clean(text,6000).toLowerCase();
  if(!t)return{responseClass:"none",stage:"CONTACTED"};
  const reject=["not interested","no thanks","decline","not relevant","do not contact","cannot collaborate","unable to collaborate"];
  if(reject.some(x=>t.includes(x)))return{responseClass:"declined",stage:"DECLINED"};
  const positive=["interested","happy to collaborate","open to collaborate","let's collaborate","lets collaborate","sounds good","available","partner","collaborate","work together"];
  const question=["?","pricing","terms","scope","how would","what kind","details"];
  if(positive.some(x=>t.includes(x)))return{responseClass:"interested",stage:"INTERESTED"};
  if(question.some(x=>t.includes(x)))return{responseClass:"question",stage:"ENGAGED"};
  return{responseClass:"response",stage:"ENGAGED"};
}

async function storeProbe(env,row,probe){
  const now=new Date().toISOString();
  const s=probe?.selected;
  await env.DB.prepare("INSERT INTO lumen_partner_recruitment(partner_id,created_at,updated_at,stage,status,card_url,agent_url,protocol_binding,protocol_version,task_id,context_id,response_text,response_class,invite_text,request_json,response_json,error,contact_count,last_contact_at,next_action_at,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(partner_id) DO UPDATE SET updated_at=excluded.updated_at,status=excluded.status,card_url=excluded.card_url,agent_url=excluded.agent_url,protocol_binding=excluded.protocol_binding,protocol_version=excluded.protocol_version,error=excluded.error,engine_version=excluded.engine_version")
    .bind(row.id,now,now,"QUALIFIED",probe.ok?"READY":probe.status,row.card_url||row.endpoint||null,s?.url||null,s?.binding||null,s?.version||row.protocol_version||null,null,null,null,null,inviteText(row),null,null,probe.ok?null:probe.error,0,null,null,VERSION).run();
}

export async function probeNextRecruit(env){
  if(!(await ensureSchema(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  const row=await nextCandidate(env);
  if(!row)return{ok:true,probed:false,reason:"no_uncontacted_qualified_partner",version:VERSION};
  const cardUrl=row.card_url||row.endpoint;
  const probe=await fetchCard(cardUrl);
  await storeProbe(env,row,probe);
  return{ok:true,probed:true,version:VERSION,partnerId:row.id,target:row.name,reputation:Number(row.reputation_score||0),compatibility:Number(row.compatibility_score||0),matchScore:Number(row.best_match||0),status:probe.ok?"READY":probe.status,protocol:probe.selected?{binding:probe.selected.binding,version:probe.selected.version}:null,error:probe.ok?null:probe.error,nextAction:probe.ok?"send_nonbinding_invite":"do_not_send"};
}

async function ready(env){
  return env.DB.prepare("SELECT r.*,p.name,p.description,p.capabilities_json,p.reputation_score,p.compatibility_score,p.id FROM lumen_partner_recruitment r JOIN lumen_partner_agents p ON p.id=r.partner_id WHERE r.status='READY' AND r.contact_count=0 ORDER BY p.reputation_score DESC,p.compatibility_score DESC,r.updated_at ASC LIMIT 1").first();
}

async function sendReady(env,row){
  const probe=await fetchCard(row.card_url);
  if(!probe.ok){await env.DB.prepare("UPDATE lumen_partner_recruitment SET updated_at=?,status=?,error=? WHERE partner_id=?").bind(new Date().toISOString(),probe.status,probe.error,row.partner_id).run();return{ok:false,sent:false,status:probe.status,error:probe.error};}
  const e=envelope({...row,id:row.partner_id},probe.selected);
  const t=timeout(SEND_TIMEOUT_MS);let raw="";let http=0;
  try{
    const resp=await fetch(e.url,{method:"POST",headers:e.headers,body:JSON.stringify(e.payload),signal:t.signal});http=resp.status;raw=await resp.text();if(!resp.ok)throw new Error(`send_http_${resp.status}`);
    let body={};try{body=JSON.parse(raw);}catch{}
    const info=extract(body,probe.selected.binding);const c=classify(info.responseText);const now=new Date().toISOString();
    const status=info.hasMessage?"RESPONDED":info.taskId?"SENT_TASK":"SENT";
    const stage=info.hasMessage?c.stage:"CONTACTED";
    await env.DB.prepare("UPDATE lumen_partner_recruitment SET updated_at=?,stage=?,status=?,agent_url=?,protocol_binding=?,protocol_version=?,task_id=?,context_id=?,response_text=?,response_class=?,invite_text=?,request_json=?,response_json=?,error=NULL,contact_count=contact_count+1,last_contact_at=?,next_action_at=NULL,engine_version=? WHERE partner_id=?")
      .bind(now,stage,status,probe.selected.url,probe.selected.binding,probe.selected.version,info.taskId,info.contextId,info.responseText,c.responseClass,e.text,JSON.stringify(e.payload),clean(raw,12000),now,VERSION,row.partner_id).run();
    return{ok:true,sent:true,version:VERSION,partnerId:row.partner_id,target:row.name,stage,status,taskId:info.taskId,responseClass:c.responseClass,responseText:info.responseText,guardrails:{bindingAllowed:false,spendAllowed:false,contractAllowed:false}};
  }catch(err){const now=new Date().toISOString();const msg=clean(err?.message||err,500);await env.DB.prepare("UPDATE lumen_partner_recruitment SET updated_at=?,status='SEND_FAILED',error=?,response_json=? WHERE partner_id=?").bind(now,`${msg}${http?`;http=${http}`:""}`,clean(raw,12000),row.partner_id).run();return{ok:false,sent:false,status:"SEND_FAILED",error:msg};}finally{t.clear();}
}

export async function sendNextRecruit(env,{force=false}={}){
  if(!(await ensureSchema(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  let row=await ready(env);
  if(!row){const p=await probeNextRecruit(env);if(!p?.probed||p.status!=="READY")return{...p,sent:false};row=await ready(env);}
  if(!row)return{ok:true,sent:false,reason:"no_ready_partner",version:VERSION};
  const enabled=String(env?.A2A_AUTONOMOUS_RECRUITMENT||"false").toLowerCase()==="true";
  if(!force&&!enabled)return{ok:true,sent:false,ready:true,partnerId:row.partner_id,target:row.name,reason:"autonomous_recruitment_disabled",nextAction:"human_trigger_or_enable_guarded_autonomy"};
  return sendReady(env,row);
}

async function pollOne(env,row){
  if(!row.task_id||!row.agent_url)return{polled:false};
  const v1=String(row.protocol_version||"").startsWith("1.");const t=timeout(SEND_TIMEOUT_MS);
  try{
    let resp;
    if(row.protocol_binding==="HTTP+JSON")resp=await fetch(`${normalizeBaseUrl(row.agent_url)}/tasks/${encodeURIComponent(row.task_id)}`,{headers:{accept:"application/a2a+json, application/json","a2a-version":row.protocol_version||"1.0"},signal:t.signal});
    else resp=await fetch(row.agent_url,{method:"POST",headers:{"content-type":"application/json",accept:"application/json","a2a-version":row.protocol_version||(v1?"1.0":"0.3")},body:JSON.stringify({jsonrpc:"2.0",id:`lumen-recruit-poll-${crypto.randomUUID()}`,method:v1?"GetTask":"tasks/get",params:{id:row.task_id}}),signal:t.signal});
    const raw=await resp.text();if(!resp.ok)throw new Error(`poll_http_${resp.status}`);let body={};try{body=JSON.parse(raw);}catch{}
    const info=extract(body,row.protocol_binding);if(!info.responseText)return{polled:true,responded:false,state:info.state};
    const c=classify(info.responseText);const now=new Date().toISOString();
    await env.DB.prepare("UPDATE lumen_partner_recruitment SET updated_at=?,stage=?,status='RESPONDED',response_text=?,response_class=?,response_json=?,error=NULL WHERE partner_id=?").bind(now,c.stage,info.responseText,c.responseClass,clean(raw,12000),row.partner_id).run();
    return{polled:true,responded:true,partnerId:row.partner_id,stage:c.stage,responseClass:c.responseClass,responseText:info.responseText};
  }catch(e){return{polled:true,responded:false,error:clean(e?.message||e,300)};}finally{t.clear();}
}

export async function pollRecruitmentResponses(env){
  if(!(await ensureSchema(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  const r=await env.DB.prepare("SELECT * FROM lumen_partner_recruitment WHERE status='SENT_TASK' AND task_id IS NOT NULL ORDER BY updated_at ASC LIMIT 5").all();
  const results=[];for(const row of r.results||[])results.push(await pollOne(env,row));
  return{ok:true,version:VERSION,polled:results.length,results};
}

async function stats(env){
  await ensureSchema(env);const row=await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN stage='QUALIFIED' THEN 1 ELSE 0 END) qualified,SUM(CASE WHEN stage='CONTACTED' THEN 1 ELSE 0 END) contacted,SUM(CASE WHEN stage='ENGAGED' THEN 1 ELSE 0 END) engaged,SUM(CASE WHEN stage='INTERESTED' THEN 1 ELSE 0 END) interested,SUM(CASE WHEN stage='PARTNER' THEN 1 ELSE 0 END) partners,SUM(CASE WHEN stage='DECLINED' THEN 1 ELSE 0 END) declined FROM lumen_partner_recruitment").first();
  return{version:VERSION,total:Number(row?.total||0),qualified:Number(row?.qualified||0),contacted:Number(row?.contacted||0),engaged:Number(row?.engaged||0),interested:Number(row?.interested||0),partners:Number(row?.partners||0),declined:Number(row?.declined||0),autonomousRecruitment:String(env?.A2A_AUTONOMOUS_RECRUITMENT||"false").toLowerCase()==="true",autonomousHiring:false,autonomousOutgoingSpend:false};
}

async function next(env){
  await ensureSchema(env);const row=await env.DB.prepare("SELECT r.partner_id,p.name,r.stage,r.status,r.response_class,r.response_text,r.last_contact_at,r.error,p.reputation_score,p.compatibility_score FROM lumen_partner_recruitment r JOIN lumen_partner_agents p ON p.id=r.partner_id ORDER BY r.updated_at DESC LIMIT 1").first();
  return{version:VERSION,recruitment:row||null};
}

export async function handleRecruitmentEngine(request,env){
  const url=new URL(request.url);
  if(request.method==="GET"&&url.pathname==="/recruitment/stats")return json(await stats(env));
  if(request.method==="GET"&&url.pathname==="/recruitment/next")return json(await next(env));
  if(request.method==="POST"&&url.pathname==="/recruitment/probe-next"){if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);return json(await probeNextRecruit(env),202);}
  if(request.method==="POST"&&url.pathname==="/recruitment/send-next"){if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);return json(await sendNextRecruit(env,{force:true}),202);}
  if(request.method==="POST"&&url.pathname==="/recruitment/poll"){if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);return json(await pollRecruitmentResponses(env),202);}
  return null;
}
