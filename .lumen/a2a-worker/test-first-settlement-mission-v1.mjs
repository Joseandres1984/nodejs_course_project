import assert from "node:assert/strict";
import { diagnoseSettlementBlocker, chooseFirstSettlementMission, FIRST_SETTLEMENT_MISSION_POLICY } from "./first-settlement-mission-v1.js";

assert.equal(FIRST_SETTLEMENT_MISSION_POLICY.version, "1.7-verified-intent-focus-truth");
assert.equal(FIRST_SETTLEMENT_MISSION_POLICY.nonActionableInventoryRequiresVerifiedCommercialIntentToOwnMission, true);
assert.equal(FIRST_SETTLEMENT_MISSION_POLICY.requiresCurrentCommercialActionability, true);
assert.equal(FIRST_SETTLEMENT_MISSION_POLICY.rotateNonCommercialTransportResponses, true);
assert.equal(FIRST_SETTLEMENT_MISSION_POLICY.rotateNonCommercialReplies, true);
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

const notRelevantReply = diagnoseSettlementBlocker({ stage:"REPLIED", pipeline_response_class:"NOT_RELEVANT", updated_at:"2026-10-03T11:55:00Z" }, now);
assert.equal(notRelevantReply.blocker, "NONCOMMERCIAL_BUYER_RESPONSE");
assert.equal(notRelevantReply.action, "rotate_to_next_opportunity_or_human_review");

const purchaseReply = diagnoseSettlementBlocker({ stage:"REPLIED", pipeline_response_class:"PURCHASE_INTENT", updated_at:"2026-10-03T11:55:00Z" }, now);
assert.equal(purchaseReply.blocker, "RESPONSE_NOT_CLOSED");

const unclassifiedReply = diagnoseSettlementBlocker({ stage:"REPLIED", updated_at:"2026-10-03T11:55:00Z" }, now);
assert.equal(unclassifiedReply.blocker, "RESPONSE_CLASSIFICATION_REQUIRED");
assert.equal(unclassifiedReply.action, "classify_response_before_close");

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

const transportOnlyResponse = diagnoseSettlementBlocker({
  stage:"PROPOSAL_READY",quality_gate_status:"PASS",outreach_status:"RESPONDED",
  pipeline_response_class:null,commercial_reply_count:0,
  outreach_updated_at:"2026-10-03T11:30:00Z",updated_at:"2026-10-03T11:30:00Z"
}, now);
assert.equal(transportOnlyResponse.blocker,"NONCOMMERCIAL_OUTREACH_RESPONSE");
assert.equal(transportOnlyResponse.action,"rotate_to_next_opportunity_or_human_review");

const verifiedResponseNeedsSync = diagnoseSettlementBlocker({
  stage:"PROPOSAL_READY",quality_gate_status:"PASS",outreach_status:"RESPONDED",
  pipeline_response_class:"COMMERCIAL_INTEREST",commercial_reply_count:1,
  outreach_updated_at:"2026-10-03T11:30:00Z",updated_at:"2026-10-03T11:30:00Z"
}, now);
assert.equal(verifiedResponseNeedsSync.blocker,"RESPONSE_STAGE_SYNC_REQUIRED");
assert.equal(verifiedResponseNeedsSync.action,"sync_verified_response_to_replied");

const alreadySent = diagnoseSettlementBlocker({
  stage:"PROPOSAL_READY",quality_gate_status:"PASS",outreach_status:"SENT_TASK",
  outreach_updated_at:"2026-10-03T11:30:00Z",updated_at:"2026-10-03T11:30:00Z"
}, now);
assert.equal(alreadySent.blocker,"OUTREACH_ALREADY_SENT");
assert.equal(alreadySent.action,"poll_existing_outreach_before_resend");

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

