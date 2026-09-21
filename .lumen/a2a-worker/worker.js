const SERVICE = "lumen-zero-a2a";
const VERSION = "1.0-zero-a2a-cloudflare";
const PROTOCOL_VERSION = "1.0";
const RATE_LIMIT_PER_HOUR = 30;
const MAX_BODY_BYTES = 65536;
const MAX_TEXT = 8000;

function json(data, status = 200, extra = {}) {
  return Response.json(data, { status, headers: { "cache-control": "no-store", "x-content-type-options": "nosniff", "A2A-Version": PROTOCOL_VERSION, ...extra } });
}
function rpcError(id, code, message, status = 200) {
  return json({ jsonrpc: "2.0", id: id ?? null, error: { code, message } }, status);
}
function clean(value, limit = 8000) { return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit); }
function safeMetadata(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const out = {};
  for (const [k, v] of Object.entries(value).slice(0, 30)) out[clean(k,80)] = clean(typeof v === "string" ? v : JSON.stringify(v), 500);
  return out;
}
function partsText(message) {
  const chunks = [];
  for (const p of Array.isArray(message?.parts) ? message.parts : []) {
    if (typeof p?.text === "string") chunks.push(p.text);
    else if (p?.data != null) chunks.push(typeof p.data === "string" ? p.data : JSON.stringify(p.data));
  }
  return clean(chunks.join(" "), MAX_TEXT);
}
function bindingIntent(text) {
  const low = text.toLowerCase();
  return ["accept contract","accept terms","place order","purchase order","make payment","authorize payment","sign contract","binding agreement","aceptar contrato","aceptar términos","aceptar terminos","orden de compra","realizar pago","autorizar pago","firmar contrato","acuerdo vinculante","cerrar trato","confirm purchase"].some(x => low.includes(x));
}
function agentCard(origin) {
  const endpoint = `${origin}/a2a/v1`;
  return {
    protocolVersion: PROTOCOL_VERSION,
    name: "LUMEN B2B Agent",
    description: "AI-assisted B2B sourcing and commercial coordination agent for Argentina, Latin America and global trade. LUMEN exchanges non-binding buyer requirements, supplier RFQs, sourcing capabilities and commercial clarifications. Purchases, payments, contracts, commissions and binding acceptance always require human approval.",
    url: endpoint,
    preferredTransport: "JSONRPC",
    supportedInterfaces: [
      { url: endpoint, protocolBinding: "JSONRPC", protocolVersion: "1.0" },
      { url: endpoint, protocolBinding: "JSONRPC", protocolVersion: "0.3" }
    ],
    provider: { organization: "LUMEN B2B", url: origin },
    version: VERSION,
    documentationUrl: `${origin}/health`,
    capabilities: { streaming: false, pushNotifications: false, extendedAgentCard: false },
    defaultInputModes: ["text/plain", "application/json"],
    defaultOutputModes: ["text/plain", "application/json"],
    skills: [
      { id:"b2b-capability-handshake", name:"B2B agent capability handshake", description:"Exchange identity, capabilities and preferred non-binding commercial workflow with another business agent.", tags:["b2b","agent-to-agent","capabilities","interoperability","commercial-network"] },
      { id:"supplier-rfq-exchange", name:"Supplier RFQ exchange", description:"Receive and structure non-binding supplier quotation requests and clarification exchanges.", tags:["rfq","supplier","quotation","procurement","sourcing"] },
      { id:"buyer-requirement-intake", name:"Buyer requirement intake", description:"Receive a buyer need and identify the minimum technical, quantity and delivery information required for sourcing.", tags:["buyer","requirements","sourcing","procurement","demand"] },
      { id:"industrial-sourcing-latam", name:"Industrial sourcing for Argentina and Latin America", description:"Coordinate non-binding sourcing for industrial pumps, valves, instrumentation, electrical materials, spare parts and related equipment.", tags:["industrial","argentina","latin-america","pumps","valves","instrumentation","electrical","spare-parts"] },
      { id:"global-trade-sourcing", name:"Global trade sourcing", description:"Coordinate non-binding international sourcing data including Incoterm, MOQ, origin, HS/NCM, packing and logistics inputs.", tags:["international","sourcing","incoterm","logistics","global-trade","supply-chain"] },
      { id:"commercial-opportunity-exchange", name:"Commercial opportunity exchange", description:"Receive non-binding buyer requirements or supplier capabilities and route complete packets into LUMEN verification.", tags:["commercial-opportunity","buyer-demand","supplier-capability","verification","b2b"] }
    ]
  };
}
async function ensureSchema(env) {
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_a2a_inbound (id TEXT PRIMARY KEY, received_at TEXT NOT NULL, context_id TEXT NOT NULL, task_id TEXT NOT NULL, remote_message_id TEXT, remote_metadata TEXT, text TEXT NOT NULL, binding_intent INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, processed INTEGER NOT NULL DEFAULT 0, processed_at TEXT, bridge_status TEXT, opportunity_id TEXT, task_json TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_a2a_pending ON lumen_a2a_inbound(processed,received_at)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_a2a_task ON lumen_a2a_inbound(task_id,received_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_a2a_rate (bucket TEXT PRIMARY KEY, hits INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL)")
  ]);
}
async function rateAllowed(request, env) {
  const ip = clean(request.headers.get("CF-Connecting-IP") || "unknown", 100);
  const hour = new Date().toISOString().slice(0,13);
  const bucket = `${hour}|${ip}`;
  await env.DB.prepare("INSERT INTO lumen_a2a_rate(bucket,hits,updated_at) VALUES(?,1,?) ON CONFLICT(bucket) DO UPDATE SET hits=hits+1,updated_at=excluded.updated_at").bind(bucket,new Date().toISOString()).run();
  const row = await env.DB.prepare("SELECT hits FROM lumen_a2a_rate WHERE bucket=?").bind(bucket).first();
  return Number(row?.hits || 0) <= RATE_LIMIT_PER_HOUR;
}
function taskReply(contextId, taskId, state, text, data = {}) {
  const message = { messageId: crypto.randomUUID(), contextId, taskId, role:"ROLE_AGENT", parts:[{ text, mediaType:"text/plain" },{ data, mediaType:"application/json" }], metadata:{ lumenMode:"nonbinding_b2b", humanGateForBindingActions:true, agentGatewayVersion:VERSION } };
  return { id:taskId, contextId, status:{ state, message, timestamp:new Date().toISOString() }, history:[message], metadata:{ lumen:true, nonbinding:true, bindingActionsHumanGated:true, bridgeStatus:"queued_for_verification" } };
}
async function sendMessage(payload, env) {
  const id = payload?.id ?? null;
  const message = payload?.params?.message;
  if (!message || !Array.isArray(message.parts) || message.parts.length === 0) return rpcError(id,-32602,"Invalid parameters: message.parts is required");
  const text = partsText(message);
  if (!text) return rpcError(id,-32602,"Invalid parameters: message text/data is required");
  const contextId = clean(message.contextId || crypto.randomUUID(),160);
  const taskId = clean(message.taskId || crypto.randomUUID(),160);
  const inboundId = `A2AIN-${crypto.randomUUID().replaceAll("-","").slice(0,12).toUpperCase()}`;
  const binding = bindingIntent(text);
  const metadata = safeMetadata(message.metadata);
  const state = binding ? "TASK_STATE_INPUT_REQUIRED" : "TASK_STATE_WORKING";
  const replyText = binding
    ? "LUMEN received the request. Purchases, payments, contracts, commissions and binding acceptance require explicit human approval. We can continue exchanging non-binding technical and commercial information."
    : "LUMEN received the non-binding B2B message and queued it for counterparty, evidence and commercial-fit verification. The same task can be polled for the verification result or clarification request.";
  const task = taskReply(contextId,taskId,state,replyText,{ acceptedMode:"nonbinding", queuedForVerification:true, inboundId, bindingActionsHumanGated:true });
  await env.DB.prepare("INSERT INTO lumen_a2a_inbound(id,received_at,context_id,task_id,remote_message_id,remote_metadata,text,binding_intent,status,processed,task_json) VALUES(?,?,?,?,?,?,?,?,?,0,?)")
    .bind(inboundId,new Date().toISOString(),contextId,taskId,clean(message.messageId,180),JSON.stringify(metadata),text,binding?1:0,binding?"human_gate_required":"received_nonbinding",JSON.stringify(task)).run();
  return json({ jsonrpc:"2.0", id, result:{ task } });
}
async function getTask(payload, env) {
  const id = payload?.id ?? null;
  const taskId = clean(payload?.params?.id,160);
  if (!taskId) return rpcError(id,-32602,"Task id is required");
  const row = await env.DB.prepare("SELECT task_json FROM lumen_a2a_inbound WHERE task_id=? ORDER BY received_at DESC LIMIT 1").bind(taskId).first();
  if (!row?.task_json) return rpcError(id,-32001,"Task not found");
  try { return json({jsonrpc:"2.0",id,result:{task:JSON.parse(row.task_json)}}); } catch { return rpcError(id,-32603,"Task state unavailable"); }
}
async function listTasks(payload, env) {
  const id = payload?.id ?? null;
  const result = await env.DB.prepare("SELECT task_id,task_json,MAX(received_at) AS ts FROM lumen_a2a_inbound GROUP BY task_id ORDER BY ts DESC LIMIT 20").all();
  const tasks=[];
  for (const row of result.results || []) { try { tasks.push(JSON.parse(row.task_json)); } catch {} }
  return json({jsonrpc:"2.0",id,result:{tasks}});
}
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    await ensureSchema(env);
    if (request.method === "GET" && url.pathname === "/health") return json({ok:true,service:SERVICE,version:VERSION,protocol:PROTOCOL_VERSION,storage:"cloudflare-d1",bindingActionsHumanGated:true});
    if (request.method === "GET" && ["/.well-known/agent-card.json","/.well-known/agent.json"].includes(url.pathname)) return json(agentCard(url.origin),200,{"cache-control":"public, max-age=300"});
    if (request.method !== "POST" || url.pathname !== "/a2a/v1") return new Response("not_found",{status:404,headers:{"content-type":"text/plain; charset=utf-8"}});
    const length = Number(request.headers.get("content-length") || 0);
    if (length > MAX_BODY_BYTES) return rpcError(null,-32013,"Request too large",413);
    if (!(await rateAllowed(request,env))) return rpcError(null,-32029,"Rate limit exceeded",429);
    let payload; try { payload=await request.json(); } catch { return rpcError(null,-32700,"Invalid JSON payload",400); }
    if (!payload || payload.jsonrpc !== "2.0") return rpcError(payload?.id,-32600,"Invalid request");
    const method=String(payload.method||"");
    if (method === "SendMessage" || method === "message/send") return sendMessage(payload,env);
    if (method === "GetTask" || method === "tasks/get") return getTask(payload,env);
    if (method === "ListTasks") return listTasks(payload,env);
    if (method === "GetExtendedAgentCard") return rpcError(payload.id,-32601,"Extended agent card is not enabled");
    return rpcError(payload.id,-32601,"Method not found");
  }
};
