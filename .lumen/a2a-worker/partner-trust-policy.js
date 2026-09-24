const VERSION="1.0-partner-trust-policy";
function clean(v,n=1000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}

async function trustRecord(env,partnerId){
  try{return await env.DB.prepare("SELECT partner_id,name,trust_score,trust_level,auth_required,manipulation_hits,signature_status,signature_verified_count,card_fetch_status,https_card,https_endpoint,protocol_supported,runtime_failures,low_quality_events,assessed_at FROM lumen_partner_trust WHERE partner_id=? LIMIT 1").bind(partnerId).first();}
  catch{return null;}
}

export async function evaluatePartnerTrust(env,partnerId,{purpose="council"}={}){
  const id=clean(partnerId,220);
  if(!id)return{allowed:false,reason:"partner_id_required",version:VERSION,purpose};
  const t=await trustRecord(env,id);
  if(!t)return{allowed:false,reason:"trust_assessment_required",version:VERSION,purpose,partnerId:id,assessed:false};

  const score=Number(t.trust_score||0),level=clean(t.trust_level,40).toUpperCase();
  const hard=[];
  if(Number(t.auth_required||0)===1)hard.push("authentication_required");
  if(Number(t.manipulation_hits||0)>0)hard.push("manipulation_signal_detected");
  if(Number(t.https_card||0)!==1)hard.push("card_not_https");
  if(Number(t.https_endpoint||0)!==1)hard.push("endpoint_not_https");
  if(Number(t.protocol_supported||0)!==1)hard.push("unsupported_protocol");
  if(["RESTRICTED","QUARANTINE"].includes(level))hard.push(`trust_level_${level.toLowerCase()}`);
  if(hard.length)return{allowed:false,reason:"hard_trust_block",blockers:hard,version:VERSION,purpose,partnerId:id,trustScore:score,trustLevel:level,assessed:true};

  let allowed=false,reason="policy_threshold_not_met";
  if(purpose==="delegation"){
    allowed=level==="ALLOW"&&score>=70;
    reason=allowed?"delegation_trust_pass":"delegation_requires_allow_70";
  }else if(purpose==="council"){
    allowed=(level==="ALLOW"&&score>=70)||(level==="CAUTION"&&score>=50);
    reason=allowed?"council_trust_pass":"council_requires_allow_or_clean_caution";
  }else{
    allowed=level==="ALLOW"&&score>=70;
    reason=allowed?"strict_trust_pass":"strict_trust_threshold_not_met";
  }

  return{allowed,reason,version:VERSION,purpose,partnerId:id,trustScore:score,trustLevel:level,assessed:true,signatureStatus:t.signature_status||null,signatureVerifiedCount:Number(t.signature_verified_count||0),runtimeFailures:Number(t.runtime_failures||0),lowQualityEvents:Number(t.low_quality_events||0),assessedAt:t.assessed_at||null};
}
