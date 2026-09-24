import { Hono } from "hono";
import { paymentMiddleware } from "@x402/hono";
import { x402ResourceServer, HTTPFacilitatorClient } from "@x402/core/server";
import { ExactEvmScheme } from "@x402/evm/exact/server";
import { createPaywall } from "@x402/paywall";
import { evmPaywall } from "@x402/paywall/evm";

const VERSION = "1.0-referral-commission-x402";
const DEFAULT_NETWORK = "eip155:8453";
const DEFAULT_FACILITATOR = "https://facilitator.xpay.sh";

function clean(value, limit = 4000) { return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit); }
function rid(prefix) { return `${prefix}-${crypto.randomUUID().replaceAll("-", "").slice(0, 16).toUpperCase()}`; }
async function sha256Hex(value) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(String(value || "")));
  return [...new Uint8Array(digest)].map(x => x.toString(16).padStart(2, "0")).join("");
}
function decodeB64Json(value) {
  try {
    let raw = String(value || "").replace(/-/g, "+").replace(/_/g, "/");
    raw += "=".repeat((4 - raw.length % 4) % 4);
    return JSON.parse(atob(raw));
  } catch { return null; }
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_referral_commissions (id TEXT PRIMARY KEY,referral_id TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,basis_type TEXT NOT NULL,deal_value_usd REAL,proposed_rate_pct REAL,proposed_amount_usd REAL,agreed_rate_pct REAL,agreed_amount_usd REAL,currency TEXT NOT NULL DEFAULT 'USD',status TEXT NOT NULL,agreement_source TEXT,agreement_evidence TEXT,agreement_at TEXT,completion_evidence TEXT,payment_due_at TEXT,checkout_url TEXT,settlement_event_id TEXT,settled_amount_usd REAL NOT NULL DEFAULT 0,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_x402_receipts (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, product_id TEXT NOT NULL, service_id TEXT NOT NULL, amount_usd REAL NOT NULL, currency TEXT NOT NULL, network TEXT NOT NULL, pay_to TEXT NOT NULL, status TEXT NOT NULL, payment_fingerprint TEXT NOT NULL UNIQUE, redeemed_at TEXT, request_metadata TEXT)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_x402_receipts_status ON lumen_x402_receipts(status,created_at)")
  ]);
  return true;
}

function config(env) {
  return {
    network: clean(env?.X402_NETWORK || DEFAULT_NETWORK, 120),
    facilitator: clean(env?.X402_FACILITATOR || DEFAULT_FACILITATOR, 1000),
    payTo: clean(env?.X402_PAY_TO, 200),
  };
}

async function createPendingReceipt(c, commission, cfg) {
  const paymentSignature = c.req.header("payment-signature") || c.req.header("x-payment") || "";
  if (!paymentSignature) return c.json({ ok:false, error:"missing_payment_signature_after_gate" }, 500);
  const fingerprint = await sha256Hex(paymentSignature);
  const existing = await c.env.DB.prepare("SELECT * FROM lumen_x402_receipts WHERE payment_fingerprint=? LIMIT 1").bind(fingerprint).first();
  if (existing) {
    return c.json({ ok:true, duplicateSafe:true, paymentAuthorizationVerified:true, receiptId:existing.id, referralId:commission.referral_id, amountUsd:Number(existing.amount_usd), status:existing.status });
  }
  const receiptId = rid("X402C");
  const now = new Date().toISOString();
  const amount = Number(commission.agreed_amount_usd || 0);
  const meta = {
    source:"x402_referral_commission",
    authorization_verified:true,
    settlement_accounting:"await_payment_response_success",
    referral_id:commission.referral_id,
    commission_id:commission.id,
    commission_status:commission.status,
    conversion:{
      event_id:commission.referral_id,
      session_id:commission.id,
      campaign:commission.referral_id,
      source:"referral_broker",
      medium:"x402",
      creative:"success_fee"
    }
  };
  await c.env.DB.prepare("INSERT INTO lumen_x402_receipts(id,created_at,product_id,service_id,amount_usd,currency,network,pay_to,status,payment_fingerprint,request_metadata) VALUES(?,?,?,?,?,?,?,?,?,?,?)")
    .bind(receiptId,now,"REFERRAL-COMMISSION","SRV-B2B-BROKER",amount,"USD",cfg.network,cfg.payTo,"verified_pending_settlement",fingerprint,JSON.stringify(meta)).run();
  return c.json({ ok:true, paymentAuthorizationVerified:true, receiptId, referralId:commission.referral_id, commissionId:commission.id, amountUsd:amount, currency:"USD", asset:"USDC", network:"Base", status:"settlement_before_response", revenueRule:"recognized only after verified settlement" });
}

