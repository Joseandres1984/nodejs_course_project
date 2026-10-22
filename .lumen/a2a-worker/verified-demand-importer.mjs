// GitHub -> LUMEN D1 intake. Only posts authenticated research to our own proposal queue.
// Never applies to marketplace jobs, sends a third-party message, creates a contract or pays.
import {readFileSync} from "node:fs";
import {pathToFileURL} from "node:url";
import {wasInOctoberPipeline,canonicalSourceUrl} from "./commercial-proposal-operator.js";
export const IMPORT_VERSION="1.0-evidence-only-no-outreach";
export const LUMEN_API="https://lumen-zero-a2a.lumen-b2b.workers.dev";
export const FILE=".lumen/sales/verified-demand-queue.json";
const trim=(v,n=2000)=>String(v??"").trim().replace(/\s+/g," ").slice(0,n);
function httpsUrl(value){
 try{const u=new URL(value);return u.protocol==="https:"&&!u.username&&!u.password&&u.hostname.includes(".")&&!["localhost","127.0.0.1","0.0.0.0"].includes(u.hostname)&&!u.hostname.endsWith(".local");}catch{return false;}
}
function timeRecent(value,now,maximumMs){
 const t=Date.parse(String(value||""));return Number.isFinite(t)&&t<=now.getTime()&&now.getTime()-t<=maximumMs;
}
export function validateQualifiedLead(entry={},now=new Date()){
 const errors=[];
 const src=canonicalSourceUrl(entry.sourceUrl);
 const quote=trim(entry.sourceQuote,700), need=trim(entry.buyerNeed,900);
 const budget=Number(entry.budgetUsd),proposal=Number(entry.proposedUsd);
 if(!["B2B","A2A","X402"].includes(entry.lane))errors.push("invalid_lane");
 if(!src||!httpsUrl(src))errors.push("source_url_invalid");
 else if(wasInOctoberPipeline(src))errors.push("duplicate_historical_pipeline");
 if(trim(entry.buyer,140).length<3)errors.push("buyer_missing");
 if(quote.length<35||!need.toLowerCase().includes(quote.toLowerCase()))errors.push("verbatim_buyer_need_evidence_missing");
 if(!timeRecent(entry.publishedAt,now,14*86400000))errors.push("publication_stale_or_unknown");
 if(!timeRecent(entry.verifiedAt,now,36*3600000)||entry.openVerified!==true)errors.push("current_status_unverified");
 if(!Number.isFinite(budget)||budget<=0||!Number.isFinite(proposal)||proposal<=0||proposal>budget||entry.budgetCurrency!=="USD")errors.push("usd_budget_or_price_invalid");
 if(!httpsUrl(entry.paymentEvidenceUrl)||trim(entry.paymentEvidenceNote).length<16||entry.paymentCapacityVerified!==true)errors.push("payment_capacity_evidence_missing");
 if(!httpsUrl(entry.channelRulesUrl)||trim(entry.feeCheckNote).length<20||entry.freeApplicationVerified!==true||entry.channelAllowsProposal!==true||entry.requiresConnects===true||entry.requiresPaidVerification===true||Number(entry.requiredSpendUsd||0)!==0)errors.push("free_permitted_channel_not_proven");
 if(!trim(entry.channel,120))errors.push("channel_unspecified");
 if(!/^MP-(SUPPLIER-SNAPSHOT|QUOTE-SANITY|TENDER-SCAN|SOURCING-5|BUYER-SIGNALS)$/.test(trim(entry.productId,50)))errors.push("unknown_lumen_product");
 if(entry.lane==="X402"&&(entry.ownerSettlementApprovalRequired!==true||entry.x402CheckoutVerified!==true))errors.push("x402_human_approval_or_checkout_not_verified");
 if(entry.automatedApplicationRequested===true&&entry.termsAllowAutomatedApplications!==true)errors.push("automated_marketplace_applications_not_permitted");
 return{ok:errors.length===0,errors,sourceUrl:src};
}
export function validateBatch(doc,now=new Date()){
 if(doc?.version!=="1.0"||!Array.isArray(doc.leads)||doc.leads.length>10)throw Error("invalid_or_oversized_verified_demand_batch");
 const seen=new Set(),eligible=[];
 for(const lead of doc.leads){
  const check=validateQualifiedLead(lead,now);
  if(!check.ok)throw Error("lead_rejected:"+check.errors.join(","));
  if(seen.has(check.sourceUrl))throw Error("duplicate_within_verified_demand_batch");
  seen.add(check.sourceUrl);
  eligible.push({...lead,sourceUrl:check.sourceUrl,directCommercialIntentVerified:true});
 }
 return eligible;
}
export async function importVerifiedBatch(doc,{now=new Date(),fetchImpl=fetch,token,apiBase=LUMEN_API}={}){
 if(apiBase!==LUMEN_API)throw Error("refuse_non_lumen_destination");
 const candidates=validateBatch(doc,now);
 if(candidates.length===0)return{ok:true,version:IMPORT_VERSION,checked:0,prepared:0,duplicates:0,failed:0,outboundMessages:0,spendUsd:0};
 if(typeof token!=="string"||token.length<10)throw Error("owner_admin_secret_required");
 let prepared=0,duplicates=0,failed=0;
 for(const input of candidates){
  // No contact channel is called. Only LUMEN's own authenticated draft API.
  const response=await fetchImpl(LUMEN_API+"/commercial/proposals/prepare",{
   method:"POST",redirect:"manual",headers:{"x-lumen-admin":token,"content-type":"application/json","accept":"application/json"},
   body:JSON.stringify(input)
  });
  if(response.status===409){duplicates++;continue;}
  if(response.status!==201){failed++;continue;}
  const result=await response.json();
  if(result?.ok===true&&result?.proposal?.status==="AWAITING_OWNER_REVIEW"&&result?.proposal?.controls?.messagesSent===0)prepared++;
  else failed++;
 }
 return{ok:failed===0,version:IMPORT_VERSION,checked:candidates.length,prepared,duplicates,failed,outboundMessages:0,spendUsd:0,contracts:0,settlements:0};
}
async function main(){
 const file=process.env.LUMEN_VERIFIED_DEMAND_FILE||FILE;
 const doc=JSON.parse(readFileSync(file,"utf8"));
 const token=process.env.OPPORTUNITY_ADMIN_TOKEN;
 const result=await importVerifiedBatch(doc,{token});
 console.log(JSON.stringify(result));
 if(!result.ok)process.exitCode=1;
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href)main().catch(e=>{console.error("LUMEN_INTAKE_FAILED:"+trim(e?.message||e,300));process.exitCode=1;});
