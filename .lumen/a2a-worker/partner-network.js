const VERSION = "1.0-partner-network";
const REGISTRY_BASE = "https://api.a2a-registry.org";
const FETCH_TIMEOUT_MS = 8000;
const MAX_PER_QUERY = 30;

const PARTNER_QUERIES = [
  "sourcing supplier procurement",
  "verification due diligence trust",
  "pricing quote market intelligence",
  "research data analysis",
  "logistics shipping export import",
  "buyer sales prospect demand",
  "tender procurement bid",
  "x402 payment commerce"
];

const CAPABILITY_RULES = [
  ["sourcing", ["sourcing", "supplier", "vendor", "procurement", "purchasing"]],
  ["verification", ["verify", "verification", "due diligence", "reputation", "evidence", "trust"]],
  ["pricing", ["price", "pricing", "quote", "quotation", "cost", "benchmark"]],
  ["research", ["research", "intelligence", "analysis", "search", "investigation", "data"]],
  ["logistics", ["logistics", "shipping", "freight", "delivery", "transport", "warehouse"]],
  ["export", ["export", "import", "importer", "distributor", "international trade", "customs"]],
  ["sales", ["buyer", "sales", "prospect", "lead", "demand", "intent"]],
  ["tender", ["tender", "bid", "rfq", "public procurement", "request for quote"]],
  ["payments", ["x402", "payment", "checkout", "invoice", "settlement", "commerce"]],
  ["automation", ["workflow", "automation", "orchestration", "agent", "task"]]
];

const OFFER_NEEDS = {
  "MP-SUPPLIER-SNAPSHOT": ["verification", "research", "sourcing"],
  "MP-QUOTE-SANITY": ["pricing", "research", "verification"],
  "MP-TENDER-SCAN": ["tender", "research"],
  "MP-SOURCING-5": ["sourcing", "verification", "pricing"],
  "MP-BUYER-SIGNALS": ["sales", "research"],
  "MP-EXPORT-PULSE": ["export", "logistics", "research"]
};

function json(data, status = 200) {
  return Response.json(data, {
    status,
    headers: {
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "access-control-allow-origin": "*"
    }
  });
}

function clean(value, limit = 4000) {
  return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit);
}

function arr(value) {
  return Array.isArray(value) ? value : value == null ? [] : [value];
}

function safeJson(value) {
  try { return JSON.stringify(value ?? null); } catch { return "null"; }
}

async function sha256(text) {
  const bytes = new TextEncoder().encode(String(text));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, "0")).join("");
}

function registryItems(payload) {
  if (Array.isArray(payload)) return payload;
  for (const value of [payload?.agents, payload?.data?.agents, payload?.data, payload?.results, payload?.items]) {
    if (Array.isArray(value)) return value;
  }
  return [];
}

function textOf(item, card = null) {
  const skills = arr(card?.skills || item?.skills).flatMap(s => [s?.name, s?.description, ...arr(s?.tags), ...arr(s?.examples)]);
  const tags = arr(item?.tags).map(x => typeof x === "string" ? x : x?.name || x?.id || "");
  return clean([
    card?.name, card?.description,
    item?.name, item?.displayName, item?.display_name, item?.description,
    ...tags, ...skills
  ].filter(Boolean).join(" "), 16000).toLowerCase();
}

function capabilitiesFromText(text) {
  return CAPABILITY_RULES
    .filter(([, words]) => words.some(w => text.includes(w)))
    .map(([name]) => name);
}

