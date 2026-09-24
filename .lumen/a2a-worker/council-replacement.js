const VERSION="1.1-council-replacement";
function json(d,s=200){return Response.json(d,{status:s,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function clean(v,n=4000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}
function authorized(r,e){const a=clean(e?.OPPORTUNITY_ADMIN_TOKEN,500),b=clean(r.headers.get("x-lumen-admin"),500);return Boolean(a&&b&&a===b);}
async function ensure(env){await env.DB.batch([
 env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_partner_runtime_observations (id TEXT PRIMARY KEY,partner_id TEXT NOT NULL,observed_at TEXT NOT NULL,capability TEXT NOT NULL,status TEXT NOT NULL,evidence TEXT)"),
 env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_partner_runtime_observations ON lumen_partner_runtime_observations(partner_id,observed_at)")
]);}
async function roomFor(env,roomId=""){return roomId?env.DB.prepare("SELECT * FROM lumen_council_rooms WHERE id=? LIMIT 1").bind(roomId).first():env.DB.prepare("SELECT * FROM lumen_council_rooms WHERE status IN ('ACTIVE','INVITING','DELIBERATING') ORDER BY updated_at DESC LIMIT 1").first();}
async function observe(env,partnerId,capability,status,evidence){const id=`OBS-${crypto.randomUUID().replaceAll('-','').slice(0,16).toUpperCase()}`;await env.DB.prepare("INSERT INTO lumen_partner_runtime_observations(id,partner_id,observed_at,capability,status,evidence) VALUES(?,?,?,?,?,?)").bind(id,partnerId,new Date().toISOString(),capability,status,clean(evidence,1600)).run();}
async function replacementCandidate(env,room,role){
 const like=`%\"${clean(role,80).replaceAll('"','')}\"%`;
 return env.DB.prepare("SELECT p.id,p.name,p.endpoint,p.card_url,p.protocol_version,p.reputation_score,p.compatibility_score,m.match_score,m.matched_capabilities_json FROM lumen_partner_matches m JOIN lumen_partner_agents p ON p.id=m.partner_id WHERE m.opportunity_id=? AND m.status='quality_candidate' AND m.matched_capabilities_json LIKE ? AND p.status IN ('strong_candidate','candidate') AND m.partner_id NOT IN (SELECT partner_id FROM lumen_council_room_members WHERE room_id=?) AND m.partner_id NOT IN (SELECT partner_id FROM lumen_partner_runtime_observations WHERE status IN ('unsupported','low_quality')) ORDER BY m.match_score DESC,p.reputation_score DESC,p.compatibility_score DESC LIMIT 1").bind(room.opportunity_id,like,room.id).first();
}
async function installReplacement(env,room,oldMember,candidate,reasonTag){
 const now=new Date().toISOString();const role=clean(oldMember.role,80);
 await env.DB.prepare("UPDATE lumen_council_room_members SET room_status=?,error=COALESCE(error,'')||';replaced_by='||? WHERE room_id=? AND partner_id=?").bind(reasonTag,candidate.id,room.id,oldMember.partner_id).run();
 await env.DB.prepare("INSERT INTO lumen_council_room_members(room_id,partner_id,name,role,endpoint,card_url,protocol_version,recruitment_stage,room_status,invite_count,task_id,context_id,last_message_at,last_response_at,contribution_text,response_class,error,match_score) VALUES(?,?,?,?,?,?,?,'UNCONTACTED','PENDING',0,NULL,NULL,NULL,NULL,NULL,NULL,NULL,?)").bind(room.id,candidate.id,candidate.name,role,candidate.endpoint,candidate.card_url,candidate.protocol_version,Number(candidate.match_score||0)).run();
 await env.DB.prepare("UPDATE lumen_council_rooms SET updated_at=? WHERE id=?").bind(now,room.id).run();
 return{ok:true,replaced:true,version:VERSION,roomId:room.id,role,removed:{partnerId:oldMember.partner_id,name:oldMember.name,status:reasonTag},replacement:{partnerId:candidate.id,name:candidate.name,matchScore:Number(candidate.match_score||0),reputation:Number(candidate.reputation_score||0),compatibility:Number(candidate.compatibility_score||0),protocolVersion:candidate.protocol_version},guardrails:{bindingAllowed:false,spendAllowed:false,contractAllowed:false}};
}
export async function replaceFailedCouncilMember(env,roomId=""){
 await ensure(env);const room=await roomFor(env,roomId);if(!room)return{ok:false,error:"room_not_found",version:VERSION};
 const failed=await env.DB.prepare("SELECT * FROM lumen_council_room_members WHERE room_id=? AND room_status='FAILED' ORDER BY match_score DESC LIMIT 1").bind(room.id).first();
 if(!failed)return{ok:true,replaced:false,reason:"no_failed_member",roomId:room.id,version:VERSION};
 await observe(env,failed.partner_id,"a2a_runtime","unsupported",failed.error||"Council runtime transport failed");
 const candidate=await replacementCandidate(env,room,failed.role);if(!candidate)return{ok:false,replaced:false,error:"no_replacement_candidate_for_role",role:failed.role,roomId:room.id,version:VERSION};
 return installReplacement(env,room,failed,candidate,"REPLACED");
}
export async function replaceLowQualityCouncilMember(env,roomId=""){
 await ensure(env);const room=await roomFor(env,roomId);if(!room)return{ok:false,error:"room_not_found",version:VERSION};
 let rejected;
 try{rejected=await env.DB.prepare("SELECT m.*,q.score,q.reasons_json FROM lumen_council_room_members m JOIN lumen_council_contribution_quality q ON q.room_id=m.room_id AND q.partner_id=m.partner_id WHERE m.room_id=? AND m.room_status='CONTRIBUTED' AND q.status='REJECT' ORDER BY q.score ASC,m.match_score DESC LIMIT 1").bind(room.id).first();}
 catch{return{ok:false,replaced:false,error:"contribution_quality_not_ready",roomId:room.id,version:VERSION};}
 if(!rejected)return{ok:true,replaced:false,reason:"no_rejected_contribution",roomId:room.id,version:VERSION};
 await observe(env,rejected.partner_id,"council_contribution","low_quality",`score=${Number(rejected.score||0)};reasons=${clean(rejected.reasons_json,1200)}`);
 const candidate=await replacementCandidate(env,room,rejected.role);if(!candidate)return{ok:false,replaced:false,error:"no_replacement_candidate_for_role",role:rejected.role,roomId:room.id,version:VERSION};
 return installReplacement(env,room,rejected,candidate,"LOW_QUALITY_REPLACED");
}
export async function handleCouncilReplacement(request,env){
 const url=new URL(request.url);
 if(request.method==="POST"&&url.pathname==="/council-runtime/replace-failed"){
  if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);let b={};try{b=await request.json();}catch{}return json(await replaceFailedCouncilMember(env,clean(b?.roomId,120)),202);
 }
 if(request.method==="POST"&&url.pathname==="/council-runtime/replace-low-quality"){
  if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);let b={};try{b=await request.json();}catch{}return json(await replaceLowQualityCouncilMember(env,clean(b?.roomId,120)),202);
 }
 return null;
}
