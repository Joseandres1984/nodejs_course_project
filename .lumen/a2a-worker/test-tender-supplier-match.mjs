import assert from "node:assert/strict";
import { __test } from "./tender-supplier-match.js";

const { matchScore, supplierLike, bucketSet } = __test;

const future = JSON.stringify({ deadline:"2099-12-31T12:00:00Z" });

const valveTender = {
  name:"Supply of industrial control valves and valve spare parts",
  description:"Procurement of valves for a water treatment plant.",
  score:82,
  raw_json:future
};
const valveSupplier = {
  name:"Industrial Valve Supplier",
  description:"Manufacturer and supplier of control valves, actuated valves, pumps and piping equipment.",
  tags_json:'["valves","pumps","industrial"]',
  score:75
};
const good = matchScore(valveTender,valveSupplier);
assert.ok(good, "true capability match should be retained");
assert.ok(good.score >= 78);
assert.ok(good.strong.includes("valves") || good.strong.includes("valve"));
assert.ok(good.sharedBuckets.includes("MECHANICAL"));

const batteryTender = {
  name:"Supply of DSP 27 Battery Carrier Spare Parts",
  description:"Battery carrier spare parts required for fleet maintenance.",
  score:85,
  raw_json:future
};
const inferenceAgent = {
  name:"Inference Supply Discovery Agent",
  description:"AI data inference discovery service and software API marketplace provider.",
  tags_json:'["data","ai","software"]',
  score:80
};
assert.equal(matchScore(batteryTender,inferenceAgent), null, "battery spare-parts tender must not match a data/inference agent");

const refurbTender = {
  name:"Internal refurbishment works",
  description:"Client requires documents for refurbishment and change of use.",
  score:80,
  raw_json:future
};
const crawlerAgent = {
  name:"MCP Endpoint Conformance",
  description:"Software provider for API and network endpoint conformance testing.",
  tags_json:'["software","api","network"]',
  score:75
};
assert.equal(matchScore(refurbTender,crawlerAgent), null, "generic words must not create a construction/software false match");

assert.equal(supplierLike({
  name:"AI Crawler Index",
  description:"Data index and analysis agent.",
  tags_json:'["data","analysis"]'
}), false, "generic data agents are not supplier targets");

assert.ok(bucketSet("PLC SCADA automation integrator").has("AUTOMATION"));
assert.ok(bucketSet("industrial control valve pump piping supplier").has("MECHANICAL"));

console.log("TENDER_SUPPLIER_MATCH_QUALITY_OK");
