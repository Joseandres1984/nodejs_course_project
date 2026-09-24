const VERSION = "1.1-council-contribution-quality";

const ROLE_WORDS = {
  verification:["verify","verification","evidence","trust","certification","assurance","risk","provenance","readiness"],
  sourcing:["source","sourcing","supplier","vendor","procurement","broker","buyer","market"],
  research:["research","evidence","analysis","investigate","data","source","finding","reference"],
  pricing:["price","pricing","quote","cost","benchmark","market"],
  logistics:["logistics","shipping","freight","delivery","transport"],
  sales:["buyer","sales","lead","prospect","demand","customer"]
};

function json(data,status=200){return Response.json(data,{status,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function clean(v,n=12000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}
function authorized(request,env){const a=clean(env?.OPPORTUNITY_ADMIN_TOKEN,500),b=clean(request.headers.get("x-lumen-admin"),500);return Boolean(a&&b&&a===b);}
function words(text){return new Set((clean(text,20000).toLowerCase().match(/[a-z0-9][a-z0-9_-]{3,}/g)||[]).filter(x=>!["this","that","with","from","your","have","will","into","agent","lumen","council","please","contribute","binding","guest","specialist"].includes(x)));}
function overlap(a,b){const A=words(a),B=words(b);if(!A.size||!B.size)return 0;let hit=0;for(const x of A)if(B.has(x))hit++;return hit/Math.min(A.size,B.size);}
function countHits(text,list){const t=clean(text,20000).toLowerCase();return list.filter(x=>t.includes(x)).length;}
function conceptScore(text,context){
  let shared=0;
  for(const list of Object.values(ROLE_WORDS)){
    const inText=list.filter(x=>clean(text,20000).toLowerCase().includes(x));
    const inContext=list.filter(x=>clean(context,20000).toLowerCase().includes(x));
    if(inText.length&&inContext.length)shared+=Math.min(2,Math.min(inText.length,inContext.length));
  }
  return Math.min(14,shared*3);
}
function stripPromptEcho(text,prompt){
  let novel=clean(text,20000);
  const p=clean(prompt,12000);
  let echo=0;
  if(!p)return{novel,echo,promptOverlap:0};
  const promptOverlap=overlap(novel,p);
  if(promptOverlap>0.62)echo+=20; else if(promptOverlap>0.48)echo+=10;
  const low=novel.toLowerCase();
  const marker="you are invited as a guest specialist";
  const endMarker="do not assume spending authority.";
  const start=low.indexOf(marker);
  if(start>=0){
    echo+=15;
    const end=low.indexOf(endMarker,start);
    if(end>=0)novel=clean(`${novel.slice(0,start)} ${novel.slice(end+endMarker.length)}`,20000);
    else if(p&&novel.includes(p))novel=clean(novel.replace(p," "),20000);
  } else if(p&&novel.includes(p)) {
    echo+=15;
    novel=clean(novel.replace(p," "),20000);
  }
  return{novel,echo:Math.min(35,echo),promptOverlap};
}

async function ensureSchema(env){
  if(!env?.DB)return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_council_contribution_quality (room_id TEXT NOT NULL,partner_id TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,score INTEGER NOT NULL,status TEXT NOT NULL,relevance_score INTEGER NOT NULL,specialty_score INTEGER NOT NULL,evidence_score INTEGER NOT NULL,action_score INTEGER NOT NULL,peer_score INTEGER NOT NULL,prompt_echo_penalty INTEGER NOT NULL,offtopic_penalty INTEGER NOT NULL,reasons_json TEXT NOT NULL,engine_version TEXT NOT NULL,PRIMARY KEY(room_id,partner_id))"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_council_quality_status ON lumen_council_contribution_quality(room_id,status,score)")
  ]);
  return true;
}

