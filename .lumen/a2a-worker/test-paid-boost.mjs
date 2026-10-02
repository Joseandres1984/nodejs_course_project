import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { registerHooks } from "node:module";
import { estimateAiReservation, reserveAiBudget, withBudgetedAi } from "./ai-router.js";
import { ensureBoostSchema, checkpoint, observedOpportunityStage, observeOpportunity, startDeepCycle } from "./paid-boost-runtime.js";

registerHooks({ resolve(name, context, next) {
  if (name === "cloudflare:workers") return { url: "data:text/javascript,export class WorkflowEntrypoint { constructor(ctx, env) { this.env = env; } }", shortCircuit: true };
  return next(name, context);
} });
const { handlePaidBoost, default: entry } = await import("./paid-boost-entry.js");
const { LumenOpportunityWorkflow, LumenDeepWorkflow } = await import("./paid-boost-workflows.js");
const sqlite = new DatabaseSync(":memory:");
const DB = { prepare(sql) {
  const stmt = sqlite.prepare(sql); let args = [];
  return { bind(...values) { args = values; return this; },
    async run() { const r = stmt.run(...args); return { meta: { changes: Number(r.changes) } }; },
    async first() { return stmt.get(...args) || null; },
    async all() { return { results: stmt.all(...args) }; }
  };
}, async batch(statements) { return Promise.all(statements.map(s => s.run())); } };
const env = { DB, OPPORTUNITY_ADMIN_TOKEN: "test-admin" };
await ensureBoostSchema(env);

// Concurrent budget reservations are atomic, including failures and midnight.
const reservations = await Promise.allSettled(Array.from({ length: 20 }, () => reserveAiBudget(env, 200)));
assert.equal(reservations.filter(x => x.status === "fulfilled").length, 12);
assert.equal(sqlite.prepare("SELECT reserved_neurons FROM lumen_paid_boost_ai_usage").get().reserved_neurons, 2400);
assert.throws(() => estimateAiReservation("unknown", { max_tokens: 10 }), /allowlisted/);
assert.throws(() => estimateAiReservation("@cf/google/gemma-4-26b-a4b-it", { max_tokens: 601 }), /budget/);
assert.throws(() => estimateAiReservation("@cf/google/gemma-4-26b-a4b-it", { stream: true, max_tokens: 10 }), /unbudgeted/);
let calls = 0;
await assert.rejects(() => withBudgetedAi({ DB, AI: { run() { calls++; } } }).AI.run("@cf/google/gemma-4-26b-a4b-it", { messages: [{ role: "user", content: "a".repeat(10000) }], max_tokens: 100 }), /exhausted/);
assert.equal(calls, 0);
sqlite.prepare("DELETE FROM lumen_paid_boost_ai_usage").run();
const failedAi = withBudgetedAi({ DB, AI: { async run() { throw new Error("provider_timeout"); } } });
await assert.rejects(() => failedAi.AI.run("@cf/google/gemma-4-26b-a4b-it", { messages: [], max_tokens: 100 }), /timeout/);
assert.equal(sqlite.prepare("SELECT calls FROM lumen_paid_boost_ai_usage").get().calls, 1);

// Successful callbacks are recovered without repeating writes; ambiguous and
// failed mutating steps cannot be blindly retried after a process restart.
let mutations = 0;
assert.deepEqual(await checkpoint(env, "run1", "learn", async () => ({ ok: true, n: ++mutations })), { ok: true, n: 1 });
await checkpoint(env, "run1", "learn", async () => { mutations++; });
assert.equal(mutations, 1);
sqlite.prepare("INSERT INTO lumen_paid_boost_steps VALUES('run1','ambiguous','RUNNING',NULL,'now')").run();
assert.equal((await checkpoint(env, "run1", "ambiguous", async () => { mutations++; })).ok, false);
await checkpoint(env, "run1", "fail", async () => { throw new Error("isolated"); });
await checkpoint(env, "run1", "fail", async () => { mutations++; });
assert.equal(mutations, 1);
assert.equal((await checkpoint(env, "run1", "after-fail", async () => ({ ok: true }))).ok, true);

