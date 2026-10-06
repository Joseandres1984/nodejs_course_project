import assert from "node:assert/strict";
import { diagnoseSettlementBlocker, chooseFirstSettlementMission, FIRST_SETTLEMENT_MISSION_POLICY } from "./first-settlement-mission-v1.js";

assert.equal(FIRST_SETTLEMENT_MISSION_POLICY.version, "1.1-first-settlement-rotation");
assert.equal(FIRST_SETTLEMENT_MISSION_POLICY.autonomousSpendUsd, 0);
assert.equal(FIRST_SETTLEMENT_MISSION_POLICY.bindingActionsHumanGated, true);
assert.equal(FIRST_SETTLEMENT_MISSION_POLICY.skipExplicitMoveOn, true);
assert.equal(FIRST_SETTLEMENT_MISSION_POLICY.penalizeWaitingSent, true);
assert.equal(FIRST_SETTLEMENT_MISSION_POLICY.rotateLowScoreDeadEnds, true);

const now = Date.parse("2026-10-03T12:00:00Z");
const rows = [
  { opportunity_id:"low", stage:"QUALIFIED", first_cash_score:0.1, intent_score:0.9, updated_at:"2026-10-03T11:00:00Z" },
  { opportunity_id:"cash", stage:"PROPOSAL_READY", first_cash_score:2.5, intent_score:0.7, quality_gate_status:"PASS", updated_at:"2026-10-02T20:00:00Z" },
  { opportunity_id:"paid", stage:"PAID", first_cash_score:99, verified_receipt_id:"receipt-1", updated_at:"2026-10-03T11:00:00Z" }
];
const mission = chooseFirstSettlementMission(rows, now);
assert.equal(mission.focus.opportunity_id, "cash");
assert.equal(mission.diagnosis.blocker, "AWAITING_EXISTING_SEND_GATE");
assert.equal(mission.diagnosis.stalled, true);

const sent = diagnoseSettlementBlocker({ stage:"SENT", updated_at:"2026-09-29T00:00:00Z" }, now);
assert.equal(sent.blocker, "WAITING_BUYER_RESPONSE");
assert.equal(sent.stalled, true);

const negotiating = diagnoseSettlementBlocker({ stage:"NEGOTIATING", updated_at:"2026-10-03T10:00:00Z" }, now);
assert.equal(negotiating.blocker, "CHECKOUT_OR_SETTLEMENT_PENDING");
assert.equal(negotiating.stalled, false);

const paid = diagnoseSettlementBlocker({ stage:"PAID", verified_receipt_id:"r" }, now);
assert.equal(paid.action, "settlement_verified");
assert.equal(paid.stalled, false);

const rotateRows = [
  { opportunity_id:"dead", stage:"SENT", first_cash_score:9, intent_score:.7, next_action:"move_on", updated_at:"2026-10-03T11:00:00Z" },
  { opportunity_id:"ready", stage:"PROPOSAL_READY", first_cash_score:.15, intent_score:.8, quality_gate_status:"PASS", updated_at:"2026-10-03T11:30:00Z" }
];
const rotated = chooseFirstSettlementMission(rotateRows, now);
assert.equal(rotated.focus.opportunity_id,"ready","explicit move_on candidates must not monopolize First Cash");

const sentVsReplied = chooseFirstSettlementMission([
  { opportunity_id:"sent-high", stage:"SENT", first_cash_score:.8, intent_score:.8, updated_at:"2026-10-03T11:30:00Z" },
  { opportunity_id:"replied", stage:"REPLIED", first_cash_score:.15, intent_score:.6, updated_at:"2026-10-03T11:45:00Z" }
], now);
assert.equal(sentVsReplied.focus.opportunity_id,"replied","verified buyer response must outrank waiting SENT inventory");

console.log("First Settlement Mission v1 tests passed");
