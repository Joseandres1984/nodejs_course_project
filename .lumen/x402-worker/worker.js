import { Hono } from "hono";
import { paymentMiddleware, x402ResourceServer } from "@x402/hono";
import { HTTPFacilitatorClient } from "@x402/core/server";
import { registerExactEvmScheme as registerServerEvmScheme } from "@x402/evm/exact/server";

const SERVICE = "lumen-zero-x402";
const VERSION = "1.1-x402-base-usdc-mainnet";
const PAY_TO = "0x04285DE6A083CEb28fb0C254a2ed0F5fdB2eeD28";
const NETWORK = "eip155:8453";
const FACILITATOR = "https://facilitator.xpay.sh";

const PRODUCTS = {
  "supplier-snapshot": { id:"MP-SUPPLIER-SNAPSHOT", name:"Supplier Snapshot", price_usd:5, service_id:"SRV-SUPPLIERCHECK" },
  "quote-sanity": { id:"MP-QUOTE-SANITY", name:"Quote Sanity Check", price_usd:7, service_id:"SRV-QUOTECHECK" },
  "tender-scan": { id:"MP-TENDER-SCAN", name:"Tender Quick Scan", price_usd:9, service_id:"SRV-TENDER-HUNTER" },
  "sourcing-5": { id:"MP-SOURCING-5", name:"Supplier Shortlist 5", price_usd:15, service_id:"SRV-SOURCING-EXPRESS" },
  "buyer-signals": { id:"MP-BUYER-SIGNALS", name:"Buyer Signal Scan", price_usd:19, service_id:"SRV-B2B-PROSPECTING" },
  "export-pulse": { id:"MP-EXPORT-PULSE", name:"Export Market Pulse", price_usd:25, service_id:"SRV-EXPORT-SCOUT" },
};

const app = new Hono();

app.use("*", async (c, next) => {
  if (c.req.method === "OPTIONS") {
    return new Response(null, {
      status: 204,
      headers: {
        "access-control-allow-origin": "*",
        "access-control-allow-methods": "GET,POST,OPTIONS",
        "access-control-allow-headers": "content-type,payment-signature,x-payment",
      },
    });
  }
  await next();
  c.header("access-control-allow-origin", "*");
  c.header("cache-control", "no-store");
  c.header("x-content-type-options", "nosniff");
});

const facilitatorClient = new HTTPFacilitatorClient({ url: FACILITATOR });
const resourceServer = new x402ResourceServer(facilitatorClient);
registerServerEvmScheme(resourceServer);

const paidRoutes = {};
for (const [slug, product] of Object.entries(PRODUCTS)) {
  paidRoutes[`GET /buy/${slug}`] = {
    accepts: [{
      scheme: "exact",
      price: `$${product.price_usd.toFixed(2)}`,
      network: NETWORK,
      payTo: PAY_TO,
    }],
    description: `LUMEN ${product.name} machine-intelligence purchase`,
    mimeType: "application/json",
  };
}
app.use(paymentMiddleware(paidRoutes, resourceServer));

function clean(value, limit = 4000) {
  return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit);
}

function rid(prefix) {
  return `${prefix}-${crypto.randomUUID().replaceAll("-", "").slice(0, 16).toUpperCase()}`;
}

async function sha256Hex(value) {
  const bytes = new TextEncoder().encode(String(value || ""));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map(x => x.toString(16).padStart(2, "0")).join("");
}

