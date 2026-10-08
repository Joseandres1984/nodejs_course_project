import assert from "node:assert/strict";
import { __test } from "./tender-supplier-match.js";

const { matchScore, supplierLike, bucketSet, targetedSupplierQuery, registrySupplierRow } = __test;

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

const highwaysTender = {
  name:"Framework for Highways Services",
  description:"Maintenance services across the strategic road network.",
  score:82,
  raw_json:future
};
const networkSoftwareAgent = {
  name:"AgentLux",
  description:"Software provider for API network automation and digital services.",
  tags_json:'["software","network","api"]',
  score:78
};
assert.equal(matchScore(highwaysTender,networkSoftwareAgent), null, "road network language must not be treated as an IT-network supplier match");

assert.equal(supplierLike({
  name:"AI Crawler Index",
  description:"Data index and analysis agent.",
  tags_json:'["data","analysis"]'
}), false, "generic data agents are not supplier targets");

assert.ok(bucketSet("PLC SCADA automation integrator").has("AUTOMATION"));
assert.ok(bucketSet("industrial control valve pump piping supplier").has("MECHANICAL"));

const softwareTender = {
  name:"Software support and cybersecurity services",
  description:"Public tender requires software security support.",
  score:90,
  raw_json:future
};
assert.equal(
  targetedSupplierQuery(softwareTender),
  "software cybersecurity security supplier vendor manufacturer provider",
  "targeted registry query must be derived from exact high-signal tender capabilities"
);
assert.equal(
  targetedSupplierQuery({name:"General administrative framework",description:"Professional services",raw_json:future}),
  null,
  "generic tender language must not trigger broad supplier discovery"
);

const registrySupplier = registrySupplierRow({
  id:"verified-software-provider",
  name:"SecureSoft Supplier",
  description:"Verified software cybersecurity services provider and vendor.",
  endpoint:"https://securesoft.example/.well-known/agent-card.json",
  tags:["software","cybersecurity","security"],
  verified:true
});
assert.ok(registrySupplier);
assert.equal(registrySupplier.score,78);
assert.equal(registrySupplier.endpoint,"https://securesoft.example/.well-known/agent-card.json");
assert.ok(supplierLike(registrySupplier));
assert.ok(matchScore(softwareTender,registrySupplier)?.score >= 78);

assert.equal(registrySupplierRow({
  id:"no-endpoint",
  name:"Software Supplier",
  description:"software supplier",
  tags:["software"]
}),null,"registry result without HTTPS endpoint must be rejected before inventory");


console.log("TENDER_SUPPLIER_MATCH_QUALITY_OK");
