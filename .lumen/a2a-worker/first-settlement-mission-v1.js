export const FIRST_SETTLEMENT_MISSION_POLICY = Object.freeze({
  version: "1.0-first-settlement-mission",
  objective: "move_the_best_real_opportunity_toward_first_verified_settlement",
  settlementTruth: "verified_x402_receipt_only",
  autonomousSpendUsd: 0,
  autonomousPurchase: false,
  autonomousContract: false,
  changesPrices: false,
  createsNewSenderAuthority: false,
  bindingActionsHumanGated: true
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
  if (stage === "NEGOTIATING") { blocker = "CHECKOUT_OR_SETTLEMENT_PENDING"; action ||= "prepare_existing_checkout_or_close_gate"; }
  const ageHours = hoursSince(row.stage_updated_at || row.updated_at, now);
  const thresholdHours = STALL_HOURS[stage] ?? 168;
  return { stalled: ageHours >= thresholdHours, blocker, action, ageHours: Number(ageHours.toFixed(2)), thresholdHours };
}

export function chooseFirstSettlementMission(rows = [], now = Date.now()) {
  const eligible = rows.filter(r => !r.verified_receipt_id && !["PAID", "DELIVERED"].includes(String(r.stage || "").toUpperCase()));
  eligible.sort((a,b) => Number(b.first_cash_score || 0) - Number(a.first_cash_score || 0) || Number(b.intent_score || 0) - Number(a.intent_score || 0));
  const focus = eligible[0] || null;
  if (!focus) return { status: "NO_OPEN_MISSION", focus: null, diagnosis: null };
  return { status: "ACTIVE", focus, diagnosis: diagnoseSettlementBlocker(focus, now) };
}

export async function getFirstSettlementMissionStatus(env) {
  if (!env?.DB) throw new Error("first_settlement_mission_persistence_required");
  const result = await env.DB.prepare(`SELECT r.*, p.quality_gate_status,
    b.receipt_id AS verified_receipt_id
    FROM lumen_revenue_loop_v5 r
    LEFT JOIN lumen_proposal_drafts p ON p.proposal_id=r.proposal_id
    LEFT JOIN lumen_x402_revenue_bridge b ON b.proposal_id=r.proposal_id AND b.bridge_status='ATTRIBUTABLE'
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