function pickEndpoint(item, card = null) {
  const interfaces = arr(card?.supportedInterfaces || card?.supported_interfaces || card?.interfaces);
  const direct = [
    interfaces[0]?.url,
    card?.url,
    item?.endpoint,
    item?.a2a_url,
    item?.a2aUrl,
    item?.url
  ];
  for (const candidate of direct) {
    const value = clean(candidate, 1000);
    if (/^https:\/\//i.test(value)) return value;
  }
  return "";
}

function remoteId(item, fallback = "") {
  return clean(item?.package_name || item?.packageName || item?.id || item?.agent_id || item?.agentId || item?.name || fallback, 300);
}

function protocolVersion(card, item) {
  const direct = clean(card?.protocolVersion || card?.protocol_version || item?.protocolVersion || item?.protocol_version, 30);
  if (direct) return direct;
  const interfaces = arr(card?.supportedInterfaces || card?.supported_interfaces || card?.interfaces);
  return clean(interfaces[0]?.protocolVersion || interfaces[0]?.protocol_version, 30);
}

function transports(card) {
  const interfaces = arr(card?.supportedInterfaces || card?.supported_interfaces || card?.interfaces);
  return interfaces.map(x => clean(x?.transport || x?.binding || x?.protocolBinding || x?.protocol_binding, 50)).filter(Boolean);
}

function normalizeSkills(card, item) {
  return arr(card?.skills || item?.skills).slice(0, 30).map(s => ({
    id: clean(s?.id, 100),
    name: clean(s?.name, 180),
    description: clean(s?.description, 800),
    tags: arr(s?.tags).map(x => clean(x, 80)).filter(Boolean).slice(0, 20),
    inputModes: arr(s?.inputModes || s?.input_modes).map(x => clean(x, 80)).filter(Boolean),
    outputModes: arr(s?.outputModes || s?.output_modes).map(x => clean(x, 80)).filter(Boolean)
  }));
}

function candidateCardUrls(item) {
  const urls = [];
  const direct = [item?.agent_card_url, item?.agentCardUrl, item?.manifest_url, item?.manifestUrl, item?.url, item?.endpoint];
  for (const raw of direct) {
    const value = clean(raw, 1000);
    if (!/^https:\/\//i.test(value)) continue;
    if (/agent-card\.json/i.test(value)) urls.push(value);
    try {
      const u = new URL(value);
      urls.push(`${u.origin}/.well-known/agent-card.json`);
    } catch {}
  }
  return [...new Set(urls)];
}

async function fetchJson(url) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const response = await fetch(url, {
      signal: controller.signal,
      headers: {
        "accept": "application/json",
        "user-agent": "LUMEN-PartnerNetwork/1.0"
      }
    });
    if (!response.ok) throw new Error(`http_${response.status}`);
    return await response.json();
  } finally { clearTimeout(timer); }
}

async function resolveCard(item) {
  if (item?.agentCard && typeof item.agentCard === "object") return { card: item.agentCard, cardUrl: clean(item?.agentCardUrl, 1000), reachable: true };
  if (item?.agent_card && typeof item.agent_card === "object") return { card: item.agent_card, cardUrl: clean(item?.agent_card_url, 1000), reachable: true };
  for (const url of candidateCardUrls(item)) {
    try {
      const card = await fetchJson(url);
      if (card && typeof card === "object" && (card.name || card.description || card.skills)) return { card, cardUrl: url, reachable: true };
    } catch {}
  }
  return { card: null, cardUrl: candidateCardUrls(item)[0] || "", reachable: false };
}

