import assert from 'node:assert/strict';
import { deriveLifecycleStage } from './revenue-loop-v5.js';

assert.equal(deriveLifecycleStage({proposal_status:'RESPONDED',pipeline_stage:'RESPONDED',response_text:null,proposal_id:'P1',outreach_status:'SENT'}),'SENT','flags alone must not prove REPLIED');
assert.equal(deriveLifecycleStage({proposal_status:'RESPONDED',pipeline_stage:'RESPONDED',response_text:'Interested, what is included?',proposal_id:'P1',outreach_status:'SENT'}),'REPLIED','real persisted response may prove REPLIED');
assert.equal(deriveLifecycleStage({response_class:'PURCHASE_INTENT',response_text:'Ready to buy',proposal_id:'P1'}),'NEGOTIATING');
assert.equal(deriveLifecycleStage({verified_receipt_id:'R1',proposal_id:'P1'}),'PAID','verified settlement truth must remain authoritative');
console.log('reply-integrity-gate regression tests: PASS');
