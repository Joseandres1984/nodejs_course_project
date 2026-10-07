import assert from "node:assert/strict";
import { diagnoseSettlementBlocker, chooseFirstSettlementMission, FIRST_SETTLEMENT_MISSION_POLICY } from "./first-settlement-mission-v1.js";

assert.equal(FIRST_SETTLEMENT_MISSION_POLICY.version, "1.3-tender-lead-close-priority");
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

const negotiatingUnknown = diagnoseSettlementBlocker({ stage:"NEGOTIATING", updated_at:"2026-10-03T10:00:00Z" }, now);
assert.equal(negotiatingUnknown.blocker, "NEGOTIATING_WITHOUT_VERIFIED_COMMERCIAL_INTENT");
assert.equal(negotiatingUnknown.action, "reclassify_response_before_checkout");
assert.equal(negotiatingUnknown.stalled, false);

const negotiatingQuestion = diagnoseSettlementBlocker({ stage:"NEGOTIATING", response_class:"COMMERCIAL_QUESTION", next_action:"close_exact_scope_with_existing_first_cash_gate", updated_at:"2026-10-03T10:00:00Z" }, now);
assert.equal(negotiatingQuestion.blocker, "COMMERCIAL_QUESTION_OPEN");
assert.equal(negotiatingQuestion.action, "answer_commercial_question_before_checkout");

const exhaustedQuestion = diagnoseSettlementBlocker({ stage:"NEGOTIATING", response_class:"COMMERCIAL_QUESTION", commercial_reply_count:3, updated_at:"2026-10-03T10:00:00Z" }, now);
assert.equal(exhaustedQuestion.blocker, "COMMERCIAL_DIALOGUE_EXHAUSTED");
assert.equal(exhaustedQuestion.action, "rotate_to_next_opportunity_or_human_review");

const terminalOutreach = diagnoseSettlementBlocker({
  stage:"PROPOSAL_READY",quality_gate_status:"PASS",outreach_status:"INCOMPATIBLE",
  outreach_updated_at:"2026-10-03T11:00:00Z",updated_at:"2026-10-03T11:00:00Z"
}, now);
assert.equal(terminalOutreach.blocker,"OUTREACH_PATH_TERMINAL");
assert.equal(terminalOutreach.action,"rotate_to_next_opportunity_or_human_review");

const coolingOutreach = diagnoseSettlementBlocker({
  stage:"PROPOSAL_READY",quality_gate_status:"PASS",outreach_status:"CARD_FETCH_FAILED",
  outreach_updated_at:"2026-10-03T10:00:00Z",updated_at:"2026-10-03T10:00:00Z"
}, now);
assert.equal(coolingOutreach.blocker,"OUTREACH_RETRY_COOLDOWN");
assert.equal(coolingOutreach.action,"rotate_while_outreach_retry_cools_down");

const retryDueOutreach = diagnoseSettlementBlocker({
  stage:"PROPOSAL_READY",quality_gate_status:"PASS",outreach_status:"SEND_FAILED",
  outreach_updated_at:"2026-10-02T20:00:00Z",updated_at:"2026-10-02T20:00:00Z"
}, now);
assert.equal(retryDueOutreach.blocker,"OUTREACH_RETRY_DUE");
assert.equal(retryDueOutreach.action,"retry_existing_outreach_probe");

const negotiatingPurchase = diagnoseSettlementBlocker({ stage:"NEGOTIATING", response_class:"PURCHASE_INTENT", updated_at:"2026-10-03T10:00:00Z" }, now);
assert.equal(negotiatingPurchase.blocker, "CHECKOUT_OR_SETTLEMENT_PENDING");
assert.equal(negotiatingPurchase.action, "prepare_existing_checkout_or_close_gate");

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
  { opportunity_id:"replied", stage:"REPLIED", first_cash_score:.15, intent_score:.6, response_class:"COMMERCIAL_INTEREST", updated_at:"2026-10-03T11:45:00Z" }
], now);
assert.equal(sentVsReplied.focus.opportunity_id,"replied","verified buyer response must outrank waiting SENT inventory");

