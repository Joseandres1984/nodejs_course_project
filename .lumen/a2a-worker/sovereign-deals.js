import { clean, object, number, digest, iso, host, rows, V4_POLICY } from "./sovereign-store.js";
import { ACTIVE_PLAYBOOKS } from "./sovereign-operations.js";
import { researchDraft } from "./sovereign-memory.js";
import { prepareProtocolEnvelope } from "./sovereign-protocol-mesh.js";

const PAY_TO = "0x04285DE6A083CEb28fb0C254a2ed0F5fdB2eeD28";
export function verifiedSettlement(receipt, expected = {}) {
  const settlement = object(receipt?.request_metadata).settlement;
  return Boolean(receipt?.receipt_id && ["settled_verified", "redeemed_queued"].includes(receipt.status) &&
    settlement?.success === true && /^0x[a-fA-F0-9]{64}$/.test(settlement.transaction || "") &&
    receipt.network === "eip155:8453" && clean(receipt.pay_to).toLowerCase() === PAY_TO.toLowerCase() &&
    receipt.currency === "USD" && number(receipt.amount_usd) > 0 &&
    (!expected.proposalId || receipt.proposal_id === expected.proposalId) &&
    (!expected.offerId || receipt.product_id === expected.offerId) &&
    (expected.amountUsd === undefined || Math.abs(number(receipt.amount_usd) - expected.amountUsd) < 0.000001));
}
export function proposalScope(row) {
  return { proposalId: row.proposal_id, opportunityId: row.opportunity_id, endpoint: row.endpoint || null,
    offerId: row.offer_id, amountUsd: number(row.amount_usd), subject: row.subject, message: row.message,
    quality: row.quality_gate_status, sourceStatus: row.status };
}
export function dealStage(row, receipt, fulfillment, delivery) {
  if (["REJECTED", "CANCELLED", "EXPIRED"].includes(row.status)) return "CLOSED";
  if (receipt) {
    if (delivery?.status === "delivered" && delivery.provider_message_id && fulfillment?.status === "delivered") return "POSTSALE_OBSERVATION";
    if (delivery?.status === "delivery_ambiguous" || fulfillment?.status === "delivery_ambiguous") return "HUMAN_DELIVERY_REVIEW";
    if (fulfillment?.status === "report_ready" || fulfillment?.status === "ready_for_delivery") return "DELIVERY_QUALITY_GATE_PENDING";
    return "PAID_FULFILLMENT_PENDING";
  }
  if (["PURCHASE_INTENT", "COMMERCIAL_INTEREST", "COMMERCIAL_QUESTION"].includes(row.response_class)) return "SCOPE_CONFIRMATION_REQUIRED";
  if (row.status === "RESPONDED") return "RESPONSE_QUALIFICATION_REQUIRED";
  if (row.status === "SENT") return "AWAITING_RESPONSE";
  if (row.quality_gate_status !== "PASS") return "RESEARCH_AND_QUALITY_REVIEW";
  return "APPROVAL_PACKET_PENDING";
}

export async function prepareApprovalPacket(env, row, research, now = Date.now()) {
  const scope = proposalScope(row), hash = await digest(scope), id = `V4-AP-${hash}`;
  // Invalidating old approvals includes already approved scopes. An admin's
  // earlier decision cannot authorize changed copy, target or price.
  await env.DB.prepare("UPDATE lumen_v4_approvals SET status='SUPERSEDED' WHERE proposal_id=? AND kind='PROPOSAL_REVIEW' AND scope_hash<>? AND status IN ('PENDING','APPROVED')")
    .bind(row.proposal_id, hash).run();
  const packet = { id, kind: "PROPOSAL_REVIEW", scope, scopeHash: hash,
    research, estimatedIncomeUsd: scope.amountUsd, estimateIsGuaranteed: false,
    blockers: row.quality_gate_status === "PASS" ? [] : ["quality_gate_not_passed"],
    authority: "REVIEW_ONLY_EXECUTION_REQUIRES_EXISTING_GOVERNOR", executesOnApproval: false,
    decisionUrl: `/sovereign/approvals/${id}/decision` };
  await env.DB.prepare("INSERT OR IGNORE INTO lumen_v4_approvals(id,proposal_id,kind,scope_hash,status,created_at,expires_at,packet_json) VALUES(?,?,?,?,'PENDING',?,?,?)")
    .bind(id, row.proposal_id, packet.kind, hash, new Date(now).toISOString(), new Date(now + V4_POLICY.approvalTtlHours * 3600000).toISOString(), JSON.stringify(packet)).run();
  return packet;
}