async function reconcileSettlement(env, request, response) {
  const paymentSignature = request.headers.get("payment-signature") || request.headers.get("x-payment") || "";
  if (!paymentSignature) return;
  const paymentResponse = response?.headers?.get("payment-response") || response?.headers?.get("x-payment-response") || "";
  if (!paymentResponse) return;
  const settlement = decodeB64Json(paymentResponse);
  const fingerprint = await sha256Hex(paymentSignature);
  if (settlement?.success === true) {
    const row = await env.DB.prepare("SELECT request_metadata FROM lumen_x402_receipts WHERE payment_fingerprint=? LIMIT 1").bind(fingerprint).first();
    if (!row) return;
    let meta = {};
    try { meta = JSON.parse(row.request_metadata || "{}"); } catch {}
    meta.settlement = {
      success:true,
      transaction:clean(settlement.transaction, 100),
      network:clean(settlement.network, 80),
      payer:clean(settlement.payer, 100),
      reconciled_at:new Date().toISOString()
    };
    await env.DB.prepare("UPDATE lumen_x402_receipts SET status='settled_verified',request_metadata=? WHERE payment_fingerprint=?")
      .bind(JSON.stringify(meta),fingerprint).run();
  } else {
    await env.DB.prepare("UPDATE lumen_x402_receipts SET status='settlement_failed' WHERE payment_fingerprint=? AND status='verified_pending_settlement'")
      .bind(fingerprint).run();
  }
}

export async function handleCommissionCheckout(request, env) {
  const url = new URL(request.url);
  if (!url.pathname.startsWith("/commission/")) return null;
  if (request.method === "OPTIONS") return new Response(null, { status:204, headers:{ "access-control-allow-origin":"*", "access-control-allow-methods":"GET,OPTIONS", "access-control-allow-headers":"content-type,payment-signature,x-payment" } });
  if (request.method !== "GET") return Response.json({ ok:false, error:"method_not_allowed" }, { status:405, headers:{"cache-control":"no-store","access-control-allow-origin":"*"} });
  if (!(await ensureSchema(env))) return Response.json({ ok:false, error:"persistence_unavailable" }, { status:503 });

  const referralId = clean(decodeURIComponent(url.pathname.slice("/commission/".length)), 100);
  if (!referralId) return Response.json({ ok:false, error:"referral_id_required" }, { status:400 });
  const commission = await env.DB.prepare("SELECT * FROM lumen_referral_commissions WHERE referral_id=? LIMIT 1").bind(referralId).first();
  if (!commission) return Response.json({ ok:false, error:"commission_not_found" }, { status:404, headers:{"cache-control":"no-store","access-control-allow-origin":"*"} });
  if (commission.status === "SETTLED") return Response.json({ ok:true, referralId, commissionId:commission.id, status:"SETTLED", duplicateSafe:true }, { status:200, headers:{"cache-control":"no-store","access-control-allow-origin":"*"} });
  if (commission.status !== "PAYMENT_DUE") return Response.json({ ok:false, error:"commission_not_payable_yet", status:commission.status }, { status:409, headers:{"cache-control":"no-store","access-control-allow-origin":"*"} });
  const amount = Number(commission.agreed_amount_usd || 0);
  if (!(amount > 0)) return Response.json({ ok:false, error:"agreed_amount_missing" }, { status:409 });

  const cfg = config(env);
  if (!cfg.payTo) return Response.json({ ok:false, error:"payment_recipient_not_configured" }, { status:503 });

  const facilitatorClient = new HTTPFacilitatorClient({ url:cfg.facilitator });
  const resourceServer = new x402ResourceServer(facilitatorClient).register(cfg.network, new ExactEvmScheme());
  try { await resourceServer.initialize(); }
  catch (error) { return Response.json({ ok:false, error:"x402_facilitator_initialization_failed", detail:clean(error?.message || error, 300), paymentAttempted:false }, { status:503, headers:{"cache-control":"no-store","access-control-allow-origin":"*"} }); }

  const path = `/commission/${encodeURIComponent(referralId)}`;
  const paidRoutes = {
    [`GET ${path}`]: {
      accepts:[{ scheme:"exact", price:`$${amount.toFixed(2)}`, network:cfg.network, payTo:cfg.payTo, extra:{assetTransferMethod:"eip3009"} }],
      description:`LUMEN B2B broker success fee for ${referralId}`,
      mimeType:"application/json"
    }
  };
  const humanPaywall = createPaywall().withNetwork(evmPaywall).withConfig({ appName:"LUMEN", testnet:false }).build();
  const gate = paymentMiddleware(paidRoutes, resourceServer, undefined, humanPaywall, false);
  const app = new Hono();
  app.use("*", gate);
  app.get("*", (c) => createPendingReceipt(c, commission, cfg));
  app.notFound((c) => c.json({ok:false,error:"not_found"},404));

  const response = await app.fetch(request, env);
  try { await reconcileSettlement(env, request, response); } catch (error) { console.error("commission_x402_reconciliation_error", error); }
  response.headers.set("access-control-allow-origin", "*");
  response.headers.set("cache-control", "no-store");
  response.headers.set("x-content-type-options", "nosniff");
  response.headers.set("x-lumen-commission-checkout-version", VERSION);
  return response;
}
