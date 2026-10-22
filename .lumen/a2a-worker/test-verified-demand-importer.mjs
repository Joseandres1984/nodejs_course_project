import assert from "node:assert/strict";
import test from "node:test";
import {validateQualifiedLead,validateBatch,importVerifiedBatch,LUMEN_API} from "./verified-demand-importer.mjs";
const now=new Date("2026-10-21T21:00:00Z");
const quote="We need a priced comparison of vetted electronics suppliers and lead times.";
const good={
 lane:"B2B",sourceUrl:"https://rfq.example.com/tenders/445?utm_source=test",buyer:"Example Procurement",
 sourceQuote:quote,buyerNeed:"Buyer posting: "+quote+" Provide BOM review and alternatives.",
 publishedAt:"2026-10-20T12:00:00Z",verifiedAt:"2026-10-21T20:00:00Z",openVerified:true,
 budgetUsd:200,budgetCurrency:"USD",proposedUsd:150,
 paymentCapacityVerified:true,paymentEvidenceUrl:"https://rfq.example.com/tenders/445",
 paymentEvidenceNote:"Buyer platform displays a verified funding marker.",
 channel:"platform-only tender inbox",channelRulesUrl:"https://rfq.example.com/terms",
 feeCheckNote:"Official supplier portal permits free single proposals without paid verification.",
 freeApplicationVerified:true,channelAllowsProposal:true,requiredSpendUsd:0,requiresConnects:false,requiresPaidVerification:false,
 productId:"MP-SOURCING-5",deliverable:"Evidence-linked supplier shortlist and price comparison"
};
test("high confidence demand is ready for internal draft intake, not external submission",()=>{
 const r=validateQualifiedLead(good,now);
 assert.equal(r.ok,true);assert.equal(r.sourceUrl,"https://rfq.example.com/tenders/445");
 assert.equal(validateBatch({version:"1.0",leads:[good]},now).length,1);
});
test("historical duplicates, unsupported money and paid channels fail closed",()=>{
 for(const bad of [
 {sourceUrl:"https://www.upwork.com/freelance-jobs/apply/old_~022107693090507282665/"},
 {paymentCapacityVerified:false},{paymentEvidenceUrl:""},
 {freeApplicationVerified:false},{requiresConnects:true},{requiresPaidVerification:true},{requiredSpendUsd:1},
 {sourceQuote:"I want a supplier."},{budgetCurrency:"EUR"},{proposedUsd:250},
 {publishedAt:"2026-09-12T00:00:00Z"},{verifiedAt:"2026-10-16T00:00:00Z"},
 {channelAllowsProposal:false},{automatedApplicationRequested:true,termsAllowAutomatedApplications:false}
 ])assert.equal(validateQualifiedLead({...good,...bad},now).ok,false,JSON.stringify(bad));
});
test("unique evidence-qualified leads only; zero synthetic prospects",()=>{
 assert.deepEqual(validateBatch({version:"1.0",leads:[]},now),[]);
 assert.throws(()=>validateBatch({version:"1.0",leads:[good,{...good,sourceUrl:"https://rfq.example.com/tenders/445?utm_campaign=dup"}]},now),/duplicate_within/);
});
test("upload to LUMEN internal draft endpoint only, with owner-review response gate",async()=>{
 const calls=[];
 const fetchImpl=async (url,opts)=>{
  calls.push({url,opts});
  return{status:201,json:async()=>({ok:true,proposal:{status:"AWAITING_OWNER_REVIEW",controls:{messagesSent:0}}})};
 };
 const r=await importVerifiedBatch({version:"1.0",leads:[good]},{now,fetchImpl,token:"test-admin-token-valid"});
 assert.equal(r.ok,true);assert.equal(r.prepared,1);
 assert.equal(r.outboundMessages,0);assert.equal(r.spendUsd,0);assert.equal(r.settlements,0);
 assert.equal(calls.length,1);assert.equal(calls[0].url,LUMEN_API+"/commercial/proposals/prepare");
 assert.equal(calls[0].opts.method,"POST");assert.equal(calls[0].opts.redirect,"manual");
 const sent=JSON.parse(calls[0].opts.body);assert.equal(sent.sourceUrl,"https://rfq.example.com/tenders/445");
 assert.equal(sent.directCommercialIntentVerified,true);
});
test("unknown endpoint and invalid secret cannot leak the API secret",async()=>{
 await assert.rejects(importVerifiedBatch({version:"1.0",leads:[good]},{now,token:"test-admin-token-valid",apiBase:"https://attacker.example"}),/refuse_non_lumen_destination/);
 await assert.rejects(importVerifiedBatch({version:"1.0",leads:[good]},{now,token:"",fetchImpl:async()=>{throw Error("unreachable");}}),/owner_admin_secret_required/);
});
test("duplicate API proposals count as duplicates not sales",async()=>{
 const r=await importVerifiedBatch({version:"1.0",leads:[good]},{now,token:"test-admin-token-valid",fetchImpl:async()=>({status:409})});
 assert.equal(r.ok,true);assert.equal(r.prepared,0);assert.equal(r.duplicates,1);assert.equal(r.settlements,0);
});
test("no leads triggers no external requests and no secret requirement",async()=>{
 let count=0;
 const r=await importVerifiedBatch({version:"1.0",leads:[]},{now,fetchImpl:async()=>{count++;throw Error("unexpected");}});
 assert.equal(count,0);assert.equal(r.checked,0);assert.equal(r.ok,true);
});
