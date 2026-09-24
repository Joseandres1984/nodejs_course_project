const VERSION="1.0-council-quality-synthesis";
function json(d,s=200){return Response.json(d,{status:s,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function clean(v,n=12000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}
function authorized(r,e){const a=clean(e?.OPPORTUNITY_ADMIN_TOKEN,500),b=clean(r.headers.get("x-lumen-admin"),500);return Boolean(a&&b&&a===b);}
function sentences(text){return String(text||"").split(/(?<=[.!?])\s+/).map(x=>clean(x,700)).filter(Boolean);}
function pick(text,keys,limit=6){return sentences(text).filter(s=>keys.some(k=>s.toLowerCase().includes(k))).slice(0,limit);}
function tokens(text){const stop=new Set(["this","that","with","from","your","have","will","into","agent","lumen","council","please","their","they","then","also","about","there","which"]);return new Set((clean(text,20000).toLowerCase().match(/[a-z0-9][a-z0-9_-]{3,}/g)||[]).filter(x=>!stop.has(x)));}
function alignment(rows){if(rows.length<2)return 0;let sum=0,pairs=0;for(let i=0;i<rows.length;i++)for(let j=i+1;j<rows.length;j++){const a=tokens(rows[i].contribution_text),b=tokens(rows[j].contribution_text),u=new Set([...a,...b]);let hit=0;for(const x of a)if(b.has(x))hit++;if(u.size){sum+=hit/u.size;pairs++;}}return pairs?Math.round((sum/pairs)*100):0;}
async function logInternal(env,roomId,text){try{const id=`CRM-${crypto.randomUUID().replaceAll('-','').slice(0,20).toUpperCase()}`;await env.DB.prepare("INSERT INTO lumen_council_room_messages(id,room_id,partner_id,direction,kind,created_at,text,raw_json) VALUES(?,?,NULL,'INTERNAL','QUALITY_SYNTHESIS',?,?,NULL)").bind(id,roomId,new Date().toISOString(),clean(text,12000)).run();}catch{}}
export async function synthesizeQualityCouncil(env,roomId=""){
  const room=roomId?await env.DB.prepare("SELECT * FROM lumen_council_rooms WHERE id=? LIMIT 1").bind(roomId).first():await env.DB.prepare("SELECT * FROM lumen_council_rooms WHERE status IN ('ACTIVE','DELIBERATING','READY_TO_SYNTHESIZE') ORDER BY updated_at DESC LIMIT 1").first();
  if(!room)return{ok:false,synthesized:false,error:"room_not_found",version:VERSION};
  let q;
  try{q=await env.DB.prepare("SELECT m.partner_id,m.name,m.role,m.contribution_text,q.score,q.status,q.reasons_json FROM lumen_council_room_members m JOIN lumen_council_contribution_quality q ON q.room_id=m.room_id AND q.partner_id=m.partner_id WHERE m.room_id=? AND m.contribution_text IS NOT NULL AND TRIM(m.contribution_text)<>'' AND q.status='PASS' ORDER BY q.score DESC,m.last_response_at ASC").bind(room.id).all();}
  catch{return{ok:false,synthesized:false,error:"contribution_quality_not_ready",roomId:room.id,version:VERSION};}
  const rows=q.results||[];
  if(rows.length<2)return{ok:true,synthesized:false,version:VERSION,roomId:room.id,reason:"insufficient_quality_contributions",required:2,available:rows.length,passingContributors:rows.map(x=>({partnerId:x.partner_id,name:x.name,role:x.role,score:Number(x.score||0)})),nextAction:"keep_room_open_and_seek_another_quality_contribution"};
  const all=rows.map(x=>x.contribution_text).join(" ");
  const avg=Math.round(rows.reduce((a,x)=>a+Number(x.score||0),0)/rows.length);
  const synthesis={
    generatedBy:"quality_gated_rule_based_synthesis_v1",
    objective:clean(room.objective,1800),
    qualityAverage:avg,
    contributorCount:rows.length,
    contributors:rows.map(x=>({partnerId:x.partner_id,name:x.name,role:x.role,qualityScore:Number(x.score||0),excerpt:clean(x.contribution_text,1000)})),
    keyPoints:rows.flatMap(x=>sentences(x.contribution_text).slice(0,2)).slice(0,8),
    riskSignals:pick(all,["risk","concern","assumption","limitation","does not","cannot","uncertain","constraint"],6),
    actionSignals:pick(all,["recommend","next","should","verify","check","use ","create ","contact","build","discover","confirm"],6),
    ventureSignals:pick(all,["business","opportunity","market","customer","buyer","revenue","service","product","idea"],6),
    note:"Non-binding quality-gated synthesis. No spend, contract, hiring, purchase, debt or legal commitment is authorized."
  };
  const align=alignment(rows);const now=new Date().toISOString();
  await env.DB.prepare("UPDATE lumen_council_rooms SET updated_at=?,status='SYNTHESIZED',synthesis_json=?,alignment_score=? WHERE id=?").bind(now,JSON.stringify(synthesis),align,room.id).run();
  await logInternal(env,room.id,JSON.stringify(synthesis));
  return{ok:true,synthesized:true,version:VERSION,roomId:room.id,status:"SYNTHESIZED",alignmentScore:align,synthesis,guardrails:{bindingAllowed:false,spendAllowed:false,contractAllowed:false}};
}
export async function handleCouncilQualitySynthesis(request,env){
  const url=new URL(request.url);
  if(request.method==="POST"&&url.pathname==="/council-quality/synthesize"){
    if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);let b={};try{b=await request.json();}catch{}return json(await synthesizeQualityCouncil(env,clean(b?.roomId,120)),202);
  }
  if(request.method==="GET"&&url.pathname==="/council-quality/synthesis"){
    if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);const id=clean(url.searchParams.get("id"),120);const room=await env.DB.prepare("SELECT id,status,synthesis_json,alignment_score,updated_at FROM lumen_council_rooms WHERE id=? LIMIT 1").bind(id).first();if(!room)return json({ok:false,error:"room_not_found"},404);let synthesis=null;try{synthesis=JSON.parse(room.synthesis_json||"null");}catch{}return json({version:VERSION,room:{id:room.id,status:room.status,alignmentScore:room.alignment_score,synthesis,updatedAt:room.updated_at}});
  }
  return null;
}