export async function decideApproval(env, id, body, now = Date.now()) {
  const packet = (await rows(env, "SELECT * FROM lumen_v4_approvals WHERE id=?", [id]))[0];
  if (!packet) return { status: 404, result: { ok: false, error: "packet_not_found" } };
  if (!["APPROVE", "REJECT"].includes(body.decision) || body.scopeHash !== packet.scope_hash)
    return { status: 400, result: { ok: false, error: "decision_and_exact_scope_hash_required" } };
  const nowIso = new Date(now).toISOString();
  if (packet.status !== "PENDING" || packet.expires_at <= nowIso)
    return { status: 409, result: { ok: false, error: "packet_expired_or_already_decided" } };
  const proposal = (await rows(env, "SELECT p.*,o.endpoint FROM lumen_proposal_drafts p JOIN lumen_opportunities o ON o.id=p.opportunity_id WHERE p.proposal_id=?", [packet.proposal_id]))[0];
  if (!proposal || await digest(proposalScope(proposal)) !== packet.scope_hash)
    return { status: 409, result: { ok: false, error: "scope_changed_prepare_new_packet" } };
  if (body.decision === "APPROVE" && proposal.quality_gate_status !== "PASS")
    return { status: 409, result: { ok: false, error: "quality_gate_not_passed" } };
  const status = body.decision === "APPROVE" ? "APPROVED" : "REJECTED";
  const changed = await env.DB.prepare("UPDATE lumen_v4_approvals SET status=?,decided_at=? WHERE id=? AND scope_hash=? AND status='PENDING' AND expires_at>?")
    .bind(status, nowIso, id, packet.scope_hash, nowIso).run();
  if (Number(changed.meta?.changes) !== 1) return { status: 409, result: { ok: false, error: "decision_conflict" } };
  return { status: 200, result: { ok: true, id, status, executed: false, sendsMessages: false, financialAuthorityGranted: false } };
}

export async function operateDeals(env, data, selected = []) {
  const deals = [];
  const selectedIds = new Set(selected.map(a => a.sourceId));
  const paidIds = new Set(data.settlements.map(r => r.proposal_id));
  const observed = new Map((await rows(env, "SELECT proposal_id,updated_at FROM lumen_v4_deals")).map(d => [d.proposal_id,d.updated_at]));
  const ordered = data.proposals.filter(p => !["REJECTED", "CANCELLED", "EXPIRED"].includes(p.status)).sort((a,b) =>
    Number(paidIds.has(b.proposal_id)) - Number(paidIds.has(a.proposal_id)) ||
    Number(selectedIds.has(b.proposal_id) || selectedIds.has(b.opportunity_id)) - Number(selectedIds.has(a.proposal_id) || selectedIds.has(a.opportunity_id)) ||
    (observed.get(a.proposal_id) || "").localeCompare(observed.get(b.proposal_id) || "") || a.proposal_id.localeCompare(b.proposal_id));
  for (const row of ordered.slice(0, ACTIVE_PLAYBOOKS.maxInternalDeals)) {
    const source = data.opportunities.find(o => o.id === row.opportunity_id);
    if (!source || source.synthetic_or_test_only || !source.commercially_actionable) continue;
    const research = await researchDraft(source);
    const receipt = data.settlements.find(r => verifiedSettlement(r, { proposalId: row.proposal_id, offerId: row.offer_id, amountUsd: number(row.amount_usd) }));
    const fulfillment = receipt && data.fulfillments.find(f => f.receipt_id === receipt.receipt_id && f.item_id === row.offer_id && number(f.amount_usd) === number(receipt.amount_usd));
    const delivery = fulfillment && data.deliveries.find(d => d.order_id === fulfillment.order_id && d.receipt_id === receipt.receipt_id);
    let stage = dealStage(row, receipt, fulfillment, delivery);
    let packet = null;
    if (["APPROVAL_PACKET_PENDING", "RESEARCH_AND_QUALITY_REVIEW"].includes(stage)) packet = await prepareApprovalPacket(env, row, research);
    if (packet) {
      const review = (await rows(env, "SELECT status,expires_at FROM lumen_v4_approvals WHERE id=?", [packet.id]))[0];
      if (review.expires_at <= iso()) stage = "REVIEW_EXPIRED";
      else if (review.status === "APPROVED") stage = "REVIEW_APPROVED_EXISTING_GOVERNOR_REQUIRED";
      else if (review.status === "REJECTED") stage = "REVIEW_REJECTED";
    }
    const envelope = host(row.endpoint) ? prepareProtocolEnvelope("a2a", { id: row.proposal_id, text: row.message, endpoint: row.endpoint }) : null;
    const deal = { proposalId: row.proposal_id, stage, research, packetId: packet?.id || null,
      receiptId: receipt?.receipt_id || null, orderId: fulfillment?.order_id || null,
      fulfillmentStatus: fulfillment?.status || null, deliveryStatus: delivery?.status || null,
      proposalEnvelope: envelope, negotiation: { priceChangeAllowed: false, contractAcceptanceAllowed: false,
        nextStep: stage === "SCOPE_CONFIRMATION_REQUIRED" ? "prepare_exact_existing_catalog_scope_for_human_review" : null },
      executesExternalActions: false, releasesDelivery: false };
    await env.DB.prepare("INSERT INTO lumen_v4_deals VALUES(?,?,?,?,?,?) ON CONFLICT(proposal_id) DO UPDATE SET updated_at=excluded.updated_at,stage=excluded.stage,packet_id=excluded.packet_id,deal_json=excluded.deal_json")
      .bind(row.proposal_id, row.opportunity_id, iso(), stage, packet?.id || null, JSON.stringify(deal)).run();
    deals.push(deal);
  }
  return { deals, sendsMessages: false, releasesDelivery: false };
}