async function outboundPrompt(env,roomId,partnerId){
  const r=await env.DB.prepare("SELECT text FROM lumen_council_room_messages WHERE room_id=? AND partner_id=? AND direction='OUT' AND kind='COUNCIL_TURN' ORDER BY created_at DESC LIMIT 1").bind(roomId,partnerId).first();
  return clean(r?.text,12000);
}

function scoreContribution(room,member,prompt,allMembers){
  const original=clean(member.contribution_text,20000);
  const context=clean(`${room.objective||""} ${room.shared_context||""}`,14000);
  const role=clean(member.role,80).toLowerCase();
  const stripped=stripPromptEcho(original,prompt);
  const text=stripped.novel;
  const lower=text.toLowerCase();
  const peerNames=(allMembers||[]).filter(x=>x.partner_id!==member.partner_id&&x.contribution_text).map(x=>clean(x.name,120).toLowerCase()).filter(Boolean);
  const reasons=[];

  const lexical=Math.round(Math.min(22,overlap(text,context)*55));
  const concepts=conceptScore(text,context);
  const rel=Math.min(32,lexical+concepts);
  if(rel>=14)reasons.push("context_relevant");
  if(concepts>=6)reasons.push("shared_domain_concepts");

  const roleHits=countHits(text,ROLE_WORDS[role]||[role]);
  const specialty=Math.min(16,roleHits*4);
  if(specialty>=8)reasons.push("role_specific");

  const evidenceHits=countHits(text,["evidence","source","observed","verified","http://","https://","receipt","profile","record","data","reference","certification","readiness"]);
  const evidence=Math.min(14,evidenceHits*2);
  if(evidence>=6)reasons.push("evidence_or_source_signal");

  const actionHits=countHits(text,["recommend","next","should","propose","verify","check","contact","build","use ","create ","discover","confirm"]);
  const action=Math.min(14,actionHits*2);
  if(action>=6)reasons.push("actionable");

  let peer=0;
  if(peerNames.some(n=>lower.includes(n)))peer+=7;
  if(countHits(text,["agree","disagree","however","improve","building on","in addition","contrary"]))peer+=6;
  peer=Math.min(13,peer);
  if(peer>=7)reasons.push("engages_peer_context");

  const echo=stripped.echo;
  if(echo)reasons.push(`prompt_echo_penalty:${echo}`);

  let off=0;
  const verticals=[
    ["packaging",["packaging","carton","sku","shopify","closure","printer type"]],
    ["travel",["hotel","flight","travel","tourism"]],
    ["real_estate",["property","realtor","real estate"]]
  ];
  for(const [name,list] of verticals){
    const hits=countHits(text,list);
    const contextHits=countHits(context,list);
    if(hits>=3&&contextHits===0){off=Math.max(off,24);reasons.push(`offtopic_vertical:${name}`);}
  }

  let score=Math.max(0,Math.min(100,28+rel+specialty+evidence+action+peer-echo-off));
  if(echo>=25&&off>=20)score=Math.min(score,44);
  if(clean(text,20000).length<80)score=Math.min(score,58);
  const status=score>=65?"PASS":score>=45?"WEAK":"REJECT";
  return {score,status,relevance_score:rel,specialty_score:specialty,evidence_score:evidence,action_score:action,peer_score:peer,prompt_echo_penalty:echo,offtopic_penalty:off,reasons};
}

