import { inviteNextCouncilMember } from "./council-runtime.js";
import { replaceFailedCouncilMember, replaceLowQualityCouncilMember } from "./council-replacement.js";
import { synthesizeQualityCouncil } from "./council-quality-synthesis.js";
import { evaluatePartnerTrust } from "./partner-trust-policy.js";

const VERSION="1.1-council-round-manager";
function json(d,s=200){return Response.json(d,{status:s,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function clean(v,n=4000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}
function authorized(r,e){const a=clean(e?.OPPORTUNITY_ADMIN_TOKEN,500),b=clean(r.headers.get("x-lumen-admin"),500);return Boolean(a&&b&&a===b);}
function bool(v){return String(v??"false").toLowerCase()==="true";}
function num(v,fallback){const x=Number(v);return Number.isFinite(x)&&x>=0?x:fallback;}
function ageHours(iso){if(!iso)return Infinity;const t=Date.parse(iso);return Number.isFinite(t)?Math.max(0,(Date.now()-t)/3600000):Infinity;}

async function openRoom(env){return env.DB.prepare("SELECT * FROM lumen_council_rooms WHERE status IN ('DRAFT','INVITING','ACTIVE','DELIBERATING','READY_TO_SYNTHESIZE') ORDER BY updated_at DESC LIMIT 1").first();}
async function qualityCounts(env,roomId){try{return await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN status='PASS' THEN 1 ELSE 0 END) pass,SUM(CASE WHEN status='WEAK' THEN 1 ELSE 0 END) weak,SUM(CASE WHEN status='REJECT' THEN 1 ELSE 0 END) reject FROM lumen_council_contribution_quality WHERE room_id=?").bind(roomId).first();}catch{return{total:0,pass:0,weak:0,reject:0};}}
async function latestExternalMessage(env,roomId){const r=await env.DB.prepare("SELECT MAX(last_message_at) AS t FROM lumen_council_room_members WHERE room_id=? AND last_message_at IS NOT NULL").bind(roomId).first();return r?.t||null;}
async function memberCounts(env,roomId){return env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN room_status='PENDING' THEN 1 ELSE 0 END) pending,SUM(CASE WHEN room_status='INVITED' THEN 1 ELSE 0 END) invited,SUM(CASE WHEN room_status='WAITING_TASK' THEN 1 ELSE 0 END) waiting,SUM(CASE WHEN room_status='CONTRIBUTED' THEN 1 ELSE 0 END) contributed,SUM(CASE WHEN room_status='FAILED' THEN 1 ELSE 0 END) failed,SUM(CASE WHEN room_status='TRUST_BLOCKED' THEN 1 ELSE 0 END) trustBlocked,SUM(CASE WHEN room_status='LOW_QUALITY_REPLACED' THEN 1 ELSE 0 END) lowQualityReplaced FROM lumen_council_room_members WHERE room_id=?").bind(roomId).first();}
async function rejectedContributor(env,roomId){try{return await env.DB.prepare("SELECT m.partner_id,m.name,m.last_response_at,q.score FROM lumen_council_room_members m JOIN lumen_council_contribution_quality q ON q.room_id=m.room_id AND q.partner_id=m.partner_id WHERE m.room_id=? AND m.room_status='CONTRIBUTED' AND q.status='REJECT' ORDER BY q.score ASC LIMIT 1").bind(roomId).first();}catch{return null;}}
async function staleInvite(env,roomId,timeoutHours){const rows=await env.DB.prepare("SELECT partner_id,name,last_message_at FROM lumen_council_room_members WHERE room_id=? AND room_status='INVITED' AND contribution_text IS NULL ORDER BY last_message_at ASC LIMIT 10").bind(roomId).all();for(const row of rows.results||[]){if(ageHours(row.last_message_at)>=timeoutHours)return row;}return null;}

async function trustGateNextCandidate(env,roomId){
  const rows=await env.DB.prepare("SELECT partner_id,name,room_status,match_score FROM lumen_council_room_members WHERE room_id=? AND invite_count=0 AND room_status IN ('ELIGIBLE','ENGAGED_PENDING','PENDING') ORDER BY match_score DESC,name ASC").bind(roomId).all();
  for(const row of rows.results||[]){
    const trust=await evaluatePartnerTrust(env,row.partner_id,{purpose:"council"});
    if(trust.allowed)return{allowed:true,candidate:{partnerId:row.partner_id,name:row.name},trust};
    if(trust.reason==="trust_assessment_required")return{allowed:false,pendingAssessment:true,reason:"trust_assessment_required",candidate:{partnerId:row.partner_id,name:row.name},trust};
    await env.DB.prepare("UPDATE lumen_council_room_members SET room_status='TRUST_BLOCKED',error=? WHERE room_id=? AND partner_id=? AND invite_count=0")
      .bind(`trust_gate:${trust.reason};level=${trust.trustLevel||"unknown"};score=${Number(trust.trustScore||0)}`,roomId,row.partner_id).run();
  }
  return{allowed:false,pendingAssessment:false,reason:"no_trust_eligible_candidate"};
}

async function trustGatedInvite(env,roomId){
  const gate=await trustGateNextCandidate(env,roomId);
  if(!gate.allowed)return{ok:true,sent:false,reason:gate.reason,trustGate:gate,version:VERSION};
  const invite=await inviteNextCouncilMember(env,roomId,{forceGuest:true});
  return{...invite,trustGate:{required:true,passed:true,partnerId:gate.candidate.partnerId,trustLevel:gate.trust.trustLevel,trustScore:gate.trust.trustScore}};
}

export async function runCouncilRoundManager(env,{force=false}={}){
  if(!env?.DB)return{ok:false,error:"persistence_unavailable",version:VERSION};
  const room=await openRoom(env);if(!room)return{ok:true,acted:false,reason:"no_open_room",version:VERSION};
  const auto=bool(env?.A2A_AUTONOMOUS_COUNCIL_INVITES);
  const cooldownHours=num(env?.A2A_COUNCIL_INVITE_COOLDOWN_HOURS,6);
  const timeoutHours=num(env?.A2A_COUNCIL_RESPONSE_TIMEOUT_HOURS,12);
  const q=await qualityCounts(env,room.id);const pass=Number(q?.pass||0);

  if(pass>=2){const s=await synthesizeQualityCouncil(env,room.id);return{ok:true,acted:Boolean(s?.synthesized),action:"quality_synthesis",version:VERSION,roomId:room.id,result:s};}

  const rejected=await rejectedContributor(env,room.id);
  if(rejected){
    const rep=await replaceLowQualityCouncilMember(env,room.id);
    if(!rep?.replaced)return{ok:true,acted:false,reason:"rejected_contribution_no_replacement",version:VERSION,roomId:room.id,replacement:rep};
    const latest=await latestExternalMessage(env,room.id);const cooldownReady=ageHours(latest)>=cooldownHours;
    if((auto||force)&&cooldownReady){const invite=await trustGatedInvite(env,room.id);return{ok:true,acted:Boolean(invite?.sent),action:"replace_low_quality_and_trust_gated_invite",version:VERSION,roomId:room.id,replacement:rep,invite};}
    return{ok:true,acted:true,action:"replace_low_quality_only",version:VERSION,roomId:room.id,replacement:rep,nextAction:(auto||force)?"wait_cooldown":"autonomous_council_invites_disabled"};
  }

  const stale=await staleInvite(env,room.id,timeoutHours);
  if(stale){
    await env.DB.prepare("UPDATE lumen_council_room_members SET room_status='FAILED',error=COALESCE(error,'')||';council_invite_no_response_timeout' WHERE room_id=? AND partner_id=? AND room_status='INVITED'").bind(room.id,stale.partner_id).run();
    const rep=await replaceFailedCouncilMember(env,room.id);
    if(rep?.replaced&&(auto||force)){
      const invite=await trustGatedInvite(env,room.id);
      return{ok:true,acted:Boolean(invite?.sent),action:"timeout_replace_and_trust_gated_invite",version:VERSION,roomId:room.id,stale:{partnerId:stale.partner_id,name:stale.name},replacement:rep,invite};
    }
    return{ok:true,acted:true,action:"timeout_replace_only",version:VERSION,roomId:room.id,stale:{partnerId:stale.partner_id,name:stale.name},replacement:rep};
  }

  const latest=await latestExternalMessage(env,room.id);const since=ageHours(latest);const cooldownReady=since>=cooldownHours;
  const counts=await memberCounts(env,room.id);
  if((auto||force)&&cooldownReady&&Number(counts?.pending||0)>0){
    const invite=await trustGatedInvite(env,room.id);
    return{ok:true,acted:Boolean(invite?.sent),action:"trust_gated_invite_one_pending_member",version:VERSION,roomId:room.id,invite};
  }

  return{ok:true,acted:false,version:VERSION,roomId:room.id,reason:Number(counts?.invited||0)>0?"waiting_for_invited_agent":cooldownReady?"no_pending_member_ready":"invite_cooldown",quality:{pass:Number(q?.pass||0),weak:Number(q?.weak||0),reject:Number(q?.reject||0)},members:{pending:Number(counts?.pending||0),invited:Number(counts?.invited||0),waiting:Number(counts?.waiting||0),contributed:Number(counts?.contributed||0),trustBlocked:Number(counts?.trustBlocked||0)},autonomousInvites:auto,trustGateRequired:true,cooldownHours,responseTimeoutHours:timeoutHours,hoursSinceLastExternalMessage:Number.isFinite(since)?Math.round(since*10)/10:null};
}

export async function handleCouncilRoundManager(request,env){
  const url=new URL(request.url);
  if(request.method==="GET"&&url.pathname==="/council-round/stats"){
    const room=await openRoom(env);if(!room)return json({version:VERSION,openRoom:null,autonomousInvites:bool(env?.A2A_AUTONOMOUS_COUNCIL_INVITES),trustGateRequired:true});
    const q=await qualityCounts(env,room.id),m=await memberCounts(env,room.id),last=await latestExternalMessage(env,room.id);
    return json({version:VERSION,openRoom:{id:room.id,status:room.status},quality:{pass:Number(q?.pass||0),weak:Number(q?.weak||0),reject:Number(q?.reject||0)},members:{pending:Number(m?.pending||0),invited:Number(m?.invited||0),waiting:Number(m?.waiting||0),contributed:Number(m?.contributed||0),failed:Number(m?.failed||0),trustBlocked:Number(m?.trustBlocked||0)},autonomousInvites:bool(env?.A2A_AUTONOMOUS_COUNCIL_INVITES),trustGateRequired:true,cooldownHours:num(env?.A2A_COUNCIL_INVITE_COOLDOWN_HOURS,6),responseTimeoutHours:num(env?.A2A_COUNCIL_RESPONSE_TIMEOUT_HOURS,12),lastExternalMessage:last||null});
  }
  if(request.method==="POST"&&url.pathname==="/council-round/run"){
    if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);let b={};try{b=await request.json();}catch{}return json(await runCouncilRoundManager(env,{force:Boolean(b?.force)}),202);
  }
  return null;
}
