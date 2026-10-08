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
  "deadline": "2026-10-30",
  "deadline-receipt-tender-date-lot": ["2026-11-09"],
  "deadline-receipt-tender-time-lot": ["09:00:00"],
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
assert.equal(normalized.raw.deadline, "2026-11-09", "submission deadline from BT-131, not question deadline BT-13");
assert.equal(normalized.raw.informationDeadline, "2026-10-30");
assert.equal(normalized.raw.deadlineSource, "TED_BT_131_LOT_BID_DATE");
assert.equal(normalized.raw.deadlineTimeVerified, false);
assert.deepEqual(normalized.raw.lotSubmissionDates, ["2026-11-09"]);

const ambiguous=__test.normalizeTedItem({
  "publication-number":"111112-2026",
  "deadline":"2026-10-30",
  "deadline-receipt-tender-date-lot":["2026-11-02","2026-11-09"]
});
assert.equal(ambiguous.raw.deadline,null,"different lot dates must not yield a single misleading deadline");
assert.equal(ambiguous.raw.deadlineSource,"NO_UNAMBIGUOUS_BID_DATE");
const questionOnly=__test.normalizeTedItem({
  "publication-number":"111113-2026",
  "deadline":"2026-10-30"
});
assert.equal(questionOnly.raw.deadline,null,"questions deadline cannot substitute for bid date");
assert.equal(questionOnly.raw.informationDeadline,"2026-10-30");
assert.deepEqual(__test.tedLotDateValues({"LOT-0001":["2026-11-09"],"LOT-0002":["2026-11-09"]}),["2026-11-09"]);


console.log("PROCUREMENT_BUYER_CONTACT_BRIDGE_OK");
