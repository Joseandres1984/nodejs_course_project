export const FIRST_SETTLEMENT_MISSION_POLICY = Object.freeze({
  version: "1.2-first-settlement-commercial-truth",
  objective: "move_the_best_real_opportunity_toward_first_verified_settlement",
  settlementTruth: "verified_x402_receipt_only",
  autonomousSpendUsd: 0,
  autonomousPurchase: false,
  autonomousContract: false,
  changesPrices: false,
  createsNewSenderAuthority: false,
  bindingActionsHumanGated: true,
  skipExplicitMoveOn: true,
  penalizeWaitingSent: true,
  rotateLowScoreDeadEnds: true
});

const STALL_HOURS = Object.freeze({
  DISCOVERED: 168,
  QUALIFIED: 24,
  PROPOSAL_READY: 12,
  SENT: 72,
  REPLIED: 12,
  NEGOTIATING: 24
});

function hoursSince(value, now = Date.now()) {
  const ts = Date.parse(value || "");
  return Number.isFinite(ts) ? Math.max(0, (now - ts) / 3600000) : Infinity;
}

export function diagnoseSettlementBlocker(row = {}, now = Date.now()) {
  const stage = String(row.stage || "DISCOVERED").toUpperCase();
  if (row.verified_receipt_id || stage === "PAID" || stage === "DELIVERED") {
    return { stalled: false, blocker: null, action: "settlement_verified" };
  }
  let blocker = null;
  let action = row.next_action || null;
  if (stage === "DISCOVERED") { blocker = "NO_QUALIFIED_DEMAND"; action ||= "continue_verified_demand_discovery"; }
  if (stage === "QUALIFIED") { blocker = "PROPOSAL_NOT_READY"; action ||= "prepare_non_binding_proposal"; }
  if (stage === "PROPOSAL_READY") {
    blocker = row.quality_gate_status === "FAIL" ? "QUALITY_GATE_FAIL" : "AWAITING_EXISTING_SEND_GATE";
    action ||= row.quality_gate_status === "FAIL" ? "repair_proposal_quality_without_price_mutation" : "request_existing_human_send_approval";
  }
  if (stage === "SENT") { blocker = "WAITING_BUYER_RESPONSE"; action ||= "follow_up_when_existing_cooldown_allows"; }
  if (stage === "REPLIED") { blocker = "RESPONSE_NOT_CLOSED"; action ||= "classify_response_and_prepare_close"; }
  if (stage === "NEGOTIATING") {
    const responseClass=String(row.response_class || row.pipeline_response_class || "").toUpperCase();
    if (["PURCHASE_INTENT","COMMERCIAL_INTEREST"].includes(responseClass)) {
      blocker = "CHECKOUT_OR_SETTLEMENT_PENDING";
      action = "prepare_existing_checkout_or_close_gate";
    } else if (responseClass === "COMMERCIAL_QUESTION") {
      const replyCount=Number(row.commercial_reply_count || 0);
      if(replyCount >= 3){
        blocker = "COMMERCIAL_DIALOGUE_EXHAUSTED";
        action = "rotate_to_next_opportunity_or_human_review";
      } else {
        blocker = "COMMERCIAL_QUESTION_OPEN";
        action = "answer_commercial_question_before_checkout";
      }
    } else {
      blocker = "NEGOTIATING_WITHOUT_VERIFIED_COMMERCIAL_INTENT";
      action = "reclassify_response_before_checkout";
    }
  }
  const ageHours = hoursSince(row.stage_updated_at || row.updated_at, now);
  const thresholdHours = STALL_HOURS[stage] ?? 168;
  return { stalled: ageHours >= thresholdHours, blocker, action, ageHours: Number(ageHours.toFixed(2)), thresholdHours };
}

