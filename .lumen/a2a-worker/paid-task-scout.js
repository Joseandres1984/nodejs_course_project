// Read-only funded A2A procurement task scout. Never registers, claims, sends or pays.
export const VERSION="1.0-funded-demand-observer";
const ENDPOINT="https://api.basedagents.ai/v1/tasks?status=open&limit=50&min_usdc=0.50";
const SOURCE="basedagents";
const RETRY_MS=4*3600000;
const FIT=/(supplier|sourcing|procurement|quotation|rfq\b|tender|\bbom\b|quote|price compar|industrial|buyer intent|export market|market research|mcp integration|a2a integration|x402 integration)/i;
const clean=(x,n=2000)=>String(x??"").replace(/[\x00-\x1f\x7f]/g," ").replace(/\s+/g," ").trim().slice(0,n);
const json=(x,status=200)=>Response.json(x,{status,headers:{"cache-control":"no-store","x-content-type-options":"nosniff"}});
const instant=x=>{const ms=Date.parse(String(x||""));return Number.isFinite(ms)?ms:null;};
const money=x=>{const s=String(x??"");return /^\d{1,7}(\.\d{1,6})?$/.test(s)?Number(s):null;};
export function qualifyTask(t={},now=new Date()){
 const errors=[],id=clean(t.task_id||t.id,120),title=clean(t.title,200),description=clean(t.description,2200);
 const created=clean(t.created_at||t.createdAt,50),expires=clean(t.expires_at||t.expiresAt,50);
 const nowMs=now instanceof Date?now.getTime():Number(now), createdMs=instant(created),expiryMs=expires?instant(expires):null;
 const amount=money(t.bounty?.amount_display);
 const funded=t.escrow?.status==="funded"&&Boolean(t.escrow?.funded_at)&&Boolean(t.escrow?.deposit_tx_hash);
 if(!/^task_[a-zA-Z0-9_-]{5,115}$/.test(id))errors.push("missing_task_id");
 if(t.status!=="open"||t.claimable!==true)errors.push("not_open_claimable");
 if(title.length<8||description.length<45)errors.push("scope_not_explicit");
 if(!FIT.test(title+" "+description))errors.push("not_lumen_capability");
 if(createdMs===null||createdMs>nowMs||nowMs-createdMs>14*86400000)errors.push("not_recent");
 if(expires&&(expiryMs===null||expiryMs<=nowMs))errors.push("expired");
 if(amount===null||amount<0.50)errors.push("budget_unverified_or_too_small");
 if(t.bounty?.token!=="USDC"||t.bounty?.network!=="eip155:8453")errors.push("not_base_mainnet_usdc");
 if(!funded)errors.push("no_source_funded_escrow");
 const service=/(quote|rfq|pricing)/i.test(title+" "+description)?"MP-QUOTE-SANITY":/(tender)/i.test(title+" "+description)?"MP-TENDER-SCAN":/(supplier|sourcing|procurement|\bbom\b|industrial)/i.test(title+" "+description)?"MP-SOURCING-5":"MP-BUYER-SIGNALS";
 return {eligible:errors.length===0,errors,id,title,description,amount,created,expires,service,
 buyer:clean(t.creator?.name||t.creator?.id||"",160),
 sourceUrl:id?"https://api.basedagents.ai/v1/tasks/"+encodeURIComponent(id):null,
 fundingLabel:funded?"PROVIDER_REPORTED_ESCROW_FUNDED":"NOT_VERIFIED",
 independentChainEvidence:false,claimAuthorized:false,proposalSent:false,verifiedSettlement:false};
}
function auth(r,e){return Boolean(e?.OPPORTUNITY_ADMIN_TOKEN&&r.headers.get("x-lumen-admin")===e.OPPORTUNITY_ADMIN_TOKEN);}
async function schema(env){
 if(!env?.DB)throw Error("persistence_unavailable");
 await env.DB.batch([
 env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_funded_task_scans (source TEXT PRIMARY KEY,last_attempt_at TEXT,last_success_at TEXT,status TEXT,examined INTEGER NOT NULL DEFAULT 0,eligible INTEGER NOT NULL DEFAULT 0,error TEXT)"),
 env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_funded_task_research (source TEXT NOT NULL,task_id TEXT NOT NULL,source_url TEXT NOT NULL,title TEXT NOT NULL,buyer TEXT,bounty_usdc REAL NOT NULL,posted_at TEXT,expires_at TEXT,service TEXT NOT NULL,status TEXT NOT NULL,funding_label TEXT NOT NULL,first_seen_at TEXT NOT NULL,last_seen_at TEXT NOT NULL,scope_excerpt TEXT NOT NULL,PRIMARY KEY(source,task_id))")
 ]);
}
async function readProvider(fetchImpl){
 const abort=new AbortController(),timer=setTimeout(()=>abort.abort("timeout"),9000);
 try{
  const r=await fetchImpl(ENDPOINT,{method:"GET",redirect:"manual",headers:{accept:"application/json"},signal:abort.signal});
  if(!r?.ok)throw Error("provider_http_"+(r?.status||0));
  if(Number(r.headers?.get?.("content-length")||0)>250000)throw Error("provider_response_too_large");
  const raw=await r.text();
  if(raw.length>250000)throw Error("provider_response_too_large");
  const o=JSON.parse(raw);
  if(o?.ok!==true||!Array.isArray(o.tasks))throw Error("provider_schema_changed");
  return o.tasks.slice(0,50);
 }finally{clearTimeout(timer);}
}
export async function scanFundedTasks(env,{now=new Date(),fetchImpl=fetch}={}){
 const iso=now.toISOString();
 try{
  await schema(env);
  const state=await env.DB.prepare("SELECT last_attempt_at,status FROM lumen_funded_task_scans WHERE source=?").bind(SOURCE).first();
  const previous=instant(state?.last_attempt_at);
  const retryLimit=state?.status==='SUCCESS'?RETRY_MS:60*1000;
  if(previous!==null&&now.getTime()-previous<retryLimit)return{ok:true,skipped:true,reason:"four_hour_cooldown"};
  await env.DB.prepare("INSERT INTO lumen_funded_task_scans(source,last_attempt_at,status) VALUES(?,?,'RUNNING') ON CONFLICT(source) DO UPDATE SET last_attempt_at=excluded.last_attempt_at,status='RUNNING'").bind(SOURCE,iso).run();
  const found=await readProvider(fetchImpl), qualified=found.map(t=>qualifyTask(t,now)).filter(t=>t.eligible).slice(0,15);
  let added=0;
  for(const t of qualified){
   const result=await env.DB.prepare("INSERT OR IGNORE INTO lumen_funded_task_research(source,task_id,source_url,title,buyer,bounty_usdc,posted_at,expires_at,service,status,funding_label,first_seen_at,last_seen_at,scope_excerpt) VALUES(?,?,?,?,?,?,?,?,?,'RESEARCH_ONLY',?,?,?,?)")
    .bind(SOURCE,t.id,t.sourceUrl,t.title,t.buyer,t.amount,t.created,t.expires,t.service,t.fundingLabel,iso,iso,t.description.slice(0,500)).run();
   if(Number(result?.meta?.changes||0)>0)added++;
   await env.DB.prepare("UPDATE lumen_funded_task_research SET last_seen_at=? WHERE source=? AND task_id=?").bind(iso,SOURCE,t.id).run();
  }
  await env.DB.prepare("UPDATE lumen_funded_task_scans SET last_success_at=?,status='SUCCESS',examined=?,eligible=?,error=NULL WHERE source=?").bind(iso,found.length,qualified.length,SOURCE).run();
  return{ok:true,version:VERSION,examined:found.length,eligible:qualified.length,newResearchCandidates:added,source:ENDPOINT,autonomousMessages:0,spendUsd:0,claims:0,settlementsVerifiedByThisScan:0};
 }catch(err){
  const error=clean(err?.message||err,140);
  try{await env.DB.prepare("UPDATE lumen_funded_task_scans SET status='FAILED',error=? WHERE source=?").bind(error,SOURCE).run();}catch{}
  return{ok:false,version:VERSION,error,autonomousMessages:0,spendUsd:0,claims:0};
 }
}
export async function handleFundedTaskScout(request,env){
 const path=new URL(request.url).pathname;
 if(!path.startsWith("/commercial/paid-tasks/"))return null;
 if(request.method==="GET"&&path==="/commercial/paid-tasks/policy")return json({version:VERSION,source:ENDPOINT,readOnly:true,escrowMustBeProviderReportedFunded:true,onchainVerificationStillRequired:true,ownerApprovalBeforeClaim:true,autonomousMessages:0,autonomousSpendUsd:0});
 if(!auth(request,env))return json({ok:false,error:"admin_token_required"},403);
 if(!env?.DB)return json({ok:false,error:"persistence_unavailable"},503);
 if(request.method==="POST"&&path==="/commercial/paid-tasks/scan")return json(await scanFundedTasks(env),202);
 if(request.method==="GET"&&path==="/commercial/paid-tasks/state"){
  try{
   await schema(env);
   const state=await env.DB.prepare("SELECT * FROM lumen_funded_task_scans WHERE source=?").bind(SOURCE).first();
   const list=await env.DB.prepare("SELECT task_id,source_url,title,buyer,bounty_usdc,posted_at,expires_at,service,status,funding_label,first_seen_at,last_seen_at FROM lumen_funded_task_research WHERE source=? ORDER BY last_seen_at DESC,bounty_usdc DESC LIMIT 25").bind(SOURCE).all();
   return json({ok:true,version:VERSION,state:state||null,candidates:list.results||[],note:"Provider-reported funded escrow is not on-chain verified settlement or buyer interest in LUMEN"});
  }catch{return json({ok:false,error:"database_unavailable"},503);}
 }
 return json({ok:false,error:"not_found"},404);
}
