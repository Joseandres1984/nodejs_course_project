const VERSION = "1.0-travel-broker-referral";
const REGISTRY_BASE = "https://api.a2a-registry.org";
const FETCH_TIMEOUT_MS = 8000;
const MAX_PER_QUERY = 35;
const MAX_MATCHES_PER_DEMAND = 3;

const TRAVEL_DEMAND_QUERIES = [
  "corporate travel buyer request flight hotel",
  "business travel need accommodation transfer",
  "company trip conference hotel flight booking",
  "group business travel procurement request"
];

const TRAVEL_WORDS = ["travel","trip","flight","airfare","airline","hotel","accommodation","lodging","transfer","airport","booking","reservation","itinerary","conference","congress"];
const B2B_WORDS = ["corporate","business","company","employee","employees","team","crew","technician","technicians","conference","congress","event","group","procurement","buyer","client","customer"];
const DEMAND_WORDS = ["need","needs","looking for","seeking","request","require","required","book","booking request","quote","rfq","arrange","organize","organise","send","travel for"];
const SUPPLY_WORDS = ["travel agency","travel management","booking platform","flight booking","hotel booking","accommodation provider","travel provider","reservation platform","corporate travel","business travel service","travel api"];

function json(data, status = 200) {
  return Response.json(data, { status, headers: { "cache-control":"no-store", "x-content-type-options":"nosniff", "access-control-allow-origin":"*" } });
}
function clean(value, limit = 5000) { return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit); }
function num(value, fallback = 0) { const n = Number(value); return Number.isFinite(n) ? n : fallback; }
function boolVar(value, fallback = false) {
  const v = clean(value, 20).toLowerCase();
  if (!v) return fallback;
  return ["1","true","yes","on"].includes(v);
}
function authorized(request, env) {
  const configured = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const provided = clean(request.headers.get("x-lumen-admin"), 500);
  return Boolean(configured && provided && configured === provided);
}
function safeHttps(value) {
  try {
    const u = new URL(value);
    if (u.protocol !== "https:") return false;
    const h = u.hostname.toLowerCase();
    if (h === "localhost" || h.endsWith(".local") || h === "::1" || /^127\./.test(h) || /^10\./.test(h) || /^192\.168\./.test(h) || /^169\.254\./.test(h)) return false;
    const m = h.match(/^172\.(\d+)\./);
    return !(m && Number(m[1]) >= 16 && Number(m[1]) <= 31);
  } catch { return false; }
}
function scrub(text, limit = 1600) {
  return clean(text, 12000)
    .replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, "[redacted-email]")
    .replace(/\+?\d[\d\s().-]{8,}\d/g, "[redacted-phone]")
    .replace(/\b(?:\d[ -]*?){13,19}\b/g, "[redacted-payment-number]")
    .replace(/\b(passport|pasaporte)\s*(?:no\.?|number|nro\.?|#)?\s*[:=-]?\s*[A-Z0-9-]{5,20}\b/gi, "$1 [redacted]")
    .slice(0, limit);
}
function textOf(item) {
  const skills = Array.isArray(item?.skills) ? item.skills.flatMap(s => [s?.name, s?.description, ...(Array.isArray(s?.tags) ? s.tags : [])]) : [];
  const tags = Array.isArray(item?.tags) ? item.tags.map(x => typeof x === "string" ? x : x?.name || x?.id || "") : [];
  return clean([item?.name,item?.displayName,item?.display_name,item?.description,item?.summary,item?.message,item?.text,...tags,...skills].filter(Boolean).join(" "), 16000).toLowerCase();
}
function isTravel(text) { return TRAVEL_WORDS.some(w => text.includes(w)); }
function isB2B(text) { return B2B_WORDS.some(w => text.includes(w)); }
function isDemand(text) { return DEMAND_WORDS.some(w => text.includes(w)); }
function isSupply(text) { return SUPPLY_WORDS.some(w => text.includes(w)); }
function travelKind(text) {
  if (/conference|congress|event|group|team|crew/.test(text)) return "GROUP_OR_EVENT";
  const flight = /flight|airfare|airline/.test(text);
  const hotel = /hotel|accommodation|lodging/.test(text);
  const transfer = /transfer|airport|ground transport/.test(text);
  if (flight && hotel) return transfer ? "CORPORATE_TRIP_BUNDLE" : "FLIGHT_AND_HOTEL";
  if (flight) return "FLIGHT";
  if (hotel) return "HOTEL";
  if (transfer) return "TRANSFER";
  return "CORPORATE_TRAVEL";
}
function componentTags(text) {
  const tags = [];
  if (/flight|airfare|airline/.test(text)) tags.push("flight");
  if (/hotel|accommodation|lodging/.test(text)) tags.push("hotel");
  if (/transfer|airport|ground transport/.test(text)) tags.push("transfer");
  if (/conference|congress|event|group/.test(text)) tags.push("group-event");
  if (/car rental|rental car|vehicle hire/.test(text)) tags.push("car-rental");
  return tags.length ? tags : ["travel"];
}
function pickEndpoint(item) {
  const interfaces = Array.isArray(item?.supportedInterfaces) ? item.supportedInterfaces : [];
  for (const raw of [interfaces[0]?.url,item?.endpoint,item?.a2a_url,item?.a2aUrl,item?.url,item?.manifest_url,item?.manifestUrl]) {
    const v = clean(raw, 1200);
    if (safeHttps(v)) return v;
  }
  return "";
}
function remoteId(item, fallback = "") { return clean(item?.package_name || item?.packageName || item?.id || item?.agent_id || item?.agentId || item?.name || fallback, 300); }
function registryItems(payload) {
  if (Array.isArray(payload)) return payload;
  for (const value of [payload?.agents,payload?.data?.agents,payload?.data,payload?.results,payload?.items]) if (Array.isArray(value)) return value;
  return [];
}
function requestScore(text, source = "registry") {
  let score = 20;
  const travelHits = TRAVEL_WORDS.filter(w => text.includes(w)).length;
  const b2bHits = B2B_WORDS.filter(w => text.includes(w)).length;
  const demandHits = DEMAND_WORDS.filter(w => text.includes(w)).length;
  score += Math.min(25, travelHits * 5);
  score += Math.min(25, b2bHits * 5);
  score += Math.min(20, demandHits * 5);
  if (source === "a2a_inbound") score += 8;
  return Math.max(0, Math.min(100, score));
}
function matchScore(demand, supplier) {
  let score = 35;
  const dTags = new Set(JSON.parse(demand.components_json || "[]"));
  let supplierText = "";
  try { supplierText = `${supplier.name || ""} ${supplier.description || ""} ${supplier.skills_json || ""} ${supplier.capabilities_json || ""}`.toLowerCase(); } catch {}
  for (const tag of dTags) {
    if (tag === "flight" && /flight|airfare|airline/.test(supplierText)) score += 10;
    else if (tag === "hotel" && /hotel|accommodation|lodging/.test(supplierText)) score += 10;
    else if (tag === "transfer" && /transfer|transport|airport/.test(supplierText)) score += 8;
    else if (tag === "group-event" && /group|event|conference|congress/.test(supplierText)) score += 8;
    else if (tag === "travel" && /travel|booking|reservation/.test(supplierText)) score += 8;
  }
  score += Math.min(16, num(supplier.reputation_score) * 0.1);
  score += Math.min(12, num(supplier.compatibility_score) * 0.08);
  score += Math.min(10, num(demand.signal_score) * 0.08);
  return Math.round(Math.max(0, Math.min(100, score)));
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_travel_demands (id TEXT PRIMARY KEY,source_type TEXT NOT NULL,source_id TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,name TEXT,kind TEXT NOT NULL,summary TEXT NOT NULL,components_json TEXT NOT NULL,signal_score INTEGER NOT NULL,status TEXT NOT NULL,evidence TEXT,raw_reference TEXT,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_travel_demands_rank ON lumen_travel_demands(status,signal_score DESC,updated_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_travel_matches (id TEXT PRIMARY KEY,demand_id TEXT NOT NULL,partner_id TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,match_score INTEGER NOT NULL,status TEXT NOT NULL,endpoint TEXT NOT NULL,protocol_version TEXT,request_text TEXT,response_text TEXT,task_id TEXT,error TEXT,referral_id TEXT,engine_version TEXT NOT NULL,UNIQUE(demand_id,partner_id))"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_travel_matches_state ON lumen_travel_matches(status,match_score DESC,updated_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_travel_runs (id TEXT PRIMARY KEY,created_at TEXT NOT NULL,status TEXT NOT NULL,demands INTEGER NOT NULL DEFAULT 0,matches INTEGER NOT NULL DEFAULT 0,details_json TEXT,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_travel_runs_created ON lumen_travel_runs(created_at DESC)")
  ]);
  return true;
}
async function fetchJson(url, init = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort("timeout"), FETCH_TIMEOUT_MS);
  try {
    const response = await fetch(url, { ...init, signal: controller.signal, headers: { "accept":"application/json", "user-agent":"LUMEN-TravelBroker/1.0", ...(init.headers || {}) } });
    if (!response.ok) throw new Error(`http_${response.status}`);
    return await response.json();
  } finally { clearTimeout(timer); }
}
async function upsertDemand(env, { sourceType, sourceId, name, text, evidence = "", rawReference = "" }) {
  const normalized = clean(text, 12000).toLowerCase();
  if (!isTravel(normalized) || !isB2B(normalized) || !isDemand(normalized)) return null;
  const score = requestScore(normalized, sourceType === "A2A_INBOUND" ? "a2a_inbound" : "registry");
  if (score < 60) return null;
  const id = `TRV-${sourceType.slice(0,8)}-${clean(sourceId, 80).replace(/[^A-Za-z0-9_-]/g, "").slice(-46).toUpperCase()}`;
  const now = new Date().toISOString();
  const summary = scrub(text, 1600);
  const kind = travelKind(normalized);
  const components = componentTags(normalized);
  await env.DB.prepare("INSERT INTO lumen_travel_demands(id,source_type,source_id,created_at,updated_at,name,kind,summary,components_json,signal_score,status,evidence,raw_reference,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET updated_at=excluded.updated_at,name=excluded.name,kind=excluded.kind,summary=excluded.summary,components_json=excluded.components_json,signal_score=MAX(lumen_travel_demands.signal_score,excluded.signal_score),status=CASE WHEN lumen_travel_demands.status IN ('MATCHED','PARTNER_INTEREST','REFERRAL_CREATED') THEN lumen_travel_demands.status ELSE excluded.status END,evidence=excluded.evidence,raw_reference=excluded.raw_reference,engine_version=excluded.engine_version")
    .bind(id, sourceType, sourceId, now, now, clean(name, 260) || null, kind, summary, JSON.stringify(components), score, "QUALIFIED", clean(evidence, 1200) || null, clean(rawReference, 1200) || null, VERSION).run();
  return { id, sourceType, sourceId, name: clean(name,260), kind, summary, components, signalScore: score };
}
async function scanRegistryDemands(env) {
  const found = [];
  const errors = [];
  for (const query of TRAVEL_DEMAND_QUERIES) {
    const url = `${REGISTRY_BASE}/public/agents?q=${encodeURIComponent(query)}`;
    try {
      const payload = await fetchJson(url);
      const items = registryItems(payload).slice(0, MAX_PER_QUERY);
      for (const item of items) {
        const text = textOf(item);
        if (isSupply(text) && !isDemand(text)) continue;
        const rid = remoteId(item, `${query}-${found.length}`);
        const demand = await upsertDemand(env, { sourceType:"A2A_REGISTRY", sourceId:`${rid}|${query}`, name:item?.displayName || item?.display_name || item?.name || rid, text, evidence:url, rawReference:pickEndpoint(item) });
        if (demand) found.push(demand);
      }
    } catch (error) { errors.push(`${query}:${clean(error?.message || error, 180)}`); }
  }
  return { found: found.length, errors };
}
async function scanInboundDemands(env) {
  const found = [];
  let rows = [];
  try {
    const r = await env.DB.prepare("SELECT id,received_at,text,binding_intent,status FROM lumen_a2a_inbound WHERE binding_intent=0 ORDER BY received_at DESC LIMIT 250").all();
    rows = r.results || [];
  } catch { return { found:0, errors:["a2a_inbound_not_ready"] }; }
  for (const row of rows) {
    const text = clean(row.text, 12000);
    const demand = await upsertDemand(env, { sourceType:"A2A_INBOUND", sourceId:row.id, name:"Inbound A2A corporate travel request", text, evidence:`a2a_inbound:${row.id}`, rawReference:"" });
    if (demand) found.push(demand);
  }
  return { found: found.length, errors:[] };
}
async function trustedTravelPartners(env) {
  try {
    const r = await env.DB.prepare("SELECT p.id,p.name,p.endpoint,p.card_url,p.description,p.protocol_version,p.skills_json,p.capabilities_json,p.reputation_score,p.compatibility_score,t.trust_score,t.trust_level,t.auth_required,t.manipulation_hits FROM lumen_partner_agents p JOIN lumen_partner_trust t ON t.partner_id=p.id WHERE p.endpoint IS NOT NULL AND p.status IN ('strong_candidate','candidate') AND t.trust_level IN ('ALLOW','CAUTION') AND t.auth_required=0 AND t.manipulation_hits=0 ORDER BY p.reputation_score DESC,p.compatibility_score DESC LIMIT 300").all();
    return (r.results || []).filter(p => {
      const text = `${p.name || ""} ${p.description || ""} ${p.skills_json || ""} ${p.capabilities_json || ""}`.toLowerCase();
      return safeHttps(p.endpoint) && isTravel(text) && (isSupply(text) || text.includes("travel"));
    });
  } catch { return []; }
}
async function buildMatches(env) {
  const demandsResult = await env.DB.prepare("SELECT * FROM lumen_travel_demands WHERE status IN ('QUALIFIED','MATCHED') ORDER BY signal_score DESC,updated_at DESC LIMIT 120").all();
  const demands = demandsResult.results || [];
  const partners = await trustedTravelPartners(env);
  const now = new Date().toISOString();
  let matches = 0;
  for (const demand of demands) {
    const ranked = partners.map(partner => ({ partner, score: matchScore(demand, partner) })).filter(x => x.score >= 60).sort((a,b) => b.score - a.score).slice(0, MAX_MATCHES_PER_DEMAND);
    for (const { partner, score } of ranked) {
      const id = `TRVM-${clean(demand.id,80)}-${clean(partner.id,80)}`.slice(0,220);
      const requestText = scrub(`LUMEN identified a public or agent-submitted B2B travel requirement (${demand.kind}): ${demand.summary} If your organization can support this requirement, reply with a non-binding capability confirmation, supported travel components and any referral or affiliate terms you can offer. Do not create a reservation, ticket, charge or binding commitment. LUMEN is not authorizing traveler spend. Reference ${id}.`, 2200);
      await env.DB.prepare("INSERT INTO lumen_travel_matches(id,demand_id,partner_id,created_at,updated_at,match_score,status,endpoint,protocol_version,request_text,response_text,task_id,error,referral_id,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(demand_id,partner_id) DO UPDATE SET updated_at=excluded.updated_at,match_score=excluded.match_score,endpoint=excluded.endpoint,protocol_version=excluded.protocol_version,request_text=excluded.request_text,engine_version=excluded.engine_version,status=CASE WHEN lumen_travel_matches.status IN ('SENT','SENT_TASK','RESPONDED_POSITIVE','RESPONDED_OTHER','DECLINED','REFERRAL_CREATED') THEN lumen_travel_matches.status ELSE 'READY' END")
        .bind(id,demand.id,partner.id,now,now,score,"READY",partner.endpoint,clean(partner.protocol_version,30)||"0.3.0",requestText,null,null,null,null,VERSION).run();
      matches += 1;
    }
    if (ranked.length) await env.DB.prepare("UPDATE lumen_travel_demands SET status='MATCHED',updated_at=? WHERE id=? AND status='QUALIFIED'").bind(now,demand.id).run();
  }
  return { matches, partners: partners.length };
}

