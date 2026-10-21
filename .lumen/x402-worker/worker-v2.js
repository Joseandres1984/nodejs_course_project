import { Hono } from "hono";
import { paymentMiddleware } from "@x402/hono";
import { x402ResourceServer, HTTPFacilitatorClient } from "@x402/core/server";
import { ExactEvmScheme } from "@x402/evm/exact/server";
import { createPaywall } from "@x402/paywall";
import { evmPaywall } from "@x402/paywall/evm";
import { buildWellKnownX402, buildDiscoveryOpenApi, buildDiscoveryLlmsTxt } from "./discovery.js";
import { declareDiscoveryExtension, bazaarResourceServerExtension } from "@x402/extensions/bazaar";
import { inspectBuyerBrief, briefFromUrl } from "./buyer-brief.js";
import { verifyBaseUsdcTransfer } from "./base-usdc-verifier.js";

const SERVICE = "lumen-zero-x402";
const VERSION = "1.6-x402-human-approval";
const PAY_TO = "0x04285DE6A083CEb28fb0C254a2ed0F5fdB2eeD28";
const NETWORK = "eip155:8453";
const FACILITATOR = "https://facilitator.xpay.sh";

export const PRODUCTS = {
  "supplier-snapshot": { id:"MP-SUPPLIER-SNAPSHOT", name:"Supplier Snapshot", price_usd:1, service_id:"SRV-SUPPLIERCHECK" },
  "quote-sanity": { id:"MP-QUOTE-SANITY", name:"Quote Sanity Check", price_usd:7, service_id:"SRV-QUOTECHECK" },
  "tender-hot-lead": { id:"MP-TENDER-LEAD", name:"Tender Hot Lead", price_usd:1, service_id:"SRV-TENDER-LEAD" },
  "tender-scan": { id:"MP-TENDER-SCAN", name:"Tender Quick Scan", price_usd:9, service_id:"SRV-TENDER-HUNTER" },
  "sourcing-5": { id:"MP-SOURCING-5", name:"Supplier Shortlist 5", price_usd:15, service_id:"SRV-SOURCING-EXPRESS" },
  "buyer-signals": { id:"MP-BUYER-SIGNALS", name:"Buyer Signal Scan", price_usd:19, service_id:"SRV-B2B-PROSPECTING" },
  "export-pulse": { id:"MP-EXPORT-PULSE", name:"Export Market Pulse", price_usd:25, service_id:"SRV-EXPORT-SCOUT" },
};

const app = new Hono();

function clean(value, limit = 4000) {
  return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit);
}
function rid(prefix) {
  return `${prefix}-${crypto.randomUUID().replaceAll("-", "").slice(0, 16).toUpperCase()}`;
}
async function sha256Hex(value) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(String(value || "")));
  return [...new Uint8Array(digest)].map(x => x.toString(16).padStart(2, "0")).join("");
}
function decodeB64Json(value) {
  try {
    let raw = String(value || "").replace(/-/g, "+").replace(/_/g, "/");
    raw += "=".repeat((4 - raw.length % 4) % 4);
    return JSON.parse(atob(raw));
  } catch {
    return null;
  }
}
function conversionAttribution(c) {
  const url = new URL(c.req.url);
  const attribution = {
    event_id: clean(url.searchParams.get("conversion_event"), 80),
    session_id: clean(url.searchParams.get("conversion_session"), 80),
    campaign: clean(url.searchParams.get("campaign"), 120),
    source: clean(url.searchParams.get("source"), 80),
    medium: clean(url.searchParams.get("medium"), 80),
    creative: clean(url.searchParams.get("creative"), 120),
    brief_id: clean(url.searchParams.get("brief_id"), 80),
  };
  return Object.values(attribution).some(Boolean) ? attribution : null;
}

