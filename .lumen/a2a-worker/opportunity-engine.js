const VERSION = "1.0-a2a-opportunity-engine";
const REGISTRY_BASE = "https://api.a2a-registry.org";
const SIGNALS_URL = "https://clavis.citriac.deno.net/signals";
const MAX_PER_SOURCE = 40;
const FETCH_TIMEOUT_MS = 8000;

const REGISTRY_QUERIES = [
  "procurement sourcing RFQ",
  "buyer demand commerce",
  "tender purchasing supplier",
  "export importer distributor",
  "B2B market intelligence",
  "x402 agent commerce"
];

const OFFER_RULES = [
  { id: "MP-TENDER-SCAN", words: ["tender", "procurement notice", "bid", "public procurement"] },
  { id: "MP-QUOTE-SANITY", words: ["rfq", "quote", "quotation", "pricing", "proposal"] },
  { id: "MP-SOURCING-5", words: ["sourcing", "supplier", "procurement", "vendor", "purchase"] },
  { id: "MP-BUYER-SIGNALS", words: ["buyer", "sales", "prospect", "demand", "lead", "intent"] },
  { id: "MP-EXPORT-PULSE", words: ["export", "import", "importer", "distributor", "international trade"] },
  { id: "MP-SUPPLIER-SNAPSHOT", words: ["verification", "verify", "due diligence", "trust", "supplier"] }
];

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

function stringifyTags(value) {
  return arr(value).map(x => clean(typeof x === "string" ? x : x?.name || x?.id, 100)).filter(Boolean);
}

function normalizedText(item) {
  const skills = arr(item?.skills).flatMap(s => [s?.name, s?.description, ...arr(s?.tags)]);
  return clean([
    item?.name,
    item?.displayName,
    item?.display_name,
    item?.description,
    item?.category,
    item?.target,
    ...stringifyTags(item?.tags),
    ...skills
  ].filter(Boolean).join(" "), 12000).toLowerCase();
}

function pickEndpoint(item) {
  const direct = [item?.url, item?.endpoint, item?.a2a_url, item?.a2aUrl, item?.manifest_url, item?.manifestUrl];
  const interfaces = arr(item?.supportedInterfaces || item?.supported_interfaces || item?.interfaces);
  for (const candidate of [...direct, ...interfaces.map(x => x?.url)]) {
    const value = clean(candidate, 500);
    if (/^https:\/\//i.test(value)) return value;
  }
  return "";
}

function remoteId(item, fallback = "") {
  return clean(item?.package_name || item?.packageName || item?.id || item?.agent_id || item?.agentId || item?.name || fallback, 300);
}

async function sha256(text) {
  const bytes = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, "0")).join("");
}

function chooseOffer(text) {
  let best = { id: "MP-BUYER-SIGNALS", hits: 0 };
  for (const rule of OFFER_RULES) {
    const hits = rule.words.reduce((n, w) => n + (text.includes(w) ? 1 : 0), 0);
    if (hits > best.hits) best = { id: rule.id, hits };
  }
  return best.id;
}

