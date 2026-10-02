import { digest, host, iso, rows, clean, V4_POLICY } from "./sovereign-store.js";

function node(env, writes, id, kind, data) {
  writes.push(env.DB.prepare("INSERT INTO lumen_v4_nodes VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,data_json=excluded.data_json")
    .bind(id, kind, iso(), JSON.stringify(data)));
}
function edge(env, writes, source, relation, target, evidence) {
  writes.push(env.DB.prepare("INSERT INTO lumen_v4_edges VALUES(?,?,?,?,?) ON CONFLICT(source,relation,target) DO UPDATE SET updated_at=excluded.updated_at,evidence_json=excluded.evidence_json")
    .bind(source, relation, target, iso(), JSON.stringify(evidence)));
}
// Exact IDs only. A host is a demand proxy, not proof of a legal company or an
// independent buyer. Shared registry hosts are excluded by the reader.
export async function updateEconomicGraph(env, proposals, settlements, opportunities) {
  const writes = [];
  for (const row of opportunities.slice(0, V4_POLICY.graphWindow.opportunities)) {
    const oid = `opportunity:${row.id}`, domain = host(row.endpoint);
    node(env, writes, oid, "opportunity", { name: clean(row.name), description: clean(row.description, 1000), evidence: clean(row.evidence, 1000), offerId: row.revenue_offer_id });
    if (domain) {
      const buyer = `host:${domain}`;
      node(env, writes, buyer, "host_proxy", { domain, verifiedIndependentBuyer: false });
      edge(env, writes, buyer, "signals", oid, { opportunityId: row.id });
    }
    if (row.revenue_offer_id) {
      const product = `offer:${row.revenue_offer_id}`;
      node(env, writes, product, "offer", { offerId: row.revenue_offer_id });
      edge(env, writes, oid, "needs", product, { offerId: row.revenue_offer_id });
    }
  }
  for (const row of proposals.slice(0, V4_POLICY.graphWindow.proposals)) {
    const pid = `proposal:${row.proposal_id}`;
    node(env, writes, pid, "proposal", { status: row.status, offerId: row.offer_id, amountUsd: row.amount_usd, quality: row.quality_gate_status });
    edge(env, writes, `opportunity:${row.opportunity_id}`, "proposed", pid, { proposalId: row.proposal_id });
    edge(env, writes, pid, "offers", `offer:${row.offer_id}`, { amountUsd: row.amount_usd });
    if (row.response_class) {
      const rid = `response:${row.proposal_id}`;
      node(env, writes, rid, "response", { classification: row.response_class });
      edge(env, writes, pid, "received", rid, { source: "lumen_sales_pipeline" });
    }
  }
  for (const row of settlements.slice(0, V4_POLICY.graphWindow.receipts)) {
    const id = `receipt:${row.receipt_id}`;
    node(env, writes, id, "verified_receipt", { receiptId: row.receipt_id, amountUsd: row.amount_usd, offerId: row.offer_id });
    if (row.proposal_id) edge(env, writes, `proposal:${row.proposal_id}`, "settled", id, { exactReceiptId: row.receipt_id });
  }
  // Bound each D1 batch while avoiding a separate round trip for every edge.
  for (let offset = 0; offset < writes.length; offset += 50)
    await env.DB.batch(writes.slice(offset, offset + 50));
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