const notRelevantRotates = chooseFirstSettlementMission([
  { opportunity_id:"nope", stage:"REPLIED", first_cash_score:20, intent_score:.9, pipeline_response_class:"NOT_RELEVANT", updated_at:"2026-10-03T11:58:00Z" },
  { opportunity_id:"real-next", stage:"PROPOSAL_READY", first_cash_score:.2, intent_score:.7, quality_gate_status:"PASS", updated_at:"2026-10-03T11:57:00Z" }
], now);
assert.equal(notRelevantRotates.focus.opportunity_id,"real-next","NOT_RELEVANT reply must rotate out of First Settlement");

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

const transportOnlyRotates = chooseFirstSettlementMission([
  { opportunity_id:"transport-only", stage:"PROPOSAL_READY", first_cash_score:9, intent_score:.95, quality_gate_status:"PASS", outreach_status:"RESPONDED", pipeline_response_class:null, commercial_reply_count:0, outreach_updated_at:"2026-10-03T11:50:00Z", updated_at:"2026-10-03T11:50:00Z" },
  { opportunity_id:"sendable-next", stage:"PROPOSAL_READY", first_cash_score:.25, intent_score:.7, quality_gate_status:"PASS", updated_at:"2026-10-03T11:55:00Z" }
], now);
assert.equal(transportOnlyRotates.focus.opportunity_id,"sendable-next","transport-only RESPONDED rows must rotate instead of masquerading as awaiting send");

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

const rawProcurementCannotOwnMission = chooseFirstSettlementMission([
  { opportunity_id:"raw-ted", offer_id:"MP-TENDER-SCAN", commercially_actionable:0, stage:"PROPOSAL_READY", first_cash_score:99, intent_score:.99, quality_gate_status:"PASS", updated_at:"2026-10-03T11:59:00Z" },
  { opportunity_id:"matched-supplier", offer_id:"MP-TENDER-LEAD", commercially_actionable:1, stage:"QUALIFIED", first_cash_score:.05, intent_score:.55, updated_at:"2026-10-03T11:58:00Z" }
], now);
assert.equal(rawProcurementCannotOwnMission.focus.opportunity_id,"matched-supplier","raw procurement evidence must never monopolize First Settlement");

const nonActionableSentCannotOwnMission = chooseFirstSettlementMission([
  { opportunity_id:"sent-before-reassess", commercially_actionable:0, stage:"SENT", outreach_status:"SENT_TASK", first_cash_score:9, intent_score:.9, updated_at:"2026-10-03T11:58:00Z" },
  { opportunity_id:"actionable-next", commercially_actionable:1, stage:"QUALIFIED", first_cash_score:.05, intent_score:.5, updated_at:"2026-10-03T11:57:00Z" }
], now);
assert.equal(nonActionableSentCannotOwnMission.focus.opportunity_id,"actionable-next","non-actionable sent inventory may remain auditable but must not own First Settlement without verified commercial intent");

const nonActionableVerifiedInterestMayOwnMission = chooseFirstSettlementMission([
  { opportunity_id:"verified-interest", commercially_actionable:0, stage:"NEGOTIATING", response_class:"COMMERCIAL_INTEREST", first_cash_score:.2, intent_score:.7, updated_at:"2026-10-03T11:58:00Z" }
], now);
assert.equal(nonActionableVerifiedInterestMayOwnMission.focus.opportunity_id,"verified-interest","verified buyer commercial intent remains eligible even after later reassessment");

const phantomNonActionableNegotiatingRotates = chooseFirstSettlementMission([
  { opportunity_id:"phantom-nonactionable", commercially_actionable:0, stage:"NEGOTIATING", response_class:"GENERIC_RESPONSE", first_cash_score:99, intent_score:.99, updated_at:"2026-10-03T11:59:00Z" },
  { opportunity_id:"real-actionable", commercially_actionable:1, stage:"QUALIFIED", first_cash_score:.01, intent_score:.4, updated_at:"2026-10-03T11:58:00Z" }
], now);
assert.equal(phantomNonActionableNegotiatingRotates.focus.opportunity_id,"real-actionable","non-actionable phantom negotiation must not monopolize First Settlement");

console.log("First Settlement Mission v1 tests passed");