function messageEnvelope(row) {
  const id = `lumen-travel-${crypto.randomUUID()}`;
  const version = clean(row.protocol_version, 30) || "0.3.0";
  const isV1 = version.startsWith("1.");
  return {
    jsonrpc:"2.0",
    id,
    method:isV1 ? "SendMessage" : "message/send",
    params:{ message:{ messageId:id, role:isV1 ? "ROLE_USER" : "user", parts:[{ text:row.request_text }] }, metadata:{ lumen:{ vertical:"TRAVEL", matchId:row.id, demandId:row.demand_id, nonBinding:true, bookingAuthorized:false, paymentAuthorized:false } } }
  };
}
function extractText(payload) {
  if (!payload) return "";
  if (typeof payload === "string") return clean(payload,6000);
  const value = payload?.result || payload;
  const parts = value?.message?.parts || value?.task?.status?.message?.parts || value?.artifacts?.flatMap?.(a => a?.parts || []) || value?.task?.artifacts?.flatMap?.(a => a?.parts || []) || [];
  const fromParts = (Array.isArray(parts) ? parts : []).map(p => p?.text || "").filter(Boolean).join(" ");
  return clean(fromParts || value?.text || value?.message || value?.response, 6000);
}
function extractTaskId(payload) {
  const value = payload?.result || payload || {};
  return clean(value?.task?.id || value?.task_id || value?.taskId || (value?.status ? value?.id : ""), 240);
}
function classifySupplierResponse(text) {
  const t = clean(text,6000).toLowerCase();
  if (!t) return "EMPTY";
  if (/not interested|cannot support|can't support|unable to support|decline|declined|no thanks/.test(t)) return "DECLINE";
  if (/can support|we support|available|we can help|we can provide|referral|affiliate|commission|booking endpoint|quote endpoint|travel service|hotel inventory|flight inventory|yes/.test(t)) return "POSITIVE";
  return "OTHER";
}
async function createTravelReferral(env, row, responseText) {
  const demand = await env.DB.prepare("SELECT * FROM lumen_travel_demands WHERE id=? LIMIT 1").bind(row.demand_id).first();
  const partner = await env.DB.prepare("SELECT id,name,card_url FROM lumen_partner_agents WHERE id=? LIMIT 1").bind(row.partner_id).first();
  if (!demand || !partner) return null;
  const referralId = `REF-TRAVEL-${clean(row.id,180).replace(/[^A-Za-z0-9]/g, "").slice(-16).toUpperCase()}`;
  const attribution = `TRAVEL|${row.id}`;
  const now = new Date().toISOString();
  try {
    await env.DB.prepare("INSERT INTO lumen_referrals(id,direction,created_at,updated_at,source,origin_partner_id,origin_partner_name,origin_card_url,target_partner_id,target_partner_name,opportunity_id,title,summary,capability,estimated_value_usd,status,trust_score,trust_level,match_score,attribution_key,external_contact_sent,binding_allowed,spend_allowed,commission_status,settled_revenue_usd,settlement_event_id,raw_json,engine_version) VALUES(?,'OUTBOUND',?,?,?,NULL,'LUMEN',NULL,?,?,?,?,?,?,NULL,'OUTBOUND_CANDIDATE',NULL,NULL,?,?,1,0,0,'NOT_CONFIGURED',0,NULL,?,?) ON CONFLICT(attribution_key) DO UPDATE SET updated_at=excluded.updated_at,summary=excluded.summary,match_score=excluded.match_score,external_contact_sent=1,engine_version=excluded.engine_version")
      .bind(referralId,now,now,"travel_broker",partner.id,partner.name,demand.id,clean(`B2B travel referral — ${demand.kind}`,300),scrub(`${demand.summary} Supplier capability response: ${responseText}`,4200),"travel",num(row.match_score),attribution,JSON.stringify({travelMatchId:row.id,demandId:demand.id,partnerId:partner.id,nonBinding:true}).slice(0,6000),VERSION).run();
    await env.DB.prepare("UPDATE lumen_travel_matches SET status='REFERRAL_CREATED',referral_id=?,updated_at=?,response_text=?,engine_version=? WHERE id=?").bind(referralId,now,scrub(responseText,5000),VERSION,row.id).run();
    await env.DB.prepare("UPDATE lumen_travel_demands SET status='REFERRAL_CREATED',updated_at=? WHERE id=?").bind(now,demand.id).run();
    return referralId;
  } catch { return null; }
}
async function applyResponse(env, row, responseText) {
  const cls = classifySupplierResponse(responseText);
  const now = new Date().toISOString();
  if (cls === "POSITIVE") {
    await env.DB.prepare("UPDATE lumen_travel_matches SET status='RESPONDED_POSITIVE',response_text=?,updated_at=?,error=NULL WHERE id=?").bind(scrub(responseText,5000),now,row.id).run();
    await env.DB.prepare("UPDATE lumen_travel_demands SET status='PARTNER_INTEREST',updated_at=? WHERE id=?").bind(now,row.demand_id).run();
    const referralId = await createTravelReferral(env,row,responseText);
    return { classification:cls, referralId };
  }
  const status = cls === "DECLINE" ? "DECLINED" : "RESPONDED_OTHER";
  await env.DB.prepare("UPDATE lumen_travel_matches SET status=?,response_text=?,updated_at=?,error=NULL WHERE id=?").bind(status,scrub(responseText,5000),now,row.id).run();
  return { classification:cls, referralId:null };
}

export async function runTravelBroker(env) {
  if (!(await ensureSchema(env))) return { ok:false, error:"persistence_unavailable", version:VERSION };
  const registry = await scanRegistryDemands(env);
  const inbound = await scanInboundDemands(env);
  const matching = await buildMatches(env);
  const statsRow = await env.DB.prepare("SELECT COUNT(*) demands,SUM(CASE WHEN status IN ('MATCHED','PARTNER_INTEREST','REFERRAL_CREATED') THEN 1 ELSE 0 END) matched FROM lumen_travel_demands").first();
  const now = new Date().toISOString();
  const runId = `TRUN-${crypto.randomUUID().replaceAll("-","").slice(0,14).toUpperCase()}`;
  await env.DB.prepare("INSERT INTO lumen_travel_runs(id,created_at,status,demands,matches,details_json,engine_version) VALUES(?,?,?,?,?,?,?)").bind(runId,now,(registry.errors.length ? "partial" : "complete"),num(statsRow?.demands),matching.matches,JSON.stringify({registry,inbound,matching}).slice(0,8000),VERSION).run();
  return { ok:true, version:VERSION, runId, registryDemands:registry.found, inboundDemands:inbound.found, activeDemands:num(statsRow?.demands), matchesBuilt:matching.matches, trustedTravelPartners:matching.partners, errors:[...registry.errors,...inbound.errors], guardrails:{ b2bOnly:true, consumerTripsAutoOutreach:false, storesPaymentData:false, storesPassportData:false, createsBooking:false, createsCharge:false, autonomousSpend:false, autonomousPurchase:false, autonomousContract:false, bindingActionsHumanGated:true } };
}

export async function runTravelReferralAction(env, { force = false } = {}) {
  if (!(await ensureSchema(env))) return { ok:false, sent:false, error:"persistence_unavailable", version:VERSION };
  const row = await env.DB.prepare("SELECT m.*,d.kind,d.summary,d.signal_score,p.name partner_name FROM lumen_travel_matches m JOIN lumen_travel_demands d ON d.id=m.demand_id JOIN lumen_partner_agents p ON p.id=m.partner_id WHERE m.status='READY' ORDER BY m.match_score DESC,d.signal_score DESC,m.created_at ASC LIMIT 1").first();
  if (!row) return { ok:true, sent:false, reason:"no_travel_referral_ready", version:VERSION };
  const enabled = boolVar(env?.A2A_AUTONOMOUS_OUTREACH, false);
  if (!force && !enabled) return { ok:true, sent:false, ready:true, reason:"autonomous_outreach_disabled", matchId:row.id, version:VERSION };
  if (!safeHttps(row.endpoint)) return { ok:false, sent:false, externalAttempted:false, error:"unsafe_partner_endpoint", matchId:row.id, version:VERSION };
  const payload = messageEnvelope(row);
  const now = new Date().toISOString();
  let raw = "";
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort("timeout"), 15000);
    let response;
    try { response = await fetch(row.endpoint,{method:"POST",headers:{"content-type":"application/json","accept":"application/json","a2a-version":clean(row.protocol_version,30)||"0.3.0"},body:JSON.stringify(payload),signal:controller.signal}); }
    finally { clearTimeout(timer); }
    raw = await response.text();
    if (!response.ok) throw new Error(`travel_referral_http_${response.status}`);
    let body = {}; try { body = JSON.parse(raw); } catch { body = { text:raw }; }
    const responseText = extractText(body);
    const taskId = extractTaskId(body);
    const status = responseText ? "RESPONDED_OTHER" : taskId ? "SENT_TASK" : "SENT";
    await env.DB.prepare("UPDATE lumen_travel_matches SET status=?,task_id=?,response_text=?,updated_at=?,error=NULL WHERE id=?").bind(status,taskId||null,responseText?scrub(responseText,5000):null,now,row.id).run();
    let handled = null;
    if (responseText) handled = await applyResponse(env,{...row,task_id:taskId},responseText);
    return { ok:true, sent:true, externalAttempted:true, version:VERSION, matchId:row.id, demandId:row.demand_id, partnerId:row.partner_id, partnerName:row.partner_name, status:handled?.referralId ? "REFERRAL_CREATED" : (responseText ? `RESPONDED_${handled?.classification || "OTHER"}` : status), taskId:taskId||null, referralId:handled?.referralId||null, guardrails:{ maxExternalMessagesPerRun:1, nonBindingOnly:true, bookingCreated:false, chargeCreated:false, outgoingPayment:false, autonomousSpend:false, bindingActionsHumanGated:true } };
  } catch (error) {
    const err = clean(error?.message || error,500);
    await env.DB.prepare("UPDATE lumen_travel_matches SET status='SEND_FAILED',updated_at=?,error=? WHERE id=?").bind(now,err,row.id).run();
    return { ok:false, sent:false, externalAttempted:true, version:VERSION, matchId:row.id, status:"SEND_FAILED", error:err };
  }
}