// Public policy is read-only; private state and manual runs fail closed.
assert.equal((await handlePaidBoost(new Request("https://lumen.test/paid-boost/policy"), {})).status, 200);
assert.equal((await handlePaidBoost(new Request("https://lumen.test/paid-boost/status"), env)).status, 403);
assert.equal((await handlePaidBoost(new Request("https://lumen.test/paid-boost/deep/run", { method: "POST", headers: { "x-lumen-admin": "wrong" } }), env)).status, 403);
const batch = [];
const workflowEnv = { ...env, LUMEN_DEEP_WORKFLOW: { async createBatch(values) { batch.push(values); } }, LUMEN_OPPORTUNITY_WORKFLOW: {} };
assert.equal(await startDeepCycle(workflowEnv, 3600000), await startDeepCycle(workflowEnv, 3650000));
assert.equal(batch[0][0].id, "deep-1");
const promises = [];
await entry.scheduled({ cron: "12 * * * *", scheduledTime: 3600000 }, workflowEnv, { waitUntil(p) { promises.push(p); } });
await Promise.all(promises);
assert.equal(batch.length, 3, "hourly schedule creates a workflow rather than running fast commercial actions");

sqlite.exec("CREATE TABLE lumen_proposal_drafts(proposal_id TEXT,status TEXT,quality_gate_status TEXT); CREATE TABLE lumen_x402_revenue_bridge(receipt_id TEXT,proposal_id TEXT,created_at TEXT); CREATE TABLE lumen_x402_receipts(id TEXT,status TEXT,request_metadata TEXT)");
sqlite.prepare("INSERT INTO lumen_proposal_drafts VALUES('P1','RESPONDED','PASS')").run();
sqlite.prepare("INSERT INTO lumen_x402_revenue_bridge VALUES('R1','P1','now')").run();
sqlite.prepare("INSERT INTO lumen_x402_receipts VALUES('R1','settled_verified',?)").run(JSON.stringify({ settlement: { success: false } }));
assert.equal((await observeOpportunity(env, "P1", "opp1")).paymentVerified, false);
assert.equal(observedOpportunityStage({ status: "APPROVED", quality_gate_status: "FAIL" }, null), "AWAITING_QUALITY_REVIEW");
sqlite.prepare("UPDATE lumen_x402_receipts SET request_metadata=?").run(JSON.stringify({ settlement: { success: true } }));
const settled = await observeOpportunity(env, "P1", "opp1");
assert.equal(settled.stage, "PAYMENT_VERIFIED_DELIVERY_PENDING");
assert.equal(settled.releasesDelivery, false);
assert.equal((await observeOpportunity(env, "different-proposal", "opp2")).paymentVerified, false);
const instance = new LumenOpportunityWorkflow({}, env);
const steps = [];
await instance.run({ instanceId: "opp1", payload: { proposalId: "P1" } }, {
  async do(name, config, fn) { steps.push(name); return fn(); },
  async sleep() { throw new Error("verified settlement must not sleep"); }
});
assert.deepEqual(steps, ["initialize", "observe-0", "finish"]);
// Run the real orchestration with provider networking disabled. Missing legacy
// schemas produce visible degraded steps, while later steps still checkpoint.
const originalFetch = globalThis.fetch;
globalThis.fetch = async () => { throw new Error("test_network_disabled"); };
try {
  const deep = new LumenDeepWorkflow({}, env), persisted = new Map();
  const durableSteps = { async do(name, config, action) {
    if (!persisted.has(name)) persisted.set(name, await action());
    return persisted.get(name);
  } };
  const result = await deep.run({ instanceId: "deep-test", payload: { scheduledTime: 3600000 } }, durableSteps);
  assert.equal(result.steps, 15);
  assert.ok(persisted.has("sovereign-revenue-v4"));
  assert.ok(persisted.has("foundry-experiments"));
  assert.ok(persisted.has("growth-decision"));
  const count = sqlite.prepare("SELECT COUNT(*) n FROM lumen_paid_boost_steps WHERE run_id='deep-test'").get().n;
  assert.deepEqual(await deep.run({ instanceId: "deep-test", payload: { scheduledTime: 3600000 } }, durableSteps), result);
  assert.equal(sqlite.prepare("SELECT COUNT(*) n FROM lumen_paid_boost_steps WHERE run_id='deep-test'").get().n, count);
} finally { globalThis.fetch = originalFetch; }
console.log("PAID_BOOST_TESTS_OK: atomic budgets, recovery, authorization, cadence, exact settlement evidence");
