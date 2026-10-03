export const RESPONSE_CLOSER_POLICY = Object.freeze({
  version: "1.0-response-closer",
  objective: "classify_real_buyer_replies_and_prepare_the_shortest_safe_path_to_verified_settlement",
  autonomousSpendUsd: 0,
  autonomousPurchase: false,
  autonomousContract: false,
  changesPrices: false,
  createsNewSenderAuthority: false,
  sendsBindingMessages: false,
  bindingActionsHumanGated: true,
  revenueTruth: "verified_x402_settlement_only"
});

function clean(v, n=4000) { return String(v ?? "").trim().replace(/\s+/g," ").slice(0,n); }
function has(text, terms) { const t=clean(text).toLowerCase(); return terms.some(x => t.includes(x)); }

export function classifyBuyerResponse(text="") {
  const t=clean(text);
  if (!t) return { responseClass:"UNCLASSIFIED", commercialQuality:"UNKNOWN", intentScore:0, nextAction:"request_manual_review" };
  if (has(t,["unsubscribe","remove me","no interesa","no gracias","not interested","do not contact"]))
    return { responseClass:"DECLINED", commercialQuality:"NONE", intentScore:0, nextAction:"close_without_followup" };
  if (has(t,["precio","price","cost","cuánto","cuanto","pagar","payment","checkout","comprar","buy","purchase","contratar","hire","send invoice","factura"]))
    return { responseClass:"PURCHASE_INTENT", commercialQuality:"HIGH", intentScore:0.95, nextAction:"prepare_existing_checkout_and_human_close_gate" };
  if (has(t,["alcance","scope","incluye","include","entrega","delivery","plazo","timeline","cómo funciona","como funciona","details","detalle"]))
    return { responseClass:"SCOPE_QUESTION", commercialQuality:"MEDIUM_HIGH", intentScore:0.78, nextAction:"prepare_exact_scope_answer_then_close_gate" };
  if (has(t,["interesa","interested","hablemos","talk","reunión","reunion","meeting","cotización","cotizacion","quote","proposal","propuesta"]))
    return { responseClass:"COMMERCIAL_INTEREST", commercialQuality:"MEDIUM_HIGH", intentScore:0.82, nextAction:"prepare_close_or_scope_confirmation" };
  if (has(t,["out of office","fuera de oficina","automatic reply","respuesta automática","no-reply","noreply"]))
    return { responseClass:"AUTOMATION", commercialQuality:"NONE", intentScore:0, nextAction:"do_not_treat_as_buyer_reply" };
  return { responseClass:"HUMAN_REPLY_UNCLEAR", commercialQuality:"LOW_MEDIUM", intentScore:0.35, nextAction:"prepare_one_question_clarification" };
}

export function prepareClosePlan(row={}) {
  const classification=classifyBuyerResponse(row.response_text);
  const allowedToPrepare=["PURCHASE_INTENT","COMMERCIAL_INTEREST","SCOPE_QUESTION","HUMAN_REPLY_UNCLEAR"].includes(classification.responseClass);
  return {
    opportunityId:row.opportunity_id||null,
    proposalId:row.proposal_id||null,
    offerId:row.offer_id||null,
    ...classification,
    stageRecommendation:["PURCHASE_INTENT","COMMERCIAL_INTEREST","SCOPE_QUESTION"].includes(classification.responseClass)?"NEGOTIATING":"REPLIED",
    prepareOnly:allowedToPrepare,
    executeCheckout:false,
    sendMessage:false,
    mutatePrice:false,
    humanGateRequired:allowedToPrepare,
    successCriterion:"verified_x402_settlement_greater_than_zero"
  };
}

async function safeFirst(env,sql,bind=[]) { try { const s=env.DB.prepare(sql); return bind.length?await s.bind(...bind).first():await s.first(); } catch { return null; } }

export async function getResponseCloserStatus(env, opportunityId=null) {
  if (!env?.DB) throw new Error("response_closer_persistence_required");
  const row = opportunityId
    ? await safeFirst(env,`SELECT r.opportunity_id,r.proposal_id,r.offer_id,r.stage,x.response_text,s.response_class,s.next_action,s.next_action_at,p.amount_usd,p.quality_gate_status FROM lumen_revenue_loop_v5 r LEFT JOIN lumen_outreach_attempts x ON x.proposal_id=r.proposal_id LEFT JOIN lumen_sales_pipeline s ON s.proposal_id=r.proposal_id LEFT JOIN lumen_proposal_drafts p ON p.proposal_id=r.proposal_id WHERE r.opportunity_id=? ORDER BY x.created_at DESC LIMIT 1`,[opportunityId])
    : await safeFirst(env,`SELECT r.opportunity_id,r.proposal_id,r.offer_id,r.stage,x.response_text,s.response_class,s.next_action,s.next_action_at,p.amount_usd,p.quality_gate_status FROM lumen_revenue_loop_v5 r LEFT JOIN lumen_outreach_attempts x ON x.proposal_id=r.proposal_id LEFT JOIN lumen_sales_pipeline s ON s.proposal_id=r.proposal_id LEFT JOIN lumen_proposal_drafts p ON p.proposal_id=r.proposal_id WHERE r.stage='REPLIED' ORDER BY r.first_cash_score DESC,r.updated_at DESC LIMIT 1`);
  if (!row) return { ok:true, policy:RESPONSE_CLOSER_POLICY, status:"NO_REPLIED_OPPORTUNITY", plan:null };
  return { ok:true, policy:RESPONSE_CLOSER_POLICY, status:"READY_FOR_CLASSIFICATION", source:{ opportunityId:row.opportunity_id, proposalId:row.proposal_id, stage:row.stage, amountUsd:row.amount_usd, qualityGate:row.quality_gate_status }, plan:prepareClosePlan(row) };
}
