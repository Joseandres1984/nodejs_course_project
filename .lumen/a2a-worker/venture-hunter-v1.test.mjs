import assert from "node:assert/strict";
import { runVentureHunterV1 } from "./venture-hunter-v1.js";

const signals = [
  { id: "s1", company: "Acme", url: "https://example.com/rfq", text: "Urgent: looking for supplier quotes and market comparison for industrial parts", score: 92 },
  { id: "s2", company: "Beta", text: "Need a daily price monitoring alert for competitor catalog changes", intent_score: 88 },
  { id: "s3", company: "Gamma", text: "Looking to extract invoice data from PDF documents automatically", priority_score: 81 },
];

const result = await runVentureHunterV1({}, { signals, topK: 10 });
assert.equal(result.ok, true);
assert.equal(result.engine, "LUMEN Venture Hunter v1");
assert.equal(result.signalsExamined, 3);
assert.equal(result.ideasGenerated, 3);
assert.equal(result.policy.autonomousExternalLaunch, false);
assert.equal(result.policy.autonomousSpending, false);
assert.equal(result.policy.autonomousContracting, false);
assert.equal(result.policy.bindingActionsHumanGated, true);
assert.ok(result.topOpportunity.metrics.score > 0.6);
assert.ok(["BUILD_CANDIDATE", "VALIDATE"].includes(result.topOpportunity.status));
console.log(JSON.stringify({ ok: true, top: result.topOpportunity, policy: result.policy }, null, 2));
