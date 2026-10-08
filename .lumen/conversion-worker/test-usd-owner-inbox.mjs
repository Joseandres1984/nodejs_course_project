import assert from "node:assert/strict";
import worker from "./worker.js";

const leadId="CL-0123456789ABCDEF0123";
const stored={
  lead_id:leadId,created_at:"2026-10-08T16:00:00.000Z",requested_at:"2026-10-08T16:00:01.000Z",
  email:"purchaser@example.org",company:"Sample Buyer",details:"Quotation for 100 units",product_id:"MP-SOURCING-5",product_slug:"sourcing-5"
};
const acknowledgements=new Set();
const statements=[];
const env={OPPORTUNITY_ADMIN_TOKEN:"demo-secure-token",DB:{
  async batch(rows){return rows.map(()=>({success:true}));},
  prepare(sql){const entry={sql,args:[]};return {
    bind(...values){entry.args=values;return this;},
    async first(){if(sql.includes("FROM lumen_conversion_events e")&&sql.includes("LEFT JOIN lumen_sales_inbox_alerts"))return acknowledgements.has(leadId)?null:stored;return null;},
    async all(){return {results:[]};},
    async run(){statements.push(entry);if(sql.includes("INSERT OR IGNORE INTO lumen_sales_inbox_alerts")){if(entry.args[0]===leadId&&!acknowledgements.has(leadId)){acknowledgements.add(leadId);return {meta:{changes:1}};}return {meta:{changes:0}};}return {meta:{changes:1}};}
  };}
}};
const origin="https://lumen-zero-conversion.lumen-b2b.workers.dev";
const get=(path,token)=>worker.fetch(new Request(origin+path,{headers:token?{"x-lumen-admin":token}:{}}),env);
const unprotected=await get("/sales/pending-usd");
assert.equal(unprotected.status,403);
assert.equal((await unprotected.json()).lead,undefined);
const bad=await get("/sales/pending-usd","wrong-token");
assert.equal(bad.status,403);
const ok=await get("/sales/pending-usd","demo-secure-token");
assert.equal(ok.status,200);
assert.equal(ok.headers.get("cache-control"),"no-store");
const body=await ok.json();
assert.equal(body.pending,true);
assert.equal(body.lead.email,"purchaser@example.org");
assert.equal(body.chargeCreated,false);
const ack=async (id,token="demo-secure-token")=>worker.fetch(new Request(origin+"/sales/ack-usd-alert",{
  method:"POST",headers:{"content-type":"application/json","x-lumen-admin":token},body:JSON.stringify({lead_id:id})
}),env);
assert.equal((await ack(leadId,"wrong-token")).status,403);
assert.equal((await ack("unsafe-id")).status,400);
const first=await ack(leadId);assert.equal(first.status,200);assert.equal((await first.json()).acknowledged,true);
assert.equal((await (await get("/sales/pending-usd","demo-secure-token")).json()).pending,false);
const second=await ack(leadId);assert.equal((await second.json()).acknowledged,false);
assert.equal(statements.filter(x=>x.sql.includes("INSERT OR IGNORE INTO lumen_sales_inbox_alerts")).length,2);
assert.equal(statements.some(x=>/charge|settled|payment_receipts/i.test(x.sql)),false);
console.log("LUMEN_PRIVATE_USD_SALES_INBOX_TEST_OK");