function scorePartner(item, cardInfo) {
  const card = cardInfo.card;
  const text = textOf(item, card);
  const skills = normalizeSkills(card, item);
  const caps = capabilitiesFromText(text);
  const endpoint = pickEndpoint(item, card);
  const protocol = protocolVersion(card, item);
  const provider = card?.provider || item?.provider || null;
  const signatures = arr(card?.signatures || card?.signature);
  const security = card?.securitySchemes || card?.security_schemes || card?.security || null;
  const interfaces = arr(card?.supportedInterfaces || card?.supported_interfaces || card?.interfaces);

  let reputation = 20;
  const reasons = [];
  if (cardInfo.reachable) { reputation += 20; reasons.push("agent_card_reachable"); }
  if (endpoint.startsWith("https://")) { reputation += 10; reasons.push("https_endpoint"); }
  if (protocol.startsWith("1.")) { reputation += 12; reasons.push("a2a_1x"); }
  else if (protocol.startsWith("0.3")) { reputation += 9; reasons.push("a2a_03_compatible"); }
  if (skills.length) { reputation += Math.min(18, skills.length * 3); reasons.push(`skills:${skills.length}`); }
  if (provider && typeof provider === "object") { reputation += 6; reasons.push("provider_declared"); }
  if (signatures.length) { reputation += 7; reasons.push("card_signed"); }
  if (interfaces.length > 1) { reputation += 3; reasons.push("multiple_interfaces"); }
  if (caps.length >= 2) { reputation += Math.min(8, caps.length * 2); reasons.push(`capabilities:${caps.length}`); }

  const negative = ["demo only", "testnet only", "sandbox only", "mock agent", "synthetic agent", "hello world"];
  const negHits = negative.filter(x => text.includes(x)).length;
  if (negHits) { reputation -= Math.min(35, negHits * 15); reasons.push(`test_penalty:${negHits}`); }

  reputation = Math.max(0, Math.min(100, reputation));
  const compatibility = Math.max(0, Math.min(100,
    20 +
    (cardInfo.reachable ? 20 : 0) +
    (endpoint ? 15 : 0) +
    (protocol.startsWith("1.") ? 20 : protocol.startsWith("0.3") ? 16 : 5) +
    Math.min(20, caps.length * 4) +
    Math.min(5, skills.length)
  ));

  return {
    reputation,
    compatibility,
    reasons,
    text,
    skills,
    capabilities: caps,
    endpoint,
    protocol,
    transports: transports(card),
    provider,
    security,
    status: reputation >= 75 ? "strong_candidate" : reputation >= 55 ? "candidate" : "watch"
  };
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_partner_agents (id TEXT PRIMARY KEY, discovered_at TEXT NOT NULL, updated_at TEXT NOT NULL, source TEXT NOT NULL, remote_id TEXT NOT NULL, name TEXT, card_url TEXT, endpoint TEXT, description TEXT, protocol_version TEXT, transports_json TEXT, skills_json TEXT, capabilities_json TEXT, provider_json TEXT, security_json TEXT, reputation_score INTEGER NOT NULL, compatibility_score INTEGER NOT NULL, status TEXT NOT NULL, evidence TEXT, raw_json TEXT)"),
    env.DB.prepare("CREATE UNIQUE INDEX IF NOT EXISTS idx_lumen_partner_agents_source_remote ON lumen_partner_agents(source,remote_id)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_partner_agents_rank ON lumen_partner_agents(status,reputation_score,compatibility_score,updated_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_partner_runs (id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL, discovered INTEGER NOT NULL DEFAULT 0, updated INTEGER NOT NULL DEFAULT 0, cards_reachable INTEGER NOT NULL DEFAULT 0, errors INTEGER NOT NULL DEFAULT 0, details TEXT)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_partner_matches (id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL, partner_id TEXT NOT NULL, match_score INTEGER NOT NULL, matched_capabilities_json TEXT NOT NULL, reason TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"),
    env.DB.prepare("CREATE UNIQUE INDEX IF NOT EXISTS idx_lumen_partner_match_unique ON lumen_partner_matches(opportunity_id,partner_id)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_partner_matches_rank ON lumen_partner_matches(opportunity_id,status,match_score)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_partner_councils (id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, status TEXT NOT NULL, goal TEXT NOT NULL, members_json TEXT NOT NULL, plan_json TEXT NOT NULL, binding_allowed INTEGER NOT NULL DEFAULT 0, spend_allowed INTEGER NOT NULL DEFAULT 0)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_partner_councils_opp ON lumen_partner_councils(opportunity_id,created_at)")
  ]);
  return true;
}

async function upsertPartner(env, item, source, evidence) {
  const rid = remoteId(item, evidence);
  if (!rid) return { skipped: true };
  const selfText = `${rid} ${clean(item?.name,300)} ${clean(item?.description,1000)}`.toLowerCase();
  if (selfText.includes("joseandres1984") || selfText.includes("lumen_b2b") || selfText.includes("lumen b2b")) return { skipped: true };

  const cardInfo = await resolveCard(item);
  const scored = scorePartner(item, cardInfo);
  if (scored.reputation < 35 || !scored.capabilities.length) return { skipped: true, cardReachable: cardInfo.reachable };

  const id = `PAR-${(await sha256(`${source}|${rid}`)).slice(0,20).toUpperCase()}`;
  const now = new Date().toISOString();
  const existing = await env.DB.prepare("SELECT id FROM lumen_partner_agents WHERE id=?").bind(id).first();
  const name = clean(cardInfo.card?.name || item?.displayName || item?.display_name || item?.name || rid, 300);
  const description = clean(cardInfo.card?.description || item?.description, 3000);

  await env.DB.prepare("INSERT INTO lumen_partner_agents(id,discovered_at,updated_at,source,remote_id,name,card_url,endpoint,description,protocol_version,transports_json,skills_json,capabilities_json,provider_json,security_json,reputation_score,compatibility_score,status,evidence,raw_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,name=excluded.name,card_url=excluded.card_url,endpoint=excluded.endpoint,description=excluded.description,protocol_version=excluded.protocol_version,transports_json=excluded.transports_json,skills_json=excluded.skills_json,capabilities_json=excluded.capabilities_json,provider_json=excluded.provider_json,security_json=excluded.security_json,reputation_score=excluded.reputation_score,compatibility_score=excluded.compatibility_score,status=excluded.status,evidence=excluded.evidence,raw_json=excluded.raw_json")
    .bind(
      id, now, now, source, rid, name, cardInfo.cardUrl, scored.endpoint, description, scored.protocol,
      safeJson(scored.transports), safeJson(scored.skills), safeJson(scored.capabilities), safeJson(scored.provider), safeJson(scored.security),
      scored.reputation, scored.compatibility, scored.status, clean(evidence,1600), safeJson({ item, card: cardInfo.card }).slice(0,16000)
    ).run();

  return { inserted: !existing, updated: !!existing, id, cardReachable: cardInfo.reachable, reputation: scored.reputation, compatibility: scored.compatibility, capabilities: scored.capabilities };
}

