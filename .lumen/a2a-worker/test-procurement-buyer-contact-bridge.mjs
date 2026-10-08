import assert from "node:assert/strict";
import { __test } from "./source-intelligence.js";

assert.deepEqual(__test.safeParse('{"a":1}', {}), {a:1});
assert.deepEqual(__test.safeParse("not-json", {fallback:true}), {fallback:true});

const normalized = __test.normalizeTedItem({
  "publication-number": "694245-2026",
  "notice-title": "Example procurement",
  "buyer-name": "Example Public Authority",
  "buyer-email": "procurement@authority.example",
  "buyer-internet-address": "https://authority.example/",
  "buyer-contact-point": "Procurement office",
  "buyer-identifier": "AUTH-123",
  "buyer-country": "DE",
  "publication-date": "2026-10-07",
  "deadline": "2026-11-01",
  "contract-nature": "services",
  "total-value": 100000
});

assert.equal(normalized.endpoint, null, "procurement evidence URL must never masquerade as A2A endpoint");
assert.equal(normalized.evidence, "https://ted.europa.eu/en/notice/-/detail/694245-2026");
assert.equal(normalized.raw.buyerEmail, "procurement@authority.example");
assert.equal(normalized.raw.buyerWebsite, "https://authority.example/");
assert.equal(normalized.raw.buyerContactPoint, "Procurement office");
assert.equal(normalized.raw.contactSource, "official_ted_notice");
assert.equal(normalized.demandSignal, 1);

console.log("PROCUREMENT_BUYER_CONTACT_BRIDGE_OK");
