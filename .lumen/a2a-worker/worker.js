const SERVICE = "lumen-zero-a2a";
const VERSION = "2.1-zero-a2a-machine-store-truth";
const PROTOCOL_VERSION = "1.0";
const RATE_LIMIT_PER_HOUR = 30;
const MAX_BODY_BYTES = 65536;
const MAX_TEXT = 8000;
const QUOTE_VALID_HOURS = 24;

const SERVICE_CATALOG = [
  { id:"SRV-QUOTECHECK", name:"LUMEN QuoteCheck Global", from_usd:59, desc:"Review and structured comparison of B2B quotations using available public references." },
  { id:"SRV-SUPPLIERCHECK", name:"LUMEN SupplierCheck", from_usd:79, desc:"Supplier identity, official channels, public signals and commercial-risk research." },
  { id:"SRV-TENDER-HUNTER", name:"LUMEN Tender Hunter Global", from_usd:99, desc:"Detection and pre-analysis of relevant public tenders and opportunities." },
  { id:"SRV-SOURCING-EXPRESS", name:"LUMEN Sourcing Express", from_usd:149, desc:"Supplier research and preselection for a concrete B2B requirement." },
  { id:"SRV-B2B-PROSPECTING", name:"LUMEN B2B Prospecting", from_usd:199, desc:"Target companies, public buying signals and verified corporate channels compatible with a B2B offer." },
  { id:"SRV-EXPORT-SCOUT", name:"LUMEN Export Scout", from_usd:249, desc:"Market, importer, distributor and buyer discovery using public evidence." },
];

const MACHINE_PRODUCTS = [
  { id:"MP-SUPPLIER-SNAPSHOT", name:"Supplier Snapshot", price_usd:5, service_id:"SRV-SUPPLIERCHECK", billing:"per_request", desc:"Fast supplier identity and official-channel snapshot for one named company or domain." },
  { id:"MP-QUOTE-SANITY", name:"Quote Sanity Check", price_usd:7, service_id:"SRV-QUOTECHECK", billing:"per_request", desc:"Structured sanity check of one B2B quotation against supplied facts and available public references." },
  { id:"MP-TENDER-SCAN", name:"Tender Quick Scan", price_usd:9, service_id:"SRV-TENDER-HUNTER", billing:"per_request", desc:"Focused public-opportunity scan for one product/category and target market." },
  { id:"MP-SOURCING-5", name:"Supplier Shortlist 5", price_usd:15, service_id:"SRV-SOURCING-EXPRESS", billing:"per_request", desc:"Research-oriented shortlist of up to five supplier candidates for a concrete requirement." },
  { id:"MP-BUYER-SIGNALS", name:"Buyer Signal Scan", price_usd:19, service_id:"SRV-B2B-PROSPECTING", billing:"per_request", desc:"Public buying-signal and target-company scan for one B2B offer/category." },
  { id:"MP-EXPORT-PULSE", name:"Export Market Pulse", price_usd:25, service_id:"SRV-EXPORT-SCOUT", billing:"per_request", desc:"Compact market/importer/distributor pulse for one product and destination market." },
];

const RECURRING_PLANS = [
  { id:"PLAN-TENDER-WATCH", name:"Tender Watch", price_usd:29, interval:"month", service_id:"SRV-TENDER-HUNTER", desc:"Recurring monitoring brief for one defined tender/opportunity category." },
  { id:"PLAN-SUPPLIER-WATCH", name:"Supplier Watch", price_usd:39, interval:"month", service_id:"SRV-SUPPLIERCHECK", desc:"Recurring public-signal watch for a defined supplier set or supplier category." },
  { id:"PLAN-BUYER-WATCH", name:"Buyer Watch", price_usd:59, interval:"month", service_id:"SRV-B2B-PROSPECTING", desc:"Recurring buyer and demand-signal watch for one commercial offer/category." },
  { id:"PLAN-EXPORT-RADAR", name:"Export Radar", price_usd:79, interval:"month", service_id:"SRV-EXPORT-SCOUT", desc:"Recurring market/importer/distributor opportunity radar for one export category." },
];

