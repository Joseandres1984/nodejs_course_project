import assert from "node:assert/strict";
import worker from "./worker.js";

const writes=[];
const env={DB:{
  async batch(statements){return statements.map(()=>({success:true}));},
  prepare(sql){const record={sql,params:[]};return{
    bind(...values){record.params=values;return this;},
    async run(){writes.push(record);return {meta:{changes:1}};},
    async all(){return {results:[]};},
    async first(){return null;}
  }}
}};
const root="https://lumen-zero-conversion.lumen-b2b.workers.dev";
for (const [path,lang,expected] of [
  ["/en/industrial-rfq","en","Industrial Supplier Quote Review"],
  ["/industrial-rfq","es","Revisión de cotizaciones industriales"]
]) {
  const response=await worker.fetch(new Request(root+path),env);
  assert.equal(response.status,200);
  const html=await response.text();
  assert.match(html,new RegExp('<html lang="'+lang+'">'));
  assert.ok(html.includes(expected));
  assert.ok(html.includes("AISI 316"));
  assert.ok(html.includes("AISI 304"));
  assert.match(html,/USD 7/);
  assert.match(html,/name="next" value="invoice_usd"/);
  assert.match(html,/name="next" value="checkout"/);
  assert.match(html,/name="next" value="consult"/);
  assert.match(html,/action="\/intent\/quote-sanity\?/);
  assert.match(html,/src=direct/);
  assert.match(html,/campaign=industrial-first-cash-pilot/);
  assert.match(html,/type="email"/);
}
const response=await worker.fetch(new Request(root+"/intent/quote-sanity?lang=en&src=industrial-quote-audit&campaign=industrial-first-cash-pilot",{
  method:"POST",
  body:new URLSearchParams({
    email:"purchaser@example.org",
    company:"Test Industrial Co",
    details:"Valve model A-109 PN16 qty 8 at USD 470/unit, delivery Argentina, lead time missing.",
    next:"invoice_usd"
  })
}),env);
assert.equal(response.status,200);
const page=await response.text();
assert.match(page,/Request received/);
assert.match(page,/No payment has been made/);
const lead=writes.find(x=>x.sql.includes("INSERT INTO lumen_conversion_leads"));
assert.ok(lead,"lead persisted");
assert.equal(lead.params[4],"quote-sanity");
assert.equal(lead.params[5],"purchaser@example.org");
assert.equal(lead.params[8],"industrial-quote-audit");
const inquiry=writes.find(x=>x.sql.includes("INSERT OR IGNORE INTO lumen_public_inquiries"));
assert.ok(inquiry,"inquiry bridged to canonical CRM");
const paymentReq=writes.find(x=>x.sql.includes("INSERT INTO lumen_conversion_events")&&x.params[2]==="usd_payment_request");
assert.ok(paymentReq,"payment preference recorded");
assert.equal(JSON.parse(paymentReq.params[12]).charged,false);
assert.equal(JSON.parse(paymentReq.params[12]).invoiceCreated,false);
assert.ok(!writes.some(x=>/INSERT.*(receipt|payment_settled)/i.test(x.sql)));
console.log("INDUSTRIAL_RFQ_FIRST_CASH_LANDING_OK");