const verifiedCloseBeatsPhantomNegotiating = chooseFirstSettlementMission([
  { opportunity_id:"phantom", stage:"NEGOTIATING", first_cash_score:5, intent_score:.9, response_class:"GENERIC_RESPONSE", updated_at:"2026-10-03T11:50:00Z" },
  { opportunity_id:"buyer", stage:"NEGOTIATING", first_cash_score:.2, intent_score:.6, response_class:"COMMERCIAL_INTEREST", updated_at:"2026-10-03T11:45:00Z" }
], now);
assert.equal(verifiedCloseBeatsPhantomNegotiating.focus.opportunity_id,"buyer","verified commercial intent must outrank phantom NEGOTIATING state");

const exhaustedRotates = chooseFirstSettlementMission([
  { opportunity_id:"exhausted", stage:"NEGOTIATING", first_cash_score:9, intent_score:.95, response_class:"COMMERCIAL_QUESTION", commercial_reply_count:3, updated_at:"2026-10-03T11:55:00Z" },
  { opportunity_id:"next-best", stage:"PROPOSAL_READY", first_cash_score:.2, intent_score:.7, quality_gate_status:"PASS", updated_at:"2026-10-03T11:50:00Z" }
], now);
assert.equal(exhaustedRotates.focus.opportunity_id,"next-best","exhausted three-turn dialogue must rotate instead of monopolizing First Settlement");

const terminalOutreachRotates = chooseFirstSettlementMission([
  { opportunity_id:"terminal", stage:"PROPOSAL_READY", first_cash_score:8, intent_score:.9, quality_gate_status:"PASS", outreach_status:"AUTH_REQUIRED", outreach_updated_at:"2026-10-03T11:30:00Z", updated_at:"2026-10-03T11:30:00Z" },
  { opportunity_id:"sendable", stage:"PROPOSAL_READY", first_cash_score:.2, intent_score:.7, quality_gate_status:"PASS", updated_at:"2026-10-03T11:40:00Z" }
], now);
assert.equal(terminalOutreachRotates.focus.opportunity_id,"sendable","terminal outreach paths must not monopolize First Settlement");

const tenderLeadBeatsBrokenDraft = chooseFirstSettlementMission([
  { opportunity_id:"broken-old", offer_id:"MP-BUYER-SIGNALS", stage:"PROPOSAL_READY", first_cash_score:1.2, intent_score:.8, quality_gate_status:"NEEDS_REVISION", updated_at:"2026-10-03T11:55:00Z" },
  { opportunity_id:"tender-ready", offer_id:"MP-TENDER-LEAD", stage:"PROPOSAL_READY", first_cash_score:.12, intent_score:.65, quality_gate_status:"PASS", updated_at:"2026-10-03T11:56:00Z" }
], now);
assert.equal(tenderLeadBeatsBrokenDraft.focus.opportunity_id,"tender-ready","quality-passed Tender Hot Lead must outrank broken legacy draft");

const tenderGenericDoesNotBeatPurchase = chooseFirstSettlementMission([
  { opportunity_id:"tender-generic", offer_id:"MP-TENDER-LEAD", stage:"REPLIED", first_cash_score:.2, intent_score:.7, response_class:"GENERIC_RESPONSE", updated_at:"2026-10-03T11:58:00Z" },
  { opportunity_id:"real-buyer", offer_id:"MP-SUPPLIER-SNAPSHOT", stage:"NEGOTIATING", first_cash_score:.1, intent_score:.6, response_class:"PURCHASE_INTENT", updated_at:"2026-10-03T11:57:00Z" }
], now);
assert.equal(tenderGenericDoesNotBeatPurchase.focus.opportunity_id,"real-buyer","generic Tender Hot Lead response must never outrank explicit purchase intent");

console.log("First Settlement Mission v1 tests passed");