export async function pollTravelReferralTasks(env) {
  if (!(await ensureSchema(env))) return { ok:false, error:"persistence_unavailable", version:VERSION };
  const r = await env.DB.prepare("SELECT * FROM lumen_travel_matches WHERE status='SENT_TASK' AND task_id IS NOT NULL ORDER BY updated_at ASC LIMIT 6").all();
  const results = [];
  for (const row of r.results || []) {
    if (!safeHttps(row.endpoint)) continue;
    const payload = { jsonrpc:"2.0", id:`lumen-travel-poll-${Date.now()}`, method:"tasks/get", params:{id:row.task_id} };
    try {
      const body = await fetchJson(row.endpoint,{method:"POST",headers:{"content-type":"application/json","a2a-version":clean(row.protocol_version,30)||"0.3.0"},body:JSON.stringify(payload)});
      const responseText = extractText(body);
      if (!responseText) { results.push({matchId:row.id,status:"PENDING"}); continue; }
      const handled = await applyResponse(env,row,responseText);
      results.push({matchId:row.id,status:handled?.referralId?"REFERRAL_CREATED":`RESPONDED_${handled.classification}`,referralId:handled?.referralId||null});
    } catch (error) { results.push({matchId:row.id,status:"POLL_FAILED",error:clean(error?.message||error,240)}); }
  }
  return { ok:true, version:VERSION, polled:results.length, results };
}