async function ensureSchema(env) {
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_x402_receipts (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, product_id TEXT NOT NULL, service_id TEXT NOT NULL, amount_usd REAL NOT NULL, currency TEXT NOT NULL, network TEXT NOT NULL, pay_to TEXT NOT NULL, status TEXT NOT NULL, payment_fingerprint TEXT NOT NULL UNIQUE, redeemed_at TEXT, request_metadata TEXT)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_x402_receipts_created ON lumen_x402_receipts(created_at)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_x402_receipts_status ON lumen_x402_receipts(status,created_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_x402_redemptions (receipt_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, context_id TEXT NOT NULL, task_id TEXT NOT NULL, inbound_id TEXT NOT NULL, order_id TEXT NOT NULL, quote_id TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_conversion_leads (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, session_id TEXT NOT NULL, product_id TEXT NOT NULL, product_slug TEXT NOT NULL, email TEXT NOT NULL, company TEXT, details TEXT, source TEXT NOT NULL, medium TEXT NOT NULL, campaign TEXT, creative TEXT, status TEXT NOT NULL DEFAULT 'new', technical_canary INTEGER NOT NULL DEFAULT 0)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_a2a_quotes (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, context_id TEXT, service_id TEXT NOT NULL, amount_usd REAL NOT NULL, status TEXT NOT NULL, remote_metadata TEXT)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_a2a_inbound (id TEXT PRIMARY KEY, received_at TEXT NOT NULL, context_id TEXT NOT NULL, task_id TEXT NOT NULL, remote_message_id TEXT, remote_metadata TEXT, text TEXT NOT NULL, binding_intent INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, processed INTEGER NOT NULL DEFAULT 0, processed_at TEXT, bridge_status TEXT, opportunity_id TEXT, task_json TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_machine_orders (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, context_id TEXT NOT NULL, task_id TEXT NOT NULL, item_type TEXT NOT NULL, item_id TEXT NOT NULL, service_id TEXT NOT NULL, amount_usd REAL NOT NULL, billing TEXT NOT NULL, status TEXT NOT NULL, inbound_id TEXT NOT NULL, quote_id TEXT, remote_metadata TEXT)"),
  ]);
}

const facilitatorClient = new HTTPFacilitatorClient({ url: FACILITATOR });
const resourceServer = new x402ResourceServer(facilitatorClient)
  .register(NETWORK, new ExactEvmScheme())
  .registerExtension(bazaarResourceServerExtension);

let initializationPromise = null;
async function ensurePaymentServerInitialized() {
  if (!initializationPromise) {
    initializationPromise = resourceServer.initialize().catch(error => {
      initializationPromise = null;
      throw error;
    });
  }
  await initializationPromise;
}

const paidRoutes = {};
for (const [slug, product] of Object.entries(PRODUCTS)) {
  paidRoutes[`GET /buy/${slug}`] = {
    accepts: [{
      scheme: "exact",
      price: `$${product.price_usd.toFixed(2)}`,
      network: NETWORK,
      payTo: PAY_TO,
      extra: { assetTransferMethod: "eip3009" },
    }],
    description: `LUMEN ${product.name} paid research request; owner approval required before settlement`,
    mimeType: "application/json",
    extensions: {
      ...declareDiscoveryExtension({
        // Query brief is optional; buyers supply nonconfidential requirements.
        // Output is a receipt, NOT the finished research deliverable.
        input: {requirement:"Find three publicly listed manufacturers of industrial safety gloves in Argentina."},
        inputSchema: {type:"object",properties:{
          requirement:{type:"string",description:"Nonconfidential sourcing brief; 12-1200 characters; queued only after a verified settlement.",minLength:12,maxLength:1200}
        },required:[],additionalProperties:false},
        output: {
          example: {
            ok:true,paymentAuthorizationVerified:true,
            productId:product.id,amountUsd:product.price_usd,
            status:"settlement_before_response",
            nextAction:"Research request queues for fulfillment after verified payment."
          },
          schema: {
            type:"object",
            properties:{
              ok:{type:"boolean"},
              paymentAuthorizationVerified:{type:"boolean"},
              productId:{type:"string"},
              amountUsd:{type:"number"},
              status:{type:"string"},
              receiptId:{type:"string"},
              nextAction:{type:"string"}
            },
            required:["ok","productId","amountUsd"]
          }
        }
      })
    },
  };
}
const humanPaywall = createPaywall()
  .withNetwork(evmPaywall)
  .withConfig({ appName:"LUMEN", testnet:false })
  .build();
const x402Gate = paymentMiddleware(
  paidRoutes,
  resourceServer,
  undefined,
  humanPaywall,
  false,
);

app.use("*", async (c, next) => {
  if (c.req.method === "OPTIONS") {
    return new Response(null, { status:204, headers:{
      "access-control-allow-origin":"*",
      "access-control-allow-methods":"GET,POST,OPTIONS",
      "access-control-allow-headers":"content-type,payment-signature,x-payment,x-lumen-approval-id",
    }});
  }
  await next();
  c.header("access-control-allow-origin", "*");
  c.header("cache-control", "no-store");
  c.header("x-content-type-options", "nosniff");
});

// Lazy initialization is required on Workers: x402 must load facilitator
// capabilities inside a request. Keep this as a normal Hono middleware so the
// official x402 middleware remains part of the native chain.
app.use("/buy/*", async (c, next) => {
  try {
    await ensurePaymentServerInitialized();
  } catch (error) {
    return c.json({
      ok:false,
      error:"x402_facilitator_initialization_failed",
      detail:clean(error?.message || error,300),
      paymentAttempted:false,
      outgoingSpendEnabled:false,
    }, 503);
  }
  await next();
  return c.res;
});

// This wrapper runs before x402 and resumes only after x402 has verified,
// executed the paid resource and attempted settlement. That lets LUMEN record
// revenue strictly from the final PAYMENT-RESPONSE without reimplementing the
// payment gate or weakening fail-closed behavior.
app.use("/buy/*", async (c, next) => {
  await next();

  const paymentSignature = c.req.header("payment-signature") || c.req.header("x-payment") || "";
  if (!paymentSignature) return c.res;

  try {
    const fingerprint = await sha256Hex(paymentSignature);
    const paymentResponse = c.res?.headers?.get("payment-response") || c.res?.headers?.get("x-payment-response") || "";
    const settlement = decodeB64Json(paymentResponse);

    if (c.res?.ok && settlement?.success === true) {
      // Facilitator response is not independent proof of settlement.
      // Do not auto-fulfill or count revenue from this unverified evidence.
      const row = await c.env.DB.prepare("SELECT request_metadata FROM lumen_x402_receipts WHERE payment_fingerprint=? LIMIT 1").bind(fingerprint).first();
      if (row) {
        let meta = {};
        try { meta = JSON.parse(row.request_metadata || "{}"); } catch {}
        meta.settlement = {
          facilitatorReportedSuccess:true,
          independentlyVerified:false,
          transaction:clean(settlement.transaction,100),
          network:clean(settlement.network,80),
          payer:clean(settlement.payer,80),
          reconciled_at:new Date().toISOString(),
        };
        await c.env.DB.prepare("UPDATE lumen_x402_receipts SET status='awaiting_independent_verification', request_metadata=? WHERE payment_fingerprint=? AND status='verified_pending_settlement'")
          .bind(JSON.stringify(meta), fingerprint).run();
      }
    } else if (paymentResponse) {
      await c.env.DB.prepare("UPDATE lumen_x402_receipts SET status='settlement_failed' WHERE payment_fingerprint=? AND status='verified_pending_settlement'")
        .bind(fingerprint).run();
    }
  } catch (error) {
    // Settlement reconciliation must never convert a valid x402 response into a
    // false success. Log it and preserve the protocol response; revenue remains
    // uncounted unless a verified settlement was persisted.
    console.error("x402_reconciliation_error", error);
  }

  return c.res;
});

// Official x402 middleware participates natively in the Hono chain. This is the
// fail-closed payment gate: unpaid requests stop here with HTTP 402.
app.use("/buy/*", x402Gate);

function publicCatalog(origin) {
  return {
    name:"LUMEN x402 Machine Checkout",
    version:VERSION,
    settlement:{
      protocol:"x402-v2",
      asset:"USDC",
      network:"Base",
      networkId:NETWORK,
      recipient:PAY_TO,
      facilitator:FACILITATOR,
      outgoingSpendEnabled:false,
      humanApprovalRequired:true,
      humanApprovalPath:"/approvals",
      accountingRule:"facilitator responses remain unverified; realized revenue requires independent chain/provider verification",
      conversionAttribution:"campaign/session metadata is persisted with the receipt when supplied",
    },
    products:Object.entries(PRODUCTS).map(([slug,p]) => ({
      ...p,
      currency:"USD",
      billing:"per_request",
      paidUrl:`${origin}/buy/${slug}`,
    })),
    flow:[
      "GET paidUrl (optionally add a NONCONFIDENTIAL ?requirement=... brief)",
      "receive HTTP 402 PAYMENT-REQUIRED",
      "buyer signs exact USDC authorization",
      "signed retry yields HTTP 409 pending individual owner approval; no funds settle",
      "owner approves exact product, amount, network and recipient using private approval panel",
      "buyer retries with a fresh signed payment and x-lumen-approval-id",
      "LUMEN verifies authorization and consumes one-use owner approval",
      "facilitator settles USDC on Base and response includes x402 receipt",
      "LUMEN counts revenue only after verified settlement response",
      "valid query brief or linked human brief queues work AFTER settlement; otherwise clients may POST /redeem",
    ],
  };
}

async function createVerifiedPendingReceipt(c, product) {
  await ensureSchema(c.env);
  const paymentSignature = c.req.header("payment-signature") || c.req.header("x-payment") || "";
  if (!paymentSignature) return c.json({ok:false,error:"missing_payment_signature_after_gate"},500);
  const fingerprint = await sha256Hex(paymentSignature);
  const existing = await c.env.DB.prepare("SELECT * FROM lumen_x402_receipts WHERE payment_fingerprint=? LIMIT 1").bind(fingerprint).first();
  if (existing) {
    return c.json({
      ok:true,
      duplicateSafe:true,
      paymentAuthorizationVerified:true,
      receiptId:existing.id,
      productId:existing.product_id,
      amountUsd:Number(existing.amount_usd),
      status:existing.status,
      nextAction:"Linked human briefs auto-queue after settlement; machine clients may POST /redeem.",
    });
  }
  const receiptId=rid("X402R");
  const now=new Date().toISOString();
  const conversion=conversionAttribution(c);
  const meta={
    source:"x402",
    authorization_verified:true,
    settlement_accounting:"await_payment_response_success",
    cfCountry:clean(c.req.header("cf-ipcountry"),16),
    userAgent:clean(c.req.header("user-agent"),300),
    ...(conversion ? {conversion} : {}),
  };
  await c.env.DB.prepare("INSERT INTO lumen_x402_receipts(id,created_at,product_id,service_id,amount_usd,currency,network,pay_to,status,payment_fingerprint,request_metadata) VALUES(?,?,?,?,?,?,?,?,?,?,?)")
    .bind(receiptId,now,product.id,product.service_id,product.price_usd,"USD",NETWORK,PAY_TO,"verified_pending_settlement",fingerprint,JSON.stringify(meta)).run();
  return c.json({
    ok:true,
    paymentAuthorizationVerified:true,
    receiptId,
    productId:product.id,
    productName:product.name,
    amountUsd:product.price_usd,
    currency:"USD",
    asset:"USDC",
    network:"Base",
    conversionAttributed:Boolean(conversion),
    status:"settlement_before_response",
    nextAction:"Settlement is reconciled server-side. Linked human briefs auto-queue; machine clients may POST /redeem.",
  });
}

app.get("/", (c) => c.json({
  ok:true, service:SERVICE, version:VERSION,
  purpose:"LUMEN seller-side x402 checkout",
  catalog:`${new URL(c.req.url).origin}/catalog`,
  recipientConfigured:true, network:"Base", networkId:NETWORK, asset:"USDC",
  facilitator:FACILITATOR, outgoingSpendEnabled:false,
}));

app.get("/health", async (c) => {
  await ensureSchema(c.env);
  try {
    await ensurePaymentServerInitialized();
  } catch (error) {
    return c.json({ok:false,service:SERVICE,version:VERSION,x402:"DEGRADED",error:clean(error?.message,300)},503);
  }
  return c.json({
    ok:true, service:SERVICE, version:VERSION, x402:"LIVE",
    network:NETWORK, asset:"USDC", facilitator:FACILITATOR,
    recipientConfigured:true, resourceServerInitialized:true, outgoingSpendEnabled:false,
    conversionAttribution:true, humanPaywall:true, briefLinkedFulfillment:true,
    humanApprovalRequired:true,
  });
});
app.get("/catalog", (c) => c.json(publicCatalog(new URL(c.req.url).origin)));
app.get("/openapi.json", (c) => c.json(buildDiscoveryOpenApi(PRODUCTS, new URL(c.req.url).origin)));
app.get("/.well-known/x402", (c) => c.json(buildWellKnownX402(PRODUCTS, new URL(c.req.url).origin)));
app.get("/.well-known/x402-catalog.json", (c) => c.json(publicCatalog(new URL(c.req.url).origin)));
app.get("/llms.txt", (c) => new Response(buildDiscoveryLlmsTxt(PRODUCTS,new URL(c.req.url).origin),{
  headers:{"content-type":"text/plain;charset=utf-8","cache-control":"public,max-age=300","x-content-type-options":"nosniff"}
}));


for (const [slug,product] of Object.entries(PRODUCTS)) {
  app.get(`/buy/${slug}`, (c) => createVerifiedPendingReceipt(c,product));
}

async function queuePaidReceipt(env, receiptIdRaw, requirementRaw, options={}) {
  await ensureSchema(env);
  const receiptId=clean(receiptIdRaw,80);
  const inspected=inspectBuyerBrief(requirementRaw);
  if (!receiptId) return {ok:false,statusCode:400,error:"receiptId is required"};
  if (!inspected.ok) return {ok:false,statusCode:400,error:inspected.error};
  const requirement=inspected.text;
  const receipt=await env.DB.prepare("SELECT * FROM lumen_x402_receipts WHERE id=? LIMIT 1").bind(receiptId).first();
  if (!receipt) return {ok:false,statusCode:404,error:"Receipt not found"};
  if (receipt.status !== "settled_verified" && receipt.status !== "redeemed_queued") return {ok:false,statusCode:409,error:"Payment is not yet confirmed as settled",status:receipt.status};
  const prior=await env.DB.prepare("SELECT * FROM lumen_x402_redemptions WHERE receipt_id=? LIMIT 1").bind(receiptId).first();
  if (prior) return {ok:true,statusCode:200,duplicateSafe:true,receiptId,taskId:prior.task_id,orderId:prior.order_id,status:"already_redeemed"};
  const product=Object.values(PRODUCTS).find(p => p.id === receipt.product_id);
  if (!product) return {ok:false,statusCode:409,error:"Receipt product is no longer available"};
  const now=new Date().toISOString();
  const contextId=rid("X402CTX"), taskId=rid("X402TASK"), inboundId=rid("A2AIN"), orderId=rid("MORD"), quoteId=rid("A2AQ");
  let receiptMeta={};
  try { receiptMeta=JSON.parse(receipt.request_metadata || "{}"); } catch {}
  const brief=options.brief || null;
  const metadata={
    source:"a2a_machine_store", purpose:"commercial_x402_purchase",
    fulfillment_source:clean(options.source || "manual_redeem",80),
    productId:product.id, lumen_product_id:product.id, lumen_service_id:product.service_id,
    lumen_item_type:"product", lumen_item_id:product.id,
    lumen_quote_usd:String(product.price_usd), lumen_quote_id:quoteId, lumen_billing:"per_request",
    lumen_seller_mode:"receive_revenue_only", payment_verified:"true", payment_settled:"true",
    payment_method:"x402_usdc_base", x402_receipt_id:receiptId, charge_created:"true",
    ...(receiptMeta.conversion ? {conversion:receiptMeta.conversion} : {}),
    ...(brief?.id ? {brief_id:clean(brief.id,80),delivery_email:clean(brief.email,180),customer_company:clean(brief.company,180)} : {}),
  };
  const task={
    id:taskId, contextId,
    status:{state:"TASK_STATE_WORKING",timestamp:now,message:{messageId:rid("MSG"),contextId,taskId,role:"ROLE_AGENT",parts:[{text:`Paid ${product.name} request received and queued for fulfillment.`,mediaType:"text/plain"}]}},
    metadata:{lumen:true,paid:true,paymentVerified:true,paymentSettled:true,paymentMethod:"x402_usdc_base",receiptId,briefId:brief?.id || receiptMeta.conversion?.brief_id || null,sellerMode:"receive_revenue_only",lumenAutonomousSpend:false},
  };
  try {
    await env.DB.batch([
      env.DB.prepare("INSERT INTO lumen_x402_redemptions(receipt_id,created_at,context_id,task_id,inbound_id,order_id,quote_id) VALUES(?,?,?,?,?,?,?)").bind(receiptId,now,contextId,taskId,inboundId,orderId,quoteId),
      env.DB.prepare("UPDATE lumen_x402_receipts SET status='redeemed_queued', redeemed_at=? WHERE id=? AND status='settled_verified'").bind(now,receiptId),
      env.DB.prepare("INSERT INTO lumen_a2a_quotes(id,created_at,context_id,service_id,amount_usd,status,remote_metadata) VALUES(?,?,?,?,?,?,?)").bind(quoteId,now,contextId,product.service_id,product.price_usd,"PAID_VERIFIED",JSON.stringify(metadata)),
      env.DB.prepare("INSERT INTO lumen_a2a_inbound(id,received_at,context_id,task_id,remote_message_id,remote_metadata,text,binding_intent,status,processed,task_json) VALUES(?,?,?,?,?,?,?,?,?,0,?)").bind(inboundId,now,contextId,taskId,rid("X402MSG"),JSON.stringify(metadata),requirement,0,"x402_paid_service_request",JSON.stringify(task)),
      env.DB.prepare("INSERT INTO lumen_machine_orders(id,created_at,context_id,task_id,item_type,item_id,service_id,amount_usd,billing,status,inbound_id,quote_id,remote_metadata) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)").bind(orderId,now,contextId,taskId,"product",product.id,product.service_id,product.price_usd,"per_request","x402_paid_queued",inboundId,quoteId,JSON.stringify(metadata)),
    ]);
    if (brief?.id) await env.DB.prepare("UPDATE lumen_conversion_leads SET status='paid_queued' WHERE id=?").bind(clean(brief.id,80)).run();
  } catch (error) {
    const race=await env.DB.prepare("SELECT * FROM lumen_x402_redemptions WHERE receipt_id=? LIMIT 1").bind(receiptId).first();
    if (race) return {ok:true,statusCode:200,duplicateSafe:true,receiptId,taskId:race.task_id,orderId:race.order_id,status:"already_redeemed"};
    return {ok:false,statusCode:500,error:"Could not queue paid request",detail:clean(error?.message,300)};
  }
  return {ok:true,statusCode:200,paymentVerified:true,paymentSettled:true,receiptId,productId:product.id,serviceId:product.service_id,amountUsd:product.price_usd,taskId,orderId,status:"paid_queued_for_fulfillment",lumenAutonomousSpend:false};
}

app.post("/redeem", async (c) => {
  let body={};
  try { body=await c.req.json(); } catch { return c.json({ok:false,error:"Valid JSON body required"},400); }
  const result=await queuePaidReceipt(c.env,body.receiptId || body.receipt_id,body.requirement || body.request || body.input,{source:"manual_redeem"});
  const {statusCode=200,...payload}=result;
  return c.json(payload,statusCode);
});

app.get("/receipt/:id", async (c) => {
  await ensureSchema(c.env);
  const row=await c.env.DB.prepare("SELECT id,created_at,product_id,service_id,amount_usd,currency,network,status,redeemed_at,request_metadata FROM lumen_x402_receipts WHERE id=? LIMIT 1").bind(clean(c.req.param("id"),80)).first();
  if (!row) return c.json({ok:false,error:"Receipt not found"},404);
  let conversion=null;
  try { conversion=JSON.parse(row.request_metadata || "{}").conversion || null; } catch {}
  delete row.request_metadata;
  return c.json({ok:true,receipt:{...row,conversion}});
});

// Owner-controlled reconciliation: RPC evidence + DB uniqueness; no payment is initiated.
app.post("/internal/reconcile-usdc", async (c) => {
  const provided=c.req.header("x-lumen-reconcile-token") || "";
  const secret=c.env?.LUMEN_RECONCILE_TOKEN || "";
  if (!secret || secret.length < 32 || provided.length !== secret.length) return c.json({ok:false,error:"forbidden"},403);
  let mismatch=0;
  for(let i=0;i<secret.length;i++) mismatch |= provided.charCodeAt(i)^secret.charCodeAt(i);
  if(mismatch!==0) return c.json({ok:false,error:"forbidden"},403);
  if (!c.env?.BASE_RPC_URL) return c.json({ok:false,error:"base_rpc_not_configured"},503);
  let body;
  try {body=await c.req.json();} catch {return c.json({ok:false,error:"invalid_json"},400);}
  const receiptId=clean(body?.receiptId,80);
  if(!receiptId) return c.json({ok:false,error:"receipt_id_required"},400);
  await ensureSchema(c.env);
  const row=await c.env.DB.prepare("SELECT id,amount_usd,pay_to,status,request_metadata FROM lumen_x402_receipts WHERE id=? LIMIT 1").bind(receiptId).first();
  if(!row) return c.json({ok:false,error:"receipt_not_found"},404);
  if(row.status!=="awaiting_independent_verification") return c.json({ok:false,error:"receipt_not_awaiting_verification"},409);
  let meta={};try{meta=JSON.parse(row.request_metadata||"{}");}catch{}
  const transaction=clean(meta?.settlement?.transaction,100);
  if(meta?.settlement?.facilitatorReportedSuccess !== true) return c.json({ok:false,error:"facilitator_evidence_missing"},409);
  const proof=await verifyBaseUsdcTransfer({rpcUrl:c.env.BASE_RPC_URL,transaction,recipient:row.pay_to,amountUsd:row.amount_usd});
  if(!proof.ok) return c.json({ok:false,error:proof.reason},409);
  // Only one receipt can claim a specific transfer event; D1 serializes the claim.
  await c.env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_x402_verified_transfers (transfer_key TEXT PRIMARY KEY, receipt_id TEXT NOT NULL UNIQUE, verified_at TEXT NOT NULL)").run();
  if(proof.logIndex == null || !/^0x[0-9a-fA-F]+$/.test(String(proof.logIndex))) return c.json({ok:false,error:"invalid_transfer_log_index"},409);
  const transferKey=proof.transaction+":"+BigInt(proof.logIndex).toString(16);
  // The UNIQUE constraints below arbitrate concurrent requests atomically.
  meta.settlement={...meta.settlement,independentlyVerified:true,transaction:proof.transaction,network:proof.network,recipient:proof.recipient,amountUsd:proof.amountUsd,blockNumber:proof.blockNumber,logIndex:proof.logIndex,verified_at:new Date().toISOString()};
  const now=new Date().toISOString();
  try {
    const batch=await c.env.DB.batch([
      c.env.DB.prepare("INSERT INTO lumen_x402_verified_transfers(transfer_key,receipt_id,verified_at) VALUES(?,?,?)").bind(transferKey,receiptId,now),
      c.env.DB.prepare("UPDATE lumen_x402_receipts SET status='settled_verified',request_metadata=? WHERE id=? AND status='awaiting_independent_verification' AND pay_to=? AND amount_usd=?").bind(JSON.stringify(meta),receiptId,proof.recipient,proof.amountUsd)
    ]);
    if(Number(batch?.[1]?.meta?.changes)!==1) return c.json({ok:false,error:"receipt_state_conflict"},409);
  } catch {return c.json({ok:false,error:"verification_claim_conflict"},409);}
  return c.json({ok:true,receiptId,transaction:proof.transaction,independentlyVerified:true});
});

app.get("/stats", async (c) => {
  await ensureSchema(c.env);
  const pending=await c.env.DB.prepare("SELECT COUNT(*) AS n FROM lumen_x402_receipts WHERE status IN ('verified_pending_settlement','awaiting_independent_verification')").first();
  const redeemed=await c.env.DB.prepare("SELECT COUNT(*) AS n FROM lumen_x402_redemptions").first();
  // Legacy settled_verified rows may predate independent reconciliation.
  // Report only receipts with an explicit independent-verification marker.
  const paidRows=await c.env.DB.prepare("SELECT amount_usd,request_metadata FROM lumen_x402_receipts WHERE status IN ('settled_verified','redeemed_queued')").all();
  let verifiedPayments=0, verifiedRevenueUsd=0, attributedPayments=0, attributedRevenueUsd=0;
  for (const row of (paidRows.results || [])) {
    try {
      const meta=JSON.parse(row.request_metadata || "{}");
      if (meta.settlement?.independentlyVerified !== true || !/^0x[a-fA-F0-9]{64}$/.test(String(meta.settlement?.transaction || "")) || meta.settlement?.network !== NETWORK || String(meta.settlement?.recipient || "").toLowerCase() !== PAY_TO.toLowerCase() || Number(meta.settlement?.amountUsd) !== Number(row.amount_usd)) continue;
      verifiedPayments += 1;
      verifiedRevenueUsd += Number(row.amount_usd || 0);
      if (meta.conversion?.event_id || meta.conversion?.campaign || meta.conversion?.session_id) {
        attributedPayments += 1;
        attributedRevenueUsd += Number(row.amount_usd || 0);
      }
    } catch {}
  }
  return c.json({
    payments:verifiedPayments,
    realizedRevenueUsd:verifiedRevenueUsd,
    pendingSettlementVerification:Number(pending?.n||0),
    redeemedOrders:Number(redeemed?.n||0),
    attributedPayments,
    attributedRevenueUsd,
    conversionAttribution:true,
    revenueRule:"Only receipts explicitly marked independentlyVerified count as realized revenue; legacy statuses alone do not prove payment.",
    network:"Base", asset:"USDC", facilitator:FACILITATOR, recipient:PAY_TO,
  });
});

app.notFound((c) => c.json({ok:false,error:"not_found"},404));
export default app;
