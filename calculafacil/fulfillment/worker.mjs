/**
 * CalculaFácil PRO self-service digital fulfillment.
 *
 * Deliberately NOT deployed until the private workbook, MP auth and rate limiter
 * are configured. Never trust browser redirects, payment screenshots, or a paid
 * boolean supplied by the caller. Only a provider-confirmed payment qualifies.
 */
const AMOUNT_CENTS = 990000;
const FILE_KEY = "calculafacil-pro/CalculaFacil_PRO_Kit_v1.xlsx";
const PRODUCT_NAME = "CalculaFácil PRO – Kit Excel";
const DURATION_MS = 15 * 60 * 1000;
const utf8 = new TextEncoder();

function norm(s) {
  return String(s ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g,"")
    .toLowerCase().replace(/[^a-z0-9]+/g," ").trim();
}
function cents(amount) {
  if (typeof amount !== "number" || !Number.isFinite(amount)) return null;
  return Math.round(amount * 100);
}
function cleanPaymentId(value) {
  const id=String(value || "").trim();
  return /^[0-9]{6,25}$/.test(id) ? id : null;
}
function cleanEmail(value) {
  const email=String(value || "").trim().toLowerCase();
  return email.length <= 254 && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) ? email : null;
}
function htmlEscape(s) {
  return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
const NO_CACHE = {"Cache-Control":"no-store, private","X-Content-Type-Options":"nosniff","Referrer-Policy":"no-referrer"};

/** Privacy-safe error categories only: never echo remote responses, URL, token or exception text. */
function safeOutboundReason(error){
  const name=String(error?.name || "").toLowerCase();
  const message=String(error?.message || "").toLowerCase();
  if(name==="timeouterror" || name==="aborterror" || message.includes("timed out"))return "timeout";
  if(message.includes("1042"))return "cloudflare_worker_loop_1042";
  if(message.includes("1024"))return "cloudflare_ip_block_1024";
  if(message.includes("1021"))return "cloudflare_host_block_1021";
  if(message.includes("invalid") && (message.includes("header")||message.includes("character")))return "malformed_authorization_header";
  if(message.includes("redirect"))return "redirect_rejected";
  if(message.includes("dns") || message.includes("resolve"))return "dns_resolution";
  if(name==="syntaxerror")return "invalid_json";
  if(name==="typeerror")return "network_type_error";
  return "unexpected_exception";
}
async function safeNetworkCheck(url,authorization){
  try{
    const response=await fetch(url,{
      method:"GET",
      headers:authorization?{"Authorization":"Bearer "+authorization.trim(),"Accept":"application/json"}:{"Accept":"application/json"},
      redirect:"manual",signal:AbortSignal.timeout(8500)
    });
    return "http_"+response.status;
  }catch(e){return safeOutboundReason(e);}
}

/** Internal-only report: no response bodies, paths, account identifiers, or authorization material. */
async function safeAuthorizedRedirectProbe(url, env){
  try{
    const result=await fetch(url,{
      method:"GET",headers:{"Authorization":"Bearer "+String(env.MP_ACCESS_TOKEN??"").trim(),"Accept":"application/json"},
      redirect:"manual",signal:AbortSignal.timeout(8500)
    });
    let redirectDestination="none";
    if(result.status>=300 && result.status<400){
      const location=result.headers.get("Location");
      try{
        const target=new URL(location,url);
        const host=target.hostname.toLowerCase();
        redirectDestination=target.protocol!=="https:"?"non_https":
          host==="api.mercadopago.com"?"mp_api":
          host==="api.mercadolibre.com"?"ml_api":
          host.endsWith(".mercadopago.com")||host.endsWith(".mercadopago.com.ar")?"mp_site":
          host.endsWith(".mercadolibre.com")||host.endsWith(".mercadolibre.com.ar")?"ml_site":"outside_provider";
      }catch{redirectDestination="invalid_location";}
    }
    return {status:"http_"+result.status,redirectDestination};
  }catch(error){
    return {status:safeOutboundReason(error),redirectDestination:"unknown"};
  }
}

function json(body,status=200) {
  return Response.json(body,{status,headers:NO_CACHE});
}
function page(title,content,status=200) {
  const body='<!doctype html><html lang="es-AR"><head><meta charset="utf-8">'+
    '<meta name="viewport" content="width=device-width,initial-scale=1">'+
    '<title>'+htmlEscape(title)+' · CalculaFácil PRO</title>'+
    '<style>body{font-family:system-ui,sans-serif;background:#080d19;color:#eaf6ff;max-width:560px;margin:8vh auto;padding:22px;line-height:1.6}main{border:1px solid #33566a;border-radius:18px;background:#121d31;padding:28px}label{display:block;margin:18px 0}input{display:block;background:#091523;border:1px solid #55788b;border-radius:9px;color:#fff;padding:13px;width:100%;box-sizing:border-box}button,a.action{display:inline-block;background:#58e6d4;border:none;border-radius:9px;color:#06141d;font-weight:800;padding:13px 17px;text-decoration:none}p{color:#b6c9da}a{color:#70ead7}small{color:#9baec2}</style>'+
    '</head><body><main><h1>'+htmlEscape(title)+'</h1>'+content+'</main></body></html>';
  return new Response(body,{status,headers:{...NO_CACHE,"Content-Type":"text/html; charset=utf-8","Content-Security-Policy":"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"}});
}
async function mpGet(env,host,path) {
  // Workers rejects some valid authenticated responses with redirect:"error".
  // Manual mode prevents following a redirect and therefore never forwards bearer tokens.
  const response=await fetch('https://'+host+path,{headers:{"Authorization":"Bearer "+String(env.MP_ACCESS_TOKEN ?? "").trim(),"Accept":"application/json"},redirect:"manual",signal:AbortSignal.timeout(9000)});
  if(response.status>=300 && response.status<400) throw new Error("mercadopago_redirect_not_allowed");
  if(!response.ok) throw new Error("mercadopago_api_unavailable");
  return await response.json();
}
function matchItem(item) {
  const name=norm(item?.title || item?.description || "");
  return name.includes("calculafacil pro") && name.includes("kit excel") &&
    Number(item?.quantity) === 1 && String(item?.currency_id)==="ARS" &&
    cents(Number(item?.unit_price)) === AMOUNT_CENTS;
}
/** Only a matching, paid Mercado Pago merchant order qualifies; fail closed. */
export async function verifyPurchase(env,paymentId,email) {
  if(!cleanPaymentId(paymentId) || !cleanEmail(email)) return false;
  const payment=await mpGet(env,"api.mercadopago.com","/v1/payments/"+encodeURIComponent(paymentId));
  if(String(payment?.id)!==paymentId || payment?.status!=="approved" ||
     payment?.currency_id!=="ARS" || cents(payment?.transaction_amount)!==AMOUNT_CENTS ||
     cleanEmail(payment?.payer?.email)!==email || !payment?.date_approved) return false;
  const merchant=await mpGet(env,"api.mercadolibre.com","/users/me");
  if(!merchant?.id || String(payment?.collector_id)!==String(merchant.id)) return false;
  if(env.EXPECTED_MERCHANT_ID && String(merchant.id)!==String(env.EXPECTED_MERCHANT_ID)) return false;
  const orderId=String(payment?.order?.id || "");
  if(!/^[0-9]{4,25}$/.test(orderId)) return false;
  const order=await mpGet(env,"api.mercadopago.com","/merchant_orders/"+encodeURIComponent(orderId));
  if(String(order?.id)!==orderId || order?.status!=="closed" || String(order?.collector?.id)!==String(merchant.id)) return false;
  if(env.EXPECTED_PREFERENCE_ID && String(order?.preference_id)!==String(env.EXPECTED_PREFERENCE_ID)) return false;
  if(!Array.isArray(order?.items) || order.items.length!==1 || !matchItem(order.items[0])) return false;
  if(!Array.isArray(order?.payments) || !order.payments.some(x=>String(x?.id)===paymentId && x?.status==="approved")) return false;
  return true;
}
async function hmacKey(env) {
  const secret=env.DOWNLOAD_SIGNING_KEY;
  if(typeof secret!=="string" || secret.length<32) throw new Error("fulfillment_not_configured");
  return crypto.subtle.importKey("raw",utf8.encode(secret),{name:"HMAC",hash:"SHA-256"},false,["sign","verify"]);
}
function toB64Url(bytes) {
  let b="";for(const c of new Uint8Array(bytes)) b+=String.fromCharCode(c);
  return btoa(b).replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/,"");
}
function fromB64Url(value) {
  if(!/^[A-Za-z0-9_-]{32,120}$/.test(value || "")) return null;
  let b=value.replace(/-/g,"+").replace(/_/g,"/");
  b+="=".repeat((4-b.length%4)%4);
  try {return Uint8Array.from(atob(b),c=>c.charCodeAt(0));} catch {return null;}
}
async function issueToken(env,id,expiration) {
  const key=await hmacKey(env);
  return toB64Url(await crypto.subtle.sign("HMAC",key,utf8.encode(id+"|"+expiration)));
}
async function tokenValid(env,id,expiration,signature) {
  const bytes=fromB64Url(signature);
  if(!bytes) return false;
  return crypto.subtle.verify("HMAC",await hmacKey(env),bytes,utf8.encode(id+"|"+expiration));
}
function configured(env) {
  return !!(env.FULFILLMENT_ENABLED === "true" && env.MP_ACCESS_TOKEN && env.DOWNLOAD_SIGNING_KEY &&
    env.DOWNLOAD_SIGNING_KEY.length>=32 && env.PRO_KIT && env.CLAIM_LIMITER);
}
async function limitClaim(env,request) {
  if(!env.CLAIM_LIMITER?.limit) return false;
  const ip=request.headers.get("CF-Connecting-IP");
  if(!ip) return false;
  const result=await env.CLAIM_LIMITER.limit({key:ip});
  return result?.success===true;
}
export default {
  async fetch(request,env) {
    const url=new URL(request.url);
    // Privileged diagnostic; never accepts buyer data, issues payments, or exposes identities.
    if(url.pathname==="/__internal/provider-auth-check" && request.method==="POST") {
      const key=env.PROVIDER_AUDIT_SECRET;
      const supplied=request.headers.get("X-LUMEN-AUDIT-KEY")||"";
      if(typeof key!=="string" || key.length<48 || supplied!==key)
        return json({error:"not_found"},404);
      if(!env.MP_ACCESS_TOKEN)
        return json({ok:false,authenticated:false,deliveryEnabled:false,reason:"token_not_configured"},503);
      if(env.FULFILLMENT_ENABLED==="true")
        return json({ok:false,authenticated:false,deliveryEnabled:true,reason:"delivery_active"},503);
      try{
        const result=await fetch("https://api.mercadolibre.com/users/me",{
          method:"GET",
          headers:{"Authorization":"Bearer "+String(env.MP_ACCESS_TOKEN ?? "").trim(),"Accept":"application/json"},
          redirect:"manual",signal:AbortSignal.timeout(9000)
        });
        if(result.status>=300 && result.status<400)
          return json({ok:false,authenticated:false,deliveryEnabled:false,reason:"provider_redirect_not_allowed"},503);
        if(!result.ok) return json({ok:false,authenticated:false,deliveryEnabled:false,reason:"provider_http_"+result.status},503);
        const user=await result.json();
        const authenticated=!!(user && user.id);
        const siteIsArgentina=String(user?.site_id)==="MLA";
        const testUser=Array.isArray(user?.tags)&&user.tags.includes("test_user");
        const ok=authenticated && siteIsArgentina && !testUser;
        const reason=ok?"verified":!authenticated?"no_merchant_id":!siteIsArgentina?"site_not_argentina":"test_user";
        return json({ok,authenticated,siteIsArgentina,testUser,deliveryEnabled:false,reason},ok?200:503);
      }catch(error){
        let paymentsApi="not_checked";
        try{
          const paymentResponse=await fetch("https://api.mercadopago.com/v1/payments/search?limit=1",{
            method:"GET",headers:{"Authorization":"Bearer "+String(env.MP_ACCESS_TOKEN ?? "").trim(),"Accept":"application/json"},
            redirect:"manual",signal:AbortSignal.timeout(9000)
          });
          if(paymentResponse.ok){
            const paymentData=await paymentResponse.json();
            paymentsApi=Array.isArray(paymentData?.results)?"authorized":"unexpected_response";
          }else{
            paymentsApi="http_"+paymentResponse.status;
          }
        }catch{paymentsApi="network_or_parse_error";}
        const reason="identity_"+safeOutboundReason(error);
        const connectivity={
          publicWeb:await safeNetworkCheck("https://example.com/",null),
          mpNoAuth:await safeNetworkCheck("https://api.mercadopago.com/v1/payments/search?limit=1",null)
        };
        const authorizedRequests={
          identity:await safeAuthorizedRedirectProbe("https://api.mercadolibre.com/users/me",env),
          payments:await safeAuthorizedRedirectProbe("https://api.mercadopago.com/v1/payments/search?limit=1",env)
        };
        return json({ok:false,authenticated:false,deliveryEnabled:false,reason,paymentsApi,connectivity,authorizedRequests},503);
      }
    }
    if(url.pathname==="/health" && request.method==="GET") {
      const stored=env.PRO_KIT ? !!(await env.PRO_KIT.head(FILE_KEY).catch(()=>null)) : false;
      return json({ok:true,service:"calculafacil-pro-fulfillment",ready:configured(env)&&stored,privateWorkbookPresent:stored,enabled:env.FULFILLMENT_ENABLED==="true",provider:"mercadopago",paymentsMadeByServer:false,storagePrivate:true});
    }
    if(url.pathname==="/claim" && request.method==="GET") {
      return page("Descargá tu Kit PRO",
        '<p>Si ya pagaste AR$ 9.900 a LUMEN por CalculaFácil PRO, ingresá el número de operación y el correo utilizado en Mercado Pago. Solo un pago aprobado y coincidente permite descargar el archivo.</p>'+
        '<form method="post" action="/claim"><label>Correo del pago<input type="email" name="email" required maxlength="254" autocomplete="email"></label>'+
        '<label>Número de operación de Mercado Pago<input name="payment_id" inputmode="numeric" pattern="[0-9]{6,25}" required></label>'+
        '<button type="submit">Verificar y descargar</button></form><p><small>Si el pago fue en efectivo, esperá su aprobación. La verificación no realiza cargos.</small></p>');
    }
    if(url.pathname==="/claim" && request.method==="POST") {
      if(!configured(env)) return page("Entrega en preparación","<p>El sistema de entrega todavía no está habilitado. No se efectuó ningún cargo.</p>",503);
      if(!(await limitClaim(env,request))) return page("Demasiados intentos","<p>Volvé a probar en un minuto.</p>",429);
      const contentType=request.headers.get("content-type")||"";
      const contentLength=Number(request.headers.get("content-length")||"0");
      if(!contentType.startsWith("application/x-www-form-urlencoded") || contentLength>2048) return page("Solicitud inválida","<p>Usá el formulario para verificar el pago.</p>",400);
      const form=await request.formData().catch(()=>null);
      const id=cleanPaymentId(form?.get("payment_id")),email=cleanEmail(form?.get("email"));
      if(!id||!email) return page("Revisá los datos","<p>Ingresá un correo válido y el número de operación indicado en tu comprobante.</p>",400);
      if(!(await env.PRO_KIT.head(FILE_KEY).catch(()=>null))) return page("Entrega en preparación","<p>La descarga no está disponible. No se efectuó ningún cargo.</p>",503);
      let valid=false;
      try{valid=await verifyPurchase(env,id,email)}catch{return page("Verificación temporalmente no disponible","<p>Probá nuevamente más tarde. No se realizó ningún cargo nuevo.</p>",503);}
      if(!valid) return page("No pudimos confirmar el pago","<p>Comprobá que el pago esté aprobado, que el correo corresponda al comprobante y que el concepto sea CalculaFácil PRO por AR$ 9.900.</p>",422);
      const until=Date.now()+DURATION_MS;
      const sig=await issueToken(env,id,until);
      const link="/download?payment_id="+encodeURIComponent(id)+"&until="+until+"&sig="+encodeURIComponent(sig);
      return page("Pago confirmado","<p>Mercado Pago confirmó tu compra. El enlace estará disponible durante 15 minutos.</p><p><a class=\"action\" href=\""+htmlEscape(link)+"\">Descargar Excel PRO</a></p>");
    }
    if(url.pathname==="/download" && request.method==="GET") {
      if(env.FULFILLMENT_ENABLED!=="true" || !env.PRO_KIT || !env.DOWNLOAD_SIGNING_KEY) return json({error:"delivery_not_configured"},503);
      const id=cleanPaymentId(url.searchParams.get("payment_id"));
      const rawUntil=url.searchParams.get("until")||"";
      const until=Number(rawUntil),sig=url.searchParams.get("sig")||"";
      if(!id || !/^[0-9]{13}$/.test(rawUntil) || !Number.isSafeInteger(until) ||
         until<Date.now() || until>Date.now()+DURATION_MS || !(await tokenValid(env,id,until,sig))) {
        return json({error:"invalid_or_expired_download_link"},403);
      }
      const obj=await env.PRO_KIT.get(FILE_KEY);
      if(!obj) return json({error:"file_unavailable"},503);
      return new Response(obj.body,{status:200,headers:{
        ...NO_CACHE,"Content-Type":"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "Content-Disposition":'attachment; filename="CalculaFacil_PRO_Kit_v1.xlsx"',
        "Content-Security-Policy":"default-src 'none'; frame-ancestors 'none'"
      }});
    }
    return json({error:"not_found"},404);
  }
};
