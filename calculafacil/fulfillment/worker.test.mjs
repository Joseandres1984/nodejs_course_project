import test from "node:test";
import assert from "node:assert/strict";
import worker,{verifyPurchase} from "./worker.mjs";

const paymentId="12345678";
const email="buyer@example.com";
const merchantId=44112233;
const payment={
  id:Number(paymentId),status:"approved",currency_id:"ARS",transaction_amount:9900,
  payer:{email},collector_id:merchantId,date_approved:"2026-10-11T12:00:00.000Z",
  order:{id:98765432}
};
const order={
  id:98765432,status:"closed",collector:{id:merchantId},preference_id:"PREFERENCE-PRO-UNIQUE",
  items:[{title:"CalculaFácil PRO – Kit Excel",currency_id:"ARS",quantity:1,unit_price:9900}],
  payments:[{id:Number(paymentId),status:"approved"}]
};
function installMockFetch(overrides={}){
  const old=globalThis.fetch;
  globalThis.fetch=async(url,opts)=>{
    assert.match(opts.headers.Authorization,/^Bearer /);
    const path=new URL(url).pathname;
    const body=path.endsWith("/v1/payments/"+paymentId) ? {...payment,...overrides.payment}
      : path.endsWith("/merchant_orders/98765432") ? {...order,...overrides.order}
      : path==="/users/me" ? {id:merchantId,...overrides.merchant}
      : null;
    return new Response(JSON.stringify(body),{status:body?200:404,headers:{"Content-Type":"application/json"}});
  };
  return ()=>globalThis.fetch=old;
}
function makeEnv(overrides={}){
  const file=new Uint8Array([80,75,3,4,0,0]); // non-sensitive mock XLSX bytes
  return {
    FULFILLMENT_ENABLED:"true",
    MP_ACCESS_TOKEN:"TEST_ONLY_NOT_REAL",
    DOWNLOAD_SIGNING_KEY:"test-key-32bytes-test-key-32bytes-test-key",
    PRO_KIT:{
      head:async()=>({size:file.length}),
      get:async()=>({body:new ReadableStream({start(c){c.enqueue(file);c.close();}})})
    },
    CLAIM_LIMITER:{limit:async()=>({success:true})},
    ...overrides
  };
}
async function runClaim(env,form={email,payment_id:paymentId}){
  const request=new Request("https://fulfillment.example/claim",{
    method:"POST",headers:{"CF-Connecting-IP":"192.0.2.1","Content-Type":"application/x-www-form-urlencoded"},
    body:new URLSearchParams(form)
  });
  return worker.fetch(request,env);
}
test("API: accepts only an approved matching payment with owner, order and email",async()=>{
  const restore=installMockFetch();
  try{assert.equal(await verifyPurchase(makeEnv(),paymentId,email),true);}
  finally{restore();}
});
test("API: rejects unpaid and refunded payments",async()=>{
  for(const status of ["pending","rejected","cancelled","refunded","in_process"]){
    const restore=installMockFetch({payment:{status}});
    try{assert.equal(await verifyPurchase(makeEnv(),paymentId,email),false);}
    finally{restore();}
  }
});
test("API: rejects wrong price, wrong currency or missing approval",async()=>{
  for(const patch of [{transaction_amount:9800},{currency_id:"USD"},{date_approved:null}]){
    const restore=installMockFetch({payment:patch});
    try{assert.equal(await verifyPurchase(makeEnv(),paymentId,email),false);}
    finally{restore();}
  }
});
test("API: rejects different merchant regardless of valid amount",async()=>{
  for(const patch of [{collector_id:9999999},{payer:{email:"another@example.com"}}]){
    const restore=installMockFetch({payment:patch});
    try{assert.equal(await verifyPurchase(makeEnv(),paymentId,email),false);}
    finally{restore();}
  }
});
test("API: requires authenticated seller identity and optional preference match",async()=>{
  const restore=installMockFetch();
  try{assert.equal(await verifyPurchase(makeEnv({EXPECTED_PREFERENCE_ID:"OTHER"}),paymentId,email),false);}
  finally{restore();}
  const restore2=installMockFetch({merchant:{id:9933}});
  try{assert.equal(await verifyPurchase(makeEnv(),paymentId,email),false);}
  finally{restore2();}
});
test("API: rejects other products and other order payment references",async()=>{
  for(const patch of [
    {items:[{title:"Bolso",currency_id:"ARS",quantity:1,unit_price:9900}]},
    {items:[{title:"CalculaFácil PRO – Kit Excel",currency_id:"ARS",quantity:2,unit_price:9900}]},
    {payments:[{id:888888,status:"approved"}]},
    {payments:[{id:Number(paymentId),status:"pending"}]},
    {status:"opened"},
    {items:[{title:"CalculaFácil PRO – Kit Excel",quantity:1,unit_price:9900}]}
  ]){
    const restore=installMockFetch({order:patch});
    try{assert.equal(await verifyPurchase(makeEnv(),paymentId,email),false);}
    finally{restore();}
  }
});
test("API: input validation and no enabled checkout without storage/secrets",async()=>{
  const r=await runClaim(makeEnv({DOWNLOAD_SIGNING_KEY:""}));
  assert.equal(r.status,503);
  assert.match(await r.text(),/Entrega en preparación/);
  const restore=installMockFetch();
  try{
    const bad=await runClaim(makeEnv(),{email:"invalid",payment_id:paymentId});
    assert.equal(bad.status,400);
    const missing=await runClaim(makeEnv({PRO_KIT:{head:async()=>null}}));
    assert.equal(missing.status,503);
  }finally{restore();}
});
test("API: claims require rate limit, and no payment is initiated",async()=>{
  const r=await runClaim(makeEnv({CLAIM_LIMITER:{limit:async()=>({success:false})}}));
  assert.equal(r.status,429);
});
test("API: fulfilled buyer receives short lived, tamper-proof private download",async()=>{
  const restore=installMockFetch();
  try {
    const env=makeEnv();
    const result=await runClaim(env);
    assert.equal(result.status,200);
    const html=await result.text();
    assert.match(html,/Pago confirmado/);
    const href=html.match(/href="(\/download\?[^"]+)"/)?.[1]?.replaceAll("&amp;","&");
    assert.ok(href);
    const download=await worker.fetch(new Request("https://fulfillment.example"+href),env);
    assert.equal(download.status,200);
    assert.equal(download.headers.get("Cache-Control"),"no-store, private");
    assert.match(download.headers.get("Content-Disposition"),/attachment/);
    assert.deepEqual(new Uint8Array(await download.arrayBuffer()),new Uint8Array([80,75,3,4,0,0]));
    const tampered=new URL("https://fulfillment.example"+href);
    tampered.searchParams.set("payment_id","88888888");
    assert.equal((await worker.fetch(new Request(tampered),env)).status,403);
    const expired=new URL("https://fulfillment.example"+href);
    expired.searchParams.set("until",String(Date.now()-5000));
    assert.equal((await worker.fetch(new Request(expired),env)).status,403);
  } finally{restore();}
});
test("API: payment lookup errors do not disclose secrets or create payments",async()=>{
  const old=globalThis.fetch;
  globalThis.fetch=async()=>new Response("blocked",{status:403});
  try {
    const r=await runClaim(makeEnv());
    assert.equal(r.status,503);
    const body=await r.text();
    assert.ok(!body.includes("TEST_ONLY_NOT_REAL"));
  } finally {globalThis.fetch=old;}
});
test("Public: no purchase when only a screenshot, redirect or unsigned token exists",async()=>{
  const env=makeEnv();
  const r=await worker.fetch(new Request("https://fulfillment.example/download?payment_id=12345678&until=9999999999999&sig=fake"),env);
  assert.equal(r.status,403);
  const h=await worker.fetch(new Request("https://fulfillment.example/health"),makeEnv({PRO_KIT:{head:async()=>null}}));
  assert.equal((await h.json()).ready,false);
});

