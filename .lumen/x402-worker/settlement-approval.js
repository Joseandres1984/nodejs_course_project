// Human authorization is deliberately separate from the operational admin token.
// Missing X402_HUMAN_APPROVAL_TOKEN NEVER permits a settlement.
export const APPROVAL_POLICY = Object.freeze({
  version:"1.0-human-gated-x402",
  humanApprovalRequired:true,
  defaultDeny:true,
  oneTime:true,
  automaticApproval:false,
  approvalScope:"one_exact_route_amount_network_recipient",
  ownerCredential:"X402_HUMAN_APPROVAL_TOKEN",
  coveredRoutes:["/buy/*","/commission/*"],
  noAutonomousSpend:true
});
const HOURS_TO_APPROVE = 24;
const HOURS_AFTER_APPROVAL = 2;
const DEFAULT_NETWORK = "eip155:8453";
const clean = (v,n=180) => String(v??"").trim().slice(0,n);
const ts = () => new Date().toISOString();
const later = h => new Date(Date.now()+h*3600000).toISOString();
const json = (value,status=200) => Response.json(value,{status,headers:{"cache-control":"no-store","x-content-type-options":"nosniff","access-control-allow-origin":"*","access-control-allow-headers":"content-type,payment-signature,x-payment,x-lumen-approval-id,x-lumen-approval-token","access-control-allow-methods":"GET,POST,OPTIONS"}});
const id = () => "X402A-"+crypto.randomUUID().replaceAll("-","").toUpperCase();
async function hash(v) {
  const b=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(v));
  return Array.from(new Uint8Array(b)).map(x=>x.toString(16).padStart(2,"0")).join("");
}
function decodeB64(value) {
  try {
    let b=String(value).replace(/-/g,"+").replace(/_/g,"/");
    b+="=".repeat((4-b.length%4)%4);
    return JSON.parse(atob(b));
  } catch {return null;}
}
export function plausibleX402Signature(signature) {
  if(typeof signature!=="string"||signature.length<24||signature.length>16000||!/^[A-Za-z0-9+/_=-]+$/.test(signature))return false;
  const body=decodeB64(signature);
  return Boolean(body && (body.x402Version===1 || body.x402Version===2) && body.payload && typeof body.payload==="object" && !Array.isArray(body.payload));
}
export function sameApprovalScope(row,ctx) {
  return Boolean(row && ctx && row.request_path===ctx.path &&
    row.network===ctx.network && row.pay_to===ctx.payTo &&
    Number(row.amount_usd)===Number(ctx.amountUsd));
}
export function approvalMaySettle(row,ctx,now=ts()) {
  return sameApprovalScope(row,ctx) && row.status==="APPROVED" && row.expires_at>now;
}
async function ensure(env) {
  if(!env?.DB)throw new Error("approval_persistence_unavailable");
  await env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_x402_human_approvals (id TEXT PRIMARY KEY,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,status TEXT NOT NULL,request_path TEXT NOT NULL,product_name TEXT NOT NULL,amount_usd REAL NOT NULL,network TEXT NOT NULL,pay_to TEXT NOT NULL,request_fingerprint TEXT NOT NULL UNIQUE,expires_at TEXT NOT NULL,approved_at TEXT,consumed_at TEXT,settlement_transaction TEXT,failure_code TEXT)").run();
  await env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_x402_human_approvals_status ON lumen_x402_human_approvals(status,created_at)").run();
}
function ownerAuth(req,env) {
  const secret=clean(env?.X402_HUMAN_APPROVAL_TOKEN,500);
  const supplied=clean(req.headers.get("x-lumen-approval-token"),500);
  return secret.length>=32 && supplied.length===secret.length && supplied===secret;
}
function safeRow(r) {
  return {id:r.id,status:r.status,createdAt:r.created_at,path:r.request_path,
    product:r.product_name,amountUsd:Number(r.amount_usd),network:r.network,
    recipient:r.pay_to,expiresAt:r.expires_at,approvedAt:r.approved_at||null,
    fingerprintSuffix:clean(r.request_fingerprint,64).slice(-12),
    failureCode:r.failure_code||null};
}
async function context(url,env,products) {
  const path=url.pathname;
  if(path.startsWith("/buy/")) {
    const slug=path.slice("/buy/".length);
    const p=products[slug];
    if(!p || path!=="/buy/"+slug)return null;
    return {path,productName:p.name,amountUsd:Number(p.price_usd),
      network:DEFAULT_NETWORK,payTo:"0x04285DE6A083CEb28fb0C254a2ed0F5fdB2eeD28"};
  }
  if(path.startsWith("/commission/")) {
    const ref=decodeURIComponent(path.slice("/commission/".length));
    if(!ref||ref.length>100||ref.includes("/"))return null;
    const c=await env.DB.prepare("SELECT status,agreed_amount_usd FROM lumen_referral_commissions WHERE referral_id=? LIMIT 1").bind(ref).first();
    if(c?.status!=="PAYMENT_DUE"||!(Number(c?.agreed_amount_usd)>0))return null;
    const payTo=clean(env?.X402_PAY_TO,200);
    const network=clean(env?.X402_NETWORK||DEFAULT_NETWORK,120);
    if(!payTo||!network)return null;
    return {path,productName:"Referral commission "+ref,amountUsd:Number(c.agreed_amount_usd),
      network,payTo};
  }
  return null;
}
export async function preflightX402Settlement(request,env,products) {
  const url=new URL(request.url);
  if(request.method!=="GET"||(!url.pathname.startsWith("/buy/")&&!url.pathname.startsWith("/commission/")))return {claimedId:null,response:null};
  const signature=request.headers.get("payment-signature")||request.headers.get("x-payment")||"";
  // Unpaid discovery retains the native x402 HTTP 402 flow; it does not settle.
  if(!signature)return {claimedId:null,response:null};
  try {
    await ensure(env);
    const scope=await context(url,env,products);
    if(!scope)return {claimedId:null,response:json({ok:false,error:"approval_scope_not_payable"},409)};
    if(!plausibleX402Signature(signature))return {claimedId:null,response:json({ok:false,error:"invalid_x402_signature_format"},400)};
    const fingerprint=await hash(signature);
    const suppliedId=clean(request.headers.get("x-lumen-approval-id"),100);
    let ticket=null;
    if(suppliedId){
      ticket=await env.DB.prepare("SELECT * FROM lumen_x402_human_approvals WHERE id=? LIMIT 1").bind(suppliedId).first();
      if(!ticket)return {claimedId:null,response:json({ok:false,error:"approval_not_found"},409)};
    }else{
      ticket=await env.DB.prepare("SELECT * FROM lumen_x402_human_approvals WHERE request_fingerprint=? LIMIT 1").bind(fingerprint).first();
      if(!ticket){
        // Limit anonymous registration; no payment or outbound contact occurs here.
        const n=await env.DB.prepare("SELECT COUNT(*) AS n FROM lumen_x402_human_approvals WHERE created_at>=?").bind(new Date(Date.now()-86400000).toISOString()).first();
        if(Number(n?.n||0)>=500)return {claimedId:null,response:json({ok:false,error:"approval_queue_temporarily_full"},429)};
        const now=ts(),newId=id();
        await env.DB.prepare("INSERT OR IGNORE INTO lumen_x402_human_approvals(id,created_at,updated_at,status,request_path,product_name,amount_usd,network,pay_to,request_fingerprint,expires_at) VALUES(?,?,?,'PENDING',?,?,?,?,?,?,?)")
          .bind(newId,now,now,scope.path,scope.productName,scope.amountUsd,scope.network,scope.payTo,fingerprint,later(HOURS_TO_APPROVE)).run();
        ticket=await env.DB.prepare("SELECT * FROM lumen_x402_human_approvals WHERE request_fingerprint=? LIMIT 1").bind(fingerprint).first();
      }
    }
    if(!sameApprovalScope(ticket,scope))return {claimedId:null,response:json({ok:false,error:"approval_scope_mismatch"},409)};
    if(!approvalMaySettle(ticket,scope)) {
      return {claimedId:null,response:json({
        ok:false,error:ticket.status==="PENDING"?"awaiting_owner_approval":"approval_not_usable",
        approvalRequestId:ticket.id,approvalStatus:ticket.status,amountUsd:scope.amountUsd,
        product:scope.productName,ownerApprovalRequired:true,
        retry:"After owner approval, retry with a fresh x402 signed authorization AND x-lumen-approval-id set to approvalRequestId. No funds have been moved."
      },409)};
    }
    // Atomic one-shot claim: concurrent/replayed requests cannot use one approval twice.
    const claim=await env.DB.prepare("UPDATE lumen_x402_human_approvals SET status='IN_FLIGHT',consumed_at=?,updated_at=?,request_fingerprint=? WHERE id=? AND status='APPROVED' AND expires_at>?")
      .bind(ts(),ts(),fingerprint,ticket.id,ts()).run();
    if(Number(claim?.meta?.changes||0)!==1)return {claimedId:null,response:json({ok:false,error:"approval_already_consumed"},409)};
    return {claimedId:ticket.id,response:null};
  } catch(e) {
    console.error("x402_approval_gate_error",clean(e?.message,160));
    return {claimedId:null,response:json({ok:false,error:"human_approval_gate_unavailable",paymentAttempted:false},503)};
  }
}
export async function finalizeX402Settlement(env,claimId,response) {
  if(!claimId)return;
  // Once a payment attempt reaches the facilitator, uncertain outcomes require
  // a new owner decision; never silently restore APPROVED after any failure.
  let status="REVIEW_REQUIRED",transaction=null,code="unconfirmed_settlement";
  const header=response?.headers?.get("payment-response")||response?.headers?.get("x-payment-response")||"";
  const body=decodeB64(header);
  if(body?.success===true){
    status="SETTLED";
    transaction=clean(body.transaction,120)||null;
    code=null;
  }
  try {
    await env.DB.prepare("UPDATE lumen_x402_human_approvals SET status=?,settlement_transaction=?,failure_code=?,updated_at=? WHERE id=? AND status='IN_FLIGHT'")
      .bind(status,transaction,code,ts(),claimId).run();
  } catch(e){console.error("x402_approval_finalization_error",clean(e?.message,160));}
}
const ownerPage=`<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LUMEN · Aprobación de cobros x402</title><style>body{font:16px system-ui;background:#101927;color:#fafafa;max-width:820px;margin:36px auto;padding:18px}input,button{font:inherit;padding:10px;margin:5px;background:#24354c;border:1px solid #53708d;border-radius:6px;color:inherit}input{width:min(90%,440px)}section{background:#1d2d3e;border-radius:12px;padding:18px;margin:15px 0}small{color:#b8cce0}button{cursor:pointer}strong{color:#a9dce9}</style></head><body><h1>LUMEN · Aprobación individual x402</h1><p>Cada aprobación habilita <strong>un intento de cobro</strong> exacto. Sin aprobación, el facilitador no se ejecuta. No apruebes solicitudes que no reconozcas.</p><label>Clave privada de aprobación (no se guarda en el navegador)<input id="token" type="password" autocomplete="off" placeholder="X402_HUMAN_APPROVAL_TOKEN"></label><button onclick="loadPending()">Ver solicitudes pendientes</button><p id="notice"></p><main id="items"></main><script>const tok=document.getElementById('token'),items=document.getElementById('items'),notice=document.getElementById('notice');async function call(path,method){const r=await fetch(path,{method:method||'GET',headers:{'x-lumen-approval-token':tok.value}});const j=await r.json();if(!r.ok)throw Error(j.error||'Error de acceso');return j}async function act(id,decision){if(!confirm('¿' + (decision==='approve'?'APROBAR':'RECHAZAR') +' este cobro específico?'))return;try{await call('/approvals/'+encodeURIComponent(id)+'/'+decision,'POST');await loadPending()}catch(e){notice.textContent=e.message}}async function loadPending(){items.replaceChildren();notice.textContent='';try{const d=await call('/approvals/pending');if(!d.pending.length)notice.textContent='Sin solicitudes pendientes';for(const v of d.pending){const s=document.createElement('section');const h=document.createElement('h2');h.textContent=v.product+' — USD '+v.amountUsd;s.append(h);for(const line of ['Ruta: '+v.path,'Red: '+v.network,'Destinatario: '+v.recipient,'ID: '+v.id,'Expira: '+v.expiresAt]){let p=document.createElement('p');let sm=document.createElement('small');sm.textContent=line;p.append(sm);s.append(p)}for(const [label,dec] of [['Aprobar una vez','approve'],['Rechazar','reject']]){let b=document.createElement('button');b.textContent=label;b.onclick=()=>act(v.id,dec);s.append(b)}items.append(s)}}catch(e){notice.textContent=e.message}}</script></body></html>`;
export async function handleApprovalManagement(request,env) {
  const url=new URL(request.url);
  if(!url.pathname.startsWith("/approvals"))return null;
  if(request.method==="OPTIONS")return new Response(null,{status:204,headers:{"access-control-allow-origin":"*","access-control-allow-headers":"x-lumen-approval-token,content-type","access-control-allow-methods":"GET,POST,OPTIONS"}});
  if(url.pathname==="/approvals/policy"&&request.method==="GET")return json({...APPROVAL_POLICY,ownerCredentialConfigured:clean(env?.X402_HUMAN_APPROVAL_TOKEN,500).length>=32});
  if(url.pathname==="/approvals"&&request.method==="GET")return new Response(ownerPage,{headers:{"content-type":"text/html;charset=utf-8","cache-control":"no-store","x-content-type-options":"nosniff","content-security-policy":"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'none'"}});
  if(!ownerAuth(request,env))return json({ok:false,error:clean(env?.X402_HUMAN_APPROVAL_TOKEN,500).length<32?"approval_secret_not_configured":"owner_credential_required"},403);
  try{
    await ensure(env);
    if(url.pathname==="/approvals/pending"&&request.method==="GET"){
      const result=await env.DB.prepare("SELECT * FROM lumen_x402_human_approvals WHERE status='PENDING' AND expires_at>? ORDER BY created_at DESC LIMIT 100").bind(ts()).all();
      return json({ok:true,pending:(result.results||[]).map(safeRow)});
    }
    const match=url.pathname.match(/^\/approvals\/(X402A-[A-F0-9]+)\/(approve|reject)$/);
    if(match && request.method==="POST"){
      const row=await env.DB.prepare("SELECT * FROM lumen_x402_human_approvals WHERE id=? LIMIT 1").bind(match[1]).first();
      if(!row)return json({ok:false,error:"approval_not_found"},404);
      if(row.status!=="PENDING"||row.expires_at<=ts())return json({ok:false,error:"approval_not_pending_or_expired",status:row.status},409);
      const approve=match[2]==="approve",now=ts();
      const update=await env.DB.prepare("UPDATE lumen_x402_human_approvals SET status=?,approved_at=?,expires_at=?,updated_at=? WHERE id=? AND status='PENDING' AND expires_at>?")
        .bind(approve?"APPROVED":"REJECTED",approve?now:null,approve?later(HOURS_AFTER_APPROVAL):now,now,row.id,now).run();
      if(Number(update?.meta?.changes||0)!==1)return json({ok:false,error:"approval_race_or_expired"},409);
      return json({ok:true,ownerAction:approve?"APPROVED_ONCE":"REJECTED",settlementExecuted:false,approvalRequestId:row.id});
    }
    return json({ok:false,error:"not_found"},404);
  }catch(e){console.error("approval_management_error",clean(e?.message,160));return json({ok:false,error:"approval_management_unavailable"},503);}
}