async function stats(env) {
  if (!(await ensureSchema(env))) return { version:VERSION, demands:0, matches:0 };
  const d = await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN status='QUALIFIED' THEN 1 ELSE 0 END) qualified,SUM(CASE WHEN status='MATCHED' THEN 1 ELSE 0 END) matched,SUM(CASE WHEN status='PARTNER_INTEREST' THEN 1 ELSE 0 END) partnerInterest,SUM(CASE WHEN status='REFERRAL_CREATED' THEN 1 ELSE 0 END) referralCreated FROM lumen_travel_demands").first();
  const m = await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN status='READY' THEN 1 ELSE 0 END) ready,SUM(CASE WHEN status IN ('SENT','SENT_TASK') THEN 1 ELSE 0 END) sent,SUM(CASE WHEN status='RESPONDED_POSITIVE' THEN 1 ELSE 0 END) positive,SUM(CASE WHEN status='REFERRAL_CREATED' THEN 1 ELSE 0 END) referralCreated,SUM(CASE WHEN status='SEND_FAILED' THEN 1 ELSE 0 END) failed FROM lumen_travel_matches").first();
  return { version:VERSION, demands:Number(d?.total||0), qualified:Number(d?.qualified||0), matched:Number(d?.matched||0), partnerInterest:Number(d?.partnerInterest||0), referralsCreated:Number(d?.referralCreated||0), matches:Number(m?.total||0), readyMatches:Number(m?.ready||0), sentMatches:Number(m?.sent||0), positiveResponses:Number(m?.positive||0), referralMatches:Number(m?.referralCreated||0), failedMatches:Number(m?.failed||0), autonomousOutreachEnabled:boolVar(env?.A2A_AUTONOMOUS_OUTREACH,false) };
}

