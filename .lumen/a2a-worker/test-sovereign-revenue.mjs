import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { readFileSync } from "node:fs";
import { ensureSovereignSchema, digest, V4_POLICY } from "./sovereign-store.js";
import { evaluateEconomics, allocateAttention, judgeWorld, benchmark } from "./sovereign-economics.js";
import { prepareProtocolEnvelope } from "./sovereign-protocol-mesh.js";
import { marketRadar, productSpec } from "./sovereign-products.js";
import { verifiedSettlement, proposalScope, decideApproval, prepareApprovalPacket, operateDeals } from "./sovereign-deals.js";
import { validatePlaybooks, prepareAutocoderCandidate, ACTIVE_PLAYBOOKS } from "./sovereign-operations.js";
import { runSovereignCycle, loadEconomicEvidence, handleSovereign, validateGoal } from "./sovereign-runtime.js";
import { validateCandidate } from "../../.github/scripts/lumen-sovereign-apply-candidate.mjs";
import { recomputePortfolioGovernor } from "./portfolio-governor.js";

const sqlite = new DatabaseSync(":memory:");
const DB = { prepare(sql) {
  let args = [];
  return { bind(...values) { args = values; return this; },
    async run() { return { meta: { changes: Number(sqlite.prepare(sql).run(...args).changes) } }; },
    async first() { const row = sqlite.prepare(sql).get(...args); return row ? { ...row } : null; },
    async all() { return { results: sqlite.prepare(sql).all(...args).map(row => ({ ...row })) }; }
  };
}, async batch(statements) {
  sqlite.exec("BEGIN");
  try { const results = []; for (const statement of statements) results.push(await statement.run()); sqlite.exec("COMMIT"); return results; }
  catch (error) { sqlite.exec("ROLLBACK"); throw error; }
} };
const env = { DB, OPPORTUNITY_ADMIN_TOKEN: "test-admin" };
await ensureSovereignSchema(env);
const admin = { "x-lumen-admin": "test-admin", "content-type": "application/json" };
function req(path, body, headers = admin) { return new Request(`https://lumen.test${path}`, body === undefined ? { headers } : { method: "POST", headers, body: JSON.stringify(body) }); }

// No admin credential, no operational information or mutations. Missing tokens
// fail closed even when the caller supplies an empty matching string.
assert.equal((await handleSovereign(req("/sovereign/policy", undefined, {}), {})).status, 200);
assert.equal((await (await handleSovereign(req("/sovereign/policy", undefined, {}), { LUMEN_V4_RELEASE_ID: "release-test" })).json()).releaseId, "release-test");
assert.equal((await handleSovereign(req("/sovereign/status", undefined, {}), env)).status, 403);
assert.equal((await handleSovereign(req("/sovereign/goal", { targetMonthlyRevenueUsd: 1000 }, {}), env)).status, 403);
assert.equal((await handleSovereign(req("/sovereign/status"), { DB })).status, 403);
assert.equal((await handleSovereign(req("/sovereign/goal", { targetMonthlyRevenueUsd: 1000, autonomousSpendUsd: 500 }), env)).status, 400);
assert.throws(() => validateGoal({ targetMonthlyRevenueUsd: "1000" }), /target/);
assert.equal((await handleSovereign(req("/sovereign/goal", { targetMonthlyRevenueUsd: 1000 }), env)).status, 200);
assert.equal((await handleSovereign(new Request("https://lumen.test/sovereign/goal", { method: "POST", headers: admin, body: "x".repeat(17000) }), env)).status, 400);
assert.equal((await handleSovereign(req("/sovereign/run", {}), env)).status, 503);
assert.equal((await handleSovereign(req("/sovereign/verify", {}), env)).status, 503);
assert.equal((await handleSovereign(req("/sovereign/verify", {}, {}), env)).status, 403);
const verificationBatches = [];
const verificationEnv = { ...env, LUMEN_DEEP_WORKFLOW: { async createBatch(batch) { verificationBatches.push(batch); } } };
const verificationResponse = await handleSovereign(req("/sovereign/verify", {}), verificationEnv);
const verification = await verificationResponse.json();
assert.equal(verificationResponse.status, 202);
assert.equal(verification.sendsMessages, false);
assert.equal(verificationBatches[0][0].params.sovereignOnly, true);
assert.equal(verification.runId, `v4-${verification.instanceId}`);

