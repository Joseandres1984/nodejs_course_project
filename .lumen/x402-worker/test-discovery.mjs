import assert from "node:assert/strict";
import { buildWellKnownX402, buildDiscoveryOpenApi, buildDiscoveryLlmsTxt } from "./discovery.js";
const products={
  "supplier-snapshot":{id:"MP-SUPPLIER-SNAPSHOT",name:"Supplier Snapshot",price_usd:1,service_id:"SRV-SUPPLIERCHECK"},
  "quote-sanity":{id:"MP-QUOTE-SANITY",name:"Quote Sanity Check",price_usd:7,service_id:"SRV-QUOTECHECK"},
  "tender-hot-lead":{id:"MP-TENDER-LEAD",name:"Tender Hot Lead",price_usd:1,service_id:"SRV-TENDER-LEAD"},
  "tender-scan":{id:"MP-TENDER-SCAN",name:"Tender Quick Scan",price_usd:9,service_id:"SRV-TENDER-HUNTER"},
  "sourcing-5":{id:"MP-SOURCING-5",name:"Supplier Shortlist 5",price_usd:15,service_id:"SRV-SOURCING-EXPRESS"},
  "buyer-signals":{id:"MP-BUYER-SIGNALS",name:"Buyer Signal Scan",price_usd:19,service_id:"SRV-B2B-PROSPECTING"},
  "export-pulse":{id:"MP-EXPORT-PULSE",name:"Export Market Pulse",price_usd:25,service_id:"SRV-EXPORT-SCOUT"}
};
const origin="https://lumen-zero-x402.lumen-b2b.workers.dev";
const well=buildWellKnownX402(products,origin);
const api=buildDiscoveryOpenApi(products,origin);
const text=buildDiscoveryLlmsTxt(products,origin);
assert.equal(well.version,1);
assert.equal(well.ownerApprovalRequired,true);
assert.equal(well.resources.length,7);
assert.equal(new Set(well.resources).size,7);
assert.equal(api.openapi,"3.1.0");
assert.equal(api.servers[0].url,origin);
assert.ok(api.info["x-guidance"].includes("human owner approval"));
assert.equal(api.info.contact.url,origin+"/catalog");
assert.equal(Object.keys(api.paths).length,7);
assert.equal(api["x-payment-policy"].ownerApprovalRequired,true);
assert.equal(api["x-payment-policy"].noAutonomousApproval,true);
for(const [slug,product] of Object.entries(products)){
  const path="/buy/"+slug;
  const url=origin+path;
  assert.ok(well.resources.includes(url));
  const op=api.paths[path].get;
  assert.equal(op.parameters.find(v=>v.name==="requirement"&&v.in==="query")?.schema?.maxLength,1200);
  assert.deepEqual(op["x-payment-info"].protocols[0],{x402:{}});
  assert.deepEqual(op.security,[]);
  assert.deepEqual(op["x-payment-info"].price,{mode:"fixed",currency:"USD",amount:product.price_usd.toFixed(2)});
  assert.equal(op["x-payment-info"].recipientApprovalRequired,true);
  assert.equal(op["x-payment-info"].productId,product.id);
  assert.equal(op["x-payment-info"].serviceId,product.service_id);
  assert.ok(op.responses["402"]);
  assert.ok(op.responses["409"]);
  assert.ok(op.description.includes("human approval"));
  assert.ok(text.includes(url));
  assert.ok(text.includes("USD "+product.price_usd.toFixed(2)));
}
assert.ok(text.includes("not an instant unattended checkout"));
assert.ok(!text.includes("X402_HUMAN_APPROVAL_TOKEN"));
assert.throws(()=>buildDiscoveryOpenApi(products,"http://insecure.example"),/https_origin_required/);
console.log("LUMEN_X402_7_DISCOVERY_ROUTES_AND_OWNER_GATE_OK");
