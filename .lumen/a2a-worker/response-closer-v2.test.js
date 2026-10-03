import assert from "node:assert/strict";
import { classifyCommercialResponse } from "./response-qualification.js";

const purchase=classifyCommercialResponse("We are ready to buy. Send checkout.","Supplier snapshot for USD 7");
assert.equal(purchase.responseClass,"PURCHASE_INTENT");
assert.equal(purchase.qualified,true);

const question=classifyCommercialResponse("What is included and how much?","Supplier snapshot for USD 7");
assert.equal(question.responseClass,"COMMERCIAL_QUESTION");
assert.equal(question.qualified,true);

const ack=classifyCommercialResponse("Request received and queued.","Supplier snapshot for USD 7");
assert.equal(ack.responseClass,"TECHNICAL_ACK");
assert.equal(ack.qualified,false);

const generic=classifyCommercialResponse("Thanks for the message.","Supplier snapshot for USD 7");
assert.equal(generic.responseClass,"GENERIC_RESPONSE");
assert.equal(generic.qualified,false);

const declined=classifyCommercialResponse("No thanks, not interested.","Supplier snapshot for USD 7");
assert.equal(declined.responseClass,"DECLINED");
assert.equal(declined.qualified,false);

console.log("response-closer-v2 shared commercial truth tests: PASS");