function scoreOpportunity(item, source, query = "") {
  const text = normalizedText(item);
  let score = 15;
  const reasons = [];

  const demandWords = ["need", "needs", "buy", "buyer", "buying", "request", "rfq", "procure", "procurement", "tender", "looking for", "seeking", "demand"];
  const businessWords = ["b2b", "business", "supplier", "vendor", "commerce", "market", "sales", "sourcing", "export", "import", "distributor"];
  const agentCommerce = ["a2a", "x402", "paid", "payment", "commerce", "marketplace", "agent"];

  const demandHits = demandWords.filter(w => text.includes(w)).length;
  const businessHits = businessWords.filter(w => text.includes(w)).length;
  const commerceHits = agentCommerce.filter(w => text.includes(w)).length;

  if (demandHits) { score += Math.min(30, demandHits * 6); reasons.push(`demand_signals:${demandHits}`); }
  if (businessHits) { score += Math.min(24, businessHits * 4); reasons.push(`b2b_fit:${businessHits}`); }
  if (commerceHits) { score += Math.min(15, commerceHits * 3); reasons.push(`agent_commerce:${commerceHits}`); }
  if (item?.verified === true || String(item?.status || "").toLowerCase().includes("verified")) { score += 8; reasons.push("verified_counterparty"); }
  if (pickEndpoint(item)) { score += 5; reasons.push("reachable_endpoint_declared"); }
  if (source === "agent_exchange_signal") { score += 12; reasons.push("explicit_network_signal"); }
  if (query && text.includes(query.toLowerCase())) { score += 3; }

  const negative = ["weather", "horoscope", "game", "dating", "adult", "casino", "gambling"];
  const negativeHits = negative.filter(w => text.includes(w)).length;
  if (negativeHits) { score -= negativeHits * 15; reasons.push(`negative_fit:${negativeHits}`); }

  score = Math.max(0, Math.min(100, score));
  const fit = score >= 75 ? "A" : score >= 55 ? "B" : score >= 35 ? "C" : "D";
  return { score, fit, reasons, offerId: chooseOffer(text), text };
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_opportunities (id TEXT PRIMARY KEY, discovered_at TEXT NOT NULL, updated_at TEXT NOT NULL, source TEXT NOT NULL, remote_id TEXT NOT NULL, name TEXT, endpoint TEXT, description TEXT, tags_json TEXT, score INTEGER NOT NULL, fit TEXT NOT NULL, demand_signal INTEGER NOT NULL DEFAULT 0, revenue_offer_id TEXT, status TEXT NOT NULL, evidence TEXT, raw_json TEXT)"),
    env.DB.prepare("CREATE UNIQUE INDEX IF NOT EXISTS idx_lumen_opportunities_source_remote ON lumen_opportunities(source,remote_id)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_opportunities_rank ON lumen_opportunities(status,score,updated_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_opportunity_runs (id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL, discovered INTEGER NOT NULL DEFAULT 0, updated INTEGER NOT NULL DEFAULT 0, sources_ok INTEGER NOT NULL DEFAULT 0, sources_failed INTEGER NOT NULL DEFAULT 0, details TEXT)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_opportunity_runs_started ON lumen_opportunity_runs(started_at)")
  ]);
  return true;
}

async function fetchJson(url, init = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const response = await fetch(url, {
      ...init,
      signal: controller.signal,
      headers: {
        "accept": "application/json",
        "user-agent": "LUMEN-OpportunityEngine/1.0",
        ...(init.headers || {})
      }
    });
    if (!response.ok) throw new Error(`http_${response.status}`);
    return await response.json();
  } finally {
    clearTimeout(timer);
  }
}

function registryItems(payload) {
  if (Array.isArray(payload)) return payload;
  for (const value of [payload?.agents, payload?.data?.agents, payload?.data, payload?.results, payload?.items]) {
    if (Array.isArray(value)) return value;
  }
  return [];
}

function signalItems(payload) {
  if (Array.isArray(payload)) return payload;
  for (const value of [payload?.signals, payload?.data?.signals, payload?.data, payload?.results, payload?.items]) {
    if (Array.isArray(value)) return value;
  }
  return [];
}

function isSelf(item) {
  const text = normalizedText(item);
  const id = remoteId(item).toLowerCase();
  return id.includes("joseandres1984") || id.includes("lumen_b2b") || text.includes("lumen b2b agent");
}

async function upsertOpportunity(env, item, { source, query = "", evidence = "" }) {
  const rid = remoteId(item, clean(evidence, 180));
  if (!rid || isSelf(item)) return { skipped: true };
  const scored = scoreOpportunity(item, source, query);
  if (scored.score < 30) return { skipped: true };

  const id = `OPP-${(await sha256(`${source}|${rid}`)).slice(0, 20).toUpperCase()}`;
  const now = new Date().toISOString();
  const endpoint = pickEndpoint(item);
  const name = clean(item?.displayName || item?.display_name || item?.name || rid, 300);
  const description = clean(item?.description || item?.summary || item?.message || item?.text, 3000);
  const tags = stringifyTags(item?.tags || arr(item?.skills).flatMap(s => s?.tags || []));
  const demandSignal = scored.reasons.some(x => x.startsWith("demand_signals") || x === "explicit_network_signal") ? 1 : 0;

  const existing = await env.DB.prepare("SELECT id,score,status FROM lumen_opportunities WHERE id=?").bind(id).first();
  const nextStatus = existing?.status && !["new", "watching", "qualified"].includes(existing.status) ? existing.status : scored.fit === "A" ? "qualified" : "watching";

  await env.DB.prepare("INSERT INTO lumen_opportunities(id,discovered_at,updated_at,source,remote_id,name,endpoint,description,tags_json,score,fit,demand_signal,revenue_offer_id,status,evidence,raw_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,name=excluded.name,endpoint=excluded.endpoint,description=excluded.description,tags_json=excluded.tags_json,score=MAX(lumen_opportunities.score,excluded.score),fit=CASE WHEN excluded.score>lumen_opportunities.score THEN excluded.fit ELSE lumen_opportunities.fit END,demand_signal=MAX(lumen_opportunities.demand_signal,excluded.demand_signal),revenue_offer_id=CASE WHEN excluded.score>=lumen_opportunities.score THEN excluded.revenue_offer_id ELSE lumen_opportunities.revenue_offer_id END,evidence=excluded.evidence,raw_json=excluded.raw_json")
    .bind(id, now, now, source, rid, name, endpoint, description, JSON.stringify(tags), scored.score, scored.fit, demandSignal, scored.offerId, nextStatus, clean(evidence, 1600), JSON.stringify(item).slice(0, 12000)).run();

  return { inserted: !existing, updated: !!existing, id, score: scored.score, fit: scored.fit };
}

