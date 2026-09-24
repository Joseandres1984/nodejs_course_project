const VERSION = "1.0-council-runtime";
const CARD_TIMEOUT_MS = 8000;
const SEND_TIMEOUT_MS = 15000;

function json(data,status=200){return Response.json(data,{status,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function clean(v,n=8000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}
function parse(v,fallback=null){try{return JSON.parse(v||"");}catch{return fallback;}}
function authorized(request,env){const a=clean(env?.OPPORTUNITY_ADMIN_TOKEN,500),b=clean(request.headers.get("x-lumen-admin"),500);return Boolean(a&&b&&a===b);}
function isHttps(v){try{return new URL(v).protocol==="https:";}catch{return false;}}
function normalizeBaseUrl(v){const u=new URL(v);u.hash="";u.search="";return u.toString().replace(/\/$/,"");}
function timeout(ms){const c=new AbortController();const t=setTimeout(()=>c.abort("timeout"),ms);return{signal:c.signal,clear:()=>clearTimeout(t)};}
async function sha256(text){const d=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(String(text)));return[...new Uint8Array(d)].map(b=>b.toString(16).padStart(2,"0")).join("");}

async function ensureSchema(env){
  if(!env?.DB)return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_council_rooms (id TEXT PRIMARY KEY,council_id TEXT NOT NULL,opportunity_id TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,status TEXT NOT NULL,round_no INTEGER NOT NULL DEFAULT 0,objective TEXT NOT NULL,shared_context TEXT,synthesis_json TEXT,alignment_score INTEGER,external_messages INTEGER NOT NULL DEFAULT 0,binding_allowed INTEGER NOT NULL DEFAULT 0,spend_allowed INTEGER NOT NULL DEFAULT 0,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE UNIQUE INDEX IF NOT EXISTS idx_lumen_council_rooms_council ON lumen_council_rooms(council_id)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_council_rooms_status ON lumen_council_rooms(status,updated_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_council_room_members (room_id TEXT NOT NULL,partner_id TEXT NOT NULL,name TEXT NOT NULL,role TEXT NOT NULL,endpoint TEXT,card_url TEXT,protocol_version TEXT,recruitment_stage TEXT,room_status TEXT NOT NULL,invite_count INTEGER NOT NULL DEFAULT 0,task_id TEXT,context_id TEXT,last_message_at TEXT,last_response_at TEXT,contribution_text TEXT,response_class TEXT,error TEXT,match_score INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(room_id,partner_id))"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_council_members_state ON lumen_council_room_members(room_id,room_status,match_score)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_council_room_messages (id TEXT PRIMARY KEY,room_id TEXT NOT NULL,partner_id TEXT,direction TEXT NOT NULL,kind TEXT NOT NULL,created_at TEXT NOT NULL,text TEXT,raw_json TEXT)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_council_messages_room ON lumen_council_room_messages(room_id,created_at)")
  ]);
  return true;
}

async function latestCouncil(env,councilId=""){
  if(councilId)return env.DB.prepare("SELECT * FROM lumen_partner_councils WHERE id=? LIMIT 1").bind(councilId).first();
  return env.DB.prepare("SELECT * FROM lumen_partner_councils WHERE status='DRAFT_COUNCIL' ORDER BY created_at DESC LIMIT 1").first();
}

async function opportunityContext(env,opportunityId){
  try{
    const row=await env.DB.prepare("SELECT o.id,o.name,o.description,o.revenue_offer_id,a.commercial_score,a.evidence_strength FROM lumen_opportunities o LEFT JOIN lumen_opportunity_assessments a ON a.opportunity_id=o.id WHERE o.id=? LIMIT 1").bind(opportunityId).first();
    if(!row)return"";
    return clean(`Opportunity: ${row.name}. Offer: ${row.revenue_offer_id||"n/a"}. Commercial score: ${Number(row.commercial_score||0)}. Evidence strength: ${row.evidence_strength||"unknown"}. Context: ${row.description||""}`,2600);
  }catch{return"";}
}

async function recruitmentStage(env,partnerId){
  try{return await env.DB.prepare("SELECT stage,status,last_contact_at FROM lumen_partner_recruitment WHERE partner_id=? LIMIT 1").bind(partnerId).first();}catch{return null;}
}

async function partnerDetails(env,partnerId){
  return env.DB.prepare("SELECT id,name,endpoint,card_url,protocol_version,reputation_score,compatibility_score FROM lumen_partner_agents WHERE id=? LIMIT 1").bind(partnerId).first();
}

function memberInitialStatus(stage){
  if(stage==="PARTNER"||stage==="INTERESTED")return"ELIGIBLE";
  if(stage==="ENGAGED")return"ENGAGED_PENDING";
  if(stage==="CONTACTED")return"WAITING_RECRUITMENT";
  if(stage==="DECLINED")return"DECLINED";
  return"PENDING";
}

export async function createCouncilRoom(env,councilId=""){
  if(!(await ensureSchema(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  const council=await latestCouncil(env,councilId);
  if(!council)return{ok:false,error:"draft_council_not_found",version:VERSION};
  const existing=await env.DB.prepare("SELECT * FROM lumen_council_rooms WHERE council_id=? LIMIT 1").bind(council.id).first();
  if(existing)return{ok:true,created:false,version:VERSION,roomId:existing.id,status:existing.status,councilId:council.id};
  let members=parse(council.members_json,[]);if(!Array.isArray(members))members=[];
  const external=members.filter(x=>x?.id&&x.id!=="LUMEN");
  if(!external.length)return{ok:false,error:"council_has_no_external_members",version:VERSION};
  const roomId=`ROOM-${crypto.randomUUID().replaceAll("-","").slice(0,14).toUpperCase()}`;
  const now=new Date().toISOString();
  const context=await opportunityContext(env,council.opportunity_id);
  const objective=clean(council.goal||`Non-binding multi-agent deliberation for ${council.opportunity_id}`,1600);
  await env.DB.prepare("INSERT INTO lumen_council_rooms(id,council_id,opportunity_id,created_at,updated_at,status,round_no,objective,shared_context,synthesis_json,alignment_score,external_messages,binding_allowed,spend_allowed,engine_version) VALUES(?,?,?,?,?,'DRAFT',0,?,?,NULL,NULL,0,0,0,?)")
    .bind(roomId,council.id,council.opportunity_id,now,now,objective,context,VERSION).run();
  for(const member of external){
    const partner=await partnerDetails(env,member.id);
    if(!partner)continue;
    const rec=await recruitmentStage(env,member.id);
    const stage=clean(rec?.stage,80)||"UNCONTACTED";
    await env.DB.prepare("INSERT INTO lumen_council_room_members(room_id,partner_id,name,role,endpoint,card_url,protocol_version,recruitment_stage,room_status,invite_count,task_id,context_id,last_message_at,last_response_at,contribution_text,response_class,error,match_score) VALUES(?,?,?,?,?,?,?,?,?,0,NULL,NULL,NULL,NULL,NULL,NULL,NULL,?)")
      .bind(roomId,partner.id,partner.name,clean(member.role,80)||"specialist",partner.endpoint,partner.card_url,partner.protocol_version,stage,memberInitialStatus(stage),Number(member.matchScore||0)).run();
  }
  return{ok:true,created:true,version:VERSION,roomId,status:"DRAFT",councilId:council.id,objective,guardrails:{bindingAllowed:false,spendAllowed:false,autonomousHiring:false}};
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
    responseText:clean((Array.isArray(parts)?parts:[]).map(p=>p?.text||p?.data?.text||"").filter(Boolean).join(" "),8000)||null
  };
}

async function priorContributions(env,roomId,excludePartner=""){
  const r=await env.DB.prepare("SELECT name,role,contribution_text FROM lumen_council_room_members WHERE room_id=? AND contribution_text IS NOT NULL AND TRIM(contribution_text)<>'' AND partner_id<>? ORDER BY last_response_at ASC LIMIT 6").bind(roomId,excludePartner||"").all();
  return(r.results||[]).map(x=>`${x.name} (${x.role}): ${clean(x.contribution_text,900)}`).join("\n");
}

function councilPrompt(room,member,prior){
  const previous=prior?`\n\nOther council contributions already received:\n${prior}\n\nPlease explicitly state where you agree, disagree, or can improve these points.`:"";
  return clean(`You are invited as a guest specialist to a non-binding LUMEN multi-agent council. Council room: ${room.id}. Your role: ${member.role}. Objective: ${room.objective}. Shared context: ${room.shared_context||"No additional context."}.${previous}\n\nPlease contribute: (1) your analysis from your specialty, (2) observed evidence versus assumptions, (3) important risks or disagreements, (4) the next action you recommend, and (5) up to two adjacent business ideas or agent combinations worth exploring. This discussion creates no contract, purchase, payment obligation, exclusivity, delegation authority, or binding commitment. Do not assume spending authority.`,4200);
}

function envelope(room,member,iface,text){
  const messageId=`lumen-council-${crypto.randomUUID()}`;
  const v1=String(iface.version||"").startsWith("1.");
  const message={messageId,role:v1?"ROLE_USER":"user",parts:[{text}]};
  const metadata={lumen:{type:"council_turn",roomId:room.id,councilId:room.council_id,opportunityId:room.opportunity_id,role:member.role,nonBinding:true,spendAllowed:false,contractAllowed:false}};
  if(iface.binding==="HTTP+JSON"){
    const payload={message,metadata};if(iface.tenant)payload.tenant=iface.tenant;
    return{messageId,url:`${iface.url}/message:send`,headers:{"content-type":"application/a2a+json",accept:"application/a2a+json, application/json","a2a-version":iface.version||"1.0"},payload};
  }
  const params={message,metadata};if(iface.tenant)params.tenant=iface.tenant;
  return{messageId,url:iface.url,headers:{"content-type":"application/json",accept:"application/json","a2a-version":iface.version||(v1?"1.0":"0.3")},payload:{jsonrpc:"2.0",id:messageId,method:v1?"SendMessage":"message/send",params}};
}

async function logMessage(env,roomId,partnerId,direction,kind,text,raw){
  const id=`CRM-${(await sha256(`${roomId}|${partnerId}|${direction}|${kind}|${Date.now()}|${crypto.randomUUID()}`)).slice(0,20).toUpperCase()}`;
  await env.DB.prepare("INSERT INTO lumen_council_room_messages(id,room_id,partner_id,direction,kind,created_at,text,raw_json) VALUES(?,?,?,?,?,?,?,?)")
    .bind(id,roomId,partnerId||null,direction,kind,new Date().toISOString(),clean(text,10000)||null,clean(raw,14000)||null).run();
}

async function updateRoomStatus(env,roomId){
  const counts=await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN contribution_text IS NOT NULL AND TRIM(contribution_text)<>'' THEN 1 ELSE 0 END) contributed,SUM(CASE WHEN invite_count>0 THEN 1 ELSE 0 END) invited FROM lumen_council_room_members WHERE room_id=?").bind(roomId).first();
  const total=Number(counts?.total||0),contributed=Number(counts?.contributed||0),invited=Number(counts?.invited||0);
  let status="DRAFT";
  if(invited>0)status="INVITING";
  if(contributed===1)status="ACTIVE";
  if(contributed>=2)status="DELIBERATING";
  if(total>0&&contributed>=total)status="READY_TO_SYNTHESIZE";
  await env.DB.prepare("UPDATE lumen_council_rooms SET updated_at=?,status=? WHERE id=? AND status<>'SYNTHESIZED'").bind(new Date().toISOString(),status,roomId).run();
  return{total,contributed,invited,status};
}

async function nextInvitable(env,roomId,forceGuest=false){
  const rows=await env.DB.prepare("SELECT * FROM lumen_council_room_members WHERE room_id=? AND invite_count=0 AND room_status NOT IN ('DECLINED','FAILED') ORDER BY match_score DESC,name ASC").bind(roomId).all();
  for(const row of rows.results||[]){
    if(["ELIGIBLE","ENGAGED_PENDING"].includes(row.room_status))return row;
    if(forceGuest&&row.room_status==="PENDING")return row;
  }
  return null;
}

export async function inviteNextCouncilMember(env,roomId,{forceGuest=false}={}){
  if(!(await ensureSchema(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  const room=await env.DB.prepare("SELECT * FROM lumen_council_rooms WHERE id=? LIMIT 1").bind(roomId).first();
  if(!room)return{ok:false,error:"room_not_found",version:VERSION};
  if(room.status==="SYNTHESIZED"||room.status==="CLOSED")return{ok:true,sent:false,reason:"room_not_open",status:room.status,version:VERSION};
  const member=await nextInvitable(env,roomId,forceGuest);
  if(!member)return{ok:true,sent:false,reason:"no_eligible_uninvited_member",version:VERSION};
  const partner=await partnerDetails(env,member.partner_id);
  if(!partner)return{ok:false,sent:false,error:"partner_not_found",version:VERSION};
  const probe=await fetchCard(partner.card_url||partner.endpoint);
  if(!probe.ok){
    await env.DB.prepare("UPDATE lumen_council_room_members SET room_status='FAILED',error=? WHERE room_id=? AND partner_id=?").bind(probe.error,roomId,member.partner_id).run();
    return{ok:false,sent:false,status:probe.status,error:probe.error,partnerId:member.partner_id,target:member.name,version:VERSION};
  }
  const prior=await priorContributions(env,roomId,member.partner_id);
  const text=councilPrompt(room,member,prior);
  const e=envelope(room,member,probe.selected,text);
  const t=timeout(SEND_TIMEOUT_MS);let raw="";let http=0;
  try{
    const resp=await fetch(e.url,{method:"POST",headers:e.headers,body:JSON.stringify(e.payload),signal:t.signal});http=resp.status;raw=await resp.text();if(!resp.ok)throw new Error(`send_http_${resp.status}`);
    let body={};try{body=JSON.parse(raw);}catch{}
    const info=extract(body);const now=new Date().toISOString();
    const memberStatus=info.responseText?"CONTRIBUTED":info.taskId?"WAITING_TASK":"INVITED";
    await env.DB.prepare("UPDATE lumen_council_room_members SET room_status=?,invite_count=invite_count+1,task_id=?,context_id=?,last_message_at=?,last_response_at=?,contribution_text=?,response_class=?,error=NULL WHERE room_id=? AND partner_id=?")
      .bind(memberStatus,info.taskId,info.contextId,now,info.responseText?now:null,info.responseText,info.responseText?"contribution":"none",roomId,member.partner_id).run();
    await env.DB.prepare("UPDATE lumen_council_rooms SET updated_at=?,round_no=round_no+1,external_messages=external_messages+1 WHERE id=?").bind(now,roomId).run();
    await logMessage(env,roomId,member.partner_id,"OUT","COUNCIL_TURN",text,JSON.stringify(e.payload));
    if(info.responseText)await logMessage(env,roomId,member.partner_id,"IN","CONTRIBUTION",info.responseText,raw);
    const state=await updateRoomStatus(env,roomId);
    return{ok:true,sent:true,version:VERSION,roomId,partnerId:member.partner_id,target:member.name,role:member.role,status:memberStatus,taskId:info.taskId,responseText:info.responseText,roomStatus:state.status,guardrails:{bindingAllowed:false,spendAllowed:false,contractAllowed:false}};
  }catch(err){
    const msg=clean(err?.message||err,500);await env.DB.prepare("UPDATE lumen_council_room_members SET room_status='FAILED',error=? WHERE room_id=? AND partner_id=?").bind(`${msg}${http?`;http=${http}`:""}`,roomId,member.partner_id).run();
    return{ok:false,sent:false,status:"SEND_FAILED",error:msg,target:member.name,version:VERSION};
  }finally{t.clear();}
}

async function pollMember(env,room,member){
  if(!member.task_id||!member.endpoint)return{polled:false};
  const partner=await partnerDetails(env,member.partner_id);if(!partner)return{polled:false};
  const probe=await fetchCard(partner.card_url||partner.endpoint);if(!probe.ok)return{polled:false,error:probe.error};
  const iface=probe.selected;const v1=String(iface.version||"").startsWith("1.");const t=timeout(SEND_TIMEOUT_MS);
  try{
    let resp;
    if(iface.binding==="HTTP+JSON")resp=await fetch(`${normalizeBaseUrl(iface.url)}/tasks/${encodeURIComponent(member.task_id)}`,{headers:{accept:"application/a2a+json, application/json","a2a-version":iface.version||"1.0"},signal:t.signal});
    else resp=await fetch(iface.url,{method:"POST",headers:{"content-type":"application/json",accept:"application/json","a2a-version":iface.version||(v1?"1.0":"0.3")},body:JSON.stringify({jsonrpc:"2.0",id:`lumen-council-poll-${crypto.randomUUID()}`,method:v1?"GetTask":"tasks/get",params:{id:member.task_id}}),signal:t.signal});
    const raw=await resp.text();if(!resp.ok)throw new Error(`poll_http_${resp.status}`);let body={};try{body=JSON.parse(raw);}catch{}
    const info=extract(body);if(!info.responseText)return{polled:true,responded:false,state:info.state};
    const now=new Date().toISOString();
    await env.DB.prepare("UPDATE lumen_council_room_members SET room_status='CONTRIBUTED',last_response_at=?,contribution_text=?,response_class='contribution',error=NULL WHERE room_id=? AND partner_id=?").bind(now,info.responseText,room.id,member.partner_id).run();
    await logMessage(env,room.id,member.partner_id,"IN","CONTRIBUTION",info.responseText,raw);
    return{polled:true,responded:true,partnerId:member.partner_id,responseText:info.responseText};
  }catch(e){return{polled:true,responded:false,error:clean(e?.message||e,400)};}finally{t.clear();}
}

export async function pollCouncilRuntime(env){
  if(!(await ensureSchema(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  const rooms=await env.DB.prepare("SELECT * FROM lumen_council_rooms WHERE status IN ('INVITING','ACTIVE','DELIBERATING','READY_TO_SYNTHESIZE') ORDER BY updated_at DESC LIMIT 6").all();
  const results=[];
  for(const room of rooms.results||[]){
    const members=await env.DB.prepare("SELECT * FROM lumen_council_room_members WHERE room_id=? AND room_status='WAITING_TASK' AND task_id IS NOT NULL LIMIT 6").bind(room.id).all();
    for(const member of members.results||[])results.push({roomId:room.id,...await pollMember(env,room,member)});
    await updateRoomStatus(env,room.id);
  }
  return{ok:true,version:VERSION,polled:results.length,results};
}

function tokens(text){
  const stop=new Set(["the","and","for","with","that","this","from","your","you","our","are","but","not","into","can","will","should","have","has","about","agent","lumen","council","their","they","then","also"]);
  return new Set(clean(text,12000).toLowerCase().match(/[a-z0-9][a-z0-9_-]{3,}/g)?.filter(x=>!stop.has(x))||[]);
}
function alignment(contribs){
  if(contribs.length<2)return 0;
  let pairs=0,sum=0;
  for(let i=0;i<contribs.length;i++)for(let j=i+1;j<contribs.length;j++){
    const a=tokens(contribs[i].contribution_text),b=tokens(contribs[j].contribution_text);const union=new Set([...a,...b]);let inter=0;for(const x of a)if(b.has(x))inter++;
    if(union.size){sum+=inter/union.size;pairs++;}
  }
  return pairs?Math.round((sum/pairs)*100):0;
}
function extractSentences(text,keywords,limit=4){
  const parts=String(text||"").split(/(?<=[.!?])\s+/).map(x=>clean(x,500)).filter(Boolean);
  return parts.filter(s=>keywords.some(k=>s.toLowerCase().includes(k))).slice(0,limit);
}

export async function synthesizeCouncil(env,roomId){
  if(!(await ensureSchema(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  const room=await env.DB.prepare("SELECT * FROM lumen_council_rooms WHERE id=? LIMIT 1").bind(roomId).first();if(!room)return{ok:false,error:"room_not_found",version:VERSION};
  const r=await env.DB.prepare("SELECT partner_id,name,role,contribution_text,last_response_at FROM lumen_council_room_members WHERE room_id=? AND contribution_text IS NOT NULL AND TRIM(contribution_text)<>'' ORDER BY last_response_at ASC").bind(roomId).all();
  const contribs=r.results||[];if(!contribs.length)return{ok:false,error:"no_contributions",version:VERSION};
  const all=contribs.map(x=>x.contribution_text).join(" ");
  const synthesis={
    generatedBy:"rule_based_council_synthesis_v1",
    contributionCount:contribs.length,
    contributors:contribs.map(x=>({partnerId:x.partner_id,name:x.name,role:x.role,excerpt:clean(x.contribution_text,900)})),
    riskSignals:extractSentences(all,["risk","concern","disagree","however","uncertain","assumption","constraint"],6),
    actionSignals:extractSentences(all,["recommend","next","should","propose","action","verify","contact","build"],6),
    ventureSignals:extractSentences(all,["business","opportunity","revenue","market","customer","buyer","service","idea"],6),
    note:"Non-binding synthesis. It summarizes observed council contributions and does not authorize spending, contracting, hiring, or execution."
  };
  const score=alignment(contribs);const now=new Date().toISOString();
  await env.DB.prepare("UPDATE lumen_council_rooms SET updated_at=?,status='SYNTHESIZED',synthesis_json=?,alignment_score=? WHERE id=?").bind(now,JSON.stringify(synthesis),score,roomId).run();
  await logMessage(env,roomId,null,"INTERNAL","SYNTHESIS",JSON.stringify(synthesis),null);
  return{ok:true,version:VERSION,roomId,status:"SYNTHESIZED",alignmentScore:score,synthesis,guardrails:{bindingAllowed:false,spendAllowed:false}};
}

async function stats(env){
  if(!(await ensureSchema(env)))return{version:VERSION,rooms:0};
  const row=await env.DB.prepare("SELECT COUNT(*) rooms,SUM(CASE WHEN status='DRAFT' THEN 1 ELSE 0 END) draft,SUM(CASE WHEN status='INVITING' THEN 1 ELSE 0 END) inviting,SUM(CASE WHEN status='ACTIVE' THEN 1 ELSE 0 END) active,SUM(CASE WHEN status='DELIBERATING' THEN 1 ELSE 0 END) deliberating,SUM(CASE WHEN status='SYNTHESIZED' THEN 1 ELSE 0 END) synthesized,COALESCE(SUM(external_messages),0) externalMessages FROM lumen_council_rooms").first();
  const members=await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN room_status='CONTRIBUTED' THEN 1 ELSE 0 END) contributed,SUM(CASE WHEN room_status='WAITING_TASK' THEN 1 ELSE 0 END) waiting FROM lumen_council_room_members").first();
  return{version:VERSION,rooms:Number(row?.rooms||0),draft:Number(row?.draft||0),inviting:Number(row?.inviting||0),active:Number(row?.active||0),deliberating:Number(row?.deliberating||0),synthesized:Number(row?.synthesized||0),externalMessages:Number(row?.externalMessages||0),members:Number(members?.total||0),contributions:Number(members?.contributed||0),waitingTasks:Number(members?.waiting||0),autonomousInvites:false,autonomousOutgoingSpend:false,bindingActionsHumanGated:true};
}

async function roomDetail(env,roomId){
  const room=await env.DB.prepare("SELECT * FROM lumen_council_rooms WHERE id=? LIMIT 1").bind(roomId).first();if(!room)return null;
  const m=await env.DB.prepare("SELECT partner_id,name,role,recruitment_stage,room_status,invite_count,task_id,last_message_at,last_response_at,contribution_text,error,match_score FROM lumen_council_room_members WHERE room_id=? ORDER BY match_score DESC,name ASC").bind(roomId).all();
  return{...room,synthesis:parse(room.synthesis_json,null),members:m.results||[]};
}

export async function handleCouncilRuntime(request,env){
  const url=new URL(request.url);
  if(request.method==="GET"&&url.pathname==="/council-runtime/stats")return json(await stats(env));
  if(request.method==="GET"&&url.pathname==="/council-runtime/room"){
    if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);
    const room=await roomDetail(env,clean(url.searchParams.get("id"),120));return room?json({version:VERSION,room}):json({ok:false,error:"room_not_found"},404);
  }
  if(request.method==="POST"&&url.pathname==="/council-runtime/create"){
    if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);
    let b={};try{b=await request.json();}catch{}return json(await createCouncilRoom(env,clean(b?.councilId,120)),202);
  }
  if(request.method==="POST"&&url.pathname==="/council-runtime/invite-next"){
    if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);
    let b={};try{b=await request.json();}catch{}return json(await inviteNextCouncilMember(env,clean(b?.roomId,120),{forceGuest:Boolean(b?.forceGuest)}),202);
  }
  if(request.method==="POST"&&url.pathname==="/council-runtime/poll"){
    if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);
    return json(await pollCouncilRuntime(env),202);
  }
  if(request.method==="POST"&&url.pathname==="/council-runtime/synthesize"){
    if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);
    let b={};try{b=await request.json();}catch{}return json(await synthesizeCouncil(env,clean(b?.roomId,120)),202);
  }
  return null;
}