test("Provider audit route is inaccessible without its independent ephemeral key",async()=>{
  const env=makeEnv({FULFILLMENT_ENABLED:"false",PROVIDER_AUDIT_SECRET:"test-temporary-private-probe-key-min-48-chars-xxxxxxxx"});
  for(const headers of [{},{"X-LUMEN-AUDIT-KEY":"wrong"}]){
    const r=await worker.fetch(new Request("https://fulfillment.example/__internal/provider-auth-check",{method:"POST",headers}),env);
    assert.equal(r.status,404);
  }
});
test("Provider audit verifies a live merchant identity by read-only GET (mocked)",async()=>{
  const env=makeEnv({FULFILLMENT_ENABLED:"false",PROVIDER_AUDIT_SECRET:"test-temporary-private-probe-key-min-48-chars-xxxxxxxx"});
  const restore=installMockFetch({merchant:{site_id:"MLA",tags:[]}});
  try{
    const r=await worker.fetch(new Request("https://fulfillment.example/__internal/provider-auth-check",{method:"POST",headers:{"X-LUMEN-AUDIT-KEY":env.PROVIDER_AUDIT_SECRET}}),env);
    assert.equal(r.status,200);
    const j=await r.json();
    assert.equal(j.authenticated,true);assert.equal(j.siteIsArgentina,true);assert.equal(j.deliveryEnabled,false);
    assert.equal(j.ok,true);assert.ok(!Object.hasOwn(j,"id"));
  }finally{restore();}
});
test("Provider audit rejects test-user credentials and delivery already enabled",async()=>{
  const env=makeEnv({FULFILLMENT_ENABLED:"false",PROVIDER_AUDIT_SECRET:"test-temporary-private-probe-key-min-48-chars-xxxxxxxx"});
  const restore=installMockFetch({merchant:{site_id:"MLA",tags:["test_user"]}});
  try{
    const r=await worker.fetch(new Request("https://fulfillment.example/__internal/provider-auth-check",{method:"POST",headers:{"X-LUMEN-AUDIT-KEY":env.PROVIDER_AUDIT_SECRET}}),env);
    assert.equal(r.status,503);
    assert.equal((await r.json()).testUser,true);
  }finally{restore();}
  const enabled=makeEnv({PROVIDER_AUDIT_SECRET:env.PROVIDER_AUDIT_SECRET,FULFILLMENT_ENABLED:"true"});
  const r=await worker.fetch(new Request("https://fulfillment.example/__internal/provider-auth-check",{method:"POST",headers:{"X-LUMEN-AUDIT-KEY":enabled.PROVIDER_AUDIT_SECRET}}),enabled);
  assert.equal(r.status,503);
});

