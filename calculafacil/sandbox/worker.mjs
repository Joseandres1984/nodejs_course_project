/**
 * Independent CalculaFácil PRO test-only Mercado Pago integration.
 * NEVER put production Mercado Pago credentials here. No production checkout,
 * no real money, no fulfillment R2 access or downloadable customer workbook.
 * Test checkout can only be issued by admin and exact pre-approved test seller.
 */
import {verifyPurchase} from "../fulfillment/worker.mjs";
const ITEM_TITLE="CalculaFácil PRO – Kit Excel (PRUEBA)";
const EXPECTED_AMOUNT=9900;
const SAFETY_HEADERS={"Cache-Control":"no-store, private","Referrer-Policy":"no-referrer","X-Content-Type-Options":"nosniff"};
function json(body,status=200){return Response.json(body,{status,headers:SAFETY_HEADERS});}
function validId(value){return /^[0-9]{6,25}$/.test(String(value??""));}
function cleanEmail(value){const s=String(value??"").trim().toLowerCase();return s.length<=254&&/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s)?s:null;}
function privateAdmin(request,env){
  const expected=env.SANDBOX_ADMIN_KEY;
  const supplied=request.headers.get("X-SANDBOX-ADMIN-KEY")||"";
  return typeof expected==="string"&&expected.length>=48&&supplied.length>=48&&supplied===expected;
}
function validTestToken(env){
  return typeof env.MP_TEST_ACCESS_TOKEN==="string"&&env.MP_TEST_ACCESS_TOKEN.trim().startsWith("APP_USR-")
    &&env.MP_TEST_ACCESS_TOKEN.length>40;
}
async function mpGetIdentity(env){
  const response=await fetch("https://api.mercadolibre.com/users/me",{
    method:"GET",
    headers:{"Authorization":"Bearer "+env.MP_TEST_ACCESS_TOKEN.trim(),"Accept":"application/json"},
    redirect:"manual",signal:AbortSignal.timeout(9000)
  });
  if(!response.ok||response.status>=300&&response.status<400)return null;
  const me=await response.json();
  // All test operations must use exactly the known Argentinian seller TEST account.
  if(!me||String(me.id)!==String(env.EXPECTED_TEST_SELLER_ID)||me.site_id!=="MLA")return null;
  return me;
}
async function createPreference(env){
  const body={
    items:[{id:"CALCULAFACIL_PRO_SANDBOX",title:ITEM_TITLE,description:"SIMULACIÓN SIN DINERO REAL",quantity:1,currency_id:"ARS",unit_price:EXPECTED_AMOUNT}],
    external_reference:"CALCULAFACIL_PRO_TEST_ONLY",
    binary_mode:true
  };
  const response=await fetch("https://api.mercadopago.com/checkout/preferences",{
    method:"POST",
    headers:{"Authorization":"Bearer "+env.MP_TEST_ACCESS_TOKEN.trim(),"Content-Type":"application/json","Accept":"application/json","X-Idempotency-Key":crypto.randomUUID()},
    body:JSON.stringify(body),redirect:"manual",signal:AbortSignal.timeout(9000)
  });
  if(response.status!==201&&response.status!==200)throw new Error("test_preference_not_created");
  const data=await response.json();
  const raw=data?.sandbox_init_point;
  if(typeof raw!=="string"||!String(data?.id||"") || String(data?.collector_id)!==String(env.EXPECTED_TEST_SELLER_ID))throw new Error("invalid_test_preference");
  const url=new URL(raw);
  if(url.protocol!=="https:"||![
    "sandbox.mercadopago.com","sandbox.mercadopago.com.ar"
  ].includes(url.hostname.toLowerCase()))throw new Error("unexpected_checkout_origin");
  return {checkout_url:url.toString(),preference_id:String(data.id)};
}
export default {
  async fetch(request,env){
    const url=new URL(request.url);
    if(url.pathname==="/health"&&request.method==="GET"){
      const enabled=env.SANDBOX_ENABLED==="true";
      return json({service:"calculafacil-pro-sandbox",mode:"test_only",
        ready:enabled&&validTestToken(env)&&!!env.SANDBOX_ADMIN_KEY,
        checkoutProductionEnabled:false,readsProductionWorkbook:false});
    }
    // Read-only identity validation with ephemeral CI-generated secret.
    // This is available with checkout OFF and cannot issue payments.
    if(url.pathname==="/__internal/verify-test-seller" && request.method==="POST"){
      const key=env.SANDBOX_AUDIT_SECRET;
      const supplied=request.headers.get("X-SANDBOX-AUDIT-KEY")||"";
      if(typeof key!=="string" || key.length<48 || supplied!==key)
        return json({error:"not_found"},404);
      if(!validTestToken(env))
        return json({ok:false,tokenPresent:!!env.MP_TEST_ACCESS_TOKEN,
          credentialFormatValid:false,sellerMatched:false,sandboxEnabled:env.SANDBOX_ENABLED==="true"},503);
      try{
        const response=await fetch("https://api.mercadolibre.com/users/me",{
          method:"GET",headers:{"Authorization":"Bearer "+env.MP_TEST_ACCESS_TOKEN.trim(),"Accept":"application/json"},
          redirect:"manual",signal:AbortSignal.timeout(9000)
        });
        if(!response.ok || response.status>=300&&response.status<400)
          return json({ok:false,tokenPresent:true,credentialFormatValid:true,
            sellerMatched:false,reason:"provider_http_"+response.status,sandboxEnabled:false},503);
        const user=await response.json();
        const matched=String(user?.id)===String(env.EXPECTED_TEST_SELLER_ID)&&user?.site_id==="MLA";
        return json({ok:matched,tokenPresent:true,credentialFormatValid:true,
          sellerMatched:matched,siteIsArgentina:user?.site_id==="MLA",
          testUserTag:Array.isArray(user?.tags)?user.tags.includes("test_user"):false,
          sandboxEnabled:env.SANDBOX_ENABLED==="true"},matched?200:409);
      }catch{
        return json({ok:false,tokenPresent:true,credentialFormatValid:true,
          sellerMatched:false,reason:"provider_unavailable",sandboxEnabled:false},503);
      }
    }
    if(!["/admin/create-preference","/admin/check-payment"].includes(url.pathname)
        ||request.method!=="POST"||!privateAdmin(request,env))return json({error:"not_found"},404);
    if(env.SANDBOX_ENABLED!=="true"||!validTestToken(env))return json({error:"sandbox_not_configured"},503);
    if(request.headers.get("Content-Length")&&Number(request.headers.get("Content-Length"))>2048)
      return json({error:"invalid_request"},400);
    if(!await mpGetIdentity(env).catch(()=>null))
      return json({error:"test_seller_identity_not_verified"},503);
    if(url.pathname==="/admin/create-preference"){
      try{
        const checkout=await createPreference(env);
        return json({ok:true,simulated:true,...checkout});
      }catch{return json({error:"sandbox_checkout_creation_failed"},503);}
    }
    try{
      const body=await request.json();
      const id=String(body?.payment_id??"").trim(),email=cleanEmail(body?.email);
      if(!validId(id)||!email)return json({error:"invalid_request"},400);
      // Reuse production validation invariants, but with isolated TEST seller token.
      const approved=await verifyPurchase({
        MP_ACCESS_TOKEN:env.MP_TEST_ACCESS_TOKEN.trim(),
        EXPECTED_MERCHANT_ID:env.EXPECTED_TEST_SELLER_ID
      },id,email);
      return json({ok:true,simulated:true,providerConfirmedApproved:approved,
        workbookDelivered:false,moneyReceived:0});
    }catch{return json({error:"sandbox_payment_not_verified"},503);}
  }
};
