import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { repairFocusedProposalQuality } from "./quality-gate.js";

function adapter(sqlite) {
  return {
    prepare(sql) {
      let stmt, args = [];
      return {
        bind(...values) { args = values; return this; },
        async run() { stmt ||= sqlite.prepare(sql); const value = stmt.run(...args); return {meta:{changes:Number(value.changes)}}; },
        async first() { stmt ||= sqlite.prepare(sql); return stmt.get(...args) || null; },
        async all() { stmt ||= sqlite.prepare(sql); return {results:stmt.all(...args)}; }
      };
    },
    async batch(statements) {
      const results = [];
      for (const statement of statements) results.push(await statement.run());
      return results;
    }
  };
}

const sqlite = new DatabaseSync(":memory:");
sqlite.exec(`
  CREATE TABLE lumen_opportunities(id TEXT PRIMARY KEY,name TEXT,endpoint TEXT,description TEXT,evidence TEXT);
  CREATE TABLE lumen_opportunity_assessments(
    opportunity_id TEXT PRIMARY KEY,commercial_score INTEGER,commercial_fit TEXT,evidence_strength TEXT,
    commercially_actionable INTEGER,synthetic_or_test_only INTEGER);
  CREATE TABLE lumen_proposal_drafts(
    proposal_id TEXT PRIMARY KEY,opportunity_id TEXT,created_at TEXT,updated_at TEXT,status TEXT,
    offer_id TEXT,offer_name TEXT,amount_usd REAL,subject TEXT,message TEXT,quality_gate_status TEXT,
    metadata_json TEXT
  );
  CREATE TABLE lumen_outreach_attempts(proposal_id TEXT PRIMARY KEY, status TEXT);
`);
const now = new Date().toISOString();
function insert({id,score=88,evidence="strong",actionable=1,synthetic=0,endpoint="https://supplier.example/a2a",status="DRAFT",quality="NEEDS_REVISION",outreach=false,metadata={}}) {
  sqlite.prepare("INSERT INTO lumen_opportunities VALUES(?,?,?,?,?)").run(id,id,endpoint,"A current verified commercial sourcing request with evidence.","https://official.example/notice");
  sqlite.prepare("INSERT INTO lumen_opportunity_assessments VALUES(?,?,?,?,?,?)").run(id,score,"A",evidence,actionable,synthetic);
  sqlite.prepare("INSERT INTO lumen_proposal_drafts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)")
    .run("prop-"+id,id,now,now,status,"MP-TENDER-LEAD","Tender Hot Lead",1,"bad","Too short",quality,JSON.stringify(metadata));
  if (outreach) sqlite.prepare("INSERT INTO lumen_outreach_attempts VALUES(?,?)").run("prop-"+id,"SENT");
}
insert({id:"structural",score:100,endpoint:"http://invalid.example/a2a"});
insert({id:"already-sent",score:99,outreach:true});
insert({id:"stale",score:95,actionable:0});
insert({id:"synthetic",score:94,synthetic:1});
insert({id:"weak",score:93,evidence:"weak"});
insert({id:"already-repaired",score:92,metadata:{quality_repair:{attempted:true}}});
insert({id:"repair-me",score:91});
insert({id:"pending-other",score:87,status:"DRAFT",quality:"PENDING_QUALITY_GATE"});

const env = {DB:adapter(sqlite)};
try {
  const result = await repairFocusedProposalQuality(env);
  assert.equal(result.repaired,true,JSON.stringify(result));
  assert.equal(result.proposalId,"prop-repair-me");
  assert.equal(result.passed,true,JSON.stringify(result));
  assert.equal(result.review.proposalId,"prop-repair-me");
  const repaired = sqlite.prepare("SELECT status,quality_gate_status,metadata_json,subject,message FROM lumen_proposal_drafts WHERE proposal_id='prop-repair-me'").get();
  assert.equal(repaired.status,"APPROVED");
  assert.equal(repaired.quality_gate_status,"PASS");
  assert.equal(JSON.parse(repaired.metadata_json).quality_repair.attempted,true);
  assert.match(repaired.message,/non-binding/i);
  for (const id of ["structural","already-sent","stale","synthetic","weak","already-repaired"]) {
    const q = sqlite.prepare("SELECT status,quality_gate_status,message FROM lumen_proposal_drafts WHERE proposal_id=?").get("prop-"+id);
    assert.equal(q.status,"DRAFT",id);
    assert.equal(q.quality_gate_status,"NEEDS_REVISION",id);
    assert.equal(q.message,"Too short",id);
  }
  assert.equal(sqlite.prepare("SELECT quality_gate_status FROM lumen_proposal_drafts WHERE proposal_id='prop-pending-other'").get().quality_gate_status,"PENDING_QUALITY_GATE");
  const again = await repairFocusedProposalQuality(env);
  assert.equal(again.repaired,false,JSON.stringify(again));
  assert.equal(again.reason,"no_safe_unexposed_copy_repair_candidate");
  console.log("BACKLOG_COPY_REPAIR_OK: recovered untouched actionable draft; exposed, weak, structural and repeat attempts protected");
} finally {
  sqlite.close();
}
