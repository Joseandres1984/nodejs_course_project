import { appendFileSync } from "node:fs";
import { AFFILIATE_PRODUCTS, AFFILIATE_POLICY, buildAffiliateCampaign, qualifyAffiliateProduct } from "./affiliate-sales.js";

const campaigns = ["en","es"].map(locale=>buildAffiliateCampaign(locale));
const today = new Date().toISOString().slice(0,10);
const result = {
  ok:true, version:AFFILIATE_POLICY.version, date:today,
  activity:"review_and_content_preparation_only",
  outsideMessagesSent:0, published:0, spendUsd:0,
  revenueVerifiedUsd:null, officialAmazonReportIntegrated:false,
  candidateCount:AFFILIATE_PRODUCTS.length,
  candidateReadiness:AFFILIATE_PRODUCTS.map(item=>({id:item.id,qualify:qualifyAffiliateProduct(item)})),
  campaigns:campaigns.map(x=>({campaignId:x.campaignId, status:x.status, requiresOwnerReview:true}))
};
const markdown=[
  "# LUMEN Affiliate Sales — "+today,
  "",
  "- Marketplace: Amazon.com | Channel: @"+AFFILIATE_POLICY.channelHandle,
  "- Daily cycle: campaign preparation only; no external messages or spend",
  "- Official Amazon Associates sale metrics: not connected; no commission credited",
  "",
  "## Product evidence gates",
  ...result.candidateReadiness.map(x=>"- "+x.id+": "+(x.qualify.eligible?"READY":"BLOCKED")+" — "+x.qualify.blockers.join(", ")),
  "",
  "## Campaigns",
  ...campaigns.map(x=>"- "+x.campaignId+": "+x.status),
  "",
  "**Do not publish unverified prices, inventory, purchase counts or made-up reviews.**",
  "**New external-channel publishing or paid promotion requires explicit authorization.**"
].join("\n")+"\n";
if (process.env.GITHUB_STEP_SUMMARY) appendFileSync(process.env.GITHUB_STEP_SUMMARY, markdown);
console.log(JSON.stringify(result,null,2));
