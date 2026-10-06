import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { registerHooks } from "node:module";
import { estimateAiReservation, reserveAiBudget, withBudgetedAi } from "./ai-router.js";
import { ensureBoostSchema, checkpoint, observedOpportunityStage, observeOpportunity, startDeepCycle } from "./paid-boost-runtime.js";
registerHooks({ resolve(name, context, next) { if (name === "cloudflare:workers") return { url: "data:text/javascript,export class WorkflowEntrypoint { constructor(ctx, env) { this.env = env; } }", shortCircuit: true }; return next(name, context); } });
const { handlePaidBoost, handleUnifiedBrain, default: entry } = await import("./paid-boost-entry.js");
const { LumenOpportunityWorkflow, LumenDeepWorkflow, runRevenueConversionRouter, shouldRunPostRevenueRouter } = await import("./paid-boost-workflows.js");

const sqlite=new DatabaseSync(":memory:");
const DB={prepare(sql){let stmt=null,args=[];return{bind(...v){args=v;return this;},async run(){stmt ||= sqlite.prepare(sql);const r=stmt.run(...args);return{meta:{changes:Number(r.changes)}};},async first(){stmt ||= sqlite.prepare(sql);return stmt.get(...args)||null;},async all(){stmt ||= sqlite.prepare(sql);return{results:stmt.all(...args)}}};},async batch(statements){const results=[];for(const statement of statements)results.push(await statement.run());return results;}};
const env={DB,OPPORTUNITY_ADMIN_TOKEN:"test-admin"};
await ensureBoostSchema(env);

const reservations=await Promise.allSettled(Array.from({length:20},()=>reserveAiBudget(env,200)));
assert.equal(reservations.filter(x=>x.status==="fulfilled").length,12);
assert.equal(sqlite.prepare("SELECT reserved_neurons FROM lumen_paid_boost_ai_usage").get().reserved_neurons,2400);
assert.throws(()=>estimateAiReservation("unknown",{max_tokens:10}),/allowlisted/);
assert.throws(()=>estimateAiReservation("@cf/google/gemma-4-26b-a4b-it",{max_tokens:601}),/budget/);
assert.throws(()=>estimateAiReservation("@cf/google/gemma-4-26b-a4b-it",{stream:true,max_tokens:10}),/unbudgeted/);
let calls=0;
await assert.rejects(()=>withBudgetedAi({DB,AI:{run(){calls++;}}}).AI.run("@cf/google/gemma-4-26b-a4b-it",{messages:[{role:"user",content:"a".repeat(10000)}],max_tokens:100}),/exhausted/);
assert.equal(calls,0);
sqlite.prepare("DELETE FROM lumen_paid_boost_ai_usage").run();
let mutations=0;
assert.deepEqual(await checkpoint(env,"run1","learn",async()=>({ok:true,n:++mutations})),{ok:true,n:1});
await checkpoint(env,"run1","learn",async()=>{mutations++;});
assert.equal(mutations,1);

assert.equal((await handlePaidBoost(new Request("https://lumen.test/paid-boost/policy"),{})).status,200);
const brainPolicy=await handleUnifiedBrain(new Request("https://lumen.test/brain/policy"),{});
assert.equal(brainPolicy.status,200);
const brainPolicyBody=await brainPolicy.json();
assert.equal(brainPolicyBody.oneGlobalEconomicMission,true);
assert.equal(brainPolicyBody.openEndedBusinessModels,true);
assert.equal(brainPolicyBody.autonomousSpendUsd,0);
assert.equal((await handleUnifiedBrain(new Request("https://lumen.test/brain/status"),env)).status,403);

const batch=[];
const workflowEnv={...env,LUMEN_DEEP_WORKFLOW:{async createBatch(v){batch.push(v);}},LUMEN_OPPORTUNITY_WORKFLOW:{}};
assert.equal(await startDeepCycle(workflowEnv,3600000),await startDeepCycle(workflowEnv,3650000));
const promises=[];
await entry.scheduled({cron:"12 * * * *",scheduledTime:3600000},workflowEnv,{waitUntil(p){promises.push(p);}});
await Promise.all(promises);