async function ensureSchema(env) {
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_x402_receipts (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, product_id TEXT NOT NULL, service_id TEXT NOT NULL, amount_usd REAL NOT NULL, currency TEXT NOT NULL, network TEXT NOT NULL, pay_to TEXT NOT NULL, status TEXT NOT NULL, payment_fingerprint TEXT NOT NULL UNIQUE, redeemed_at TEXT, request_metadata TEXT)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_x402_receipts_created ON lumen_x402_receipts(created_at)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_x402_receipts_status ON lumen_x402_receipts(status,created_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_x402_redemptions (receipt_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, context_id TEXT NOT NULL, task_id TEXT NOT NULL, inbound_id TEXT NOT NULL, order_id TEXT NOT NULL, quote_id TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_a2a_quotes (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, context_id TEXT, service_id TEXT NOT NULL, amount_usd REAL NOT NULL, status TEXT NOT NULL, remote_metadata TEXT)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_a2a_inbound (id TEXT PRIMARY KEY, received_at TEXT NOT NULL, context_id TEXT NOT NULL, task_id TEXT NOT NULL, remote_message_id TEXT, remote_metadata TEXT, text TEXT NOT NULL, binding_intent INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, processed INTEGER NOT NULL DEFAULT 0, processed_at TEXT, bridge_status TEXT, opportunity_id TEXT, task_json TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_machine_orders (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, context_id TEXT NOT NULL, task_id TEXT NOT NULL, item_type TEXT NOT NULL, item_id TEXT NOT NULL, service_id TEXT NOT NULL, amount_usd REAL NOT NULL, billing TEXT NOT NULL, status TEXT NOT NULL, inbound_id TEXT NOT NULL, quote_id TEXT, remote_metadata TEXT)"),
  ]);
}

function publicCatalog(origin) {
  return {
    name: "LUMEN x402 Machine Checkout",
    version: VERSION,
    settlement: {
      protocol: "x402-v2",
      asset: "USDC",
      network: "Base",
      networkId: NETWORK,
      recipient: PAY_TO,
      facilitator: FACILITATOR,
      outgoingSpendEnabled: false,
    },
    products: Object.entries(PRODUCTS).map(([slug, p]) => ({
      ...p,
      currency: "USD",
      billing: "per_request",
      paidUrl: `${origin}/buy/${slug}`,
    })),
    flow: [
      "GET paidUrl",
      "receive HTTP 402 payment requirement",
      "retry with PAYMENT-SIGNATURE after signing USDC payment",
      "receive settled LUMEN receipt",
      "POST receiptId + requirement to /redeem",
      "LUMEN queues verified paid work for execution and delivery",
    ],
  };
}

async function createSettledReceipt(c, product) {
  await ensureSchema(c.env);
  const paymentSignature = c.req.header("payment-signature") || c.req.header("x-payment") || "";
  if (!paymentSignature) {
    return c.json({ ok:false, error:"x402 middleware passed request without payment credential" }, 500);
  }
  const fingerprint = await sha256Hex(paymentSignature);
  const existing = await c.env.DB.prepare("SELECT * FROM lumen_x402_receipts WHERE payment_fingerprint=? LIMIT 1").bind(fingerprint).first();
  if (existing) {
    return c.json({
      ok:true,
      duplicateSafe:true,
      paymentVerified:true,
      receiptId:existing.id,
      productId:existing.product_id,
      amountUsd:Number(existing.amount_usd),
      status:existing.status,
      nextAction:"POST /redeem with receiptId and requirement.",
    });
  }
  const receiptId = rid("X402R");
  const now = new Date().toISOString();
  const meta = {
    cfCountry: clean(c.req.header("cf-ipcountry"), 16),
    userAgent: clean(c.req.header("user-agent"), 300),
  };
  await c.env.DB.prepare("INSERT INTO lumen_x402_receipts(id,created_at,product_id,service_id,amount_usd,currency,network,pay_to,status,payment_fingerprint,request_metadata) VALUES(?,?,?,?,?,?,?,?,?,?,?)")
    .bind(receiptId, now, product.id, product.service_id, product.price_usd, "USD", NETWORK, PAY_TO, "settled_verified", fingerprint, JSON.stringify(meta)).run();
  return c.json({
    ok:true,
    paymentVerified:true,
    settlement:"x402_facilitator_verified_and_settled",
    receiptId,
    productId:product.id,
    productName:product.name,
    amountUsd:product.price_usd,
    currency:"USD",
    asset:"USDC",
    network:"Base",
    status:"settled_verified",
    nextAction:"POST /redeem with receiptId and requirement to start fulfillment.",
  });
}

app.get("/", (c) => c.json({
  ok:true,
  service:SERVICE,
  version:VERSION,
  purpose:"LUMEN seller-side x402 checkout",
  catalog:`${new URL(c.req.url).origin}/catalog`,
  recipientConfigured:true,
  network:"Base",
  networkId:NETWORK,
  asset:"USDC",
  facilitator:FACILITATOR,
  outgoingSpendEnabled:false,
}));

app.get("/health", async (c) => {
  await ensureSchema(c.env);
  return c.json({ ok:true, service:SERVICE, version:VERSION, x402:"LIVE", network:NETWORK, asset:"USDC", facilitator:FACILITATOR, recipientConfigured:true, outgoingSpendEnabled:false });
});

app.get("/catalog", (c) => c.json(publicCatalog(new URL(c.req.url).origin)));

for (const [slug, product] of Object.entries(PRODUCTS)) {
  app.get(`/buy/${slug}`, (c) => createSettledReceipt(c, product));
}

app.post("/redeem", async (c) => {
  await ensureSchema(c.env);
  let body = {};
  try { body = await c.req.json(); } catch { return c.json({ok:false,error:"Valid JSON body required"},400); }
  const receiptId = clean(body.receiptId || body.receipt_id, 80);
  const requirement = clean(body.requirement || body.request || body.input, 8000);
  if (!receiptId || !requirement) return c.json({ok:false,error:"receiptId and requirement are required"},400);

  const receipt = await c.env.DB.prepare("SELECT * FROM lumen_x402_receipts WHERE id=? LIMIT 1").bind(receiptId).first();
  if (!receipt) return c.json({ok:false,error:"Receipt not found"},404);
  if (!String(receipt.status).startsWith("settled") && receipt.status !== "redeemed_queued") {
    return c.json({ok:false,error:"Receipt is not in a settled state"},409);
  }
  const prior = await c.env.DB.prepare("SELECT * FROM lumen_x402_redemptions WHERE receipt_id=? LIMIT 1").bind(receiptId).first();
  if (prior) {
    return c.json({ok:true,duplicateSafe:true,receiptId,taskId:prior.task_id,orderId:prior.order_id,status:"already_redeemed"});
  }

  const product = Object.values(PRODUCTS).find(p => p.id === receipt.product_id);
  if (!product) return c.json({ok:false,error:"Receipt product is no longer available"},409);

  const now = new Date().toISOString();
  const contextId = rid("X402CTX");
  const taskId = rid("X402TASK");
  const inboundId = rid("A2AIN");
  const orderId = rid("MORD");
  const quoteId = rid("A2AQ");
  const metadata = {
    source:"a2a_machine_store",
    purpose:"commercial_x402_purchase",
    productId:product.id,
    lumen_product_id:product.id,
    lumen_service_id:product.service_id,
    lumen_item_type:"product",
    lumen_item_id:product.id,
    lumen_quote_usd:String(product.price_usd),
    lumen_quote_id:quoteId,
    lumen_billing:"per_request",
    lumen_seller_mode:"receive_revenue_only",
    payment_verified:"true",
    payment_method:"x402_usdc_base",
    x402_receipt_id:receiptId,
    charge_created:"true",
  };
  const task = {
    id:taskId,
    contextId,
    status:{
      state:"TASK_STATE_WORKING",
      timestamp:now,
      message:{
        messageId:rid("MSG"),
        contextId,
        taskId,
        role:"ROLE_AGENT",
        parts:[{text:`Paid ${product.name} request received and queued for fulfillment.`,mediaType:"text/plain"}],
      },
    },
    metadata:{
      lumen:true,
      paid:true,
      paymentVerified:true,
      paymentMethod:"x402_usdc_base",
      receiptId,
      sellerMode:"receive_revenue_only",
      lumenAutonomousSpend:false,
    },
  };

  try {
    await c.env.DB.batch([
      c.env.DB.prepare("INSERT INTO lumen_x402_redemptions(receipt_id,created_at,context_id,task_id,inbound_id,order_id,quote_id) VALUES(?,?,?,?,?,?,?)")
        .bind(receiptId,now,contextId,taskId,inboundId,orderId,quoteId),
      c.env.DB.prepare("UPDATE lumen_x402_receipts SET status='redeemed_queued', redeemed_at=? WHERE id=? AND status='settled_verified'")
        .bind(now,receiptId),
      c.env.DB.prepare("INSERT INTO lumen_a2a_quotes(id,created_at,context_id,service_id,amount_usd,status,remote_metadata) VALUES(?,?,?,?,?,?,?)")
        .bind(quoteId,now,contextId,product.service_id,product.price_usd,"PAID_VERIFIED",JSON.stringify(metadata)),
      c.env.DB.prepare("INSERT INTO lumen_a2a_inbound(id,received_at,context_id,task_id,remote_message_id,remote_metadata,text,binding_intent,status,processed,task_json) VALUES(?,?,?,?,?,?,?,?,?,0,?)")
        .bind(inboundId,now,contextId,taskId,rid("X402MSG"),JSON.stringify(metadata),requirement,0,"x402_paid_service_request",JSON.stringify(task)),
      c.env.DB.prepare("INSERT INTO lumen_machine_orders(id,created_at,context_id,task_id,item_type,item_id,service_id,amount_usd,billing,status,inbound_id,quote_id,remote_metadata) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)")
        .bind(orderId,now,contextId,taskId,"product",product.id,product.service_id,product.price_usd,"per_request","x402_paid_queued",inboundId,quoteId,JSON.stringify(metadata)),
    ]);
  } catch (error) {
    const priorAfterRace = await c.env.DB.prepare("SELECT * FROM lumen_x402_redemptions WHERE receipt_id=? LIMIT 1").bind(receiptId).first();
    if (priorAfterRace) return c.json({ok:true,duplicateSafe:true,receiptId,taskId:priorAfterRace.task_id,orderId:priorAfterRace.order_id,status:"already_redeemed"});
    return c.json({ok:false,error:"Could not queue paid request",detail:clean(error?.message,300)},500);
  }

  return c.json({
    ok:true,
    paymentVerified:true,
    receiptId,
    productId:product.id,
    serviceId:product.service_id,
    amountUsd:product.price_usd,
    taskId,
    orderId,
    status:"paid_queued_for_fulfillment",
    lumenAutonomousSpend:false,
  });
});

app.get("/receipt/:id", async (c) => {
  await ensureSchema(c.env);
  const id = clean(c.req.param("id"),80);
  const row = await c.env.DB.prepare("SELECT id,created_at,product_id,service_id,amount_usd,currency,network,status,redeemed_at FROM lumen_x402_receipts WHERE id=? LIMIT 1").bind(id).first();
  if (!row) return c.json({ok:false,error:"Receipt not found"},404);
  return c.json({ok:true,receipt:row});
});

app.get("/stats", async (c) => {
  await ensureSchema(c.env);
  const totals = await c.env.DB.prepare("SELECT COUNT(*) AS payments, COALESCE(SUM(amount_usd),0) AS revenue FROM lumen_x402_receipts").first();
  const redeemed = await c.env.DB.prepare("SELECT COUNT(*) AS n FROM lumen_x402_redemptions").first();
  return c.json({
    payments:Number(totals?.payments||0),
    realizedRevenueUsd:Number(totals?.revenue||0),
    redeemedOrders:Number(redeemed?.n||0),
    revenueRule:"Counted only after x402 middleware verifies and settles payment before the paid handler executes.",
    network:"Base",
    asset:"USDC",
    facilitator:FACILITATOR,
    recipient:PAY_TO,
  });
});

app.notFound((c) => c.json({ok:false,error:"not_found"},404));

export default app;
