from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"missing patch anchor: {label}")
    return text.replace(old, new, 1)


def main() -> None:
    # Conversion: carry the exact customer brief ID into x402.
    p = Path('.lumen/conversion-worker/worker.js')
    s = p.read_text()
    s = replace_once(
        s,
        'return Response.json({ok:true,service:SERVICE,version:VERSION,x402:X402_BASE,paidSpend:false,crmBridge:true,productContractVersion:PRODUCT_CONTRACT_VERSION,requirementsBeforeHumanCheckout:true},{headers});',
        'return Response.json({ok:true,service:SERVICE,version:VERSION,x402:X402_BASE,paidSpend:false,crmBridge:true,productContractVersion:PRODUCT_CONTRACT_VERSION,requirementsBeforeHumanCheckout:true,briefLinkedCheckout:true},{headers});',
        'conversion health flag',
    )
    s = replace_once(
        s,
        '''        if (!attr.technical_canary) {
          const requirement=await env.DB.prepare("SELECT id FROM lumen_conversion_leads WHERE session_id=? AND product_slug=? AND technical_canary=0 AND LENGTH(TRIM(COALESCE(details,'')))>=8 ORDER BY created_at DESC LIMIT 1").bind(sid,slug).first();
          if (!requirement) { const q=qs(attr); headers.set("location",`/offer/${slug}${q?`?${q}`:""}`); return new Response(null,{status:303,headers}); }
        }
        const eventId=await recordEvent(env,"checkout_started",sid,slug,attr,{destination:`${X402_BASE}/buy/${slug}`,requirementsCaptured:true});
        const target=new URL(`${X402_BASE}/buy/${slug}`);
        target.searchParams.set("conversion_event",eventId);
        target.searchParams.set("conversion_session",sid);''',
        '''        const requestedBriefId=clean(url.searchParams.get("brief_id"),80);
        let brief=null;
        if (!attr.technical_canary) {
          brief=requestedBriefId
            ? await env.DB.prepare("SELECT id,email,company,details FROM lumen_conversion_leads WHERE id=? AND session_id=? AND product_slug=? AND technical_canary=0 AND LENGTH(TRIM(COALESCE(details,'')))>=8 LIMIT 1").bind(requestedBriefId,sid,slug).first()
            : await env.DB.prepare("SELECT id,email,company,details FROM lumen_conversion_leads WHERE session_id=? AND product_slug=? AND technical_canary=0 AND LENGTH(TRIM(COALESCE(details,'')))>=8 ORDER BY created_at DESC LIMIT 1").bind(sid,slug).first();
          if (!brief) { const q=qs(attr); headers.set("location",`/offer/${slug}${q?`?${q}`:""}`); return new Response(null,{status:303,headers}); }
        }
        const briefId=clean(brief?.id || requestedBriefId,80);
        const eventId=await recordEvent(env,"checkout_started",sid,slug,attr,{destination:`${X402_BASE}/buy/${slug}`,requirementsCaptured:true,brief_id:briefId});
        const target=new URL(`${X402_BASE}/buy/${slug}`);
        target.searchParams.set("conversion_event",eventId);
        target.searchParams.set("conversion_session",sid);
        if (briefId) target.searchParams.set("brief_id",briefId);''',
        'conversion checkout brief linkage',
    )
    s = replace_once(
        s,
        '''        const q=qs(attr); const go=`/go/${slug}${q?`?${q}`:""}`;
        if (next === "checkout") { await recordEvent(env,"requirements_captured",sid,slug,attr,{lead_id:leadId}); headers.set("location",go); return new Response(null,{status:303,headers}); }''',
        '''        const qparams=new URLSearchParams(qs(attr));
        qparams.set("brief_id",leadId);
        const go=`/go/${slug}?${qparams.toString()}`;
        if (next === "checkout") { await recordEvent(env,"requirements_captured",sid,slug,attr,{lead_id:leadId,brief_id:leadId}); headers.set("location",go); return new Response(null,{status:303,headers}); }''',
        'conversion intent brief linkage',
    )
    p.write_text(s)

    # x402: retain brief ID in receipt attribution and automatically queue the
    # exact paid brief only after settlement is confirmed.
    p = Path('.lumen/x402-worker/worker-v2.js')
    s = p.read_text()
    s = replace_once(
        s,
        '''    creative: clean(url.searchParams.get("creative"), 120),
  };''',
        '''    creative: clean(url.searchParams.get("creative"), 120),
    brief_id: clean(url.searchParams.get("brief_id"), 80),
  };''',
        'x402 attribution brief id',
    )
    s = replace_once(
        s,
        '''    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_x402_redemptions (receipt_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, context_id TEXT NOT NULL, task_id TEXT NOT NULL, inbound_id TEXT NOT NULL, order_id TEXT NOT NULL, quote_id TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_a2a_quotes''',
        '''    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_x402_redemptions (receipt_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, context_id TEXT NOT NULL, task_id TEXT NOT NULL, inbound_id TEXT NOT NULL, order_id TEXT NOT NULL, quote_id TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_conversion_leads (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, session_id TEXT NOT NULL, product_id TEXT NOT NULL, product_slug TEXT NOT NULL, email TEXT NOT NULL, company TEXT, details TEXT, source TEXT NOT NULL, medium TEXT NOT NULL, campaign TEXT, creative TEXT, status TEXT NOT NULL DEFAULT 'new', technical_canary INTEGER NOT NULL DEFAULT 0)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_a2a_quotes''',
        'x402 shared conversion leads table',
    )
    s = replace_once(
        s,
        '''        await c.env.DB.prepare("UPDATE lumen_x402_receipts SET status='settled_verified', request_metadata=? WHERE payment_fingerprint=?")
          .bind(JSON.stringify(meta), fingerprint).run();''',
        '''        await c.env.DB.prepare("UPDATE lumen_x402_receipts SET status='settled_verified', request_metadata=? WHERE payment_fingerprint=?")
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
          meta.fulfillment={auto_queue:false,status:"queue_error",detail:clean(error?.message,300),reconciled_at:new Date().toISOString()};
          await c.env.DB.prepare("UPDATE lumen_x402_receipts SET request_metadata=? WHERE payment_fingerprint=?").bind(JSON.stringify(meta),fingerprint).run();
        }''',
        'x402 settlement autoqueue',
    )
    s = replace_once(
        s,
        '''    conversionAttribution:true, humanPaywall:true,
  });''',
        '''    conversionAttribution:true, humanPaywall:true, briefLinkedFulfillment:true,
  });''',
        'x402 health flag',
    )

    if 'async function queuePaidReceipt(' not in s:
        start = s.index('app.post("/redeem", async (c) => {')
        end = s.index('app.get("/receipt/:id", async (c) => {')
        replacement = r'''async function queuePaidReceipt(env, receiptIdRaw, requirementRaw, options={}) {
  await ensureSchema(env);
  const receiptId=clean(receiptIdRaw,80);
  const requirement=clean(requirementRaw,8000);
  if (!receiptId || !requirement) return {ok:false,statusCode:400,error:"receiptId and requirement are required"};
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

'''
        s = s[:start] + replacement + s[end:]

    s = s.replace('"POST receiptId + requirement to /redeem for fulfillment",', '"human checkout: linked brief auto-queues only after verified settlement; machine clients may POST /redeem",', 1)
    s = s.replace('nextAction:"After settlement success, POST /redeem with receiptId and requirement.",', 'nextAction:"Linked human briefs auto-queue after settlement; machine clients may POST /redeem.",', 1)
    s = s.replace('nextAction:"When this response succeeds, settlement is reconciled server-side; POST /redeem with receiptId and requirement.",', 'nextAction:"Settlement is reconciled server-side. Linked human briefs auto-queue; machine clients may POST /redeem.",', 1)
    p.write_text(s)
    print('brief-payment migration applied')


if __name__ == '__main__':
    main()
