import assert from "node:assert/strict";
import test from "node:test";
import {VERSION,qualifyTask,scanFundedTasks,handleFundedTaskScout} from "./paid-task-scout.js";
const now=new Date("2026-10-21T22:00:00.000Z");
const good={
 task_id:"task_ABC12345",
 title:"Industrial electronics supplier sourcing evidence review",
 description:"Please compare suppliers, quotations, specifications, lead times and BOM compatibility for industrial electronic components; return a structured sourcing memo.",
 status:"open",claimable:true,
 created_at:"2026-10-21T12:00:00Z",expires_at:"2026-10-25T12:00:00Z",
 bounty:{amount_display:"7.00",token:"USDC",network:"eip155:8453"},
 escrow:{status:"funded",funded_at:"2026-10-21T13:00:00Z",deposit_tx_hash:"0x"+"a".repeat(64)},
 creator:{id:"ag_BUYER_XYZ",name:"Procurement Agent"}
};
function fakeDb(){
 const scan={},leads=new Map();
 return {scan,leads,batch:async(stmts)=>Promise.all(stmts.map(stmt=>stmt.run())),prepare(sql){
  let args=[];
  return {bind(...xs){args=xs;return this;},
   async first(){if(sql.includes("last_attempt_at FROM"))return scan.last_attempt_at?{last_attempt_at:scan.last_attempt_at,status:scan.status}:null;if(sql.startsWith("SELECT * FROM"))return Object.keys(scan).length?scan:null;throw Error("unexpected SELECT "+sql);},
   async all(){if(sql.startsWith("SELECT task_id"))return {results:[...leads.values()]};throw Error("unexpected SELECT ALL "+sql);},
   async run(){
    if(sql.startsWith("CREATE TABLE"))return {meta:{changes:0}};
    if(sql.startsWith("INSERT INTO lumen_funded_task_scans")){Object.assign(scan,{source:args[0],last_attempt_at:args[1],status:"RUNNING"});return {meta:{changes:1}};}
    if(sql.startsWith("INSERT OR IGNORE INTO lumen_funded_task_research")){
     let id=args[1];if(leads.has(id))return {meta:{changes:0}};
     leads.set(id,{task_id:id,source_url:args[2],title:args[3],buyer:args[4],bounty_usdc:args[5],posted_at:args[6],expires_at:args[7],service:args[8],status:"RESEARCH_ONLY",funding_label:args[9],first_seen_at:args[10],last_seen_at:args[11]});
     return {meta:{changes:1}};
    }
    if(sql.startsWith("UPDATE lumen_funded_task_research")){const row=leads.get(args[2]);if(row)row.last_seen_at=args[0];return {meta:{changes:1}};}
    if(sql.startsWith("UPDATE lumen_funded_task_scans SET last_success")){Object.assign(scan,{last_success_at:args[0],status:"SUCCESS",examined:args[1],eligible:args[2],error:null});return {meta:{changes:1}};}
    if(sql.startsWith("UPDATE lumen_funded_task_scans SET status='FAILED'")){Object.assign(scan,{status:"FAILED",error:args[0]});return {meta:{changes:1}};}
    throw Error("Unexpected SQL: "+sql);
   }
  };
 }};
}
function provider(tasks=[good]){
 const calls=[];
 const fetchImpl=async(url,opts)=>{
  calls.push({url,method:opts?.method,redirect:opts?.redirect});
  return{ok:true,status:200,headers:{get:()=>null},text:async()=>JSON.stringify({ok:true,tasks})};
 };
 return {fetchImpl,calls};
}
test("genuine recent funded Base USDC task qualifies without claim or payout assertions",()=>{
 const r=qualifyTask(good,now);
 assert.equal(r.eligible,true);assert.equal(r.amount,7);
 assert.equal(r.sourceUrl,"https://api.basedagents.ai/v1/tasks/task_ABC12345");
 assert.equal(r.fundingLabel,"PROVIDER_REPORTED_ESCROW_FUNDED");
 assert.equal(r.claimAuthorized,false);assert.equal(r.independentChainEvidence,false);assert.equal(r.proposalSent,false);
});
test("declared-but-unfunded bounty cannot become a qualified prospect",()=>{
 for(const bad of [{escrow:null},{escrow:{status:"unfunded"}},{bounty:{...good.bounty,network:"eip155:84532"}},{bounty:{...good.bounty,amount_display:"0.10"}},{claimable:false},{status:"claimed"},{created_at:"2026-09-01T00:00:00Z"},{title:"Daily trivia job",description:"Write a daily trivia question about unrelated topics for public chat social engagement purposes."},{expires_at:"2026-10-20T00:00:00Z"}])assert.equal(qualifyTask({...good,...bad},now).eligible,false,JSON.stringify(bad));
});
test("reads public GET only, persists research leads but never proposals or claims",async()=>{
 const db=fakeDb(),api=provider();
 const r=await scanFundedTasks({DB:db},{now,fetchImpl:api.fetchImpl});
 assert.equal(r.ok,true);assert.equal(r.newResearchCandidates,1);assert.equal(r.eligible,1);
 assert.equal(db.leads.size,1);assert.equal(db.leads.get(good.task_id).status,"RESEARCH_ONLY");
 assert.equal(r.spendUsd,0);assert.equal(r.claims,0);assert.equal(r.autonomousMessages,0);
 assert.equal(api.calls.length,1);assert.equal(api.calls[0].method,"GET");assert.equal(api.calls[0].redirect,"manual");
});
test("four-hour cooldown avoids repeated provider traffic",async()=>{
 const db=fakeDb(),api=provider();
 await scanFundedTasks({DB:db},{now,fetchImpl:api.fetchImpl});
 const r=await scanFundedTasks({DB:db},{now:new Date(now.getTime()+15*60*1000),fetchImpl:api.fetchImpl});
 assert.equal(r.skipped,true);assert.equal(api.calls.length,1);
});
test("provider schema changes fail closed without changing research inventory",async()=>{
 const db=fakeDb();
 const r=await scanFundedTasks({DB:db},{now,fetchImpl:async()=>({ok:true,status:200,headers:{get:()=>null},text:async()=>JSON.stringify({data:[good]})})});
 assert.equal(r.ok,false);assert.equal(db.scan.status,"FAILED");assert.equal(db.leads.size,0);
});
test("failed provider scan can retry after one minute; no false success on redirects",async()=>{
 const db=fakeDb();
 const fail=await scanFundedTasks({DB:db},{now,fetchImpl:async()=>({ok:false,status:302,headers:{get:()=>null},text:async()=>""})});
 assert.equal(fail.ok,false);assert.equal(fail.error,"provider_http_302");
 const goodApi=provider();
 const retry=await scanFundedTasks({DB:db},{now:new Date(now.getTime()+61000),fetchImpl:goodApi.fetchImpl});
 assert.equal(retry.ok,true);
 assert.equal(retry.newResearchCandidates,1);
});
test("policy is safe public, research state and scan require admin token",async()=>{
 const env={DB:fakeDb(),OPPORTUNITY_ADMIN_TOKEN:"secret"};
 const p=await handleFundedTaskScout(new Request("https://lumen.example/commercial/paid-tasks/policy"),env);
 assert.equal(p.status,200);assert.equal((await p.json()).autonomousSpendUsd,0);
 const x=await handleFundedTaskScout(new Request("https://lumen.example/commercial/paid-tasks/state"),env);
 assert.equal(x.status,403);
 const y=await handleFundedTaskScout(new Request("https://lumen.example/commercial/paid-tasks/state",{headers:{"x-lumen-admin":"secret"}}),env);
 assert.equal(y.status,200);assert.equal((await y.json()).candidates.length,0);
});
test("missing DB refuses to operate rather than pretending a scan succeeded",async()=>{
 const r=await handleFundedTaskScout(new Request("https://lumen.example/commercial/paid-tasks/state",{headers:{"x-lumen-admin":"secret"}}),{OPPORTUNITY_ADMIN_TOKEN:"secret"});
 assert.equal(r.status,503);
});
