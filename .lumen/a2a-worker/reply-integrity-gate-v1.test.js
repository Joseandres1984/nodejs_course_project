import assert from "node:assert/strict";
import { deriveLifecycleStage } from "./revenue-loop-v5.js";

assert.equal(deriveLifecycleStage({proposal_id:"P1",proposal_status:"RESPONDED",pipeline_stage:"RESPONDED",response_text:""}),"PROPOSAL_READY","response flags without evidence must not create REPLIED");
assert.equal(deriveLifecycleStage({proposal_id:"P1",proposal_status:"SENT",outreach_status:"SENT",response_text:""}),"SENT");
assert.equal(deriveLifecycleStage({proposal_id:"P1",proposal_status:"RESPONDED",pipeline_stage:"RESPONDED",response_text:"Real buyer response"}),"REPLIED");
assert.equal(deriveLifecycleStage({proposal_id:"P1",pipeline_stage:"NEGOTIATING",response_class:"PURCHASE_INTENT",response_text:"Ready to buy"}),"NEGOTIATING");
assert.equal(deriveLifecycleStage({verified_receipt_id:"rcpt_verified",pipeline_stage:"RESPONDED",response_text:""}),"PAID");
assert.equal(deriveLifecycleStage({verified_receipt_id:"rcpt_verified",delivery_status:"delivered"}),"DELIVERED");
console.log("reply-integrity-gate-v1 tests: PASS");