// Estimates are conservative, finite, bounded and explicitly distinct from
// realized income. Invalid/self-scored worlds cannot win an authority override.
const candidate = { id: "C1", source_type: "DISCOVERY", source_id: "O1", lane: "NEW_BUSINESS", evidence_score: 90, estimated_value_usd: 19 };
const cold = evaluateEconomics(candidate), hot = evaluateEconomics(candidate, { sent: 20, verified_settlements: 8 });
assert.ok(hot.probability > cold.probability);
assert.equal(cold.verifiedRevenueUsd, 0);
assert.equal(cold.estimatesOnly, true);
const allocation = allocateAttention(Array.from({ length: 60 }, (_,i) => evaluateEconomics({ ...candidate, id: `C${i}` })));
assert.ok(allocation.usedMinutes <= 10);
assert.ok(allocation.allocations.every(a => a.simulation.worlds.length === 4 && a.simulation.winner.spendUsd === 0));
assert.equal(judgeWorld({ minutes: 1, spendUsd: 1, priceChange: false, externalExecution: true, probabilityMultiplier: 1000000, uncertainty: 0 }, hot).admissible, false);
assert.equal(benchmark({ revenuePerReservedNeuron: 0 }, { revenuePerReservedNeuron: 1 }).revenueImprovement60PercentVerified, null);
assert.equal(benchmark({ opportunitiesEvaluated: 10, usefulExperiments: 10, humanDecisions: 10, proposalLatencyMs: 10, revenuePerReservedNeuron: 10 },
  { opportunitiesEvaluated: 30, usefulExperiments: 40, humanDecisions: 3, proposalLatencyMs: 4, revenuePerReservedNeuron: 16 }).revenueImprovement60PercentVerified, true);

