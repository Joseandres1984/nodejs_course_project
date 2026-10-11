import test from "node:test";
import assert from "node:assert/strict";
import worker from "./worker.mjs";

const KEY="private-test-admin-key-48-characters-minimum-xxxxxxxxxxxx";
const TOKEN="APP_USR-FAKE_TEST_CREDENTIAL_LONG_AND_NOT_REAL_xxxxxx";
const root="https://calculafacil-pro-sandbox.example";
function env(p={}){return {SANDBOX_ENABLED:"true",MP_TEST_ACCESS_TOKEN:TOKEN,
  SANDBOX_ADMIN_KEY:KEY,EXPECTED_TEST_SELLER_ID:"3566088094",...p};}
function request(path,admin=true,payload){
  return new Request(root+path,{method:"POST",
    headers:{"Content-Type":"application/json",...(admin?{"X-SANDBOX-ADMIN-KEY":KEY}:{})},
    body:payload?JSON.stringify(payload):undefined});
}
function mockNetwork(opts={}){
  const old=globalThis.fetch;
  const seen=[];
  globalThis.fetch=async(url,init)=>{
    const u=new URL(url);seen.push({url:u.toString(),method:init?.method,body:init?.body,header:init?.headers?.Authorization});
    if(u.pathname==="/users/me")
      return Response.json({id:opts.sellerId||3566088094,site_id:"MLA"});
    if(u.pathname==="/checkout/preferences"){
      if(opts.fail) return Response.json({error:"blocked"},{status:403});
      return Response.json({id:"TEST_PREFERENCE_123",collector_id:3566088094,
        sandbox_init_point:"https://sandbox.mercadopago.com.ar/checkout/v1/redirect?pref_id=TEST_PREFERENCE_123"},{status:201});
    }
    const payment={id:12345678,status:opts.paymentStatus||"approved",currency_id:"ARS",
      transaction_amount:9900,payer:{email:"buyer-test@example.com"},collector_id:3566088094,
      date_approved:"2026-10-11T12:00:00.000Z",order:{id:123456789}};
    const order={id:123456789,status:"closed",collector:{id:3566088094},preference_id:"TEST_PREFERENCE_123",
      items:[{title:"CalculaFácil PRO – Kit Excel (PRUEBA)",currency_id:"ARS",quantity:1,unit_price:9900}],
      payments:[{id:12345678,status:opts.paymentStatus||"approved"}]};
    if(u.pathname==="/v1/payments/12345678")return Response.json(payment);
    if(u.pathname==="/merchant_orders/123456789")return Response.json(order);
    return Response.json({error:"not_found"},{status:404});
  };
  return {seen,restore:()=>globalThis.fetch=old};
}
test("Sandbox health does not reveal test token, identity, private R2, or production checkout",async()=>{
  const r=await worker.fetch(new Request(root+"/health"),env({SANDBOX_ENABLED:"false"}));
  assert.equal(r.status,200); const j=await r.json();
  assert.equal(j.ready,false);assert.equal(j.mode,"test_only");
  assert.equal(j.checkoutProductionEnabled,false);assert.equal(j.readsProductionWorkbook,false);
  assert.ok(!JSON.stringify(j).includes(TOKEN));
});
test("No admin credentials or disabled sandbox cannot create preference",async()=>{
  const f=mockNetwork();
  try{
    assert.equal((await worker.fetch(request("/admin/create-preference",false),env())).status,404);
    assert.equal((await worker.fetch(request("/admin/create-preference"),env({SANDBOX_ENABLED:"false"}))).status,503);
    assert.equal((await worker.fetch(request("/admin/create-preference"),env({MP_TEST_ACCESS_TOKEN:""}))).status,503);
    assert.equal(f.seen.length,0);
  }finally{f.restore();}
});
test("Seller ID mismatch blocks preference creation even with a test token",async()=>{
  const f=mockNetwork({sellerId:999999999});
  try{
    const r=await worker.fetch(request("/admin/create-preference"),env());
    assert.equal(r.status,503);assert.equal(f.seen.length,1);
    assert.equal(f.seen[0].method,"GET");
  }finally{f.restore();}
});
test("Authorized sandbox creates only TEST preference with no real payment or R2 access",async()=>{
  const f=mockNetwork();
  try{
    const r=await worker.fetch(request("/admin/create-preference"),env());
    assert.equal(r.status,200);const j=await r.json();
    assert.equal(j.ok,true);assert.equal(j.simulated,true);
    assert.match(j.checkout_url,/^https:\/\/sandbox\.mercadopago\.com\.ar\//);
    const post=f.seen.find(x=>x.method==="POST");
    assert.ok(post);const body=JSON.parse(post.body);
    assert.equal(body.items[0].unit_price,9900);assert.equal(body.items[0].currency_id,"ARS");
    assert.match(body.items[0].title,/PRUEBA/);
    assert.equal(body.external_reference,"CALCULAFACIL_PRO_TEST_ONLY");
    assert.equal(f.seen.length,2);
    assert.ok(!JSON.stringify(j).includes(TOKEN));
  }finally{f.restore();}
});
test("Payment confirmation uses test token but never delivers paid workbook or claims revenue",async()=>{
  const f=mockNetwork();
  try{
    const r=await worker.fetch(request("/admin/check-payment",true,{payment_id:"12345678",email:"buyer-test@example.com"}),env());
    assert.equal(r.status,200);const j=await r.json();
    assert.deepEqual({approved:j.providerConfirmedApproved,delivered:j.workbookDelivered,revenue:j.moneyReceived},
      {approved:true,delivered:false,revenue:0});
    assert.ok(f.seen.every(x=>x.header==="Bearer "+TOKEN));
  }finally{f.restore();}
});
test("Rejected test payment is not verified",async()=>{
  const f=mockNetwork({paymentStatus:"rejected"});
  try{
    const r=await worker.fetch(request("/admin/check-payment",true,{payment_id:"12345678",email:"buyer-test@example.com"}),env());
    assert.equal(r.status,200);assert.equal((await r.json()).providerConfirmedApproved,false);
  }finally{f.restore();}
});

test("Private identity probe denies all non-privileged requests with sandbox disabled",async()=>{
  const f=mockNetwork();
  try{
    const disabled=env({SANDBOX_ENABLED:"false",SANDBOX_AUDIT_SECRET:"very-long-random-test-audit-secret-48-characters-xxxxxxxxxxxx"});
    const unauth=await worker.fetch(request("/__internal/verify-test-seller"),disabled);
    assert.equal(unauth.status,404);
    assert.equal(f.seen.length,0);
  }finally{f.restore();}
});
test("Private identity probe accepts matching test seller without enabling checkout",async()=>{
  const f=mockNetwork();
  try{
    const disabled=env({SANDBOX_ENABLED:"false",SANDBOX_AUDIT_SECRET:"very-long-random-test-audit-secret-48-characters-xxxxxxxxxxxx"});
    const requestObj=new Request(root+"/__internal/verify-test-seller",{method:"POST",headers:{"X-SANDBOX-AUDIT-KEY":disabled.SANDBOX_AUDIT_SECRET}});
    const r=await worker.fetch(requestObj,disabled);
    assert.equal(r.status,200);
    const j=await r.json();
    assert.equal(j.ok,true);assert.equal(j.sellerMatched,true);assert.equal(j.siteIsArgentina,true);
    assert.equal(j.sandboxEnabled,false);assert.equal(f.seen.length,1);assert.equal(f.seen[0].method,"GET");
    assert.ok(!JSON.stringify(j).includes(TOKEN));
  }finally{f.restore();}
});
test("Private identity probe refuses an unrelated test seller",async()=>{
  const f=mockNetwork({sellerId:999999999});
  try{
    const disabled=env({SANDBOX_ENABLED:"false",SANDBOX_AUDIT_SECRET:"very-long-random-test-audit-secret-48-characters-xxxxxxxxxxxx"});
    const requestObj=new Request(root+"/__internal/verify-test-seller",{method:"POST",headers:{"X-SANDBOX-AUDIT-KEY":disabled.SANDBOX_AUDIT_SECRET}});
    const r=await worker.fetch(requestObj,disabled);
    assert.equal(r.status,409);assert.equal((await r.json()).sellerMatched,false);
    assert.equal(f.seen.length,1);
  }finally{f.restore();}
});
