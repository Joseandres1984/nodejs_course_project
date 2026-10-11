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
  const response=await fetch('https://'+host+path,{headers:{"Authorization":"Bearer "+env.MP_ACCESS_TOKEN,"Accept":"application/json"},redirect:"error",signal:AbortSignal.timeout(9000)});
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
      if(!env.PRO_KIT || !env.DOWNLOAD_SIGNING_KEY) return json({error:"delivery_not_configured"},503);
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
