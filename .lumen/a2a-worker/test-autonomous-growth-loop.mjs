import assert from "node:assert/strict";
import { chooseGrowthDecision, evaluateGrowthDelta } from "./autonomous-growth-loop.js";

const base = {
  revenue:{ verifiedSettlements:0, realizedRevenueUsd:0, orders:0, quotes:0, inbound:0, actionableOpportunities:0, sent:0, responded:0, qualifiedCommercialResponses:0, negotiating:0 },
  travel:{ clicks24h:0, results24h:0, impressions24h:0, confirmations30d:0, negativeEvents30d:0, recommendedCampaigns:0 },
  director:{ bottleneck:"demand_generation", tactic:"FIRST_CASH_DISCOVERY" },
};

{
  const s=structuredClone(base); s.revenue.qualifiedCommercialResponses=1;
  const d=chooseGrowthDecision(s,{});
  assert.equal(d.lane,"B2B_CONVERSION");
  assert.equal(d.preferredAction,"CONVERT_EXISTING_INTEREST");
}

{
  const s=structuredClone(base); s.travel.clicks24h=6; s.travel.results24h=30; s.travel.impressions24h=80;
  const d=chooseGrowthDecision(s,{});
  assert.equal(d.lane,"TRAVEL_BUYER_ACQUISITION");
  assert.equal(d.actionKind,"REFRESH_TRAVEL_ACQUISITION");
}

{
  const s=structuredClone(base); s.travel.confirmations30d=1;
  const d=chooseGrowthDecision(s,{});
  assert.equal(d.lane,"TRAVEL_SCALE");
}

{
  const s=structuredClone(base); s.revenue.verifiedSettlements=1; s.revenue.realizedRevenueUsd=7;
  const d=chooseGrowthDecision(s,{});
  assert.equal(d.lane,"SCALE_VERIFIED_WINNER");
}

{
  const before=structuredClone(base); const after=structuredClone(base);
  after.travel.clicks24h=3;
  const e=evaluateGrowthDelta(before,after);
  assert.equal(e.outcome,"QUALIFIED_CLICK_PROGRESS");
  assert.equal(e.reward,6);
  assert.equal(e.attribution,"observational_not_causal");
}

{
  const before=structuredClone(base); const after=structuredClone(base);
  after.revenue.verifiedSettlements=1; after.revenue.realizedRevenueUsd=19;
  const e=evaluateGrowthDelta(before,after);
  assert.equal(e.outcome,"VERIFIED_REVENUE");
  assert.ok(e.reward>=170);
}

{
  const d=chooseGrowthDecision(base,{B2B_FIRST_CASH:{learnedPriority:15}});
  assert.equal(d.lane,"B2B_FIRST_CASH");
  assert.ok(d.score>=77);
}

console.log("autonomous-growth-loop tests: ok");
