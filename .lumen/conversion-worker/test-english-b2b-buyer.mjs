import assert from "node:assert/strict";
import worker from "./worker.js";

const saved=[];
const env={DB:{
  async batch(qs){return qs.map(()=>({success:true}));},
  prepare(sql){const q={sql,args:[]};return {
    bind(...args){q.args=args;return this;},
    async run(){saved.push(q);return {success:true,meta:{changes:1}};},
    async all(){return {results:[]};},
    async first(){return null;}
  }}
}};
const root="https://lumen-zero-conversion.lumen-b2b.workers.dev";
const cat=await worker.fetch(new Request(root+"/en?src=international"),env);
assert.equal(cat.status,200);
let page=await cat.text();
assert.match(page,/<html lang="en">/);
assert.match(page,/Find better suppliers\. Check quotes/);
assert.match(page,/href="\/en\/offer\/sourcing-5\?/);
assert.match(page,/USD 15/);
assert.match(page,/USD 25/);
assert.match(page,/No charges from submitting a request/);
const offer=await worker.fetch(new Request(root+"/en/offer/sourcing-5?src=international&campaign=buyer-pilot"),env);
assert.equal(offer.status,200);
page=await offer.text();
assert.match(page,/B2B RESEARCH · FIXED SCOPE/);
assert.match(page,/USD 15 \/ report/);
assert.match(page,/Request USD payment details \(no charge\)/);
assert.match(page,/name="next" value="invoice_usd"/);
assert.match(page,/\/intent\/sourcing-5\?src=international&amp;/);
assert.match(page,/lang=en/);
assert.match(page,/What you receive/);
assert.match(page,/Up to five supplier candidates/);
const old=await worker.fetch(new Request(root+"/offer/sourcing-5"),env);
assert.equal(old.status,200);
assert.match(await old.text(),/Solicitar pago en USD \(sin compromiso\)/);
const email="legitimate-buyer@example.org";
const request=await worker.fetch(new Request(root+"/intent/sourcing-5?src=international&campaign=buyer-pilot&lang=en",{
  method:"POST",
  body:new URLSearchParams({email,company:"Example Manufacturing",details:"Industrial gasket part number AB123, quantity 500, delivery Hamburg Germany",next:"invoice_usd"})
}),env);
assert.equal(request.status,200);
page=await request.text();
assert.match(page,/<html lang="en">/);
assert.match(page,/Request received/);
assert.match(page,/No payment has been made/);
const dbInquiry=saved.find(e=>e.sql.includes("INSERT OR IGNORE INTO lumen_public_inquiries"));
assert.equal(dbInquiry.args[3],email);
assert.match(dbInquiry.args[6],/El comprador solicita instrucciones de pago en USD/);
const ev=saved.filter(e=>e.sql.includes("INSERT INTO lumen_conversion_events")&&e.args[2]==="usd_payment_request");
assert.equal(ev.length,1);
assert.equal(ev[0].args[6],"international");
assert.equal(JSON.parse(ev[0].args[12]).charged,false);
assert.equal(JSON.parse(ev[0].args[12]).invoiceCreated,false);
assert.ok(!saved.some(e=>/lumen_x402_receipts|payment_receipts/i.test(e.sql)));
const oldHealth=await worker.fetch(new Request(root+"/health"),env);
assert.equal((await oldHealth.json()).version,"1.4-international-buyer-sales");
console.log("ENGLISH_B2B_CATALOG_TO_INQUIRY_SUCCESS");
console.log("English prospect captured in CRM with USD manual request; no charge, x402 existing paths preserved, Spanish still works");
