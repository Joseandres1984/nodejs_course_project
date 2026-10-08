import assert from "node:assert/strict";
import { assessCommercialOpportunity } from "./commercial-intelligence.js";

const rawTender = assessCommercialOpportunity({
  source:"ted_eu_public_procurement",
  name:"Slovakia – Software support services",
  description:"Published public procurement tender. Buyer is actively requesting bids from suppliers. Software support and security services.",
  evidence:"https://ted.europa.eu/en/notice/-/detail/123-2026",
  endpoint:null,
  score:92,
  fit:"PUBLIC_PROCUREMENT",
  demand_signal:1,
  revenue_offer_id:"MP-TENDER-SCAN",
  raw_json:"{}"
});
assert.equal(rawTender.commerciallyActionable,false);
assert.ok(rawTender.reasons.includes("procurement_evidence_only_requires_supplier_match"));

const matchedSupplier = assessCommercialOpportunity({
  source:"tender_supplier_match",
  name:"Reachable Software Supplier",
  description:"Active public procurement tender matched to this supplier profile. Tender: software support services. Supplier-fit terms: software, security.",
  evidence:"https://ted.europa.eu/en/notice/-/detail/123-2026",
  endpoint:"https://supplier.example/a2a",
  score:82,
  fit:"B",
  demand_signal:1,
  revenue_offer_id:"MP-TENDER-LEAD",
  raw_json:JSON.stringify({tender_supplier_match:true})
});
assert.equal(matchedSupplier.commerciallyActionable,true);
assert.ok(!matchedSupplier.reasons.includes("procurement_evidence_only_requires_supplier_match"));

console.log("PROCUREMENT_EVIDENCE_ONLY_COMMERCIAL_TRUTH_OK");
