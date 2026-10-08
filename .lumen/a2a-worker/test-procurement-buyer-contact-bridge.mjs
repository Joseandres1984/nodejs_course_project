import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { __test, quarantineLegacyTedDeadlines } from "./source-intelligence.js";

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



// Previously stored TED BT-13 dates were mistakenly labelled bid deadlines.
// The migration must not change dates from newer BT-131 records or any UK tender.
const sqlite=new DatabaseSync(":memory:");
sqlite.exec("CREATE TABLE lumen_opportunities (id TEXT PRIMARY KEY,source TEXT,description TEXT,raw_json TEXT)");
const add=(id,source,description,raw)=>sqlite.prepare("INSERT INTO lumen_opportunities VALUES(?,?,?,?)").run(id,source,description,raw);
add("legacy-ted","ted_eu_public_procurement",
  "Official notice. Bid deadline: 2026-10-30. Buyer contact published.",
  JSON.stringify({deadline:"2026-10-30",source_intelligence_version:"1.7-indexed-deadline-caution"}));
add("current-ted","ted_eu_public_procurement",
  "Official notice. Published bid-submission date: 2026-11-09.",
  JSON.stringify({deadline:"2026-11-09",deadlineSource:"TED_BT_131_LOT_BID_DATE",source_intelligence_version:"1.8-distinct-tender-bid-deadline"}));
add("uk","uk_contracts_finder","UK tender deadline: 2026-11-09.",
  JSON.stringify({deadline:"2026-11-09",source_intelligence_version:"1.7-indexed-deadline-caution"}));
const env={DB:{
  prepare(sql){let stmt=null;return {async run(){stmt ||= sqlite.prepare(sql);const x=stmt.run();return{meta:{changes:Number(x.changes)}}}}}
}};
const first=await quarantineLegacyTedDeadlines(env);
assert.equal(first.quarantined,1);
const legacy=sqlite.prepare("SELECT description,raw_json FROM lumen_opportunities WHERE id='legacy-ted'").get();
const metadata=JSON.parse(legacy.raw_json);
assert.equal(metadata.deadline,null);
assert.equal(metadata.legacyIndexDeadline,"2026-10-30");
assert.equal(metadata.deadlineSource,"LEGACY_TED_GENERIC_DEADLINE_QUARANTINED");
assert.doesNotMatch(legacy.description,/Bid deadline: 2026-10-30/);
const newer=JSON.parse(sqlite.prepare("SELECT raw_json FROM lumen_opportunities WHERE id='current-ted'").get().raw_json);
assert.equal(newer.deadline,"2026-11-09");
const uk=JSON.parse(sqlite.prepare("SELECT raw_json FROM lumen_opportunities WHERE id='uk'").get().raw_json);
assert.equal(uk.deadline,"2026-11-09");
const repeat=await quarantineLegacyTedDeadlines(env);
assert.equal(repeat.quarantined,0,"quarantine must be idempotent");
sqlite.close();
console.log("LEGACY_TED_DATE_QUARANTINE_OK: one incorrect old date safely invalidated; UK and BT-131 records preserved; no messages");

console.log("PROCUREMENT_BUYER_CONTACT_BRIDGE_OK");