test("Signed delivery is disabled even if the R2 file and signing key exist",async()=>{
  const disabled=makeEnv({FULFILLMENT_ENABLED:"false"});
  const r=await worker.fetch(new Request("https://fulfillment.example/download?payment_id=12345678&until=9999999999999&sig=random"),disabled);
  assert.equal(r.status,503);
  assert.equal((await r.json()).error,"delivery_not_configured");
});

test("Provider redirects cannot be followed with merchant credentials",async()=>{
  const original=globalThis.fetch;
  let calls=0;
  globalThis.fetch=async(_url,options)=>{
    calls++;
    assert.equal(options.redirect,"manual");
    return new Response(null,{status:302,headers:{"Location":"https://attacker.example/steal"}});
  };
  try{
    await assert.rejects(()=>verifyPurchase(makeEnv(),paymentId,email),/mercadopago_redirect_not_allowed/);
    assert.equal(calls,1,"Never follow provider redirects or send credentials to another host");
  }finally{globalThis.fetch=original;}
});

test("Private Excel integrity probe returns 404 without an ephemeral audit key",async()=>{
  const env=makeEnv({FULFILLMENT_ENABLED:"false",KIT_AUDIT_SECRET:"a".repeat(80)});
  const r=await worker.fetch(new Request("https://fulfillment.example/__internal/check-private-kit",{method:"POST"}),env);
  assert.equal(r.status,404);
});
test("Private Excel integrity probe validates actual R2 object bytes without returning workbook",async()=>{
  const names=Array.from({length:7},(_,i)=>"xl/worksheets/sheet"+(i+1)+".xml").join("\n");
  const bytes=new Uint8Array(12000);
  bytes.set([0x50,0x4b,0x03,0x04],0);
  bytes.set(new TextEncoder().encode(names),10);
  const env=makeEnv({FULFILLMENT_ENABLED:"false",KIT_AUDIT_SECRET:"a".repeat(80),
    PRO_KIT:{get:async()=>({body:new ReadableStream({start(c){c.enqueue(bytes);c.close();}})})}
  });
  const r=await worker.fetch(new Request("https://fulfillment.example/__internal/check-private-kit",{
    method:"POST",headers:{"X-LUMEN-KIT-AUDIT-KEY":env.KIT_AUDIT_SECRET}
  }),env);
  assert.equal(r.status,200);
  const j=await r.json();
  assert.equal(j.ok,true);assert.equal(j.privateWorkbookReadable,true);
  assert.equal(j.validXlsxZip,true);assert.equal(j.worksheetsFound,7);
  assert.equal(j.privateBytesRead,12000);assert.equal(j.workbookContentExposed,false);
  assert.equal(j.productionDownloadsEnabled,false);
});
test("Private Excel integrity probe is blocked after commercial launch",async()=>{
  const env=makeEnv({FULFILLMENT_ENABLED:"true",KIT_AUDIT_SECRET:"a".repeat(80)});
  const r=await worker.fetch(new Request("https://fulfillment.example/__internal/check-private-kit",{
    method:"POST",headers:{"X-LUMEN-KIT-AUDIT-KEY":env.KIT_AUDIT_SECRET}
  }),env);
  assert.equal(r.status,503);
  assert.equal((await r.json()).error,"audit_disabled_in_live_mode");
});