// Settlement fixture mirrors every x402 field consumed by Sovereign evidence loading.
sqlite.exec("CREATE TABLE lumen_proposal_drafts(proposal_id TEXT,status TEXT,quality_gate_status TEXT,created_at TEXT); CREATE TABLE lumen_x402_revenue_bridge(receipt_id TEXT,proposal_id TEXT,offer_id TEXT,created_at TEXT); CREATE TABLE lumen_x402_receipts(id TEXT,status TEXT,product_id TEXT,amount_usd REAL,created_at TEXT,currency TEXT,network TEXT,pay_to TEXT,request_metadata TEXT)");
sqlite.prepare("INSERT INTO lumen_proposal_drafts VALUES('P1','RESPONDED','PASS','now')").run();
sqlite.prepare("INSERT INTO lumen_x402_revenue_bridge VALUES('R1','P1','O1','now')").run();
sqlite.prepare("INSERT INTO lumen_x402_receipts VALUES('R1','settled_verified','SRV-TEST',5.0,'now','USDC','base-sepolia','0xtest',?)").run(JSON.stringify({settlement:{success:true}}));
const settled=await observeOpportunity(env,"P1","opp1");
assert.equal(settled.stage,"PAYMENT_VERIFIED_DELIVERY_PENDING");
assert.equal(settled.releasesDelivery,false);
const instance=new LumenOpportunityWorkflow({},env),steps=[];
await instance.run({instanceId:"opp1",payload:{proposalId:"P1"}},{async do(n,c,f){steps.push(n);return f();},async sleep(){throw new Error("verified settlement must not sleep");}});
assert.deepEqual(steps,["initialize","observe-0","finish"]);

// One-slot conversion router: answer one real commercial question and do not also run checkout close.
{
  const sqlite2=new DatabaseSync(":memory:");
  const DB2={prepare(sql){let stmt=null,args=[];return{bind(...v){args=v;return this;},async run(){stmt ||= sqlite2.prepare(sql);const r=stmt.run(...args);return{meta:{changes:Number(r.changes)}};},async first(){stmt ||= sqlite2.prepare(sql);return stmt.get(...args)||null;},async all(){stmt ||= sqlite2.prepare(sql);return{results:stmt.all(...args)}}};},async batch(statements){const results=[];for(const statement of statements)results.push(await statement.run());return results;}};
  sqlite2.exec(`
    CREATE TABLE lumen_proposal_drafts(proposal_id TEXT PRIMARY KEY,opportunity_id TEXT,offer_id TEXT,offer_name TEXT,amount_usd REAL,message TEXT,quality_gate_status TEXT,status TEXT,updated_at TEXT);
    CREATE TABLE lumen_opportunities(id TEXT PRIMARY KEY,name TEXT);
    CREATE TABLE lumen_outreach_attempts(proposal_id TEXT,agent_url TEXT,protocol_binding TEXT,protocol_version TEXT,context_id TEXT,response_text TEXT,updated_at TEXT);
    CREATE TABLE lumen_followups(proposal_id TEXT,response_text TEXT,sent_at TEXT,updated_at TEXT);
  `);
  sqlite2.prepare("INSERT INTO lumen_proposal_drafts VALUES(?,?,?,?,?,?,?,?,?)").run("P-Q","O-Q","MP-BUYER-SIGNALS","Buyer Signal Scan",19,"We can provide buyer signals.","PASS","RESPONDED","2026-10-06T22:00:00Z");
  sqlite2.prepare("INSERT INTO lumen_opportunities VALUES(?,?)").run("O-Q","Qualified buyer");
  sqlite2.prepare("INSERT INTO lumen_outreach_attempts VALUES(?,?,?,?,?,?,?)").run("P-Q","https://buyer.example/a2a","JSONRPC","0.3.0","CTX-Q","What is the price?","2026-10-06T22:00:00Z");

  const env2={DB:DB2,OPPORTUNITY_ADMIN_TOKEN:"test-admin",A2A_AUTONOMOUS_OUTREACH:"true",A2A_AUTONOMOUS_COMMERCIAL_REPLY:"true",A2A_AUTONOMOUS_CONVERSION_CLOSE:"true"};
  const savedFetch=globalThis.fetch;
  let externalCalls=0;
  globalThis.fetch=async()=>{externalCalls++;return new Response(JSON.stringify({result:{message:{parts:[{text:"Send checkout"}]}}}),{status:200,headers:{"content-type":"application/json"}});};
  try{
    const routed=await runRevenueConversionRouter(env2);
    assert.equal(routed.ok,true);
    assert.equal(routed.route,"COMMERCIAL_REPLY");
    assert.equal(routed.externalSlotConsumed,true);
    assert.equal(routed.sent,true);
    assert.equal(routed.proposalId,"P-Q");
    assert.equal(externalCalls,1,"one commercial question must consume the only external conversion slot");
    assert.equal(routed.close,null,"first cash closer must not run after a commercial reply consumed the slot");
    assert.equal(shouldRunPostRevenueRouter(routed),false,"a consumed priority slot must block any later close attempt in the same deep cycle");
    assert.equal(shouldRunPostRevenueRouter({ok:true,externalSlotConsumed:false}),true);
    assert.equal(shouldRunPostRevenueRouter({ok:false,externalSlotConsumed:false}),false);
    const promoted=sqlite2.prepare("SELECT status FROM lumen_proposal_drafts WHERE proposal_id='P-Q'").get();
    assert.equal(promoted.status,"RESPONDED");
  }finally{globalThis.fetch=savedFetch;}
}