export async function runPartnerDiscovery(env, meta = {}) {
  if (!(await ensureSchema(env))) return { ok:false, error:"persistence_unavailable" };
  const runId = `PARRUN-${crypto.randomUUID().replaceAll("-","").slice(0,12).toUpperCase()}`;
  const startedAt = new Date().toISOString();
  await env.DB.prepare("INSERT INTO lumen_partner_runs(id,started_at,status,details) VALUES(?,?,?,?)").bind(runId,startedAt,"running",safeJson({trigger:clean(meta?.trigger||"manual",80)})).run();

  let discovered = 0, updated = 0, cardsReachable = 0, errorCount = 0;
  const details = [];
  for (const query of PARTNER_QUERIES) {
    const url = `${REGISTRY_BASE}/public/agents?q=${encodeURIComponent(query)}`;
    let qDiscovered = 0, qUpdated = 0, qCards = 0;
    try {
      const payload = await fetchJson(url);
      const items = registryItems(payload).slice(0,MAX_PER_QUERY);
      for (const item of items) {
        const result = await upsertPartner(env,item,"global_a2a_registry",url);
        if (result.inserted) { discovered++; qDiscovered++; }
        if (result.updated) { updated++; qUpdated++; }
        if (result.cardReachable) { cardsReachable++; qCards++; }
      }
      details.push({query,ok:true,discovered:qDiscovered,updated:qUpdated,cardsReachable:qCards});
    } catch (error) {
      errorCount++;
      details.push({query,ok:false,error:clean(error?.message||error,240)});
    }
  }

  const finishedAt = new Date().toISOString();
  const status = errorCount === 0 ? "complete" : errorCount < PARTNER_QUERIES.length ? "partial" : "failed";
  await env.DB.prepare("UPDATE lumen_partner_runs SET finished_at=?,status=?,discovered=?,updated=?,cards_reachable=?,errors=?,details=? WHERE id=?")
    .bind(finishedAt,status,discovered,updated,cardsReachable,errorCount,safeJson(details).slice(0,16000),runId).run();

  return {
    ok: status !== "failed",
    version: VERSION,
    runId,status,startedAt,finishedAt,discovered,updated,cardsReachable,errorCount,
    guardrails:{autonomousRecruitment:false,autonomousHiring:false,autonomousOutgoingSpend:false,bindingActionsHumanGated:true}
  };
}

async function resolveOpportunity(env, opportunityId = "") {
  if (opportunityId) return await env.DB.prepare("SELECT o.*,a.commercial_score,a.commercial_fit,a.evidence_strength,a.commercially_actionable,a.synthetic_or_test_only FROM lumen_opportunities o LEFT JOIN lumen_opportunity_assessments a ON a.opportunity_id=o.id WHERE o.id=? LIMIT 1").bind(opportunityId).first();
  return await env.DB.prepare("SELECT o.*,a.commercial_score,a.commercial_fit,a.evidence_strength,a.commercially_actionable,a.synthetic_or_test_only FROM lumen_opportunities o JOIN lumen_opportunity_assessments a ON a.opportunity_id=o.id WHERE a.commercially_actionable=1 AND a.synthetic_or_test_only=0 ORDER BY a.commercial_score DESC,o.updated_at DESC LIMIT 1").first();
}

function opportunityNeeds(opp) {
  const offerNeeds = OFFER_NEEDS[clean(opp?.revenue_offer_id,100)] || [];
  const textNeeds = capabilitiesFromText(textOf(opp, null));
  return [...new Set([...offerNeeds, ...textNeeds])];
}