test("Private XLSX transport denies missing or wrong temporary audit credential",async()=>{
  const env=makeEnv({FULFILLMENT_ENABLED:"false",KIT_AUDIT_SECRET:"X".repeat(80)});
  for(const headers of [{},{"X-LUMEN-KIT-AUDIT-KEY":"not-authorized"}]){
    const r=await worker.fetch(new Request("https://fulfillment.example/__internal/transport-test-download",{
      method:"POST",headers
    }),env);
    assert.equal(r.status,404);
  }
});
test("Private XLSX transport streams binary attachment only with isolated temporary audit secret",async()=>{
  const original=Uint8Array.from([0x50,0x4b,0x03,0x04,11,12,13,14,15,16,17]);
  const env=makeEnv({FULFILLMENT_ENABLED:"false",KIT_AUDIT_SECRET:"X".repeat(80),
    PRO_KIT:{get:async()=>({size:original.byteLength,body:new ReadableStream({start(controller){
      controller.enqueue(original);controller.close();
    }})})}
  });
  const r=await worker.fetch(new Request("https://fulfillment.example/__internal/transport-test-download",{
    method:"POST",headers:{"X-LUMEN-KIT-AUDIT-KEY":env.KIT_AUDIT_SECRET}
  }),env);
  assert.equal(r.status,200);
  assert.equal(r.headers.get("Cache-Control"),"no-store, private");
  assert.match(r.headers.get("Content-Disposition"),/attachment; filename="CalculaFacil_PRO_Kit_v1.xlsx"/);
  assert.equal(r.headers.get("Content-Type"),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
  assert.deepEqual(new Uint8Array(await r.arrayBuffer()),original);
});
test("Private XLSX transport cannot be used with commercial delivery enabled",async()=>{
  const env=makeEnv({FULFILLMENT_ENABLED:"true",KIT_AUDIT_SECRET:"X".repeat(80)});
  const r=await worker.fetch(new Request("https://fulfillment.example/__internal/transport-test-download",{
    method:"POST",headers:{"X-LUMEN-KIT-AUDIT-KEY":env.KIT_AUDIT_SECRET}
  }),env);
  assert.equal(r.status,503);
});