async function scanRegistry(env) {
  let discovered = 0;
  let updated = 0;
  const errors = [];

  for (const query of REGISTRY_QUERIES) {
    try {
      const url = `${REGISTRY_BASE}/public/agents?q=${encodeURIComponent(query)}`;
      const payload = await fetchJson(url);
      const items = registryItems(payload).slice(0, MAX_PER_SOURCE);
      for (const item of items) {
        const result = await upsertOpportunity(env, item, { source: "global_a2a_registry", query, evidence: url });
        if (result.inserted) discovered += 1;
        if (result.updated) updated += 1;
      }
    } catch (error) {
      errors.push(`${query}:${clean(error, 180)}`);
    }
  }
  return { source: "global_a2a_registry", discovered, updated, ok: errors.length < REGISTRY_QUERIES.length, errors };
}

async function scanSignals(env) {
  let discovered = 0;
  let updated = 0;
  const errors = [];
  try {
    const payload = await fetchJson(SIGNALS_URL);
    const items = signalItems(payload).slice(0, MAX_PER_SOURCE);
    for (let i = 0; i < items.length; i++) {
      const raw = items[i] || {};
      const normalized = {
        ...raw,
        id: raw.id || raw.signal_id || raw.signalId || `${raw.created_at || raw.timestamp || "signal"}-${i}`,
        name: raw.agent_name || raw.agent || raw.from || raw.name || "Agent Exchange signal",
        description: raw.message || raw.text || raw.description || raw.signal || "",
        tags: raw.tags || [raw.type, raw.kind].filter(Boolean),
        url: raw.url || raw.endpoint || raw.agent_url || raw.agentUrl || ""
      };
      const result = await upsertOpportunity(env, normalized, { source: "agent_exchange_signal", evidence: SIGNALS_URL });
      if (result.inserted) discovered += 1;
      if (result.updated) updated += 1;
    }
  } catch (error) {
    errors.push(clean(error, 180));
  }
  return { source: "agent_exchange_signal", discovered, updated, ok: errors.length === 0, errors };
}

export async function runOpportunityScan(env, meta = {}) {
  if (!(await ensureSchema(env))) return { ok: false, error: "persistence_unavailable" };
  const runId = `OPRUN-${crypto.randomUUID().replaceAll("-", "").slice(0, 12).toUpperCase()}`;
  const startedAt = new Date().toISOString();
  await env.DB.prepare("INSERT INTO lumen_opportunity_runs(id,started_at,status,details) VALUES(?,?,?,?)")
    .bind(runId, startedAt, "running", JSON.stringify({ trigger: clean(meta?.trigger || "scheduled", 80) })).run();

  const results = [];
  for (const fn of [scanRegistry, scanSignals]) {
    try { results.push(await fn(env)); }
    catch (error) { results.push({ source: fn.name, discovered: 0, updated: 0, ok: false, errors: [clean(error, 240)] }); }
  }

  const discovered = results.reduce((n, x) => n + Number(x.discovered || 0), 0);
  const updated = results.reduce((n, x) => n + Number(x.updated || 0), 0);
  const sourcesOk = results.filter(x => x.ok).length;
  const sourcesFailed = results.length - sourcesOk;
  const status = sourcesOk > 0 ? (sourcesFailed ? "partial" : "complete") : "failed";
  const finishedAt = new Date().toISOString();

  await env.DB.prepare("UPDATE lumen_opportunity_runs SET finished_at=?,status=?,discovered=?,updated=?,sources_ok=?,sources_failed=?,details=? WHERE id=?")
    .bind(finishedAt, status, discovered, updated, sourcesOk, sourcesFailed, JSON.stringify(results).slice(0, 12000), runId).run();

  return {
    ok: sourcesOk > 0,
    version: VERSION,
    runId,
    status,
    startedAt,
    finishedAt,
    discovered,
    updated,
    sourcesOk,
    sourcesFailed,
    results,
    guardrails: {
      autonomousOutgoingSpend: false,
      autonomousPurchase: false,
      autonomousContract: false,
      autonomousOutreach: false,
      bindingActionsHumanGated: true
    }
  };
}