export async function handleTravelBroker(request, env) {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/travel/policy") return json({ version:VERSION, name:"LUMEN B2B Travel Broker", mode:"corporate_travel_referral_first", scope:["corporate travel","business trips","group/event travel","flights","hotels","transfers"], flow:["discover B2B travel demand","sanitize and qualify","match trusted A2A travel partners","send one non-binding capability/referral request within global quota","create referral only after positive supplier response","Commission Autopilot negotiates the standard success fee separately","human authorization remains required for booking/payment"], consumerAutoOutreach:false, realTimeFareClaim:false, createsBooking:false, autonomousPurchase:false, autonomousSpend:false, automaticContract:false, bindingActionsHumanGated:true });
  if (request.method === "GET" && url.pathname === "/travel/catalog") return json({ version:VERSION, vertical:"TRAVEL", offers:[{id:"TRAVEL-CORPORATE-BROKER",name:"Corporate Travel Broker",commercialModel:"referral_or_success_fee",bookingMode:"provider_handoff",description:"Non-binding B2B travel requirement routing and trusted-provider matching for corporate trips, groups, flights, hotels and transfers."}], intake:"A2A SendMessage to the main LUMEN endpoint using a business/corporate travel requirement; do not send passport or payment-card data.", bookingAuthority:false, paymentAuthority:false });
  if (request.method === "GET" && url.pathname === "/travel/stats") return json(await stats(env));
  if (request.method === "POST" && url.pathname === "/travel/run") {
    if (!authorized(request,env)) return json({ok:false,error:"admin_token_required"},403);
    return json(await runTravelBroker(env),202);
  }
  if (request.method === "POST" && url.pathname === "/travel/referrals/run") {
    if (!authorized(request,env)) return json({ok:false,error:"admin_token_required"},403);
    return json(await runTravelReferralAction(env,{force:false}),202);
  }
  if (request.method === "POST" && url.pathname === "/travel/referrals/poll") {
    if (!authorized(request,env)) return json({ok:false,error:"admin_token_required"},403);
    return json(await pollTravelReferralTasks(env),202);
  }
  return null;
}
