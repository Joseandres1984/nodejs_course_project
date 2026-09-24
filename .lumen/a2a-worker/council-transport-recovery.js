const VERSION = "1.0.1-council-transport-recovery";
const CARD_TIMEOUT_MS = 8000;
const SEND_TIMEOUT_MS = 15000;

function json(data,status=200){return Response.json(data,{status,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function clean(v,n=8000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}
function authorized(request,env){const a=clean(env?.OPPORTUNITY_ADMIN_TOKEN,500),b=clean(request.headers.get("x-lumen-admin"),500);return Boolean(a&&b&&a===b);}
function isHttps(v){try{return new URL(v).protocol==="https:";}catch{return false;}}
function normalize(v){const u=new URL(v);u.hash="";u.search="";return u.toString().replace(/\/$/,"");}
function timeout(ms){const c=new AbortController();const t=setTimeout(()=>c.abort("timeout"),ms);return{signal:c.signal,clear:()=>clearTimeout(t)};}
async function sha256(text){const d=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(String(text)));return[...new Uint8Array(d)].map(b=>b.toString(16).padStart(2,"0")).join("");}

async function fetchCard(url){
  if(!isHttps(url))return{ok:false,error:"card_url_not_https"};
  const t=timeout(CARD_TIMEOUT_MS);
  try{
    const r=await fetch(url,{headers:{accept:"application/json, application/a2a+json"},signal:t.signal});
    const raw=await r.text();if(!r.ok)return{ok:false,error:`card_http_${r.status}`};
    let card;try{card=JSON.parse(raw);}catch{return{ok:false,error:"card_invalid_json"};}
    const req=card?.securityRequirements;if(Array.isArray(req)&&req.length)return{ok:false,error:"agent_requires_authentication"};
    const legacy=card?.security;if(Array.isArray(legacy)&&legacy.length)return{ok:false,error:"agent_requires_authentication"};
    const interfaces=Array.isArray(card?.supportedInterfaces)?card.supportedInterfaces:Array.isArray(card?.supported_interfaces)?card.supported_interfaces:[];
    for(const x of interfaces){
      const binding=clean(x?.protocolBinding||x?.binding||x?.transport,80).toUpperCase();
      if(isHttps(x?.url)&&["JSONRPC","JSON-RPC","HTTP+JSON"].includes(binding))return{ok:true,card,iface:{url:normalize(x.url),binding:binding==="HTTP+JSON"?"HTTP+JSON":"JSONRPC",version:clean(x?.protocolVersion||x?.protocol_version||card?.protocolVersion||"1.0",20),tenant:clean(x?.tenant,120)||null}};
    }
    if(isHttps(card?.url))return{ok:true,card,iface:{url:normalize(card.url),binding:"JSONRPC",version:clean(card?.protocolVersion||"0.3",20),tenant:null}};
    return{ok:false,error:"no_supported_public_a2a_interface"};
  }catch(e){return{ok:false,error:clean(e?.message||e,300)};}finally{t.clear();}
}

function extract(body){
  const value=body?.result||body||{};
  const task=value?.task||(value?.id&&value?.status?value:null);
  const msg=value?.message||(Array.isArray(value?.parts)&&value?.role?value:null);
  const parts=msg?.parts||task?.status?.message?.parts||task?.artifacts?.flatMap?.(a=>a?.parts||[])||[];
  return{taskId:clean(task?.id,300)||null,contextId:clean(task?.contextId,300)||clean(msg?.contextId,300)||null,responseText:clean((Array.isArray(parts)?parts:[]).map(p=>p?.text||p?.data?.text||"").filter(Boolean).join(" "),8000)||null};
}

async function logMessage(env,roomId,partnerId,direction,kind,text,raw){
  const id=`CRM-${(await sha256(`${roomId}|${partnerId}|${direction}|${kind}|${Date.now()}|${crypto.randomUUID()}`)).slice(0,20).toUpperCase()}`;
  await env.DB.prepare("INSERT INTO lumen_council_room_messages(id,room_id,partner_id,direction,kind,created_at,text,raw_json) VALUES(?,?,?,?,?,?,?,?)").bind(id,roomId,partnerId,direction,kind,new Date().toISOString(),clean(text,10000)||null,clean(raw,14000)||null).run();
}

async function updateRoom(env,roomId){
  const c=await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN contribution_text IS NOT NULL AND TRIM(contribution_text)<>'' THEN 1 ELSE 0 END) contributed,SUM(CASE WHEN invite_count>0 THEN 1 ELSE 0 END) invited FROM lumen_council_room_members WHERE room_id=?").bind(roomId).first();
  const total=Number(c?.total||0),contributed=Number(c?.contributed||0),invited=Number(c?.invited||0);
  let status="DRAFT";if(invited>0)status="INVITING";if(contributed===1)status="ACTIVE";if(contributed>=2)status="DELIBERATING";if(total>0&&contributed>=total)status="READY_TO_SYNTHESIZE";
  await env.DB.prepare("UPDATE lumen_council_rooms SET updated_at=?,status=? WHERE id=? AND status<>'SYNTHESIZED'").bind(new Date().toISOString(),status,roomId).run();
  return{status,total,contributed};
}

async function prior(env,roomId,exclude){
  const r=await env.DB.prepare("SELECT name,role,contribution_text FROM lumen_council_room_members WHERE room_id=? AND partner_id<>? AND contribution_text IS NOT NULL AND TRIM(contribution_text)<>'' ORDER BY last_response_at ASC LIMIT 6").bind(roomId,exclude).all();
  return(r.results||[]).map(x=>`${x.name} (${x.role}): ${clean(x.contribution_text,1000)}`).join("\n");
}

function prompt(room,member,previous){
  return clean(`You are invited as a guest specialist to a non-binding LUMEN multi-agent council. Council room: ${room.id}. Your role: ${member.role}. Objective: ${room.objective}. Shared context: ${room.shared_context||"No additional context."}.\n\nOther council contributions already received:\n${previous||"None yet."}\n\nPlease explicitly say where you agree, disagree, or can improve the prior contribution, then provide: your specialty analysis, observed evidence versus assumptions, important risks, recommended next action, and up to two adjacent business ideas or agent combinations worth exploring. This discussion creates no contract, purchase, payment obligation, exclusivity, delegation authority, or binding commitment. Do not assume spending authority.`,4200);
}

function messageObjects(room,member,iface,text){
  const id=`lumen-council-retry-${crypto.randomUUID()}`;const v1=String(iface.version||"").startsWith("1.");
  const message={messageId:id,role:v1?"ROLE_USER":"user",parts:[{text}]};
  const metadata={lumen:{type:"council_turn",roomId:room.id,councilId:room.council_id,opportunityId:room.opportunity_id,role:member.role,nonBinding:true,spendAllowed:false,contractAllowed:false,transportRecovery:true}};
  const directPayload={message,metadata};if(iface.tenant)directPayload.tenant=iface.tenant;
  const params={message,metadata};if(iface.tenant)params.tenant=iface.tenant;
  const rpcPayload={jsonrpc:"2.0",id,method:v1?"SendMessage":"message/send",params};
  return{id,directPayload,rpcPayload};
}

async function attempt(url,headers,payload){
  const t=timeout(SEND_TIMEOUT_MS);
  try{
    const r=await fetch(url,{method:"POST",headers,body:JSON.stringify(payload),signal:t.signal});
    const raw=await r.text();let body={};try{body=JSON.parse(raw);}catch{}
    return{ok:r.ok,http:r.status,raw,body};
  }catch(e){return{ok:false,http:0,raw:"",body:{},error:clean(e?.message||e,300)};}finally{t.clear();}
}

export async function retryFailedCouncilMember(env,roomId=""){
  const room=roomId?await env.DB.prepare("SELECT * FROM lumen_council_rooms WHERE id=? LIMIT 1").bind(roomId).first():await env.DB.prepare("SELECT * FROM lumen_council_rooms WHERE status IN ('ACTIVE','INVITING','DELIBERATING') ORDER BY updated_at DESC LIMIT 1").first();
  if(!room)return{ok:false,error:"room_not_found",version:VERSION};
  const member=await env.DB.prepare("SELECT * FROM lumen_council_room_members WHERE room_id=? AND room_status='FAILED' AND invite_count=0 ORDER BY match_score DESC LIMIT 1").bind(room.id).first();
  if(!member)return{ok:true,retried:false,reason:"no_retryable_failed_member",roomId:room.id,version:VERSION};
  const partner=await env.DB.prepare("SELECT * FROM lumen_partner_agents WHERE id=? LIMIT 1").bind(member.partner_id).first();if(!partner)return{ok:false,error:"partner_not_found",version:VERSION};
  const card=await fetchCard(partner.card_url||partner.endpoint);if(!card.ok)return{ok:false,error:card.error,target:member.name,version:VERSION};
  const previous=await prior(env,room.id,member.partner_id);const text=prompt(room,member,previous);const obj=messageObjects(room,member,card.iface,text);
  const tries=[];
  if(card.iface.binding==="HTTP+JSON"){
    tries.push({name:"http_json_standard",url:`${card.iface.url}/message:send`,headers:{"content-type":"application/a2a+json",accept:"application/a2a+json, application/json","a2a-version":card.iface.version||"1.0"},payload:obj.directPayload});
    tries.push({name:"http_json_direct",url:card.iface.url,headers:{"content-type":"application/a2a+json",accept:"application/a2a+json, application/json","a2a-version":card.iface.version||"1.0"},payload:obj.directPayload});
    tries.push({name:"jsonrpc_direct_fallback",url:card.iface.url,headers:{"content-type":"application/json",accept:"application/json","a2a-version":card.iface.version||"1.0"},payload:obj.rpcPayload});
  }else{
    tries.push({name:"jsonrpc_direct",url:card.iface.url,headers:{"content-type":"application/json",accept:"application/json","a2a-version":card.iface.version||"1.0"},payload:obj.rpcPayload});
    tries.push({name:"http_json_direct_fallback",url:card.iface.url,headers:{"content-type":"application/a2a+json",accept:"application/a2a+json, application/json","a2a-version":card.iface.version||"1.0"},payload:obj.directPayload});
  }
  let winner=null;const diagnostics=[];
  for(const t of tries){const r=await attempt(t.url,t.headers,t.payload);diagnostics.push({transport:t.name,http:r.http,ok:r.ok});if(r.ok){winner={...r,transport:t.name,url:t.url,payload:t.payload};break;}if(r.http&&r.http!==404&&r.http!==405&&r.http!==415)break;}
  if(!winner){const err=`transport_recovery_failed:${diagnostics.map(x=>`${x.transport}:${x.http||"network"}`).join(",")}`;await env.DB.prepare("UPDATE lumen_council_room_members SET error=? WHERE room_id=? AND partner_id=?").bind(err,room.id,member.partner_id).run();return{ok:false,retried:true,sent:false,error:err,target:member.name,diagnostics,version:VERSION};}
  const info=extract(winner.body);const now=new Date().toISOString();const status=info.responseText?"CONTRIBUTED":info.taskId?"WAITING_TASK":"INVITED";
  await env.DB.prepare("UPDATE lumen_council_room_members SET room_status=?,invite_count=invite_count+1,task_id=?,context_id=?,last_message_at=?,last_response_at=?,contribution_text=?,response_class=?,error=NULL WHERE room_id=? AND partner_id=?").bind(status,info.taskId,info.contextId,now,info.responseText?now:null,info.responseText,info.responseText?"contribution":"none",room.id,member.partner_id).run();
  await env.DB.prepare("UPDATE lumen_council_rooms SET updated_at=?,round_no=round_no+1,external_messages=external_messages+1 WHERE id=?").bind(now,room.id).run();
  await logMessage(env,room.id,member.partner_id,"OUT","COUNCIL_TURN_RECOVERY",text,JSON.stringify(winner.payload));if(info.responseText)await logMessage(env,room.id,member.partner_id,"IN","CONTRIBUTION",info.responseText,winner.raw);
  const roomState=await updateRoom(env,room.id);
  return{ok:true,retried:true,sent:true,version:VERSION,roomId:room.id,partnerId:member.partner_id,target:member.name,role:member.role,status,responseText:info.responseText,taskId:info.taskId,transportUsed:winner.transport,diagnostics,roomStatus:roomState.status,guardrails:{bindingAllowed:false,spendAllowed:false,contractAllowed:false}};
}

export async function handleCouncilTransportRecovery(request,env){
  const url=new URL(request.url);
  if(request.method==="POST"&&url.pathname==="/council-runtime/retry-failed"){
    if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);
    let b={};try{b=await request.json();}catch{}
    return json(await retryFailedCouncilMember(env,clean(b?.roomId,120)),202);
  }
  return null;
}
