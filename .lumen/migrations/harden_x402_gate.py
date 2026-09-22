from pathlib import Path


def main() -> None:
    path = Path('.lumen/x402-worker/worker-v2.js')
    text = path.read_text()
    changed = False

    # The x402 middleware must participate in Hono's middleware chain directly.
    # Calling it manually from another middleware can leave the Hono Context
    # unfinalized even when x402 has already built a valid 402 response.
    start_marker = '''// Lazy initialization is required on Workers: x402 must load facilitator\n'''
    end_marker = '''\nfunction publicCatalog(origin) {'''
    if start_marker not in text or end_marker not in text:
        raise SystemExit('missing x402 middleware block anchors')

    before, rest = text.split(start_marker, 1)
    old_block, after = rest.split(end_marker, 1)

    native_block = '''// Lazy initialization is required on Workers: x402 must load facilitator
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

    if (settlement?.success === true) {
      const row = await c.env.DB.prepare("SELECT request_metadata FROM lumen_x402_receipts WHERE payment_fingerprint=? LIMIT 1").bind(fingerprint).first();
      if (row) {
        let meta = {};
        try { meta = JSON.parse(row.request_metadata || "{}"); } catch {}
        meta.settlement = {
          success:true,
          transaction:clean(settlement.transaction,100),
          network:clean(settlement.network,80),
          payer:clean(settlement.payer,80),
          reconciled_at:new Date().toISOString(),
        };
        await c.env.DB.prepare("UPDATE lumen_x402_receipts SET status='settled_verified', request_metadata=? WHERE payment_fingerprint=?")
          .bind(JSON.stringify(meta), fingerprint).run();

        try {
          const settledReceipt=await c.env.DB.prepare("SELECT * FROM lumen_x402_receipts WHERE payment_fingerprint=? LIMIT 1").bind(fingerprint).first();
          const briefId=clean(meta?.conversion?.brief_id,80);
          if (settledReceipt && briefId) {
            const brief=await c.env.DB.prepare("SELECT id,email,company,details,product_id,product_slug FROM lumen_conversion_leads WHERE id=? AND product_id=? AND technical_canary=0 AND LENGTH(TRIM(COALESCE(details,'')))>=8 LIMIT 1").bind(briefId,settledReceipt.product_id).first();
            if (brief?.details) {
              const queued=await queuePaidReceipt(c.env,settledReceipt.id,brief.details,{source:"human_brief_auto",brief});
              meta.fulfillment={auto_queue:queued.ok===true,status:queued.status || queued.error || "unknown",task_id:queued.taskId || null,order_id:queued.orderId || null,brief_id:briefId,reconciled_at:new Date().toISOString()};
              await c.env.DB.prepare("UPDATE lumen_x402_receipts SET request_metadata=? WHERE id=?").bind(JSON.stringify(meta),settledReceipt.id).run();
            }
          }
        } catch (error) {
          meta.fulfillment={auto_queue:false,status:"queue_error",detail:clean(error?.message || error,300),reconciled_at:new Date().toISOString()};
          await c.env.DB.prepare("UPDATE lumen_x402_receipts SET request_metadata=? WHERE payment_fingerprint=?").bind(JSON.stringify(meta),fingerprint).run();
        }
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
'''

    rebuilt = before + native_block + end_marker + after
    if rebuilt != text:
        text = rebuilt
        changed = True

    # We initialize the resource server lazily above, so disable the middleware's
    # eager facilitator sync to avoid duplicate or startup-time network I/O.
    old_gate = '''const x402Gate = paymentMiddleware(\n  paidRoutes,\n  resourceServer,\n  undefined,\n  humanPaywall,\n);'''
    new_gate = '''const x402Gate = paymentMiddleware(\n  paidRoutes,\n  resourceServer,\n  undefined,\n  humanPaywall,\n  false,\n);'''
    if old_gate in text:
        text = text.replace(old_gate, new_gate, 1)
        changed = True
    elif new_gate not in text:
        raise SystemExit('missing x402 gate construction anchor')

    old_version = 'const VERSION = "1.4-x402-human-paywall";'
    new_version = 'const VERSION = "1.5-x402-native-hono-chain";'
    if old_version in text:
        text = text.replace(old_version, new_version, 1)
        changed = True

    if changed:
        path.write_text(text)
        print('x402 native Hono middleware composition applied')
    else:
        print('x402 native Hono middleware composition already current')


if __name__ == '__main__':
    main()
