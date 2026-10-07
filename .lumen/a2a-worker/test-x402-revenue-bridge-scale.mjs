import assert from "node:assert/strict";
import { syncX402SettlementsToRevenue } from "./x402-revenue-bridge.js";

const TOTAL = 10_000;
const receipts = Array.from({ length: TOTAL }, (_, i) => ({
  id: `R-${String(i + 1).padStart(5, "0")}`,
  created_at: new Date(1791331200000 + i).toISOString(),
  product_id: "MP-SUPPLIER-SNAPSHOT",
  amount_usd: 1,
  status: i % 2 === 0 ? "settled_verified" : "redeemed_queued",
  request_metadata: JSON.stringify({ settlement: { success: true, transaction: `tx-${i + 1}` } })
}));

const bridged = new Set();
const events = new Map();

function statement(sql) {
  let bound = [];
  return {
    bind(...args) { bound = args; return this; },
    async all() {
      if (sql.includes("FROM lumen_x402_receipts") && sql.includes("LEFT JOIN lumen_x402_revenue_bridge")) {
        return {
          results: receipts
            .filter(r => ["settled_verified", "redeemed_queued"].includes(r.status) && !bridged.has(r.id))
            .slice(0, 200)
        };
      }
      return { results: [] };
    },
    async first() {
      if (sql.includes("FROM lumen_revenue_events") && sql.includes("evidence=?")) {
        const row = events.get(bound[0]);
        return row ? { id: row.id } : null;
      }
      return null;
    },
    async run() {
      if (sql.includes("INSERT OR IGNORE INTO lumen_revenue_events")) {
        const [id, created_at, item_id, amount_usd, evidence, metadata] = bound;
        if (!events.has(evidence)) events.set(evidence, { id, created_at, item_id, amount_usd, metadata });
        return { success: true };
      }
      if (sql.includes("INSERT OR IGNORE INTO lumen_x402_revenue_bridge")) {
        bridged.add(bound[0]);
        return { success: true };
      }
      return { success: true };
    }
  };
}

const env = {
  DB: {
    prepare: statement,
    async batch() { return []; }
  }
};

let processed = 0;
for (let i = 0; i < 60 && processed < TOTAL; i++) {
  const result = await syncX402SettlementsToRevenue(env);
  assert.equal(result.ok, true);
  processed += result.processed;
}

assert.equal(processed, TOTAL, "all 10,000 verified payments should bridge");
assert.equal(bridged.size, TOTAL, "each receipt should bridge exactly once");
assert.equal(events.size, TOTAL, "each receipt should create exactly one verified revenue event");

const duplicatePass = await syncX402SettlementsToRevenue(env);
assert.equal(duplicatePass.processed, 0, "second pass must be idempotent");
assert.equal(bridged.size, TOTAL);
assert.equal(events.size, TOTAL);

console.log("X402_REVENUE_BRIDGE_10000_IDEMPOTENCY_OK");
