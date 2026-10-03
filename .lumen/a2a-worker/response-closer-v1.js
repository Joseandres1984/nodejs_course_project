import { classifyCommercialResponse } from "./response-qualification.js";

export const RESPONSE_CLOSER_POLICY = Object.freeze({
  version: "2.0-response-closer-shared-response",
  objective: "consume_shared_real_buyer_response_truth_and_prepare_the_shortest_safe_path_to_verified_settlement",
  autonomousSpendUsd: 0,
  autonomousPurchase: false,
  autonomousContract: false,
  changesPrices: false,
  createsNewSenderAuthority: false,
  sendsBindingMessages: false,
  bindingActionsHumanGated: true,
  revenueTruth: "verified_x402_settlement_only",
  sharedResponseTruth: true,
  technicalAckIsNotIntent: true,
  echoIsNotIntent: true,
  genericResponseIsNotIntent: true
});

function clean(v,n=5000){return String(v??"").trim().replace(/\s+/g," ").slice(0,n);}
async function safeFirst(env,sql,bind=[]){try{const s=env.DB.prepare(sql);return bind.length?await s.bind(...bind).first():await s.first();}catch{return null;}}

function closePlan(row={}){
  const responseText=clean(row.response_text);
  const c=classifyCommercialResponse(responseText,row.original_message||"");
  const commercial=["PURCHASE_INTENT","COMMERCIAL_INTEREST","COMMERCIAL_QUESTION"].includes(c.responseClass);
  const checkoutEligible=["PURCHASE_INTENT","COMMERCIAL_INTEREST"].includes(c.responseClass);
  return {
    opportunityId:row.opportunity_id||null,
    proposalId:row.proposal_id||null,
    offerId:row.offer_id||null,
    responseSource:row.response_source||null,
    responseClass:c.responseClass,
    qualifiedCommercialIntent:commercial,
    checkoutEligible,
    reason:c.reason||null,
    nextAction:c.nextAction||null,
    stageRecommendation:c.stage||"RESPONDED",
    prepareOnly:commercial,
    executeCheckout:false,
    sendMessage:false,
    mutatePrice:false,
    humanGateRequired:checkoutEligible,
    successCriterion:"verified_x402_settlement_greater_than_zero"
  };
}

async function sharedResponseRow(env,opportunityId=null){
  const where=opportunityId?"WHERE r.opportunity_id=?":"WHERE r.stage='REPLIED'";
  const bind=opportunityId?[opportunityId]:[];
  const sql=`SELECT r.opportunity_id,r.proposal_id,r.offer_id,r.stage,p.amount_usd,p.quality_gate_status,p.message AS original_message,
    COALESCE(
      (SELECT cr.response_text FROM lumen_commercial_replies cr WHERE cr.proposal_id=r.proposal_id AND cr.response_text IS NOT NULL AND TRIM(cr.response_text)<>'' ORDER BY cr.updated_at DESC LIMIT 1),
      (SELECT f.response_text FROM lumen_followups f WHERE f.proposal_id=r.proposal_id AND f.response_text IS NOT NULL AND TRIM(f.response_text)<>'' ORDER BY COALESCE(f.sent_at,f.updated_at) DESC LIMIT 1),
      (SELECT x.response_text FROM lumen_outreach_attempts x WHERE x.proposal_id=r.proposal_id AND x.response_text IS NOT NULL AND TRIM(x.response_text)<>'' ORDER BY x.updated_at DESC LIMIT 1)
    ) AS response_text,
    CASE
      WHEN EXISTS(SELECT 1 FROM lumen_commercial_replies cr WHERE cr.proposal_id=r.proposal_id AND cr.response_text IS NOT NULL AND TRIM(cr.response_text)<>'') THEN 'commercial_reply'
      WHEN EXISTS(SELECT 1 FROM lumen_followups f WHERE f.proposal_id=r.proposal_id AND f.response_text IS NOT NULL AND TRIM(f.response_text)<>'') THEN 'followup'
      WHEN EXISTS(SELECT 1 FROM lumen_outreach_attempts x WHERE x.proposal_id=r.proposal_id AND x.response_text IS NOT NULL AND TRIM(x.response_text)<>'') THEN 'outreach'
      ELSE NULL END AS response_source
    FROM lumen_revenue_loop_v5 r
    LEFT JOIN lumen_proposal_drafts p ON p.proposal_id=r.proposal_id
    ${where}
    ORDER BY r.first_cash_score DESC,r.updated_at DESC LIMIT 25`;
  let rows=[];try{const q=env.DB.prepare(sql);const res=bind.length?await q.bind(...bind).all():await q.all();rows=res.results||[];}catch{return null;}
  return rows.find(x=>clean(x.response_text))||rows[0]||null;
}

export async function getResponseCloserStatus(env,opportunityId=null){
  if(!env?.DB)throw new Error("response_closer_persistence_required");
  const row=await sharedResponseRow(env,opportunityId);
  if(!row)return{ok:true,policy:RESPONSE_CLOSER_POLICY,status:"NO_REPLIED_OPPORTUNITY",plan:null};
  if(!clean(row.response_text))return{ok:true,policy:RESPONSE_CLOSER_POLICY,status:"NO_REAL_RESPONSE_TEXT",source:{opportunityId:row.opportunity_id,proposalId:row.proposal_id,stage:row.stage,amountUsd:row.amount_usd,qualityGate:row.quality_gate_status},plan:null};
  const plan=closePlan(row);
  const status=plan.qualifiedCommercialIntent?"QUALIFIED_COMMERCIAL_RESPONSE":"NON_COMMERCIAL_RESPONSE";
  return{ok:true,policy:RESPONSE_CLOSER_POLICY,status,source:{opportunityId:row.opportunity_id,proposalId:row.proposal_id,stage:row.stage,amountUsd:row.amount_usd,qualityGate:row.quality_gate_status,responseSource:row.response_source},plan};
}
