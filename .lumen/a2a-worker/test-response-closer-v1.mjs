import assert from "node:assert/strict";
import { classifyCommercialResponse } from "./response-qualification.js";
import { getResponseCloserStatus, RESPONSE_CLOSER_POLICY } from "./response-closer-v1.js";

assert.equal(RESPONSE_CLOSER_POLICY.version,"2.0-response-closer-shared-response");
assert.equal(RESPONSE_CLOSER_POLICY.autonomousSpendUsd,0);
assert.equal(RESPONSE_CLOSER_POLICY.sendsBindingMessages,false);
assert.equal(RESPONSE_CLOSER_POLICY.bindingActionsHumanGated,true);
assert.equal(RESPONSE_CLOSER_POLICY.sharedResponseTruth,true);
assert.equal(classifyCommercialResponse("We are ready to buy. Send checkout.").responseClass,"PURCHASE_INTENT");
assert.equal(classifyCommercialResponse("What is included and how much?").responseClass,"COMMERCIAL_QUESTION");
assert.equal(classifyCommercialResponse("No thanks, not interested.").responseClass,"DECLINED");
assert.equal(classifyCommercialResponse("Request received and queued.").responseClass,"TECHNICAL_ACK");

function dbWithResponse(responseText){
 return {
   prepare(){return{async all(){return{results:[{opportunity_id:"OPP-1",proposal_id:"P-1",offer_id:"MP-QUOTE-SANITY",stage:"REPLIED",amount_usd:7,quality_gate_status:"PASS",original_message:"Price check service",response_source:"outreach",response_text:responseText}]};}};}
 };
}
const qualifying=await getResponseCloserStatus({DB:dbWithResponse("We are ready to buy. Send checkout.")});
assert.equal(qualifying.status,"QUALIFIED_COMMERCIAL_RESPONSE");
assert.equal(qualifying.plan.responseClass,"PURCHASE_INTENT");
assert.equal(qualifying.plan.stageRecommendation,"NEGOTIATING");
assert.equal(qualifying.plan.executeCheckout,false);
assert.equal(qualifying.plan.sendMessage,false);
assert.equal(qualifying.plan.checkoutEligible,true);
assert.equal(qualifying.plan.humanGateRequired,true);

const techAck=await getResponseCloserStatus({DB:dbWithResponse("Request received and queued.")});
assert.equal(techAck.status,"NON_COMMERCIAL_RESPONSE");
assert.equal(techAck.plan.checkoutEligible,false);
assert.equal(techAck.plan.executeCheckout,false);
assert.equal(techAck.plan.humanGateRequired,false);
console.log("Response Closer shared-response production contract tests passed");
