import assert from "node:assert/strict";
import test from "node:test";
import {handleCommercialProposalOperator,qualifyExternalOpportunity,prepareExternalProposal,wasInOctoberPipeline} from "./commercial-proposal-operator.js";
const clock=new Date("2026-10-21T18:00:00Z");
const valid={lane:"B2B",sourceUrl:"https://procurement.example.com/rfq/7788?utm_source=news",buyer:"Industrial Procurement Team",buyerNeed:"Compare evidence-supported quotations for procurement of six industrial electronics, including supplier credibility, MOQ, lead time and substitution risk.",publishedAt:"2026-10-21T08:00:00Z",verifiedAt:"2026-10-21T17:00:00Z",openVerified:true,directCommercialIntentVerified:true,channel:"buyer-approved tender portal",channelAllowsProposal:true,freeApplicationVerified:true,requiredSpendUsd:0,paymentCapacityVerified:true,budgetUsd:200,proposedUsd:150,productId:"MP-SOURCING-5"};
function fakeDb(){
 const rows=new Map();const binds=[];
 return {rows,prepare(sql){return {
   bind(...args){binds.splice(0,binds.length,...args);return this;},
   async run(){
    if(sql.startsWith("CREATE TABLE")) return {meta:{changes:0}};
    if(sql.startsWith("INSERT OR IGNORE")) { const key=binds[0];if(rows.has(key)) return {meta:{changes:0}};rows.set(key,{draft_json:binds[7]});return {meta:{changes:1}}; }
    throw new Error("unexpected mutation");
   },
   async all(){if(sql.startsWith("SELECT draft_json")) return {results:[...rows.values()]};throw new Error("unexpected query");}
 };}};
}
const token="QA-test-token";
async function request(path,method,body,env,headers={}){
 return handleCommercialProposalOperator(new Request("https://lumen.example"+path,{method,headers:{"x-lumen-admin":token,...headers,...(body!==undefined?{"content-type":"application/json"}:{})},...(body!==undefined?{body:typeof body==="string"?body:JSON.stringify(body)}:{})}),env);
}
test("D1 queue persists only drafts, never external communication or payments",async()=>{
 const db=fakeDb(),env={OPPORTUNITY_ADMIN_TOKEN:token,DB:db};
 // Rebase the test fixture to actual runtime to make the API date gate meaningful.
 const live={...valid,publishedAt:new Date(Date.now()-3600000).toISOString(),verifiedAt:new Date(Date.now()-60000).toISOString()};
 const created=await request("/commercial/proposals/prepare","POST",live,env);
 assert.equal(created.status,201);const p=(await created.json()).proposal;
 assert.equal(p.status,"AWAITING_OWNER_REVIEW");assert.equal(p.controls.messagesSent,0);assert.equal(p.controls.spendUsd,0);assert.equal(p.controls.contracts,0);
 const again=await request("/commercial/proposals/prepare","POST",{...live,sourceUrl:"https://procurement.example.com/rfq/7788?utm_campaign=again"},env);
 assert.equal(again.status,409);assert.equal(db.rows.size,1);
 const got=await request("/commercial/proposals/queue","GET",undefined,env);
 assert.equal(got.status,200);const queue=(await got.json()).proposals;assert.equal(queue.length,1);assert.equal(queue[0].sourceUrl,"https://procurement.example.com/rfq/7788");
});
test("unauthenticated and incorrect token requests cannot initialize or read queue",async()=>{
 const db=fakeDb(),env={OPPORTUNITY_ADMIN_TOKEN:token,DB:db};
 const denied=await handleCommercialProposalOperator(new Request("https://lumen.example/commercial/proposals/queue"),env);
 assert.equal(denied.status,403);assert.equal(db.rows.size,0);
 const deniedPost=await request("/commercial/proposals/prepare","POST",valid,env,{"x-lumen-admin":"other"});
 assert.equal(deniedPost.status,403);assert.equal(db.rows.size,0);
});
test("input rejects missing evidence and requests with paid gates",()=>{
 for(const extra of [{channelAllowsProposal:false},{openVerified:false},{paymentCapacityVerified:false},{budgetUsd:0},{requiresConnects:true},{requiresPaidVerification:true},{requiredSpendUsd:1},{directCommercialIntentVerified:false},{publishedAt:"1980-01-01"},{proposedUsd:1000},{sourceUrl:"http://insecure.example/123"}])assert.equal(qualifyExternalOpportunity({...valid,...extra},clock).ok,false,JSON.stringify(extra));
});
test("x402 settlement approval enforced for each potential offer",()=>{
 assert.equal(prepareExternalProposal({...valid,lane:"X402"},clock).prepared,false);
 const x=prepareExternalProposal({...valid,lane:"X402",x402CheckoutVerified:true,ownerSettlementApprovalRequired:true},clock);
 assert.equal(x.prepared,true);assert.equal(x.controls.individualOwnerApprovalBeforeEachX402Settlement,true);assert.equal(x.controls.independentSettlementVerification,true);
});
test("October IDs are permanently excluded, irrespective of tracking query",()=>{
 for(const id of ["022106437762482382880","022107693090507282665","022108153513156874037"])assert.equal(wasInOctoberPipeline("https://www.upwork.com/freelance-jobs/apply/abc_~"+id+"/?utm_source=social"),true);
});
test("API rejects invalid payload; unknown methods fail closed",async()=>{
 const db=fakeDb(),env={OPPORTUNITY_ADMIN_TOKEN:token,DB:db};
 const invalid=await request("/commercial/proposals/prepare","POST","not-json",env);
 assert.equal(invalid.status,400);
 const bad=await request("/commercial/proposals/queue","POST",{},env);
 assert.equal(bad.status,405);
 assert.equal(db.rows.size,0);
});
