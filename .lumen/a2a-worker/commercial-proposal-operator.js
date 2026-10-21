// LUMEN proposal operator: review-only B2B/A2A/x402 commercial queue.
// No sending, checkout execution, outgoing spend or contract creation.
export const VERSION = "1.0-review-only";
const legacyIds = ["022106437762482382880","022106953197669787680","022107335749330720517","022107724012214674066","022108153513156874037","022107600592597778777","022107304694479487424","022106234676886947780","022107606391730984809","022107693090507282665"];
const products = {
  "MP-SUPPLIER-SNAPSHOT":"Supplier Snapshot",
  "MP-QUOTE-SANITY":"Quote Sanity Check",
  "MP-TENDER-SCAN":"Tender Quick Scan",
  "MP-SOURCING-5":"Supplier Shortlist 5",
  "MP-BUYER-SIGNALS":"Buyer Signal Scan"
};
const tidy=(x,n=1200)=>String(x??"").replace(/[\x00-\x1f\x7f]/g," ").replace(/\s+/g," ").trim().slice(0,n);
export function canonicalSourceUrl(raw) {
  try {
    const u=new URL(raw);
    if(u.protocol!=="https:"||u.username||u.password) return null;
    u.hash="";
    for(const k of [...u.searchParams.keys()]) if(/^(utm_|fbclid$|gclid$|ref$|source$)/i.test(k)) u.searchParams.delete(k);
    u.searchParams.sort();
    u.pathname=u.pathname.replace(/\/+$/,"")||"/";
    return u.toString();
  } catch {return null;}
}
export function wasInOctoberPipeline(url) {
  const canonical=canonicalSourceUrl(url);
  if(!canonical) return false;
  const u=new URL(canonical);
  return /(^|\.)upwork\.com$/.test(u.hostname) && legacyIds.some(id=>u.pathname.includes(id));
}
export function qualifyExternalOpportunity(input={},now=new Date()) {
  const blockers=[];
  const lane=tidy(input.lane,12).toUpperCase();
  const sourceUrl=canonicalSourceUrl(input.sourceUrl);
  const buyer=tidy(input.buyer,140);
  const need=tidy(input.buyerNeed,900);
  const channel=tidy(input.channel,140);
  const published=Date.parse(String(input.publishedAt||""));
  const verified=Date.parse(String(input.verifiedAt||""));
  const clock=now instanceof Date?now.getTime():Date.parse(String(now));
  const budgetUsd=Number(input.budgetUsd);
  const proposedUsd=Number(input.proposedUsd);
  const noFee=input.freeApplicationVerified===true && Number(input.requiredSpendUsd??0)===0 && input.requiresConnects!==true && input.requiresPaidVerification!==true;
  if(!["B2B","A2A","X402"].includes(lane)) blockers.push("lane_invalid");
  if(!sourceUrl) blockers.push("https_source_required");
  if(sourceUrl&&wasInOctoberPipeline(sourceUrl)) blockers.push("duplicate_october_pipeline");
  if(buyer.length<3) blockers.push("buyer_identity_not_confirmed");
  if(need.length<35||input.directCommercialIntentVerified!==true) blockers.push("explicit_commercial_need_required");
  if(!Number.isFinite(published)||published>clock||clock-published>14*86400000) blockers.push("recent_publication_unverified");
  if(!Number.isFinite(verified)||verified>clock||clock-verified>36*3600000||input.openVerified!==true) blockers.push("current_open_status_unverified");
  if(!channel||input.channelAllowsProposal!==true) blockers.push("allowed_channel_unverified");
  if(!noFee) blockers.push("free_channel_unverified_or_paid_gate");
  if(input.paymentCapacityVerified!==true||!Number.isFinite(budgetUsd)||budgetUsd<=0) blockers.push("payment_capacity_missing");
  if(!Number.isFinite(proposedUsd)||proposedUsd<=0||(Number.isFinite(budgetUsd)&&proposedUsd>budgetUsd)) blockers.push("proposed_price_invalid");
  if(!products[input.productId]) blockers.push("lumen_product_unavailable");
  if(lane==="X402"&&(input.x402CheckoutVerified!==true||input.ownerSettlementApprovalRequired!==true)) blockers.push("x402_owner_checkout_gate_missing");
  if(input.automatedApplicationRequested===true&&input.termsAllowAutomatedApplications!==true) blockers.push("automated_submission_not_allowed");
  const firstCash=(input.paymentCapacityVerified===true?3:0)+(input.directCommercialIntentVerified===true?3:0)+(noFee?2:0)+(proposedUsd>0&&budgetUsd>=proposedUsd?2:0);
  const finiteScore=(value)=>{const n=Number(value);return Number.isFinite(n)?Math.max(0,Math.min(10,n)):5;};
  const speed=finiteScore(input.speedScore??5);
  const margin=finiteScore(input.marginScore??5);
  const score={firstCash,speed,margin,weighted:Number((firstCash*.55+speed*.25+margin*.20).toFixed(1))};
  if(score.weighted<7.5) blockers.push("insufficient_commercial_affinity");
  return {ok:blockers.length===0,blockers,sourceUrl,lane,buyer,need,channel,budgetUsd,proposedUsd,score};
}
export function prepareExternalProposal(input={},now=new Date()) {
  const q=qualifyExternalOpportunity(input,now);
  if(!q.ok) return {prepared:false,status:"BLOCKED",blockers:q.blockers,score:q.score};
  const product=products[input.productId];
  const scope=tidy(input.deliverable,420)||product;
  const differentiator=q.lane==="X402"?
    "For eligible agents, the defined deliverable can be offered via x402. Each settlement requires individual owner approval and independent verification.":
    q.lane==="A2A"?
    "We can deliver an evidence-backed machine-readable brief through a compatible agent interface if the recipient allows it.":
    "We will distinguish documented supplier facts from unconfirmed price, stock, lead-time and technical-equivalence claims.";
  const message=[
    "Hello "+q.buyer+",",
    "Your published purchasing requirement: "+q.need,
    "LUMEN proposes "+scope+".",
    "Fixed pilot offer: USD "+q.proposedUsd.toFixed(2)+", within the stated budget.",
    differentiator,
    "Communication, if authorized, stays inside "+q.channel+". No unverified credentials, sourcing results, contracts or past purchases will be claimed.",
    "This is non-binding. No order, payment, contract or commitment is created by this draft.",
    "If relevant, please share the detailed specification or evaluation criteria."
  ].join("\n\n");
  return {
    prepared:true,status:"AWAITING_OWNER_REVIEW",sourceUrl:q.sourceUrl,lane:q.lane,
    buyer:q.buyer,channel:q.channel,productId:input.productId,subject:"LUMEN | "+product+" | "+tidy(input.projectTitle||q.buyer,95),
    message,priceUsd:q.proposedUsd,score:q.score,
    evidence:{publishedAt:input.publishedAt,verifiedAt:input.verifiedAt,buyerNeed:q.need},
    controls:{messagesSent:0,spendUsd:0,contracts:0,autonomousSubmit:false,ownerReviewBeforeSend:true,individualOwnerApprovalBeforeEachX402Settlement:true,independentSettlementVerification:true}
  };
}
function reply(data,status=200){return Response.json(data,{status,headers:{"cache-control":"no-store","x-content-type-options":"nosniff"}});}
export async function handleCommercialProposalOperator(request,env){
  const path=new URL(request.url).pathname;
  if(!["/commercial/proposals/prepare","/commercial/proposals/queue"].includes(path)) return null;
  const token=tidy(env?.OPPORTUNITY_ADMIN_TOKEN,500);
  if(!token||tidy(request.headers.get("x-lumen-admin"),500)!==token) return reply({ok:false,error:"admin_token_required"},403);
  if(!env?.DB) return reply({ok:false,error:"persistence_unavailable"},503);
  try {
    await env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_external_proposal_queue (source_url TEXT PRIMARY KEY,lane TEXT NOT NULL,buyer TEXT NOT NULL,status TEXT NOT NULL,subject TEXT NOT NULL,message TEXT NOT NULL,evidence_json TEXT NOT NULL,draft_json TEXT NOT NULL,created_at TEXT NOT NULL)").run();
    if(request.method==="GET"&&path==="/commercial/proposals/queue"){
      const result=await env.DB.prepare("SELECT draft_json FROM lumen_external_proposal_queue WHERE status='AWAITING_OWNER_REVIEW' ORDER BY created_at DESC LIMIT 30").all();
      return reply({ok:true,proposals:(result.results||[]).map(r=>JSON.parse(r.draft_json))});
    }
    if(request.method==="POST"&&path==="/commercial/proposals/prepare"){
      const raw=await request.text();
      if(raw.length>12000) return reply({ok:false,error:"payload_too_large"},413);
      let input;try{input=JSON.parse(raw);}catch{return reply({ok:false,error:"invalid_json"},400);}
      if(!input||typeof input!=="object"||Array.isArray(input)) return reply({ok:false,error:"invalid_input"},400);
      const draft=prepareExternalProposal(input);
      if(!draft.prepared) return reply({ok:false,...draft},422);
      const inserted=await env.DB.prepare("INSERT OR IGNORE INTO lumen_external_proposal_queue(source_url,lane,buyer,status,subject,message,evidence_json,draft_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)")
        .bind(draft.sourceUrl,draft.lane,draft.buyer,draft.status,draft.subject,draft.message,JSON.stringify(draft.evidence),JSON.stringify(draft),new Date().toISOString()).run();
      if(Number(inserted?.meta?.changes||0)!==1) return reply({ok:false,reason:"duplicate_already_queued",sourceUrl:draft.sourceUrl},409);
      return reply({ok:true,proposal:draft},201);
    }
    return reply({ok:false,error:"method_not_allowed"},405);
  }catch{return reply({ok:false,error:"commercial_queue_unavailable"},503);}
}
