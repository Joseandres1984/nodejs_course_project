import assert from "node:assert/strict";
import { focusedOriginCoolingDown } from "./a2a-outreach.js";

const target={proposal_id:"P1",agent_url:"https://agent.example/a2a",card_url:"https://agent.example/.well-known/agent-card.json"};
assert.equal(focusedOriginCoolingDown(target,[]),false);
assert.equal(focusedOriginCoolingDown(target,[{proposal_id:"P2",agent_url:"https://agent.example/other"}]),true);
assert.equal(focusedOriginCoolingDown(target,[{proposal_id:"P2",agent_url:"https://other.example/a2a"}]),false);
assert.equal(focusedOriginCoolingDown(target,[{proposal_id:"P1",agent_url:"https://agent.example/a2a"}]),false,"same proposal must not block its own READY send");
console.log("FOCUSED_SEND_ANTISPAM_OK");
