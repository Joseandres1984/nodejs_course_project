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
  CREATE TABLE lumen_proposal_drafts(proposal_id TEXT PRIMARY KEY,opportunity_id TEXT,offer_id TEXT,offer_name TEXT,amount_usd REAL,message TEXT,quality_gate_status TEXT,status TEXT,updated_at TEXT);
  CREATE TABLE lumen_opportunities(id TEXT PRIMARY KEY,name TEXT);
  CREATE TABLE lumen_outreach_attempts(proposal_id TEXT,agent_url TEXT,protocol_binding TEXT,protocol_version TEXT,context_id TEXT,response_text TEXT,updated_at TEXT);
  CREATE TABLE lumen_followups(proposal_id TEXT,response_text TEXT,sent_at TEXT,updated_at TEXT);
  CREATE TABLE lumen_sales_pipeline(proposal_id TEXT PRIMARY KEY,stage TEXT,response_class TEXT,next_action TEXT,next_action_at TEXT,updated_at TEXT);
`);
sqlite.prepare("INSERT INTO lumen_proposal_drafts VALUES(?,?,?,?,?,?,?,?,?)").run("P1","O1","MP-BUYER-SIGNALS","Buyer Signal Scan",19,"Buyer Signal Scan is USD 19 per request.","PASS","RESPONDED","2026-10-06T20:00:00Z");
sqlite.prepare("INSERT INTO lumen_opportunities VALUES(?,?)").run("O1","Buyer");
sqlite.prepare("INSERT INTO lumen_outreach_attempts VALUES(?,?,?,?,?,?,?)").run("P1","https://buyer.example/a2a","JSONRPC","0.3.0","CTX1","What is the price?","2026-10-06T20:00:00Z");
sqlite.prepare("INSERT INTO lumen_sales_pipeline VALUES(?,?,?,?,?,?)").run("P1","RESPONDED","COMMERCIAL_QUESTION","answer_question_and_advance",null,"2026-10-06T20:00:00Z");

const env={DB:dbAdapter(sqlite),A2A_AUTONOMOUS_OUTREACH:"true",A2A_AUTONOMOUS_COMMERCIAL_REPLY:"true"};
const saved=globalThis.fetch;
let calls=0;
const remoteReplies=["What does it include?","Send checkout"];
globalThis.fetch=async()=>{
  const text=remoteReplies[calls++] || "Send checkout";
  return new Response(JSON.stringify({result:{message:{parts:[{text}]}}}),{status:200,headers:{"content-type":"application/json"}});
};

try{
  const first=await runCommercialReplyEngine(env);
  assert.equal(first.sent,true);
  assert.equal(first.replyCount,1);
  assert.equal(first.followOnClassification,"COMMERCIAL_QUESTION");

  const second=await runCommercialReplyEngine(env);
  assert.equal(second.sent,true);
  assert.equal(second.replyCount,2);
  assert.equal(second.followOnClassification,"PURCHASE_INTENT");

  const third=await runCommercialReplyEngine(env);
  assert.equal(third.sent,false);
  assert.equal(third.reason,"no_commercial_question_waiting");
  assert.equal(calls,2,"purchase intent must hand off to First Cash instead of sending a third commercial reply");

  const stored=sqlite.prepare("SELECT reply_count,response_text FROM lumen_commercial_replies WHERE proposal_id='P1'").get();
  assert.equal(stored.reply_count,2);
  assert.match(stored.response_text,/Send checkout/i);
  const pipeline=sqlite.prepare("SELECT stage,response_class,next_action FROM lumen_sales_pipeline WHERE proposal_id='P1'").get();
  assert.equal(pipeline.stage,"NEGOTIATING");
  assert.equal(pipeline.response_class,"PURCHASE_INTENT");
  assert.equal(pipeline.next_action,"send_exact_checkout");
}finally{globalThis.fetch=saved;}

console.log("COMMERCIAL_REPLY_BOUNDED_DIALOGUE_OK");