function missionPriority(row = {}, now = Date.now()) {
  const diagnosis = diagnoseSettlementBlocker(row, now);
  const stage = String(row.stage || "").toUpperCase();
  const action = String(diagnosis.action || "").toLowerCase();
  if (action === "move_on" || action === "rotate_to_next_opportunity_or_human_review") return -Infinity;
  let score = Number(row.first_cash_score || 0);
  const intent = Number(row.intent_score || 0);
  if (stage === "REPLIED") {
    const responseClass=String(row.response_class || row.pipeline_response_class || "").toUpperCase();
    if (responseClass === "PURCHASE_INTENT") score += 2.2 + intent;
    else if (responseClass === "COMMERCIAL_INTEREST") score += 1.8 + intent;
    else if (responseClass === "COMMERCIAL_QUESTION") score += 1.2 + intent * 0.5;
    else if (["TECHNICAL_ACK","ECHO","GENERIC_RESPONSE"].includes(responseClass)) score=Math.min(score,0.2)-0.15;
    else score += 0.15;
  }
  else if (stage === "NEGOTIATING") {
    const responseClass=String(row.response_class || row.pipeline_response_class || "").toUpperCase();
    if (responseClass === "PURCHASE_INTENT") score += 3.0 + intent;
    else if (responseClass === "COMMERCIAL_INTEREST") score += 2.5 + intent;
    else if (responseClass === "COMMERCIAL_QUESTION") score=Math.min(score,1.0)+1.2+intent*0.5;
    else score=Math.min(score,0.1)-0.35;
  }
  else if (stage === "PROPOSAL_READY") score += 0.4 + intent * 0.25;
  else if (stage === "SENT") {
    score += intent * 0.08;
    if (diagnosis.stalled) score -= 0.5;
    else score -= 0.08;
  } else if (stage === "QUALIFIED") score += intent * 0.2;
  if (diagnosis.stalled && ["DISCOVERED","QUALIFIED","PROPOSAL_READY","SENT"].includes(stage)) score -= 0.25;
  return Number(score.toFixed(6));
}

export function chooseFirstSettlementMission(rows = [], now = Date.now()) {
  const candidates = rows
    .filter(r => !r.verified_receipt_id && !["PAID", "DELIVERED"].includes(String(r.stage || "").toUpperCase()))
    .map(r => ({ row:r, diagnosis:diagnoseSettlementBlocker(r, now), priority:missionPriority(r, now) }))
    .filter(x => Number.isFinite(x.priority));
  candidates.sort((a,b) => b.priority-a.priority || Number(b.row.intent_score || 0)-Number(a.row.intent_score || 0) || Number(b.row.first_cash_score || 0)-Number(a.row.first_cash_score || 0));
  const selected = candidates[0] || null;
  if (!selected) return { status: "NO_OPEN_MISSION", focus: null, diagnosis: null };
  return { status: "ACTIVE", focus: selected.row, diagnosis: selected.diagnosis, selectionPriority:selected.priority };
}

export async function getFirstSettlementMissionStatus(env) {
  if (!env?.DB) throw new Error("first_settlement_mission_persistence_required");
  const result = await env.DB.prepare(`SELECT r.*, p.quality_gate_status,
    s.response_class AS pipeline_response_class,
    b.receipt_id AS verified_receipt_id,
    COALESCE(cr.reply_count,0) AS commercial_reply_count
    FROM lumen_revenue_loop_v5 r
    LEFT JOIN lumen_proposal_drafts p ON p.proposal_id=r.proposal_id
    LEFT JOIN lumen_sales_pipeline s ON s.proposal_id=r.proposal_id
    LEFT JOIN lumen_x402_revenue_bridge b ON b.proposal_id=r.proposal_id AND b.bridge_status='ATTRIBUTABLE'
    LEFT JOIN lumen_commercial_replies cr ON cr.proposal_id=r.proposal_id
    WHERE r.stage NOT IN ('PAID','DELIVERED')
    ORDER BY r.first_cash_score DESC,r.intent_score DESC,r.updated_at DESC LIMIT 25`).all();
  const rows = (result.results || []).map(r => ({ ...r, stage_updated_at: r.updated_at }));
  const mission = chooseFirstSettlementMission(rows);
  const stalled = rows.map(r => ({ opportunity_id:r.opportunity_id, proposal_id:r.proposal_id, stage:r.stage, first_cash_score:r.first_cash_score, ...diagnoseSettlementBlocker(r) })).filter(r => r.stalled);
  return {
    ok: true,
    policy: FIRST_SETTLEMENT_MISSION_POLICY,
    mission,
    stalledCount: stalled.length,
    stalled: stalled.slice(0,10),
    successCriterion: "verified_x402_settlement_greater_than_zero"
  };
}