export async function buildPartnerMatches(env, opportunityId = "") {
  await ensureSchema(env);
  const opp = await resolveOpportunity(env, opportunityId);
  if (!opp) return { ok:false, error:"opportunity_not_found", version:VERSION };
  const needs = opportunityNeeds(opp);
  const partners = await env.DB.prepare("SELECT * FROM lumen_partner_agents WHERE status IN ('candidate','strong_candidate') ORDER BY reputation_score DESC,compatibility_score DESC LIMIT 120").all();
  const now = new Date().toISOString();
  const matches = [];

  for (const partner of partners.results || []) {
    let caps = []; try { caps = JSON.parse(partner.capabilities_json || "[]"); } catch {}
    const hit = caps.filter(x => needs.includes(x));
    if (!hit.length) continue;
    const coverage = hit.length / Math.max(1,needs.length);
    const matchScore = Math.max(0,Math.min(100,Math.round(
      Number(partner.reputation_score||0)*0.45 + Number(partner.compatibility_score||0)*0.25 + coverage*30
    )));
    if (matchScore < 45) continue;
    const id = `PM-${(await sha256(`${opp.id}|${partner.id}`)).slice(0,20).toUpperCase()}`;
    const reason = `needs:${needs.join(",")}; matched:${hit.join(",")}; reputation:${partner.reputation_score}; compatibility:${partner.compatibility_score}`;
    await env.DB.prepare("INSERT INTO lumen_partner_matches(id,opportunity_id,partner_id,match_score,matched_capabilities_json,reason,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET match_score=excluded.match_score,matched_capabilities_json=excluded.matched_capabilities_json,reason=excluded.reason,status=excluded.status,updated_at=excluded.updated_at")
      .bind(id,opp.id,partner.id,matchScore,safeJson(hit),reason,"candidate",now,now).run();
    matches.push({partnerId:partner.id,name:partner.name,matchScore,matchedCapabilities:hit,reputation:Number(partner.reputation_score||0),compatibility:Number(partner.compatibility_score||0),protocolVersion:partner.protocol_version,endpoint:partner.endpoint});
  }

  matches.sort((a,b)=>b.matchScore-a.matchScore || b.reputation-a.reputation);
  return {ok:true,version:VERSION,opportunity:{id:opp.id,name:opp.name,offerId:opp.revenue_offer_id,commercialScore:Number(opp.commercial_score||0)},needs,matches:matches.slice(0,20)};
}

function roleFor(capabilities) {
  const order = ["verification","sourcing","pricing","research","tender","export","logistics","sales","payments","automation"];
  return order.find(x => capabilities.includes(x)) || capabilities[0] || "specialist";
}

export async function assemblePartnerCouncil(env, opportunityId = "") {
  const matched = await buildPartnerMatches(env, opportunityId);
  if (!matched.ok) return matched;
  const selected = [];
  const usedRoles = new Set();
  for (const candidate of matched.matches) {
    const role = roleFor(candidate.matchedCapabilities);
    if (usedRoles.has(role) && selected.length >= 2) continue;
    selected.push({...candidate,role});
    usedRoles.add(role);
    if (selected.length >= 3) break;
  }
  if (!selected.length) return {ok:false,error:"no_compatible_partners",version:VERSION,opportunity:matched.opportunity,needs:matched.needs};

  const councilId = `COUNCIL-${crypto.randomUUID().replaceAll("-","").slice(0,12).toUpperCase()}`;
  const now = new Date().toISOString();
  const members = [
    {id:"LUMEN",name:"LUMEN",role:"coordinator",authority:"non_binding_coordination"},
    ...selected.map(x => ({id:x.partnerId,name:x.name,role:x.role,matchScore:x.matchScore,protocolVersion:x.protocolVersion,endpoint:x.endpoint}))
  ];
  const plan = [
    {step:1,owner:"LUMEN",action:"present_problem_and_shared_context"},
    ...selected.map((x,i)=>({step:i+2,owner:x.partnerId,action:`contribute_${x.role}_analysis`})),
    {step:selected.length+2,owner:"LUMEN",action:"compare_contributions_and_form_nonbinding_plan"},
    {step:selected.length+3,owner:"human_gate",action:"approve_any_binding_commitment_or_spend_if_needed"}
  ];
  const goal = `Resolve ${matched.opportunity.name} using complementary agent capabilities: ${matched.needs.join(", ")}`;
  await env.DB.prepare("INSERT INTO lumen_partner_councils(id,opportunity_id,created_at,updated_at,status,goal,members_json,plan_json,binding_allowed,spend_allowed) VALUES(?,?,?,?,?,?,?,?,0,0)")
    .bind(councilId,matched.opportunity.id,now,now,"DRAFT_COUNCIL",goal,safeJson(members),safeJson(plan)).run();

  return {
    ok:true,version:VERSION,councilId,status:"DRAFT_COUNCIL",opportunity:matched.opportunity,needs:matched.needs,members,plan,
    guardrails:{externalInvitesSent:false,bindingAllowed:false,spendAllowed:false,humanApprovalRequiredForHiring:true}
  };
}

