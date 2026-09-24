import { dispatchNextDelegationTask } from "./delegation-runtime.js";
import { evaluatePartnerTrust } from "./partner-trust-policy.js";

const VERSION="1.0-trusted-delegation-dispatch";
function json(d,s=200){return Response.json(d,{status:s,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*"}});}
function clean(v,n=1000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}
function authorized(r,e){const a=clean(e?.OPPORTUNITY_ADMIN_TOKEN,500),b=clean(r.headers.get("x-lumen-admin"),500);return Boolean(a&&b&&a===b);}

async function nextApproved(env){
  try{return await env.DB.prepare("SELECT id,partner_id,partner_name,role,status FROM lumen_delegation_tasks WHERE status='APPROVED_FOR_DISPATCH' AND binding_allowed=0 AND spend_allowed=0 ORDER BY created_at ASC LIMIT 1").first();}
  catch{return null;}
}

export async function dispatchNextTrustedDelegation(env,{force=false}={}){
  if(!env?.DB)return{ok:false,sent:false,error:"persistence_unavailable",version:VERSION};
  const task=await nextApproved(env);
  if(!task)return{ok:true,sent:false,reason:"no_approved_task",version:VERSION,trustGateRequired:true};
  const trust=await evaluatePartnerTrust(env,task.partner_id,{purpose:"delegation"});
  if(!trust.allowed){
    if(trust.reason==="trust_assessment_required")return{ok:true,sent:false,reason:"trust_assessment_required",version:VERSION,taskId:task.id,target:task.partner_name,trustGate:trust};
    const now=new Date().toISOString();
    await env.DB.prepare("UPDATE lumen_delegation_tasks SET status='FAILED',updated_at=?,error=? WHERE id=? AND status='APPROVED_FOR_DISPATCH'")
      .bind(now,`trust_gate_block:${trust.reason};level=${trust.trustLevel||"unknown"};score=${Number(trust.trustScore||0)}`,task.id).run();
    return{ok:true,sent:false,reason:"trust_gate_blocked",version:VERSION,taskId:task.id,target:task.partner_name,trustGate:trust,nextAction:"redundancy_engine_prepare_replacement"};
  }
  const result=await dispatchNextDelegationTask(env,{force});
  return{...result,trustGate:{required:true,passed:true,partnerId:task.partner_id,trustLevel:trust.trustLevel,trustScore:trust.trustScore},trustedDispatchVersion:VERSION};
}

export async function handleTrustedDelegationDispatch(request,env){
  const url=new URL(request.url);
  if(request.method!=="POST"||url.pathname!=="/delegation/dispatch-next")return null;
  if(!authorized(request,env))return json({ok:false,error:"admin_token_required"},403);
  let b={};try{b=await request.json();}catch{}
  return json(await dispatchNextTrustedDelegation(env,{force:Boolean(b?.force)}),202);
}