// Protocol preparation must never contact a network or sign payments. AP2 is
// explicitly blocked; an arbitrary mandate cannot authorize money movement.
let networkCalls = 0;
const originalFetch = globalThis.fetch;
globalThis.fetch = async () => { networkCalls++; throw new Error("test_network_disabled"); };
try {
  const a2a = prepareProtocolEnvelope("a2a", { id: "P1", text: "non-binding scope", endpoint: "https://buyer.example/a2a" });
  assert.equal(a2a.body.method, "message/send"); assert.equal(a2a.executable, false);
  assert.equal(prepareProtocolEnvelope("mcp", { id: "M1", text: "research", tool: "supplier_lookup", arguments: { company: "buyer" } }).body.method, "tools/call");
  assert.equal(prepareProtocolEnvelope("ap2", { id: "A1", text: "pay", mandate: { approved: true } }).blocked, true);
  assert.throws(() => prepareProtocolEnvelope("a2a", { id: "P1", text: "scope", endpoint: "http://internal" }), /https/);
  assert.equal(prepareProtocolEnvelope("x402", { id: "X1", text: "checkout", checkoutUrl: "https://seller.example/buy/a" }).consumesPaymentSignature, false);

  // Real SQLite legacy fixtures, with multiple source records on one host.
  sqlite.exec(`
    CREATE TABLE lumen_opportunities (id TEXT PRIMARY KEY,name TEXT,description TEXT,endpoint TEXT,evidence TEXT,revenue_offer_id TEXT,discovered_at TEXT,updated_at TEXT);
    CREATE TABLE lumen_opportunity_assessments (opportunity_id TEXT PRIMARY KEY,commercially_actionable INTEGER,synthetic_or_test_only INTEGER,commercial_score INTEGER,evidence_strength TEXT);
    CREATE TABLE lumen_proposal_drafts (opportunity_id TEXT PRIMARY KEY,proposal_id TEXT,status TEXT,offer_id TEXT,amount_usd REAL,subject TEXT,message TEXT,quality_gate_status TEXT,created_at TEXT,updated_at TEXT);
    CREATE TABLE lumen_sales_pipeline (proposal_id TEXT PRIMARY KEY,stage TEXT,response_class TEXT,updated_at TEXT);
    CREATE TABLE lumen_opportunity_factory_candidates (id TEXT PRIMARY KEY,source_type TEXT,source_id TEXT,lane TEXT,stage TEXT,title TEXT,estimated_value_usd REAL,probability REAL,urgency REAL,evidence_score REAL,signal_score REAL,economic_score REAL,action_kind TEXT,action_ref TEXT,rationale TEXT,updated_at TEXT,active INTEGER);
    CREATE TABLE lumen_offer_performance (offer_id TEXT PRIMARY KEY,sent INTEGER,verified_settlements INTEGER,priority_adjustment INTEGER);
    CREATE TABLE lumen_x402_receipts (id TEXT PRIMARY KEY,status TEXT,product_id TEXT,amount_usd REAL,created_at TEXT,currency TEXT,network TEXT,pay_to TEXT,request_metadata TEXT);
    CREATE TABLE lumen_x402_revenue_bridge (receipt_id TEXT PRIMARY KEY,proposal_id TEXT,offer_id TEXT);
    CREATE TABLE lumen_paid_fulfillment_jobs (order_id TEXT PRIMARY KEY,receipt_id TEXT,item_id TEXT,amount_usd REAL,status TEXT,updated_at TEXT);
    CREATE TABLE lumen_paid_deliveries (order_id TEXT PRIMARY KEY,receipt_id TEXT,status TEXT,provider_message_id TEXT,updated_at TEXT);
    CREATE TABLE lumen_paid_boost_steps (run_id TEXT,step_name TEXT,status TEXT,updated_at TEXT);
    CREATE TABLE lumen_paid_boost_ai_usage (day TEXT PRIMARY KEY,reserved_neurons INTEGER,calls INTEGER);
    CREATE TABLE lumen_revenue_events (event_type TEXT,status TEXT,amount_usd REAL);
  `);
  const now = new Date().toISOString(), earlier = new Date(Date.now() - 3600000).toISOString();
  for (let i = 1; i <= 4; i++) {
    const endpoint = i < 3 ? `https://buyer.example/agent${i}` : i === 3 ? "https://another.example/a2a" : "https://github.com/registry";
    sqlite.prepare("INSERT INTO lumen_opportunities VALUES(?,?,?,?,?,?,?,?)").run(`O${i}`, `Buyer ${i}`, "needs supplier verification", endpoint, `https://evidence.example/${i}`, "MP-SUPPLIER-SNAPSHOT", earlier, now);
    sqlite.prepare("INSERT INTO lumen_opportunity_assessments VALUES(?,1,0,90,'strong')").run(`O${i}`);
  }
  sqlite.prepare("INSERT INTO lumen_proposal_drafts VALUES('O1','P1','APPROVED','MP-SUPPLIER-SNAPSHOT',1,'Supplier evidence proposal','Non-binding proposal: no order, contract or commitment created.','PASS',?,?)").run(now,now);
  sqlite.prepare("INSERT INTO lumen_opportunity_factory_candidates VALUES('C1','DISCOVERY','O1','NEW_BUSINESS','ACTIONABLE','supplier',1,0.1,0.1,90,90,90,'NEW_OUTREACH','O1','evidence',?,1)").run(now);
  sqlite.prepare("INSERT INTO lumen_offer_performance VALUES('MP-SUPPLIER-SNAPSHOT',20,1,0)").run();
  const loaded = await loadEconomicEvidence(env);
  assert.equal(loaded.missingCapabilities.length, 0);
  const radar = marketRadar(loaded.opportunities, []);
  assert.equal(radar[0].distinctHostSignals, 2, "same host duplicates and shared registry hosts do not become new buyers");
  assert.equal(radar[0].independentBuyerCount, null);
  assert.equal(productSpec({ ...radar[0], distinctHostSignals: 1 }), null);
  assert.equal(productSpec(radar[0]).checkoutEnabled, false);

  // Forged, failed, mismatched and testnet receipts cannot advance a deal.
  const receipt = { receipt_id: "R1", proposal_id: "P1", product_id: "MP-SUPPLIER-SNAPSHOT", amount_usd: 1, currency: "USD", network: "eip155:8453", pay_to: "0x04285DE6A083CEb28fb0C254a2ed0F5fdB2eeD28", status: "settled_verified", request_metadata: JSON.stringify({ settlement: { success: true, transaction: `0x${"a".repeat(64)}` } }) };
  assert.equal(verifiedSettlement(receipt, { proposalId: "P1", offerId: "MP-SUPPLIER-SNAPSHOT", amountUsd: 1 }), true);
  for (const change of [{ status: "pending" }, { network: "eip155:84532" }, { pay_to: "0x0000000000000000000000000000000000000000" }, { currency: "EUR" }, { request_metadata: '{"settlement":{"success":true}}' }, { request_metadata: '{"settlement":{"success":false}}' }])
    assert.equal(verifiedSettlement({ ...receipt, ...change }), false);
  assert.equal(verifiedSettlement(receipt, { proposalId: "P2" }), false);
  assert.equal(verifiedSettlement(receipt, { offerId: "MP-QUOTE-SANITY" }), false);
  assert.equal(verifiedSettlement(receipt, { amountUsd: 7 }), false);

  // Approval is bound to exact copy, endpoint, price and source state. Two
  // simultaneous decisions cannot both commit and neither executes a send.
  const row = loaded.proposals[0], research = { fingerprint: "test" };
  const packet = await prepareApprovalPacket(env, row, research);
  assert.equal((await decideApproval(env, packet.id, { decision: "APPROVE", scopeHash: "wrong" })).status, 400);
  sqlite.prepare("UPDATE lumen_proposal_drafts SET amount_usd=7 WHERE proposal_id='P1'").run();
  assert.equal((await decideApproval(env, packet.id, { decision: "APPROVE", scopeHash: packet.scopeHash })).status, 409);
  sqlite.prepare("UPDATE lumen_proposal_drafts SET amount_usd=1 WHERE proposal_id='P1'").run();
  const decisions = await Promise.all([decideApproval(env, packet.id, { decision: "APPROVE", scopeHash: packet.scopeHash }), decideApproval(env, packet.id, { decision: "REJECT", scopeHash: packet.scopeHash })]);
  assert.equal(decisions.filter(d => d.status === 200).length, 1);
  assert.equal(decisions.find(d => d.status === 200).result.executed, false);
  assert.equal(sqlite.prepare("SELECT status FROM lumen_proposal_drafts").get().status, "APPROVED", "v4 review never changes legacy execution authorization");
  sqlite.prepare("UPDATE lumen_proposal_drafts SET subject='Revised supplier scope' WHERE proposal_id='P1'").run();
  const changed = (await loadEconomicEvidence(env)).proposals[0];
  const newPacket = await prepareApprovalPacket(env, changed, research);
  assert.notEqual(packet.id, newPacket.id);
  assert.equal(sqlite.prepare("SELECT status FROM lumen_v4_approvals WHERE id=?").get(packet.id).status, "SUPERSEDED");
  assert.equal((await decideApproval(env, newPacket.id, { decision: "APPROVE", scopeHash: newPacket.scopeHash }, Date.now() + 25*3600000)).status, 409);

  // The full connected cycle writes useful artifacts, reaches the existing
  // governor and recovers persisted results without duplicated work or income.
  const result = await runSovereignCycle(env, { runId: "integration-1" });
  assert.equal(result.ok, true);
  assert.equal(result.products.drafts.length, 1);
  assert.equal(result.deals.deals.length, 1);
  assert.equal(result.ceo.goal.targetMonthlyRevenueUsd, 1000);
  assert.equal(result.metrics.comparison.revenueImprovement60PercentVerified, null);
  assert.equal(result.metrics.current.verifiedReceiptRevenueUsd, 0);
  assert.equal(result.autonomy.sendsMessages, false);
  const graphCount = sqlite.prepare("SELECT COUNT(*) n FROM lumen_v4_edges").get().n;
  assert.deepEqual(await runSovereignCycle(env, { runId: "integration-1" }), result);
  assert.equal(sqlite.prepare("SELECT COUNT(*) n FROM lumen_v4_edges").get().n, graphCount);
  assert.equal(sqlite.prepare("SELECT COUNT(*) n FROM lumen_v4_allocations").get().n, 1);
  const governor = await recomputePortfolioGovernor(env);
  assert.ok(governor.topCandidate.feedbackAdjustment > 0, "v4 economic attention reaches the existing governor");
  assert.ok(governor.topCandidate.feedbackAdjustment <= 8);
  assert.equal(governor.guardrails.maxExternalMessagesPerCycle, 1);
  assert.equal(governor.guardrails.autonomousSpendUsd, 0);

  sqlite.prepare("INSERT INTO lumen_x402_receipts VALUES('R1','settled_verified','MP-SUPPLIER-SNAPSHOT',1,?,'USD','eip155:8453',?,?)").run(now,receipt.pay_to,receipt.request_metadata);
  sqlite.prepare("INSERT INTO lumen_x402_revenue_bridge VALUES('R1','P1','MP-SUPPLIER-SNAPSHOT')").run();
  const paid = await runSovereignCycle(env, { runId: "integration-2" });
  assert.equal(paid.deals.deals[0].stage, "PAID_FULFILLMENT_PENDING");
  assert.equal(paid.metrics.current.verifiedReceiptRevenueUsd, 1);
  assert.equal(paid.metrics.current.verifiedSettlements, 1);
  sqlite.prepare("UPDATE lumen_x402_receipts SET status='redeemed_queued' WHERE id='R1'").run();
  sqlite.prepare("INSERT INTO lumen_paid_fulfillment_jobs VALUES('ORDER1','R1','MP-SUPPLIER-SNAPSHOT',1,'report_ready',?)").run(now);
  const readyData = await loadEconomicEvidence(env);
  assert.equal((await operateDeals(env, readyData)).deals[0].stage, "DELIVERY_QUALITY_GATE_PENDING");
  sqlite.prepare("UPDATE lumen_paid_fulfillment_jobs SET status='delivered'").run();
  sqlite.prepare("INSERT INTO lumen_paid_deliveries VALUES('ORDER1','R1','delivered','PROVIDER-MSG-1',?)").run(now);
  assert.equal((await operateDeals(env, await loadEconomicEvidence(env))).deals[0].stage, "POSTSALE_OBSERVATION");
  assert.equal((await runSovereignCycle(env, { runId: "integration-3" })).metrics.current.verifiedReceiptRevenueUsd, 1, "redeemed receipt is counted once, never as new revenue");

  // Self-healing cannot replay an ambiguous mutating legacy step. It produces
  // a real bounded patch candidate with a verifiable base for an isolated PR.
  sqlite.prepare("INSERT INTO lumen_paid_boost_steps VALUES('legacy-run','external-send','FAILED',?)").run(now);
  const unhealthy = await runSovereignCycle(env, { runId: "integration-4" });
  assert.equal(unhealthy.health.reviewRequired, 1);
  assert.equal(unhealthy.health.replaysExternalActions, false);
  const code = sqlite.prepare("SELECT * FROM lumen_v4_code_candidates LIMIT 1").get();
  if (ACTIVE_PLAYBOOKS.maxInternalDeals > 1) {
    assert.ok(code);
    const baseContent = readFileSync(new URL("./sovereign-playbooks.json", import.meta.url), "utf-8");
    const validated = validateCandidate(code, baseContent);
    assert.equal(JSON.parse(validated.content).maxInternalDeals, 1);
    const patch = JSON.parse(code.patch_json);
    assert.throws(() => validateCandidate({ ...code, patch_json: JSON.stringify({ ...patch, path: ".github/workflows/deploy.yml" }) }, baseContent), /unsafe/);
    assert.throws(() => validateCandidate({ ...code, patch_json: JSON.stringify({ ...patch, autoMerge: true }) }, baseContent), /unsafe/);
    assert.throws(() => validateCandidate(code, baseContent + " "), /stale/);
  }
  assert.equal(sqlite.prepare("SELECT status FROM lumen_paid_boost_steps").get().status, "FAILED");
  assert.throws(() => validatePlaybooks({ ...ACTIVE_PLAYBOOKS, maxInternalDeals: 100 }), /bound/);
  assert.throws(() => validatePlaybooks({ ...ACTIVE_PLAYBOOKS, spendUsd: 50 }), /keys/);
  assert.equal(V4_POLICY.autonomousSpendUsd, 0);

  sqlite.prepare("INSERT INTO lumen_v4_runs VALUES('ambiguous',?,NULL,'RUNNING',NULL)").run(now);
  assert.equal((await runSovereignCycle(env, { runId: "ambiguous" })).ok, false);
  assert.equal((await handleSovereign(req("/sovereign/status"), env)).status, 200);
  sqlite.exec("DROP TABLE lumen_paid_deliveries");
  const degraded = await runSovereignCycle(env, { runId: "integration-missing-capability" });
  assert.equal(degraded.ok, false);
  assert.ok(degraded.missingCapabilities.some(m => m.includes("lumen_paid_deliveries")));
  assert.equal(degraded.ceo.bottleneck, "CAPABILITY_HEALTH");
  assert.equal(networkCalls, 0, "all new v4 autonomy stays internal, no external messages, purchases or payments");
} finally { globalThis.fetch = originalFetch; }
console.log("SOVEREIGN_V4_TESTS_OK: integrated SQLite cycle, economics, protocol gates, exact receipts, scope-bound approvals, no replay, lab red-team, honest metrics");