export async function reviewCouncilContributions(env,roomId=""){
  if(!(await ensureSchema(env)))return{ok:false,error:"persistence_unavailable",version:VERSION};
  let room;
  if(roomId)room=await env.DB.prepare("SELECT * FROM lumen_council_rooms WHERE id=? LIMIT 1").bind(roomId).first();
  else room=await env.DB.prepare("SELECT * FROM lumen_council_rooms WHERE status IN ('ACTIVE','DELIBERATING','READY_TO_SYNTHESIZE') ORDER BY updated_at DESC LIMIT 1").first();
  if(!room)return{ok:true,reviewed:0,reason:"no_active_room",version:VERSION};
  const r=await env.DB.prepare("SELECT * FROM lumen_council_room_members WHERE room_id=? ORDER BY match_score DESC").bind(room.id).all();
  const members=r.results||[];
  const results=[];
  for(const member of members){
    if(!clean(member.contribution_text,16000))continue;
    const prompt=await outboundPrompt(env,room.id,member.partner_id);
    const q=scoreContribution(room,member,prompt,members);
    const now=new Date().toISOString();
    await env.DB.prepare("INSERT INTO lumen_council_contribution_quality(room_id,partner_id,created_at,updated_at,score,status,relevance_score,specialty_score,evidence_score,action_score,peer_score,prompt_echo_penalty,offtopic_penalty,reasons_json,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(room_id,partner_id) DO UPDATE SET updated_at=excluded.updated_at,score=excluded.score,status=excluded.status,relevance_score=excluded.relevance_score,specialty_score=excluded.specialty_score,evidence_score=excluded.evidence_score,action_score=excluded.action_score,peer_score=excluded.peer_score,prompt_echo_penalty=excluded.prompt_echo_penalty,offtopic_penalty=excluded.offtopic_penalty,reasons_json=excluded.reasons_json,engine_version=excluded.engine_version")
      .bind(room.id,member.partner_id,now,now,q.score,q.status,q.relevance_score,q.specialty_score,q.evidence_score,q.action_score,q.peer_score,q.prompt_echo_penalty,q.offtopic_penalty,JSON.stringify(q.reasons),VERSION).run();
    results.push({partnerId:member.partner_id,name:member.name,role:member.role,...q});
  }
  return{ok:true,version:VERSION,roomId:room.id,reviewed:results.length,pass:results.filter(x=>x.status==='PASS').length,weak:results.filter(x=>x.status==='WEAK').length,reject:results.filter(x=>x.status==='REJECT').length,results};
}

export async function reviewActiveCouncilContributions(env){return reviewCouncilContributions(env,"");}

async function qualityRoom(env,roomId){
  await ensureSchema(env);
  const r=await env.DB.prepare("SELECT q.*,m.name,m.role FROM lumen_council_contribution_quality q JOIN lumen_council_room_members m ON m.room_id=q.room_id AND m.partner_id=q.partner_id WHERE q.room_id=? ORDER BY q.score DESC").bind(roomId).all();
  return (r.results||[]).map(x=>({...x,reasons:(()=>{try{return JSON.parse(x.reasons_json||'[]');}catch{return[];}})()}));
}

export async function handleCouncilContributionQuality(request,env){
  const url=new URL(request.url);
  if(request.method==='GET'&&url.pathname==='/council-quality/stats'){
    if(!(await ensureSchema(env)))return json({version:VERSION,total:0});
    const x=await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN status='PASS' THEN 1 ELSE 0 END) pass,SUM(CASE WHEN status='WEAK' THEN 1 ELSE 0 END) weak,SUM(CASE WHEN status='REJECT' THEN 1 ELSE 0 END) reject FROM lumen_council_contribution_quality").first();
    return json({version:VERSION,total:Number(x?.total||0),pass:Number(x?.pass||0),weak:Number(x?.weak||0),reject:Number(x?.reject||0)});
  }
  if(request.method==='POST'&&url.pathname==='/council-quality/review'){
    if(!authorized(request,env))return json({ok:false,error:'admin_token_required'},403);
    let b={};try{b=await request.json();}catch{}
    return json(await reviewCouncilContributions(env,clean(b?.roomId,120)),202);
  }
  if(request.method==='GET'&&url.pathname==='/council-quality/room'){
    if(!authorized(request,env))return json({ok:false,error:'admin_token_required'},403);
    const roomId=clean(url.searchParams.get('id'),120);return json({version:VERSION,roomId,contributions:await qualityRoom(env,roomId)});
  }
  return null;
}
