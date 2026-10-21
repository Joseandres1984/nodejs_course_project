import assert from "node:assert/strict";
import test from "node:test";
import { canonicalSourceUrl, wasInOctoberPipeline, qualifyExternalOpportunity, prepareExternalProposal, handleCommercialProposalOperator } from "./commercial-proposal-operator.js";
const now=new Date("2026-10-21T18:00:00Z");
const good={
 lane:"B2B",sourceUrl:"https://rfq.example.org/requests/1001?utm_source=news",
 publishedAt:"2026-10-20T14:00:00Z",verifiedAt:"2026-10-21T17:00:00Z",
 openVerified:true,directCommercialIntentVerified:true,buyer:"Procurement Buyer Group",
 buyerNeed:"Request for supplier pricing comparisons, technical datasheets, stock estimates and delivery terms for ten industrial items.",
 budgetUsd:200,paymentCapacityVerified:true,channel:"official buyer RFQ portal",
 channelAllowsProposal:true,freeApplicationVerified:true,requiredSpendUsd:0,
 productId:"MP-SOURCING-5",proposedUsd:150,deliverable:"Evidence-linked shortlist with a comparison matrix"
};
test("canonical URLs and October historical deduplication",()=>{
 assert.equal(canonicalSourceUrl(good.sourceUrl),"https://rfq.example.org/requests/1001");
 assert.equal(wasInOctoberPipeline("https://www.upwork.com/freelance-jobs/apply/China-Masking-Tape-Supplier-Sourcing-Agent-Needed_~022107693090507282665/?utm_campaign=other"),true);
 assert.equal(qualifyExternalOpportunity({...good,sourceUrl:"https://www.upwork.com/freelance-jobs/apply/abc_~022107693090507282665/"},now).ok,false);
});
test("draft B2B proposal, never send or contract",()=>{
 const r=prepareExternalProposal(good,now);
 assert.equal(r.status,"AWAITING_OWNER_REVIEW");
 assert.equal(r.controls.messagesSent,0);
 assert.equal(r.controls.spendUsd,0);
 assert.equal(r.controls.contracts,0);
 assert.equal(r.controls.autonomousSubmit,false);
 assert.match(r.message,/shortlist/);
});
test("A2A paid buyer requests have their own proposal lane",()=>{
 assert.equal(prepareExternalProposal({...good,lane:"A2A"},now).prepared,true);
 assert.equal(prepareExternalProposal({...good,lane:"A2A",directCommercialIntentVerified:false},now).prepared,false);
});
test("x402 demands verified checkout and individual approval",()=>{
 assert.equal(prepareExternalProposal({...good,lane:"X402"},now).prepared,false);
 const proposal=prepareExternalProposal({...good,lane:"X402",x402CheckoutVerified:true,ownerSettlementApprovalRequired:true},now);
 assert.equal(proposal.prepared,true);
 assert.equal(proposal.controls.individualOwnerApprovalBeforeEachX402Settlement,true);
 assert.match(proposal.message,/x402/);
});
test("rejects Connects, paid verification, insufficient budget and stale postings",()=>{
 for(const delta of [{requiresConnects:true},{requiresPaidVerification:true},{freeApplicationVerified:false},{proposedUsd:999},{publishedAt:"2026-09-20T00:00:00Z"},{automatedApplicationRequested:true,termsAllowAutomatedApplications:false}]){
  assert.equal(prepareExternalProposal({...good,...delta},now).prepared,false);
 }
});
test("private API never exposes queue without owner token",async()=>{
 const r=await handleCommercialProposalOperator(new Request("https://lumen.example/commercial/proposals/queue"),{OPPORTUNITY_ADMIN_TOKEN:"test"});
 assert.equal(r.status,403);
});
test("missing D1 fails closed",async()=>{
 const r=await handleCommercialProposalOperator(new Request("https://lumen.example/commercial/proposals/queue",{headers:{"x-lumen-admin":"test"}}),{OPPORTUNITY_ADMIN_TOKEN:"test"});
 assert.equal(r.status,503);
});
