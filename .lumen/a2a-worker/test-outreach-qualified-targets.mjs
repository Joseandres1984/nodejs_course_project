import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { isEphemeralAgentEndpoint, probeNextApproved, sendApprovedBatch } from "./a2a-outreach.js";

function dbAdapter(sqlite) {
  return {
    prepare(sql) {
      let stmt = null, args = [];
      return {
        bind(...values) { args = values; return this; },
        async run() { stmt ||= sqlite.prepare(sql); const r = stmt.run(...args); return { meta: { changes: Number(r.changes) } }; },
        async first() { stmt ||= sqlite.prepare(sql); return stmt.get(...args) || null; },
        async all() { stmt ||= sqlite.prepare(sql); return { results: stmt.all(...args) }; }
      };
    },
    async batch(statements) { const results = []; for (const stmt of statements) results.push(await stmt.run()); return results; }
  };
}

assert.equal(isEphemeralAgentEndpoint("https://champion-penetration-geographic-danny.trycloudflare.com/a2a"), true);
assert.equal(isEphemeralAgentEndpoint("https://supplier.example/.well-known/agent-card.json"), false);

const sqlite = new DatabaseSync(":memory:");
sqlite.exec(`
  CREATE TABLE lumen_opportunities (id TEXT PRIMARY KEY, name TEXT, endpoint TEXT);
  CREATE TABLE lumen_opportunity_assessments (
    opportunity_id TEXT PRIMARY KEY, commercially_actionable INTEGER,
    synthetic_or_test_only INTEGER, commercial_score INTEGER, evidence_strength TEXT
  );
  CREATE TABLE lumen_proposal_drafts (
    proposal_id TEXT PRIMARY KEY, opportunity_id TEXT, offer_id TEXT, offer_name TEXT,
    amount_usd REAL, subject TEXT, message TEXT, metadata_json TEXT,
    status TEXT, quality_gate_status TEXT, updated_at TEXT
  );
`);
const db = dbAdapter(sqlite);
const env = { DB: db, A2A_AUTONOMOUS_OUTREACH: "true", X402_CHECKOUT_URL: "https://checkout.example/buy" };
const now = new Date().toISOString();
const scenarios = [
  ["old-raw-tender", 0, 0, 100, "strong", "https://tender.example/notice"],
  ["synthetic-target", 1, 1, 100, "strong", "https://synthetic.example/card"],
  ["weak-target", 1, 0, 90, "weak", "https://weak.example/card"],
  ["low-score-target", 1, 0, 49, "strong", "https://low.example/card"],
  ["good-supplier", 1, 0, 88, "strong", "https://supplier.example/.well-known/agent-card.json"],
  ["ephemeral-supplier", 1, 0, 85, "strong", "https://champion-penetration-geographic-danny.trycloudflare.com/.well-known/agent-card.json"]
];
for (const [id, actionable, synthetic, score, strength, endpoint] of scenarios) {
  sqlite.prepare("INSERT INTO lumen_opportunities(id,name,endpoint) VALUES(?,?,?)").run(id,id,endpoint);
  sqlite.prepare("INSERT INTO lumen_opportunity_assessments(opportunity_id,commercially_actionable,synthetic_or_test_only,commercial_score,evidence_strength) VALUES(?,?,?,?,?)").run(id,actionable,synthetic,score,strength);
  sqlite.prepare("INSERT INTO lumen_proposal_drafts(proposal_id,opportunity_id,offer_id,offer_name,amount_usd,subject,message,metadata_json,status,quality_gate_status,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)").run(`prop-${id}`,id,"MP-TENDER-LEAD","Tender Hot Lead",1,"Verified supplier fit","This is a non-binding proposal; no order, contract or commitment is created.","{}","APPROVED","PASS",now);
}
const fetches = [];
const originalFetch = globalThis.fetch;
globalThis.fetch = async (url, options = {}) => {
  fetches.push({url:String(url),method:options.method || "GET"});
  if (String(url) === "https://supplier.example/.well-known/agent-card.json")
    return Response.json({ supportedInterfaces: [{ protocolBinding: "JSONRPC", protocolVersion: "1.0", url: "https://supplier.example/a2a" }] });
  if (String(url) === "https://supplier.example/a2a")
    return Response.json({ jsonrpc:"2.0", result:{ task:{ id:"task-good", status:{ state:"submitted" } } } });
  if (String(url) === "https://invalid.example/card") return new Response("<html>not an agent</html>", { status: 200, headers: { "content-type": "text/html" } });
  throw new Error("Unexpected fetch: " + url);
};
try {
  // An old approved/READY proposal must not bypass current demand-truth gates.
  for (const [id,,,,,endpoint] of scenarios) {
    sqlite.prepare("INSERT INTO lumen_outreach_attempts(proposal_id,opportunity_id,created_at,updated_at,status,card_url,engine_version) VALUES(?,?,?,?,?,?,?)")
      .run(`prop-${id}`,id,now,now,"READY",endpoint,"test");
  }
} catch (e) {
  // The outreach runtime initializes its table on first call.
  if (!String(e.message).includes("no such table")) throw e;
}
try {
  await db.batch([
    db.prepare("CREATE TABLE IF NOT EXISTS lumen_outreach_attempts (proposal_id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, status TEXT NOT NULL, card_url TEXT, agent_url TEXT, protocol_binding TEXT, protocol_version TEXT, task_id TEXT, context_id TEXT, response_text TEXT, request_json TEXT, response_json TEXT, error TEXT, engine_version TEXT NOT NULL)")
  ]);
  for (const [id,,,,,endpoint] of scenarios) {
    const present = sqlite.prepare("SELECT 1 AS ok FROM lumen_outreach_attempts WHERE proposal_id=?").get(`prop-${id}`);
    if (!present) sqlite.prepare("INSERT INTO lumen_outreach_attempts(proposal_id,opportunity_id,created_at,updated_at,status,card_url,engine_version) VALUES(?,?,?,?,?,?,?)")
      .run(`prop-${id}`,id,now,now,"READY",endpoint,"test");
  }
  const result = await sendApprovedBatch(env, { force: true, limit: 10 });
  assert.equal(result.attempted, 2, JSON.stringify(result));
  assert.equal(result.sent, 1, JSON.stringify(result));
  assert.equal(result.failed, 1, JSON.stringify(result));
  assert.deepEqual(fetches.map(x => x.url), [
    "https://supplier.example/.well-known/agent-card.json",
    "https://supplier.example/a2a"
  ]);
  assert.equal(sqlite.prepare("SELECT status FROM lumen_outreach_attempts WHERE proposal_id='prop-ephemeral-supplier'").get().status, "INCOMPATIBLE");
  for (const id of ["old-raw-tender","synthetic-target","weak-target","low-score-target"]) {
    assert.equal(sqlite.prepare("SELECT status FROM lumen_outreach_attempts WHERE proposal_id=?").get(`prop-${id}`).status, "READY", `must not touch ${id}`);
  }

  sqlite.prepare("INSERT INTO lumen_opportunities(id,name,endpoint) VALUES(?,?,?)").run("invalid-card","Invalid","https://invalid.example/card");
  sqlite.prepare("INSERT INTO lumen_opportunity_assessments(opportunity_id,commercially_actionable,synthetic_or_test_only,commercial_score,evidence_strength) VALUES(?,?,?,?,?)").run("invalid-card",1,0,88,"strong");
  sqlite.prepare("INSERT INTO lumen_proposal_drafts(proposal_id,opportunity_id,offer_id,offer_name,amount_usd,subject,message,metadata_json,status,quality_gate_status,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)").run("prop-invalid-card","invalid-card","MP-TENDER-LEAD","Tender Hot Lead",1,"Valid subject","Non-binding, no order, contract or commitment.","{}","APPROVED","PASS",now);
  const probe = await probeNextApproved(env);
  assert.equal(probe.status, "INCOMPATIBLE", JSON.stringify(probe));
  assert.equal(probe.error, "card_invalid_json");
  assert.equal(sqlite.prepare("SELECT status FROM lumen_outreach_attempts WHERE proposal_id='prop-invalid-card'").get().status,"INCOMPATIBLE");
  console.log("OUTREACH_QUALIFIED_TARGETS_OK: stale/weak/synthetic excluded; temporary tunnel rejected; malformed agent card terminal");
} finally {
  globalThis.fetch = originalFetch;
  sqlite.close();
}
