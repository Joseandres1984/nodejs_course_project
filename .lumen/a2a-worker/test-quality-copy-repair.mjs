import assert from "node:assert/strict";
import { evaluateProposalQuality, splitQualityBlockers, buildRepairedProposalCopy } from "./quality-gate.js";

const base = {
  proposal_id:"P1",
  opportunity_id:"O1",
  name:"Example Buyer",
  endpoint:"https://buyer.example/a2a",
  description:"A current verified B2B requirement for supplier research and procurement support.",
  commercial_score:82,
  evidence_strength:"strong",
  synthetic_or_test_only:0,
  offer_name:"Buyer Signals",
  amount_usd:1,
  subject:"bad",
  message:"Too short"
};

const before=evaluateProposalQuality(base);
const split=splitQualityBlockers(before.blockers);
assert.equal(split.structural.length,0);
assert.ok(split.repairable.includes("subject_length_invalid"));
assert.ok(split.repairable.includes("message_length_invalid"));
assert.ok(split.repairable.includes("missing_nonbinding_disclaimer"));
assert.ok(split.repairable.includes("missing_commitment_guardrail"));
assert.ok(split.repairable.includes("missing_low_pressure_cta"));

const repaired=buildRepairedProposalCopy(base);
const after=evaluateProposalQuality({...base,...repaired});
assert.equal(after.pass,true);
assert.deepEqual(after.blockers,[]);
assert.equal(repaired.message.toLowerCase().includes("non-binding"),true);
assert.equal(repaired.message.toLowerCase().includes("no order"),true);
assert.equal(repaired.message.toLowerCase().includes("contract"),true);
assert.equal(repaired.message.toLowerCase().includes("commitment"),true);
assert.equal(repaired.message.toLowerCase().includes("if useful"),true);

const structural=evaluateProposalQuality({...base,endpoint:"http://unsafe.example",subject:repaired.subject,message:repaired.message});
const structuralSplit=splitQualityBlockers(structural.blockers);
assert.ok(structuralSplit.structural.includes("endpoint_not_https"));

const weak=evaluateProposalQuality({...base,evidence_strength:"weak",subject:repaired.subject,message:repaired.message});
assert.ok(splitQualityBlockers(weak.blockers).structural.includes("evidence_too_weak"));

const badAmount=evaluateProposalQuality({...base,amount_usd:500,subject:repaired.subject,message:repaired.message});
assert.ok(splitQualityBlockers(badAmount.blockers).structural.includes("amount_outside_safe_catalog_range"));

console.log("BOUNDED_QUALITY_COPY_REPAIR_OK");
