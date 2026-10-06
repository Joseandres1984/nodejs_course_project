import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { runCommercialReplyEngine } from "./commercial-reply-engine.js";

function dbAdapter(sqlite){
  return {
    prepare(sql){let stmt=null,args=[];return{
      bind(...v){args=v;return this;},
      async run(){stmt ||= sqlite.prepare(sql);const r=stmt.run(...args);return{meta:{changes:Number(r.changes)}};},
      async first(){stmt ||= sqlite.prepare(sql);return stmt.get(...args)||null;},
      async all(){stmt ||= sqlite.prepare(sql);return{results:stmt.all(...args)}}
    };},
    async batch(statements){const out=[];for(const s of statements)out.push(await s.run());return out;}
  };
}

const sqlite=new DatabaseSync(":memory:");
sqlite.exec(`
  CREATE TABLE lumen_proposal_drafts(
    proposal_id TEXT PRIMARY KEY,opportunity_id TEXT,offer_id TEXT,offer_name TEXT,
    amount_usd REAL,message TEXT,quality_gate_status TEXT,status TEXT,updated_at TEXT
  );
  CREATE TABLE lumen_opportunities(id TEXT PRIMARY KEY,name TEXT);
  CREATE TABLE lumen_outreach_attempts(
    proposal_id TEXT,agent_url TEXT,protocol_binding TEXT,protocol_version TEXT,
    context_id TEXT,response_text TEXT,updated_at TEXT
  );
  CREATE TABLE lumen_followups(proposal_id TEXT,response_text TEXT,sent_at TEXT,updated_at TEXT);
  CREATE TABLE lumen_sales_pipeline(
    proposal_id TEXT PRIMARY KEY,stage TEXT,response_class TEXT,next_action TEXT,next_action_at TEXT,updated_at TEXT
  );
  CREATE TABLE lumen_revenue_loop_v5(
    opportunity_id TEXT,proposal_id TEXT,stage TEXT,first_cash_score REAL,intent_score REAL,
    updated_at TEXT,response_class TEXT,next_action TEXT
  );
  CREATE TABLE lumen_x402_revenue_bridge(proposal_id TEXT,bridge_status TEXT,receipt_id TEXT);
`);

const rows=[
  {p:"P-RECENT",o:"O-RECENT",score:0.1,updated:"2026-10-06T23:50:00Z"},
  {p:"P-FIRST-CASH",o:"O-FIRST-CASH",score:0.9,updated:"2026-10-06T23:40:00Z"}
];
for(const r of rows){
  sqlite.prepare("INSERT INTO lumen_proposal_drafts VALUES(?,?,?,?,?,?,?,?,?)")
    .run(r.p,r.o,"MP-SUPPLIER-SNAPSHOT","Supplier Snapshot",5,"Supplier Snapshot is USD 5 per request.","PASS","RESPONDED",r.updated);
  sqlite.prepare("INSERT INTO lumen_opportunities VALUES(?,?)").run(r.o,r.o);
  sqlite.prepare("INSERT INTO lumen_outreach_attempts VALUES(?,?,?,?,?,?,?)")
    .run(r.p,"https://buyer.example/a2a","JSONRPC","0.3.0","CTX","What does it include?",r.updated);
  sqlite.prepare("INSERT INTO lumen_sales_pipeline VALUES(?,?,?,?,?,?)")
    .run(r.p,"NEGOTIATING","COMMERCIAL_QUESTION","answer_question_and_advance",null,r.updated);
  sqlite.prepare("INSERT INTO lumen_revenue_loop_v5 VALUES(?,?,?,?,?,?,?,?)")
    .run(r.o,r.p,"NEGOTIATING",r.score,0.5,r.updated,"COMMERCIAL_QUESTION","answer_commercial_question_before_checkout");
}

const env={DB:dbAdapter(sqlite),A2A_AUTONOMOUS_OUTREACH:"true",A2A_AUTONOMOUS_COMMERCIAL_REPLY:"true"};
const saved=globalThis.fetch;
let sentProposal=null;
globalThis.fetch=async(_url,opts)=>{
  const body=JSON.parse(opts.body);
  sentProposal=body?.params?.metadata?.lumen?.proposalId || body?.metadata?.lumen?.proposalId || null;
  return new Response(JSON.stringify({result:{message:{parts:[{text:"Thanks, tell me the price?"}]}}}),{status:200,headers:{"content-type":"application/json"}});
};

try{
  const result=await runCommercialReplyEngine(env);
  assert.equal(result.sent,true);
  assert.equal(result.proposalId,"P-FIRST-CASH");
  assert.equal(result.opportunityId,"O-FIRST-CASH");
  assert.equal(result.firstSettlementPriority,true);
  assert.equal(sentProposal,"P-FIRST-CASH");
}finally{
  globalThis.fetch=saved;
}

console.log("COMMERCIAL_REPLY_FIRST_SETTLEMENT_PRIORITY_OK");