async function listOpportunities(env, url) {
  await ensureSchema(env);
  const minScore = Math.max(0, Math.min(100, Number(url.searchParams.get("min_score") || 35)));
  const limit = Math.max(1, Math.min(100, Number(url.searchParams.get("limit") || 30)));
  const status = clean(url.searchParams.get("status"), 40);
  const sql = status
    ? "SELECT id,discovered_at,updated_at,source,remote_id,name,endpoint,description,tags_json,score,fit,demand_signal,revenue_offer_id,status,evidence FROM lumen_opportunities WHERE score>=? AND status=? ORDER BY score DESC,updated_at DESC LIMIT ?"
    : "SELECT id,discovered_at,updated_at,source,remote_id,name,endpoint,description,tags_json,score,fit,demand_signal,revenue_offer_id,status,evidence FROM lumen_opportunities WHERE score>=? ORDER BY score DESC,updated_at DESC LIMIT ?";
  const stmt = status ? env.DB.prepare(sql).bind(minScore, status, limit) : env.DB.prepare(sql).bind(minScore, limit);
  const rows = await stmt.all();
  return json({
    version: VERSION,
    opportunities: (rows.results || []).map(row => ({
      ...row,
      tags: (() => { try { return JSON.parse(row.tags_json || "[]"); } catch { return []; } })(),
      recommendedAction: row.fit === "A" ? "prepare_nonbinding_offer_for_quality_gate" : "continue_observation_and_verification"
    })),
    policy: { autonomousOutreach: false, bindingActionsHumanGated: true, autonomousOutgoingSpend: false }
  });
}

async function nextOpportunity(env) {
  await ensureSchema(env);
  const row = await env.DB.prepare("SELECT id,discovered_at,updated_at,source,remote_id,name,endpoint,description,tags_json,score,fit,demand_signal,revenue_offer_id,status,evidence FROM lumen_opportunities WHERE status IN ('qualified','watching') ORDER BY CASE fit WHEN 'A' THEN 0 WHEN 'B' THEN 1 WHEN 'C' THEN 2 ELSE 3 END, score DESC, updated_at DESC LIMIT 1").first();
  if (!row) return json({ version: VERSION, opportunity: null, nextAction: "run_or_wait_for_discovery_scan" });
  let tags = []; try { tags = JSON.parse(row.tags_json || "[]"); } catch {}
  return json({
    version: VERSION,
    opportunity: { ...row, tags },
    nextAction: {
      action: "prepare_nonbinding_offer_for_quality_gate",
      offerId: row.revenue_offer_id,
      autonomousSend: false,
      reason: "Highest-ranked current external opportunity. LUMEN may prepare a pitch, but external outreach remains disabled until a separate quality-gated sender is explicitly enabled."
    },
    guardrails: { autonomousOutgoingSpend: false, bindingActionsHumanGated: true, autonomousOutreach: false }
  });
}

async function stats(env) {
  await ensureSchema(env);
  const total = await env.DB.prepare("SELECT COUNT(*) AS n FROM lumen_opportunities").first();
  const qualified = await env.DB.prepare("SELECT COUNT(*) AS n FROM lumen_opportunities WHERE fit='A'").first();
  const demand = await env.DB.prepare("SELECT COUNT(*) AS n FROM lumen_opportunities WHERE demand_signal=1").first();
  const latestRun = await env.DB.prepare("SELECT id,started_at,finished_at,status,discovered,updated,sources_ok,sources_failed,details FROM lumen_opportunity_runs ORDER BY started_at DESC LIMIT 1").first();
  return json({
    version: VERSION,
    total: Number(total?.n || 0),
    qualifiedA: Number(qualified?.n || 0),
    withDemandSignal: Number(demand?.n || 0),
    latestRun: latestRun || null,
    sources: [REGISTRY_BASE, SIGNALS_URL],
    autonomousOutreach: false,
    autonomousOutgoingSpend: false
  });
}

async function manualRun(request, env) {
  const configured = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const provided = clean(request.headers.get("x-lumen-admin"), 500);
  if (!configured || !provided || provided !== configured) return json({ ok: false, error: "admin_token_required" }, 403);
  return json(await runOpportunityScan(env, { trigger: "manual" }), 202);
}

export async function handleOpportunityEngine(request, env) {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/opportunities") return listOpportunities(env, url);
  if (request.method === "GET" && url.pathname === "/opportunities/next") return nextOpportunity(env);
  if (request.method === "GET" && url.pathname === "/opportunities/stats") return stats(env);
  if (request.method === "POST" && url.pathname === "/opportunities/run") return manualRun(request, env);
  return null;
}
