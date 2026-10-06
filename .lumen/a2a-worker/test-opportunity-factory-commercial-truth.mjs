import assert from "node:assert/strict";
import { pipelineCandidate } from "./opportunity-factory.js";

const question=pipelineCandidate({stage:"RESPONDED",response_class:"COMMERCIAL_QUESTION"});
assert.equal(question.lane,"INBOUND");
assert.equal(question.actionKind,"COMMERCIAL_REPLY");

const purchase=pipelineCandidate({stage:"RESPONDED",response_class:"PURCHASE_INTENT"});
assert.equal(purchase.lane,"CLOSE");
assert.equal(purchase.actionKind,"FIRST_CASH");

const interest=pipelineCandidate({stage:"NEGOTIATING",response_class:"COMMERCIAL_INTEREST"});
assert.equal(interest.lane,"CLOSE");
assert.equal(interest.actionKind,"FIRST_CASH");

const ack=pipelineCandidate({stage:"RESPONDED",response_class:"TECHNICAL_ACK",next_action_at:"2099-01-01T00:00:00Z"});
assert.equal(ack.lane,"FOLLOW_UP");
assert.equal(ack.actionKind,"POLL_ONLY");
assert.ok(ack.probability<0.2);

const genericDue=pipelineCandidate({stage:"RESPONDED",response_class:"GENERIC_RESPONSE",next_action_at:"2000-01-01T00:00:00Z"});
assert.equal(genericDue.lane,"FOLLOW_UP");
assert.equal(genericDue.actionKind,"FOLLOWUP");

const unknownNegotiating=pipelineCandidate({stage:"NEGOTIATING",response_class:""});
assert.equal(unknownNegotiating.lane,"INBOUND");
assert.equal(unknownNegotiating.actionKind,"POLL_ONLY");
assert.match(unknownNegotiating.rationale,/without_verified_response_class/);

assert.equal(pipelineCandidate({stage:"RESPONDED",response_class:"DECLINED"}),null);
assert.equal(pipelineCandidate({stage:"RESPONDED",response_class:"NOT_RELEVANT"}),null);

console.log("OPPORTUNITY_FACTORY_COMMERCIAL_TRUTH_OK");
