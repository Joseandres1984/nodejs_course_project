import assert from "node:assert/strict";
import { chooseGrowthDecision, evaluateGrowthDelta } from "./autonomous-growth-loop-v11.js";

function base(){return{
  revenue:{verifiedSettlements:0,verifiedSettlements7d:0,realizedRevenueUsd:0,realizedRevenueUsd7d:0,orders:0,machineRequests:0,machineRequests7d:0,quotes7d:0,inbound7d:0,negotiating:0,pendingFulfillment:0},
  travel:{clicks24h:0,results24h:0,impressions24h:0,confirmations30d:0,negativeEvents30d:0,recommendedCampaigns:0},
  director:{bottleneck:"demand_generation",tactic:"FIRST_CASH_DISCOVERY"}
};}

{
  const s=base();s.revenue.orders=50;s.revenue.machineRequests=50;
  const d=chooseGrowthDecision(s,{});
  assert.notEqual(d.lane,"SETTLEMENT_AND_DELIVERY","historical/nonbinding machine requests must never look like unpaid orders");
  assert.equal(d.lane,"B2B_FIRST_CASH");
}

{
  const s=base();s.revenue.machineRequests7d=2;
  const d=chooseGrowthDecision(s,{});
  assert.equal(d.lane,"B2B_CONVERSION");
  assert.equal(d.preferredAction,"QUALIFY_NONBINDING_DEMAND");
  assert.match(d.reason,/non-binding/i);
}

{
  const s=base();s.revenue.pendingFulfillment=1;
  const d=chooseGrowthDecision(s,{});
  assert.equal(d.lane,"SETTLEMENT_AND_DELIVERY");
  assert.equal(d.preferredAction,"REVIEW_VERIFIED_PAID_FULFILLMENT");
}

{
  const s=base();s.revenue.verifiedSettlements=99;
  const d=chooseGrowthDecision(s,{});
  assert.notEqual(d.lane,"SCALE_VERIFIED_WINNER","old cumulative settlements must not permanently pin strategy");
}

{
  const s=base();s.revenue.verifiedSettlements7d=1;s.revenue.verifiedSettlements=1;
  const d=chooseGrowthDecision(s,{});
  assert.equal(d.lane,"SCALE_VERIFIED_WINNER");
}

{
  const s=base();s.revenue.negotiating=1;
  const d=chooseGrowthDecision(s,{});
  assert.equal(d.lane,"B2B_CONVERSION");
  assert.equal(d.preferredAction,"CONVERT_EXISTING_INTEREST");
}

{
  const s=base();s.travel.clicks24h=5;s.travel.results24h=24;s.travel.impressions24h=60;
  const d=chooseGrowthDecision(s,{});
  assert.equal(d.lane,"TRAVEL_BUYER_ACQUISITION");
}

{
  const before=base(),after=base();after.revenue.machineRequests=3;after.revenue.orders=3;
  const e=evaluateGrowthDelta(before,after);
  assert.equal(e.outcome,"NONBINDING_DEMAND_PROGRESS");
  assert.equal(e.reward,6);
  assert.match(e.truthRule,/never_count_as_paid/i);
}

{
  const before=base(),after=base();
  after.revenue.verifiedSettlements=1;
  after.revenue.verifiedSettlements7d=1;
  after.revenue.realizedRevenueUsd=12;
  after.revenue.realizedRevenueUsd7d=12;
  const e=evaluateGrowthDelta(before,after);
  assert.equal(e.outcome,"VERIFIED_REVENUE");
  assert.ok(e.reward>=170);
}

console.log("autonomous-growth-loop v1.1 truth tests: ok");