const SERVICE_BY_ID = Object.fromEntries(SERVICE_CATALOG.map(x => [x.id, x]));
const PRODUCT_BY_ID = Object.fromEntries(MACHINE_PRODUCTS.map(x => [x.id, x]));
const PLAN_BY_ID = Object.fromEntries(RECURRING_PLANS.map(x => [x.id, x]));

function json(data, status = 200, extra = {}) {
  return Response.json(data, { status, headers: { "cache-control":"no-store", "x-content-type-options":"nosniff", "access-control-allow-origin":"*", "A2A-Version":PROTOCOL_VERSION, ...extra } });
}
function rpcError(id, code, message, status = 200) { return json({ jsonrpc:"2.0", id:id ?? null, error:{code,message} }, status); }
function clean(value, limit = 8000) { return String(value ?? "").trim().replace(/\s+/g," ").slice(0,limit); }
function safeMetadata(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const out = {};
  for (const [k,v] of Object.entries(value).slice(0,40)) out[clean(k,80)] = clean(typeof v === "string" ? v : JSON.stringify(v),700);
  return out;
}
function partsText(message) {
  const chunks=[];
  for (const p of Array.isArray(message?.parts) ? message.parts : []) {
    if (typeof p?.text === "string") chunks.push(p.text);
    else if (p?.data != null) chunks.push(typeof p.data === "string" ? p.data : JSON.stringify(p.data));
  }
  return clean(chunks.join(" "),MAX_TEXT);
}
function bindingIntent(text) {
  const low=text.toLowerCase();
  return ["accept contract","accept terms","place order","purchase order","make payment","authorize payment","sign contract","binding agreement","aceptar contrato","aceptar términos","aceptar terminos","orden de compra","realizar pago","autorizar pago","firmar contrato","acuerdo vinculante","cerrar trato","confirm purchase"].some(x=>low.includes(x));
}
function moneySummary(rows, key) {
  const values=rows.map(x=>Number(x[key]||0)).filter(x=>Number.isFinite(x));
  return { floor_usd:Math.min(...values), ceiling_usd:Math.max(...values), average_usd:Number((values.reduce((a,b)=>a+b,0)/values.length).toFixed(2)) };
}
function paymentsStatus(env) {
  const recipient=clean(env?.X402_PAY_TO,180);
  const configured=/^0x[a-fA-F0-9]{40}$/.test(recipient);
  return {
    sellerMode:"receive_revenue_only",
    outgoingSpendEnabled:false,
    x402:{
      status:configured?"READY":"SETUP_REQUIRED",
      configured,
      network:clean(env?.X402_NETWORK || "base",60),
      facilitator:clean(env?.X402_FACILITATOR || "https://x402.org/facilitator",240),
      recipientConfigured:configured,
      requirement:configured?null:"A valid merchant recipient wallet address is required before x402 can collect real payments."
    },
    existingSettlement:{
      status:"AVAILABLE_AFTER_COMMERCIAL_VALIDATION",
      note:"Existing LUMEN settlement rails remain controlled by the canonical revenue/payment runtime and are never exposed from this public endpoint."
    },
    chargeCreatedByCatalogOrQuote:false,
    autonomousPurchase:false,
    autonomousOutgoingPayment:false,
    bindingActionsHumanGated:true
  };
}
function machineCatalog(origin, env) {
  return {
    name:"LUMEN Machine Store",
    version:VERSION,
    mode:"agent_consumable_b2b_intelligence",
    currency:"USD",
    machineProducts:MACHINE_PRODUCTS,
    recurringPlans:RECURRING_PLANS,
    pricing:{ machine:moneySummary(MACHINE_PRODUCTS,"price_usd"), recurring:moneySummary(RECURRING_PLANS,"price_usd") },
    protocol:{
      catalog:`${origin}/machine/catalog`,
      serviceCatalog:`${origin}/seller/catalog`,
      quoteProduct:"JSON-RPC QuoteMachineProduct",
      quotePlan:"JSON-RPC QuoteRecurringPlan",
      request:"A2A SendMessage with metadata.productId or metadata.planId",
      status:"GetTask / tasks/get",
      payments:`${origin}/payments/status`
    },
    payments:paymentsStatus(env),
    guardrails:{ noAutonomousSpend:true, noAutonomousPurchase:true, noBindingAcceptance:true, externalClaimsUntrustedUntilVerified:true }
  };
}
function sellerCatalog(origin, env) {
  return {
    sellerMode:"receive_revenue_only",
    version:VERSION,
    currency:"USD",
    quoteValidityHours:QUOTE_VALID_HOURS,
    services:SERVICE_CATALOG,
    pricing:moneySummary(SERVICE_CATALOG,"from_usd"),
    machineStore:`${origin}/machine/catalog`,
    recurringPlans:RECURRING_PLANS,
    serviceRequestProtocol:{ discover:`${origin}/seller/catalog`, quote:"JSON-RPC QuoteService", request:"A2A SendMessage with metadata.serviceId", taskStatus:"GetTask / tasks/get" },
    settlement:paymentsStatus(env)
  };
}
function quoteFor(item, itemType, contextId="") {
  const created=new Date();
  const validUntil=new Date(created.getTime()+QUOTE_VALID_HOURS*3600*1000);
  const amount=Number(item.from_usd ?? item.price_usd ?? 0);
  const effectiveServiceId=item.service_id || item.id;
  return {
    quoteId:`A2AQ-${crypto.randomUUID().replaceAll("-","").slice(0,12).toUpperCase()}`,
    contextId:clean(contextId,160)||null,
    itemType,
    itemId:item.id,
    itemName:item.name,
    serviceId:effectiveServiceId,
    amount,
    currency:"USD",
    billing:item.interval?`per_${item.interval}`:(item.billing||"fixed_scope"),
    pricingType:itemType==="service"?"launch_floor_fixed_scope":"machine_store_launch_price",
    status:"NON_BINDING_QUOTE",
    createdAt:created.toISOString(),
    validUntil:validUntil.toISOString(),
    chargeCreated:false,
    nextAction:"SendMessage with the quoted item identifier and the concrete requirement. LUMEN will verify scope and counterparty before settlement or delivery.",
    lumenAutonomousSpend:false,
    bindingActionsHumanGated:true
  };
}
function agentCard(origin, env) {
  const endpoint=`${origin}/a2a/v1`;
  return {
    protocolVersion:PROTOCOL_VERSION,
    name:"LUMEN B2B Agent",
    description:"Autonomous seller-side B2B intelligence and sourcing agent. LUMEN exposes productized full services, low-cost machine-consumable intelligence products and recurring monitoring plans. It can quote, receive service requests and route them into verification and delivery workflows. LUMEN never autonomously spends funds or accepts binding buyer-side commitments.",
    url:endpoint,
    preferredTransport:"JSONRPC",
    supportedInterfaces:[{url:endpoint,protocolBinding:"JSONRPC",protocolVersion:"1.0"},{url:endpoint,protocolBinding:"JSONRPC",protocolVersion:"0.3"}],
    provider:{organization:"LUMEN B2B",url:origin},
    version:VERSION,
    documentationUrl:`${origin}/machine/catalog`,
    capabilities:{streaming:false,pushNotifications:false,extendedAgentCard:false},
    defaultInputModes:["text/plain","application/json"],
    defaultOutputModes:["text/plain","application/json"],
    metadata:{
      sellerMode:"receive_revenue_only",
      serviceCatalogUrl:`${origin}/seller/catalog`,
      machineCatalogUrl:`${origin}/machine/catalog`,
      paymentsStatusUrl:`${origin}/payments/status`,
      quoteMethods:["QuoteService","QuoteMachineProduct","QuoteRecurringPlan"],
      autonomousSpend:false,
      bindingActionsHumanGated:true,
      x402Status:paymentsStatus(env).x402.status
    },
    skills:[
      {id:"lumen-machine-store",name:"LUMEN Machine Store",description:"Discover low-cost per-request B2B intelligence products and recurring monitoring plans designed for agent consumption.",tags:["machine-commerce","paid-service","b2b","procurement","sourcing","seller-mode"]},
      {id:"lumen-paid-service-catalog",name:"LUMEN paid B2B intelligence catalog",description:"Discover six full B2B intelligence and sourcing services with machine-readable USD launch pricing.",tags:["b2b","paid-service","catalog","quote","seller-mode","procurement"]},
      {id:"supplier-rfq-exchange",name:"Supplier RFQ exchange",description:"Receive and structure non-binding supplier quotation requests and clarification exchanges.",tags:["rfq","supplier","quotation","procurement","sourcing"]},
      {id:"buyer-requirement-intake",name:"Buyer requirement intake",description:"Receive a buyer need and route it into verification and sourcing.",tags:["buyer","requirements","sourcing","procurement","demand"]},
      {id:"commercial-opportunity-exchange",name:"Commercial opportunity exchange",description:"Receive non-binding buyer requirements or supplier capabilities and route complete packets into LUMEN verification.",tags:["commercial-opportunity","buyer-demand","supplier-capability","verification","b2b"]}
    ]
  };
}
async function ensureSchema(env) {
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_a2a_inbound (id TEXT PRIMARY KEY, received_at TEXT NOT NULL, context_id TEXT NOT NULL, task_id TEXT NOT NULL, remote_message_id TEXT, remote_metadata TEXT, text TEXT NOT NULL, binding_intent INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, processed INTEGER NOT NULL DEFAULT 0, processed_at TEXT, bridge_status TEXT, opportunity_id TEXT, task_json TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_a2a_pending ON lumen_a2a_inbound(processed,received_at)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_a2a_task ON lumen_a2a_inbound(task_id,received_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_a2a_rate (bucket TEXT PRIMARY KEY, hits INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_a2a_quotes (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, context_id TEXT, service_id TEXT NOT NULL, amount_usd REAL NOT NULL, status TEXT NOT NULL, remote_metadata TEXT)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_a2a_quotes_created ON lumen_a2a_quotes(created_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_machine_orders (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, context_id TEXT NOT NULL, task_id TEXT NOT NULL, item_type TEXT NOT NULL, item_id TEXT NOT NULL, service_id TEXT NOT NULL, amount_usd REAL NOT NULL, billing TEXT NOT NULL, status TEXT NOT NULL, inbound_id TEXT NOT NULL, quote_id TEXT, remote_metadata TEXT)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_machine_orders_status ON lumen_machine_orders(status,created_at)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_machine_orders_item ON lumen_machine_orders(item_id,created_at)")
  ]);
}
async function rateAllowed(request, env) {
  const ip=clean(request.headers.get("CF-Connecting-IP")||"unknown",100);
  const hour=new Date().toISOString().slice(0,13);
  const bucket=`${hour}|${ip}`;
  await env.DB.prepare("INSERT INTO lumen_a2a_rate(bucket,hits,updated_at) VALUES(?,1,?) ON CONFLICT(bucket) DO UPDATE SET hits=hits+1,updated_at=excluded.updated_at").bind(bucket,new Date().toISOString()).run();
  const row=await env.DB.prepare("SELECT hits FROM lumen_a2a_rate WHERE bucket=?").bind(bucket).first();
  return Number(row?.hits||0)<=RATE_LIMIT_PER_HOUR;
}
function taskReply(contextId,taskId,state,text,data={}) {
  const message={messageId:crypto.randomUUID(),contextId,taskId,role:"ROLE_AGENT",parts:[{text,mediaType:"text/plain"},{data,mediaType:"application/json"}],metadata:{lumenMode:"seller_nonbinding_b2b",sellerMode:"receive_revenue_only",humanGateForBindingActions:true,lumenAutonomousSpend:false,agentGatewayVersion:VERSION}};
  return {id:taskId,contextId,status:{state,message,timestamp:new Date().toISOString()},history:[message],metadata:{lumen:true,nonbinding:true,sellerMode:"receive_revenue_only",bindingActionsHumanGated:true,lumenAutonomousSpend:false,bridgeStatus:"queued_for_verification"}};
}
async function persistQuote(env,quote,metadata={}) {
  await env.DB.prepare("INSERT OR IGNORE INTO lumen_a2a_quotes(id,created_at,context_id,service_id,amount_usd,status,remote_metadata) VALUES(?,?,?,?,?,?,?)")
    .bind(quote.quoteId,quote.createdAt,quote.contextId,quote.serviceId,quote.amount,quote.status,JSON.stringify({...metadata,itemType:quote.itemType,itemId:quote.itemId,billing:quote.billing})).run();
}
async function quoteRpc(payload,env,kind) {
  const id=payload?.id ?? null;
  const params=payload?.params && typeof payload.params==="object" ? payload.params : {};
  let item=null;
  if (kind==="service") item=SERVICE_BY_ID[clean(params.serviceId||params.service_id,80)];
  if (kind==="product") item=PRODUCT_BY_ID[clean(params.productId||params.product_id,80)];
  if (kind==="plan") item=PLAN_BY_ID[clean(params.planId||params.plan_id,80)];
  if (!item) return rpcError(id,-32602,`Unknown ${kind} identifier. Fetch the relevant catalog first.`);
  const quote=quoteFor(item,kind,clean(params.contextId||params.context_id,160));
  await persistQuote(env,quote,safeMetadata(params.metadata));
  return json({jsonrpc:"2.0",id,result:{quote,payments:paymentsStatus(env)}});
}
async function persistMachineOrder(env,{contextId,taskId,inboundId,itemType,item,quote,metadata}) {
  if (!item || itemType==="service") return;
  await env.DB.prepare("INSERT OR IGNORE INTO lumen_machine_orders(id,created_at,context_id,task_id,item_type,item_id,service_id,amount_usd,billing,status,inbound_id,quote_id,remote_metadata) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)")
    .bind(`MORD-${crypto.randomUUID().replaceAll("-","").slice(0,12).toUpperCase()}`,new Date().toISOString(),contextId,taskId,itemType,item.id,item.service_id,quote.amount,quote.billing,"received_unverified",inboundId,quote.quoteId,JSON.stringify(metadata||{})).run();
}
async function sendMessage(payload,env) {
  const id=payload?.id ?? null;
  const message=payload?.params?.message;
  if (!message || !Array.isArray(message.parts) || message.parts.length===0) return rpcError(id,-32602,"Invalid parameters: message.parts is required");
  const text=partsText(message);
  if (!text) return rpcError(id,-32602,"Invalid parameters: message text/data is required");
  const contextId=clean(message.contextId||crypto.randomUUID(),160);
  const taskId=clean(message.taskId||crypto.randomUUID(),160);
  const inboundId=`A2AIN-${crypto.randomUUID().replaceAll("-","").slice(0,12).toUpperCase()}`;
  const binding=bindingIntent(text);
  const metadata=safeMetadata(message.metadata);
  const service=SERVICE_BY_ID[clean(metadata.serviceId||metadata.service_id,80)]||null;
  const product=PRODUCT_BY_ID[clean(metadata.productId||metadata.product_id,80)]||null;
  const plan=PLAN_BY_ID[clean(metadata.planId||metadata.plan_id,80)]||null;
  const item=product||plan||service;
  const itemType=product?"product":plan?"plan":service?"service":"";
  const effectiveServiceId=item ? (item.service_id||item.id) : "";
  let quote=null;
  if (item && !binding) {
    quote=quoteFor(item,itemType,contextId);
    await persistQuote(env,quote,metadata);
  }
  const state=binding?"TASK_STATE_INPUT_REQUIRED":"TASK_STATE_WORKING";
  const replyText=binding
    ? "LUMEN received the request. Purchases, outgoing payments, contracts and binding acceptance require explicit human approval. Non-binding commercial analysis can continue."
    : item
      ? `LUMEN received ${item.name}. Non-binding launch quote: USD ${quote.amount}${item.interval?`/${item.interval}`:""}. No charge was created by this message. The request is queued for scope, counterparty and evidence verification.`
      : "LUMEN received the non-binding B2B message. Agents can discover machine products at /machine/catalog, full services at /seller/catalog, request a quote by JSON-RPC, and then send the concrete requirement with metadata.productId, metadata.planId or metadata.serviceId.";
  const taskData={acceptedMode:"nonbinding",sellerMode:"receive_revenue_only",queuedForVerification:true,inboundId,bindingActionsHumanGated:true,lumenAutonomousSpend:false};
  if (item) taskData.commercialItem={itemType,itemId:item.id,itemName:item.name,serviceId:effectiveServiceId,priceUsd:quote.amount,billing:quote.billing};
  if (quote) taskData.quote=quote;
  taskData.payments=paymentsStatus(env);
  const task=taskReply(contextId,taskId,state,replyText,taskData);
  const storedMetadata={...metadata};
  if (item) {
    storedMetadata.lumen_service_id=effectiveServiceId;
    storedMetadata.lumen_item_type=itemType;
    storedMetadata.lumen_item_id=item.id;
    storedMetadata.lumen_product_id=product?.id||"";
    storedMetadata.lumen_plan_id=plan?.id||"";
    storedMetadata.lumen_quote_usd=String(quote.amount);
    storedMetadata.lumen_quote_id=quote.quoteId;
    storedMetadata.lumen_billing=quote.billing;
    storedMetadata.lumen_seller_mode="receive_revenue_only";
  }
  await env.DB.prepare("INSERT INTO lumen_a2a_inbound(id,received_at,context_id,task_id,remote_message_id,remote_metadata,text,binding_intent,status,processed,task_json) VALUES(?,?,?,?,?,?,?,?,?,0,?)")
    .bind(inboundId,new Date().toISOString(),contextId,taskId,clean(message.messageId,180),JSON.stringify(storedMetadata),text,binding?1:0,binding?"human_gate_required":item?"priced_service_request_received":"received_nonbinding",JSON.stringify(task)).run();
  if (item && !binding) await persistMachineOrder(env,{contextId,taskId,inboundId,itemType,item,quote,metadata:storedMetadata});
  return json({jsonrpc:"2.0",id,result:{task}});
}
async function getTask(payload,env) {
  const id=payload?.id ?? null;
  const taskId=clean(payload?.params?.id,160);
  if (!taskId) return rpcError(id,-32602,"Task id is required");
  const row=await env.DB.prepare("SELECT task_json FROM lumen_a2a_inbound WHERE task_id=? ORDER BY received_at DESC LIMIT 1").bind(taskId).first();
  if (!row?.task_json) return rpcError(id,-32001,"Task not found");
  try { return json({jsonrpc:"2.0",id,result:{task:JSON.parse(row.task_json)}}); } catch { return rpcError(id,-32603,"Task state unavailable"); }
}
async function listTasks(payload,env) {
  const id=payload?.id ?? null;
  const result=await env.DB.prepare("SELECT task_id,task_json,MAX(received_at) AS ts FROM lumen_a2a_inbound GROUP BY task_id ORDER BY ts DESC LIMIT 20").all();
  const tasks=[];
  for (const row of result.results||[]) { try { tasks.push(JSON.parse(row.task_json)); } catch {} }
  return json({jsonrpc:"2.0",id,result:{tasks}});
}
async function storeStats(env) {
  const realOrderFilter = "remote_metadata IS NULL OR (remote_metadata NOT LIKE '%technical_machine_order_canary%' AND remote_metadata NOT LIKE '%lumen_deployment_canary%')";
  const orders=await env.DB.prepare(`SELECT COUNT(*) AS n, COALESCE(SUM(amount_usd),0) AS quoted FROM lumen_machine_orders WHERE ${realOrderFilter}`).first();
  const quotes=await env.DB.prepare("SELECT COUNT(*) AS n FROM lumen_a2a_quotes WHERE remote_metadata IS NULL OR (remote_metadata NOT LIKE '%technical_quote_canary%' AND remote_metadata NOT LIKE '%technical_machine_order_canary%' AND remote_metadata NOT LIKE '%lumen_deployment_canary%')").first();
  return {
    orders:Number(orders?.n||0),
    quotedPipelineUsd:Number(orders?.quoted||0),
    quotes:Number(quotes?.n||0),
    technicalCanariesExcluded:true,
    realizedRevenueUsd:null,
    realizedRevenueRule:"Only canonical settled transactions count as realized revenue. Deployment canaries are excluded from commercial metrics."
  };
}

export default {
  async fetch(request,env) {
    const url=new URL(request.url);
    if (request.method==="OPTIONS") return new Response(null,{status:204,headers:{"access-control-allow-origin":"*","access-control-allow-methods":"GET,POST,OPTIONS","access-control-allow-headers":"content-type,a2a-version,payment-signature"}});
    await ensureSchema(env);
    if (request.method==="GET" && url.pathname==="/health") return json({ok:true,service:SERVICE,version:VERSION,protocol:PROTOCOL_VERSION,storage:"cloudflare-d1",sellerMode:"receive_revenue_only",catalogServices:SERVICE_CATALOG.length,machineProducts:MACHINE_PRODUCTS.length,recurringPlans:RECURRING_PLANS.length,x402:paymentsStatus(env).x402.status,bindingActionsHumanGated:true,lumenAutonomousSpend:false});
    if (request.method==="GET" && url.pathname==="/seller/catalog") return json(sellerCatalog(url.origin,env),200,{"cache-control":"public, max-age=300"});
    if (request.method==="GET" && url.pathname==="/machine/catalog") return json(machineCatalog(url.origin,env),200,{"cache-control":"public, max-age=300"});
    if (request.method==="GET" && url.pathname==="/payments/status") return json(paymentsStatus(env),200,{"cache-control":"public, max-age=60"});
    if (request.method==="GET" && url.pathname==="/machine/stats") return json(await storeStats(env));
    if (request.method==="GET" && ["/.well-known/agent-card.json","/.well-known/agent.json"].includes(url.pathname)) return json(agentCard(url.origin,env),200,{"cache-control":"public, max-age=300"});
    if (request.method!=="POST" || url.pathname!=="/a2a/v1") return new Response("not_found",{status:404,headers:{"content-type":"text/plain; charset=utf-8"}});
    const length=Number(request.headers.get("content-length")||0);
    if (length>MAX_BODY_BYTES) return rpcError(null,-32013,"Request too large",413);
    if (!(await rateAllowed(request,env))) return rpcError(null,-32029,"Rate limit exceeded",429);
    let payload; try { payload=await request.json(); } catch { return rpcError(null,-32700,"Invalid JSON payload",400); }
    if (!payload || payload.jsonrpc!=="2.0") return rpcError(payload?.id,-32600,"Invalid request");
    const method=String(payload.method||"");
    if (method==="SendMessage" || method==="message/send") return sendMessage(payload,env);
    if (method==="GetTask" || method==="tasks/get") return getTask(payload,env);
    if (method==="ListTasks") return listTasks(payload,env);
    if (method==="GetServiceCatalog") return json({jsonrpc:"2.0",id:payload.id,result:{catalog:sellerCatalog(url.origin,env)}});
    if (method==="GetMachineCatalog") return json({jsonrpc:"2.0",id:payload.id,result:{catalog:machineCatalog(url.origin,env)}});
    if (method==="GetPaymentsStatus") return json({jsonrpc:"2.0",id:payload.id,result:{payments:paymentsStatus(env)}});
    if (method==="QuoteService") return quoteRpc(payload,env,"service");
    if (method==="QuoteMachineProduct") return quoteRpc(payload,env,"product");
    if (method==="QuoteRecurringPlan") return quoteRpc(payload,env,"plan");
    if (method==="GetExtendedAgentCard") return rpcError(payload.id,-32601,"Extended agent card is not enabled");
    return rpcError(payload.id,-32601,"Method not found");
  }
};