const originalFetch=globalThis.fetch;
globalThis.fetch=async()=>{throw new Error("test_network_disabled");};
try{
  const deep=new LumenDeepWorkflow({},env),persisted=new Map();
  const durableSteps={async do(n,c,a){if(!persisted.has(n))persisted.set(n,await a());return persisted.get(n);}};
  const result=await deep.run({instanceId:"deep-test",payload:{scheduledTime:3600000}},durableSteps);
  assert.ok(persisted.has("verified-commercial-truth"));
  assert.ok(persisted.has("conversion-close-priority"),"cash conversion must run before exploration/discovery");
  assert.equal(persisted.get("conversion-close-priority")?.externalSlotConsumed,false);
  assert.equal(persisted.get("conversion-close-priority")?.route,"NONE");
  assert.ok(persisted.has("venture-hunter-v1"));
  assert.ok(persisted.has("viator-conversions-observe"));
  assert.ok(persisted.has("unified-economic-brain-v1"));
  assert.equal(result.brain.version,"1.1-demand-conversion-learning");
  assert.equal(result.brain.lane,"REVENUE");
  assert.equal(result.specialistPlan.revenue,true);
  assert.equal(result.specialistPlan.venture,false);
  assert.equal(result.specialistPlan.commerce,false);
  assert.equal(result.cashBeforeExplore?.enabled,true);
  assert.equal(result.cashBeforeExplore?.externalSlotConsumed,false);
  for(const name of ["sovereign-revenue-v4","revenue-loop-v5","conversion-close-router","opportunity-observers"]) assert.ok(persisted.has(name),`${name} must run for REVENUE mission`);
  assert.equal(persisted.get("conversion-close-router")?.externalSlotConsumed,false,"conversion router must stay silent when there is no qualified commercial response");
  assert.equal(persisted.get("conversion-close-router")?.route,"NONE");
  assert.equal(persisted.has("first-cash-close"),false,"legacy independent close step must be replaced by one-slot conversion router");
  for(const name of ["venture-founder-v2","venture-builder-v1","venture-launcher-v1","supplier-market-launch","travel-acquisition","growth-decision"]) assert.equal(persisted.has(name),false,`${name} must stay off when Brain selected REVENUE`);
  assert.ok(result.steps<20,"Brain must reduce indiscriminate specialist execution");

  const missionCount=sqlite.prepare("SELECT COUNT(*) count FROM lumen_brain_missions").get().count;
  assert.equal(missionCount,1,"one hourly economic mission must be persisted");
  const mission=sqlite.prepare("SELECT execution_lane,business_model FROM lumen_brain_missions LIMIT 1").get();
  assert.equal(mission.execution_lane,"REVENUE");
  assert.ok(mission.business_model.length>0);

  const canarySteps=[];
  const canary=await deep.run({instanceId:"verify-test",payload:{sovereignOnly:true}},{async do(n,c,a){canarySteps.push(n);return a();}});
  assert.equal(canary.steps,1);
  assert.deepEqual(canarySteps,["initialize","sovereign-revenue-v4","finish"]);
  assert.equal(canary.verificationMode,"isolated_sovereign_canary");
}finally{globalThis.fetch=originalFetch;}

console.log("PAID_BOOST_TESTS_OK: unified brain governs specialists, canonical x402 fixture, isolated sovereign canary");
