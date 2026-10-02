import { digest, host, iso, rows, clean, V4_POLICY } from "./sovereign-store.js";

async function node(env, id, kind, data) {
  await env.DB.prepare("INSERT INTO lumen_v4_nodes VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,data_json=excluded.data_json")
    .bind(id, kind, iso(), JSON.stringify(data)).run();
}
async function edge(env, source, relation, target, evidence) {
  await env.DB.prepare("INSERT INTO lumen_v4_edges VALUES(?,?,?,?,?) ON CONFLICT(source,relation,target) DO UPDATE SET updated_at=excluded.updated_at,evidence_json=excluded.evidence_json")
    .bind(source, relation, target, iso(), JSON.stringify(evidence)).run();
}
// Exact IDs only. A host is a demand proxy, not proof of a legal company or an
// independent buyer. Shared registry hosts are excluded by the reader.
export async function updateEconomicGraph(env, proposals, settlements, opportunities) {
  for (const row of opportunities.slice(0, V4_POLICY.graphWindow.opportunities)) {
    const oid = `opportunity:${row.id}`, domain = host(row.endpoint);
    await node(env, oid, "opportunity", { name: clean(row.name), description: clean(row.description, 1000), evidence: clean(row.evidence, 1000), offerId: row.revenue_offer_id });
    if (domain) {
      const buyer = `host:${domain}`;
      await node(env, buyer, "host_proxy", { domain, verifiedIndependentBuyer: false });
      await edge(env, buyer, "signals", oid, { opportunityId: row.id });
    }
    if (row.revenue_offer_id) {
      const product = `offer:${row.revenue_offer_id}`;
      await node(env, product, "offer", { offerId: row.revenue_offer_id });
      await edge(env, oid, "needs", product, { offerId: row.revenue_offer_id });
    }
  }
  for (const row of proposals.slice(0, V4_POLICY.graphWindow.proposals)) {
    const pid = `proposal:${row.proposal_id}`;
    await node(env, pid, "proposal", { status: row.status, offerId: row.offer_id, amountUsd: row.amount_usd, quality: row.quality_gate_status });
    await edge(env, `opportunity:${row.opportunity_id}`, "proposed", pid, { proposalId: row.proposal_id });
    await edge(env, pid, "offers", `offer:${row.offer_id}`, { amountUsd: row.amount_usd });
    if (row.response_class) {
      const rid = `response:${row.proposal_id}`;
      await node(env, rid, "response", { classification: row.response_class });
      await edge(env, pid, "received", rid, { source: "lumen_sales_pipeline" });
    }
  }
  for (const row of settlements.slice(0, V4_POLICY.graphWindow.receipts)) {
    const id = `receipt:${row.receipt_id}`;
    await node(env, id, "verified_receipt", { receiptId: row.receipt_id, amountUsd: row.amount_usd, offerId: row.offer_id });
    if (row.proposal_id) await edge(env, `proposal:${row.proposal_id}`, "settled", id, { exactReceiptId: row.receipt_id });
  }
  const stats = await rows(env, "SELECT kind,COUNT(*) count FROM lumen_v4_nodes GROUP BY kind");
  return { nodesByKind: stats, exactIdentifiersOnly: true, fuzzyCompanyMerging: false, refreshWindow: V4_POLICY.graphWindow };
}

export async function offerCohort(env, offerId) {
  if (!offerId || offerId.length > 100) throw new Error("invalid_offer_id");
  return rows(env, "SELECT n.id,n.data_json FROM lumen_v4_edges e JOIN lumen_v4_nodes n ON n.id=e.source WHERE e.relation='offers' AND e.target=? ORDER BY e.updated_at DESC LIMIT 20", [`offer:${offerId}`]);
}

export async function researchDraft(row) {
  const content = { opportunityId: row.id, target: clean(row.name), domain: host(row.endpoint),
    observedDescription: clean(row.description, 1800), sourceEvidence: clean(row.evidence, 1400),
    evidenceStrength: row.evidence_strength || "unknown", sourceUpdatedAt: row.updated_at || null,
    inference: "possible_fit_requires_scope_confirmation", independentlyResearched: false,
    missingInputs: ["buyer_requirement", "deliverable_scope", "confirmed_recipient"] };
  return { ...content, fingerprint: await digest(content) };
}
