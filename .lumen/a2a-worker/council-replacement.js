const VERSION="1.0-council-replacement";
function json(d,s=200){return Response.json(d,{status:s,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function clean(v,n=4000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}
function authorized(r,e){const a=clean(e?.OPPORTUNITY_ADMIN_TOKEN,500),b=clean(r.headers.get("x-lumen-admin"),500);return Boolean(a&&b&&a===b);}
async function ensure(env){await env.DB.batch([
 env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_partner_runtime_observations (id TEXT PRIMARY KEY,partner_id TEXT NOT NULL,observed_at TEXT NOT NULL,capability TEXT NOT NULL,status TEXT NOT NULL,evidence TEXT)"),
 env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_partner_runtime_observations ON lumen_partner_runtime_observations(partner_id,observed_at)")
]);}
export async function replaceFailedCouncilMember(env,roomId=""){
 await ensure(env);
 const room=roomId?await env.DB.prepare("SELECT * FROM lumen_council_rooms WHERE id=? LIMIT 1").bind(roomId).first():await env.DB.prepare("SELECT * FROM lumen_council_rooms WHERE status IN ('ACTIVE','INVITING','DELIBERATING') ORDER BY updated_at DESC LIMIT 1").first();
 if(!room)return{ok:false,error:"room_not_found",version:VERSION};
 const failed=await env.DB.prepare("SELECT * FROM lumen_council_room_members WHERE room_id=? AND room_status='FAILED' ORDER BY match_score DESC LIMIT 1").bind(room.id).first();
 if(!failed)return{ok:true,replaced:false,reason:"no_failed_member",roomId:room.id,version:VERSION};
 const now=new Date().toISOString();
 const obsId=`OBS-${crypto.randomUUID().replaceAll('-','').slice(0,16).toUpperCase()}`;
 await env.DB.prepare("INSERT INTO lumen_partner_runtime_observations(id,partner_id,observed_at,capability,status,evidence) VALUES(?,?,?,?,?,?)").bind(obsId,failed.partner_id,now,"a2a_runtime","unsupported",clean(failed.error||"Council runtime transport failed",1200)).run();
 const role=clean(failed.role,80);
 const like=`%\"${role.replaceAll('"','')}\"%`;
 const candidate=await env.DB.prepare("SELECT p.id,p.name,p.endpoint,p.card_url,p.protocol_version,p.reputation_score,p.compatibility_score,m.match_score,m.matched_capabilities_json FROM lumen_partner_matches m JOIN lumen_partner_agents p ON p.id=m.partner_id WHERE m.opportunity_id=? AND m.status='quality_candidate' AND m.matched_capabilities_json LIKE ? AND p.status IN ('strong_candidate','candidate') AND m.partner_id NOT IN (SELECT partner_id FROM lumen_council_room_members WHERE room_id=?) ORDER BY m.match_score DESC,p.reputation_score DESC,p.compatibility_score DESC LIMIT 1").bind(room.opportunity_id,like,room.id).first();
 if(!candidate)return{ok:false,replaced:false,error:"no_replacement_candidate_for_role",role,roomId:room.id,version:VERSION};
 await env.DB.prepare("UPDATE lumen_council_room_members SET room_status='REPLACED',error=COALESCE(error,'')||';replaced_by='||? WHERE room_id=? AND partner_id=?").bind(candidate.id,room.id,failed.partner_id).run();
 await env.DB.prepare("INSERT INTO lumen_council_room_members(room_id,partner_id,name,role,endpoint,card_url,protocol_version,recruitment_stage,room_status,invite_count,task_id,context_id,last_message_at,last_response_at,contribution_text,response_class,error,match_score) VALUES(?,?,?,?,?,?,?,'UNCONTACTED','PENDING',0,NULL,NULL,NULL,NULL,NULL,NULL,NULL,?)").bind(room.id,candidate.id,candidate.name,role,candidate.endpoint,candidate.card_url,candidate.protocol_version,Number(candidate.match_score||0)).run();
 await env.DB.prepare("UPDATE lumen_council_rooms SET updated_at=? WHERE id=?").bind(now,room.id).run();
 return{ok:true,replaced:true,version:VERSION,roomId:room.id,role,removed:{partnerId:failed.partner_id,name:failed.name,status:"REPLACED"},replacement:{partnerId:candidate.id,name:candidate.name,matchScore:Number(candidate.match_score||0),reputation:Number(candidate.reputation_score||0),compatibility:Number(candidate.compatibility_score||0),protocolVersion:candidate.protocol_version},guardrails:{bindingAllowed:false,spendAllowed:false,contractAllowed:false}};
}
export async function handleCouncilReplacement(request,env){const url=new URL(request.url);if(request.method==="POST"&&url.pathname==="/council-runtime/replace-failed"){if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);let b={};try{b=await request.json();}catch{}return json(await replaceFailedCouncilMember(env,clean(b?.roomId,120)),202);}return null;}