async function stats(env) {
  await ensureSchema(env);
  const total = await env.DB.prepare("SELECT COUNT(*) AS n FROM lumen_partner_agents").first();
  const strong = await env.DB.prepare("SELECT COUNT(*) AS n FROM lumen_partner_agents WHERE status='strong_candidate'").first();
  const a2a1 = await env.DB.prepare("SELECT COUNT(*) AS n FROM lumen_partner_agents WHERE protocol_version LIKE '1.%'").first();
  const matched = await env.DB.prepare("SELECT COUNT(*) AS n FROM lumen_partner_matches WHERE status='candidate'").first();
  const councils = await env.DB.prepare("SELECT COUNT(*) AS n FROM lumen_partner_councils").first();
  const latestRun = await env.DB.prepare("SELECT id,started_at,finished_at,status,discovered,updated,cards_reachable,errors FROM lumen_partner_runs ORDER BY started_at DESC LIMIT 1").first();
  return json({version:VERSION,total:Number(total?.n||0),strongCandidates:Number(strong?.n||0),a2a1Compatible:Number(a2a1?.n||0),activeMatches:Number(matched?.n||0),councils:Number(councils?.n||0),latestRun:latestRun||null,autonomousRecruitment:false,autonomousHiring:false,autonomousOutgoingSpend:false});
}

async function topPartners(env) {
  await ensureSchema(env);
  const rows = await env.DB.prepare("SELECT id,name,endpoint,card_url,protocol_version,capabilities_json,reputation_score,compatibility_score,status,updated_at FROM lumen_partner_agents ORDER BY reputation_score DESC,compatibility_score DESC,updated_at DESC LIMIT 30").all();
  return json({version:VERSION,partners:(rows.results||[]).map(r=>{let c=[];try{c=JSON.parse(r.capabilities_json||"[]");}catch{}return {...r,capabilities:c};})});
}

async function councils(env) {
  await ensureSchema(env);
  const rows = await env.DB.prepare("SELECT id,opportunity_id,created_at,updated_at,status,goal,members_json,plan_json,binding_allowed,spend_allowed FROM lumen_partner_councils ORDER BY created_at DESC LIMIT 30").all();
  return json({version:VERSION,councils:(rows.results||[]).map(r=>{let members=[],plan=[];try{members=JSON.parse(r.members_json||"[]");}catch{}try{plan=JSON.parse(r.plan_json||"[]");}catch{}return {...r,members,plan};})});
}

function authorized(request, env) {
  const configured = clean(env?.OPPORTUNITY_ADMIN_TOKEN,500);
  const provided = clean(request.headers.get("x-lumen-admin"),500);
  return Boolean(configured && provided && configured === provided);
}

async function bodyJson(request) {
  try { return await request.json(); } catch { return {}; }
}

export async function handlePartnerNetwork(request, env) {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/partners/stats") return stats(env);
  if (request.method === "GET" && url.pathname === "/partners/top") return topPartners(env);
  if (request.method === "GET" && url.pathname === "/partners/councils") return councils(env);

  if (request.method === "POST" && url.pathname === "/partners/discover") {
    if (!authorized(request,env)) return json({ok:false,error:"admin_token_required"},403);
    return json(await runPartnerDiscovery(env,{trigger:"admin_api"}),202);
  }
  if (request.method === "POST" && url.pathname === "/partners/match") {
    if (!authorized(request,env)) return json({ok:false,error:"admin_token_required"},403);
    const body = await bodyJson(request);
    return json(await buildPartnerMatches(env,clean(body?.opportunityId,100)),202);
  }
  if (request.method === "POST" && url.pathname === "/partners/council") {
    if (!authorized(request,env)) return json({ok:false,error:"admin_token_required"},403);
    const body = await bodyJson(request);
    return json(await assemblePartnerCouncil(env,clean(body?.opportunityId,100)),202);
  }
  return null;
}
