import assert from "node:assert/strict";
import test from "node:test";
import {
  AFFILIATE_POLICY,AFFILIATE_PRODUCTS,specialLink,qualifyAffiliateProduct,
  buildAffiliateCampaign,handleAffiliateSales
} from "./affiliate-sales.js";

const candidate = AFFILIATE_PRODUCTS[0];
const base="https://lumen.example";
const env={OPPORTUNITY_ADMIN_TOKEN:"local-test-token"};
const adminHeaders={"x-lumen-admin":"local-test-token"};
test("fixed Amazon.com special link has correct Associates tag",()=>{
  assert.equal(specialLink(candidate.asin),"https://www.amazon.com/dp/B0D2LZYQ2M?tag=lumenb2b-20");
  assert.throws(()=>specialLink("../malicious"),/invalid_asin/);
  assert.throws(()=>specialLink(candidate.asin,"bad"),/invalid_tracking_id/);
});
test("no unsupported claims of verified price, orders or commissions",()=>{
  assert.equal(AFFILIATE_POLICY.outgoingSpendUsd,0);
  assert.equal(AFFILIATE_POLICY.unsolicitedOutreach,false);
  assert.equal(AFFILIATE_POLICY.autonomousAds,false);
  assert.equal(AFFILIATE_POLICY.postsFromThisModule,0);
  const q=qualifyAffiliateProduct(candidate);
  assert.equal(q.eligible,false);
  assert.equal(q.estimatedCommissionUsd,null);
  assert.ok(q.blockers.includes("new_condition_unverified"));
  assert.ok(q.blockers.includes("live_price_unverified"));
  assert.ok(q.blockers.includes("commission_unverified"));
});
test("future candidate only ready after evidence-backed prices and demand",()=>{
  const q=qualifyAffiliateProduct({...candidate,offerCondition:"NEW_VERIFIED",livePriceUsd:299,confirmedCommissionPct:4.5,recentUnitsVerified:8000});
  assert.deepEqual(q,{eligible:true,blockers:[],estimatedCommissionUsd:13.46});
});
test("English and Spanish copy disclose paid affiliate relationship and AI depiction",()=>{
  for (const locale of ["en","es"]) {
    const campaign=buildAffiliateCampaign(locale);
    assert.equal(campaign.publishing.automatic,false);
    assert.equal(campaign.publishing.paidPromotion,false);
    assert.equal(campaign.claimStatus.eligible,false);
    assert.equal(campaign.reportedMetrics.commissionsUsd,null);
    assert.ok(campaign.caption.includes("Amazon"));
    assert.match(campaign.caption,/AI|IA/);
    assert.match(campaign.caption,/qualifying purchases|compras que cumplen los requisitos/i);
    assert.match(campaign.storyText,/affiliate|afiliado/i);
  }
  assert.throws(()=>buildAffiliateCampaign("xx"),/invalid_locale/);
});
test("policy is public, campaigns/status are admin-only, methods are read-only",async()=>{
  const publicResponse=await handleAffiliateSales(new Request(base+"/affiliate-sales/policy"),{});
  assert.equal(publicResponse.status,200);
  const payload=await publicResponse.json();
  assert.equal(payload.outgoingSpendUsd,0);
  const unauth=await handleAffiliateSales(new Request(base+"/affiliate-sales/campaign"),{});
  assert.equal(unauth.status,403);
  const authorized=await handleAffiliateSales(new Request(base+"/affiliate-sales/campaign?locale=es",{headers:adminHeaders}),env);
  assert.equal(authorized.status,200);
  assert.match((await authorized.json()).campaign.caption,/PUBLICIDAD/);
  const status=await handleAffiliateSales(new Request(base+"/affiliate-sales/status",{headers:adminHeaders}),env);
  assert.equal(status.status,200);
  assert.equal((await status.json()).verifiedRevenueUsd,null);
  const post=await handleAffiliateSales(new Request(base+"/affiliate-sales/campaign",{method:"POST",headers:adminHeaders}),env);
  assert.equal(post.status,405);
  const other=await handleAffiliateSales(new Request(base+"/unrelated"),env);
  assert.equal(other,null);
});