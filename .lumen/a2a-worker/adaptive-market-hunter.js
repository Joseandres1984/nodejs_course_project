const VERSION = "1.0-adaptive-market-hunter";
const REGISTRY_BASE = "https://api.a2a-registry.org";
const MAX_QUERIES_PER_RUN = 3;
const MAX_RESULTS_PER_QUERY = 20;
const MAX_ACTIVE_STRATEGIES = 24;
const FETCH_TIMEOUT_MS = 8000;

const QUALIFIED_CLASSES = ["PURCHASE_INTENT", "COMMERCIAL_INTEREST", "COMMERCIAL_QUESTION"];
const INTENT_VARIANTS = ["seeking", "need", "request", "buying", "looking for"];

const OFFER_CORE = Object.freeze({
  "MP-SUPPLIER-SNAPSHOT": "supplier verification due diligence procurement",
  "MP-QUOTE-SANITY": "rfq quote pricing comparison vendor",
  "MP-TENDER-SCAN": "tender bid procurement deadline",
  "MP-SOURCING-5": "supplier vendor sourcing shortlist",
  "MP-BUYER-SIGNALS": "buyer demand intent procurement",
  "MP-EXPORT-PULSE": "importer distributor export sourcing"
});

const SEEDS = [
  { id: "MH-SUPPLIER-VERIFY", query: "supplier verification due diligence procurement", offerId: "MP-SUPPLIER-SNAPSHOT" },
  { id: "MH-RFQ-PRICE", query: "request for quote rfq supplier pricing", offerId: "MP-QUOTE-SANITY" },
  { id: "MH-TENDER-BID", query: "tender bid procurement deadline", offerId: "MP-TENDER-SCAN" },
  { id: "MH-SOURCING", query: "seeking supplier vendor sourcing", offerId: "MP-SOURCING-5" },
  { id: "MH-BUYER-INTENT", query: "buyer intent looking to buy procurement", offerId: "MP-BUYER-SIGNALS" },
  { id: "MH-EXPORT", query: "importer distributor export sourcing", offerId: "MP-EXPORT-PULSE" },
  { id: "MH-X402-COMMERCE", query: "x402 buyer procurement agent commerce", offerId: "MP-BUYER-SIGNALS" },
  { id: "MH-VENDOR-COMPARE", query: "vendor comparison quotation procurement", offerId: "MP-QUOTE-SANITY" }
];

const STOPWORDS = new Set([
  "about","after","again","agent","agents","also","and","any","are","available","been","before","being","between","business","can","commerce","could","description","from","have","into","looking","market","more","need","needs","offer","public","request","service","services","signal","signals","that","their","them","there","these","they","this","through","using","vendor","with","would","your","procurement","supplier","sourcing","buyer","quote","tender","export","importer","distributor","pricing"
]);

function json(data, status = 200) {
  return Response.json(data, { status, headers: { "cache-control": "no-store", "x-content-type-options": "nosniff", "access-control-allow-origin": "*" } });
}
function clean(value, limit = 6000) { return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit); }
function num(value, fallback = 0) { const n = Number(value); return Number.isFinite(n) ? n : fallback; }
function clamp(value, min = 0, max = 100) { return Math.max(min, Math.min(max, num(value))); }
function arr(value) { return Array.isArray(value) ? value : value == null ? [] : [value]; }
function authorized(request, env) {
  const configured = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const provided = clean(request.headers.get("x-lumen-admin"), 500);
  return Boolean(configured && provided && configured === provided);
}
function isHttps(value) { try { return new URL(value).protocol === "https:"; } catch { return false; } }

async function sha256(text) {
  const bytes = new TextEncoder().encode(String(text));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, "0")).join("");
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_opportunities (id TEXT PRIMARY KEY, discovered_at TEXT NOT NULL, updated_at TEXT NOT NULL, source TEXT NOT NULL, remote_id TEXT NOT NULL, name TEXT, endpoint TEXT, description TEXT, tags_json TEXT, score INTEGER NOT NULL, fit TEXT NOT NULL, demand_signal INTEGER NOT NULL DEFAULT 0, revenue_offer_id TEXT, status TEXT NOT NULL, evidence TEXT, raw_json TEXT)"),
    env.DB.prepare("CREATE UNIQUE INDEX IF NOT EXISTS idx_lumen_opportunities_source_remote ON lumen_opportunities(source,remote_id)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_market_hunter_strategies (id TEXT PRIMARY KEY,query TEXT NOT NULL UNIQUE,offer_id TEXT NOT NULL,parent_id TEXT,generation INTEGER NOT NULL DEFAULT 0,active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,runs INTEGER NOT NULL DEFAULT 0,discoveries INTEGER NOT NULL DEFAULT 0,actionable INTEGER NOT NULL DEFAULT 0,proposals INTEGER NOT NULL DEFAULT 0,qualified_responses INTEGER NOT NULL DEFAULT 0,settlements INTEGER NOT NULL DEFAULT 0,revenue_usd REAL NOT NULL DEFAULT 0,score REAL NOT NULL DEFAULT 50,evidence_level TEXT NOT NULL DEFAULT 'COLD',no_signal_runs INTEGER NOT NULL DEFAULT 0,last_run_at TEXT,last_reason TEXT,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_market_hunter_rank ON lumen_market_hunter_strategies(active,score DESC,runs ASC,updated_at DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_market_hunter_attribution (opportunity_id TEXT PRIMARY KEY,strategy_id TEXT NOT NULL,first_seen_at TEXT NOT NULL,last_seen_at TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_market_hunter_attr_strategy ON lumen_market_hunter_attribution(strategy_id,last_seen_at DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_market_hunter_runs (id TEXT PRIMARY KEY,started_at TEXT NOT NULL,finished_at TEXT,status TEXT NOT NULL,selected_json TEXT NOT NULL,results_json TEXT,generated_strategy_id TEXT,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_market_hunter_runs_started ON lumen_market_hunter_runs(started_at DESC)")
  ]);
  const now = new Date().toISOString();
  for (const seed of SEEDS) {
    await env.DB.prepare("INSERT INTO lumen_market_hunter_strategies(id,query,offer_id,parent_id,generation,active,created_at,updated_at,engine_version) VALUES(?,?,?,?,0,1,?,?,?) ON CONFLICT(id) DO NOTHING")
      .bind(seed.id, seed.query, seed.offerId, null, now, now, VERSION).run();
  }
  return true;
}

async function safeAll(env, sql, binds = []) {
  try { const q = env.DB.prepare(sql); const r = binds.length ? await q.bind(...binds).all() : await q.all(); return r.results || []; } catch { return []; }
}
async function safeFirst(env, sql, binds = []) {
  try { const q = env.DB.prepare(sql); return binds.length ? await q.bind(...binds).first() : await q.first(); } catch { return null; }
}
async function safeNumber(env, sql, binds = []) {
  const row = await safeFirst(env, sql, binds); return num(row?.n, 0);
}

function registryItems(payload) {
  if (Array.isArray(payload)) return payload;
  for (const value of [payload?.agents, payload?.data?.agents, payload?.data, payload?.results, payload?.items]) if (Array.isArray(value)) return value;
  return [];
}
function stringifyTags(value) { return arr(value).map(x => clean(typeof x === "string" ? x : x?.name || x?.id, 100)).filter(Boolean); }
function normalizedText(item) {
  const skills = arr(item?.skills).flatMap(s => [s?.name, s?.description, ...arr(s?.tags)]);
  return clean([item?.name,item?.displayName,item?.display_name,item?.description,item?.summary,item?.message,item?.text,item?.category,item?.target,...stringifyTags(item?.tags),...skills].filter(Boolean).join(" "), 16000).toLowerCase();
}
function remoteId(item, fallback = "") { return clean(item?.package_name || item?.packageName || item?.id || item?.agent_id || item?.agentId || item?.name || fallback, 300); }
function pickEndpoint(item) {
  const direct = [item?.url,item?.endpoint,item?.a2a_url,item?.a2aUrl,item?.manifest_url,item?.manifestUrl];
  const interfaces = arr(item?.supportedInterfaces || item?.supported_interfaces || item?.interfaces);
  for (const candidate of [...direct, ...interfaces.map(x => x?.url)]) {
    const value = clean(candidate, 500); if (isHttps(value)) return value;
  }
  return "";
}
function isSelf(item) {
  const text = normalizedText(item), id = remoteId(item).toLowerCase();
  return id.includes("joseandres1984") || id.includes("lumen_b2b") || text.includes("lumen b2b agent");
}

function scoreOpportunity(item, strategy) {
  const text = normalizedText(item);
  let score = 15;
  const reasons = [];
  const demandWords = ["need","needs","buy","buyer","buying","request","rfq","procure","procurement","tender","looking for","seeking","demand","quantity","budget"];
  const businessWords = ["b2b","business","supplier","vendor","commerce","market","sales","sourcing","export","import","distributor","pricing","quotation"];
  const commerceWords = ["a2a","x402","paid","payment","commerce","marketplace","agent"];
  const demandHits = demandWords.filter(w => text.includes(w)).length;
  const businessHits = businessWords.filter(w => text.includes(w)).length;
  const commerceHits = commerceWords.filter(w => text.includes(w)).length;
  if (demandHits) { score += Math.min(32, demandHits * 6); reasons.push(`demand_signals:${demandHits}`); }
  if (businessHits) { score += Math.min(24, businessHits * 4); reasons.push(`b2b_fit:${businessHits}`); }
  if (commerceHits) { score += Math.min(12, commerceHits * 2); reasons.push(`agent_commerce:${commerceHits}`); }
  if (pickEndpoint(item)) { score += 6; reasons.push("reachable_endpoint_declared"); }
  if (item?.verified === true || String(item?.status || "").toLowerCase().includes("verified")) { score += 6; reasons.push("verified_counterparty"); }
  const queryTokens = clean(strategy?.query, 500).toLowerCase().split(/[^a-z0-9]+/).filter(x => x.length >= 4);
  const queryHits = queryTokens.filter(w => text.includes(w)).length;
  if (queryHits) { score += Math.min(10, queryHits * 2); reasons.push(`strategy_match:${queryHits}`); }
  const negative = ["weather","horoscope","dating","adult","casino","gambling","paper-only","synthetic purchase","demo only","sandbox only"];
  const negativeHits = negative.filter(w => text.includes(w)).length;
  if (negativeHits) { score -= negativeHits * 18; reasons.push(`negative_fit:${negativeHits}`); }
  score = Math.round(clamp(score, 0, 100));
  return { score, fit: score >= 75 ? "A" : score >= 55 ? "B" : score >= 35 ? "C" : "D", reasons, demandSignal: demandHits > 0 ? 1 : 0, text };
}

async function fetchJson(url) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort("timeout"), FETCH_TIMEOUT_MS);
  try {
    const response = await fetch(url, { signal: controller.signal, headers: { "accept":"application/json", "user-agent":`LUMEN-MarketHunter/${VERSION}` } });
    if (!response.ok) throw new Error(`http_${response.status}`);
    return await response.json();
  } finally { clearTimeout(timer); }
}

async function upsertOpportunity(env, item, strategy, evidenceUrl) {
  const rid = remoteId(item);
  if (!rid || isSelf(item)) return { skipped: true };
  const scored = scoreOpportunity(item, strategy);
  if (scored.score < 30) return { skipped: true };
  const id = `OPP-${(await sha256(`global_a2a_registry|${rid}`)).slice(0, 20).toUpperCase()}`;
  const now = new Date().toISOString();
  const endpoint = pickEndpoint(item);
  const name = clean(item?.displayName || item?.display_name || item?.name || rid, 300);
  const description = clean(item?.description || item?.summary || item?.message || item?.text, 3000);
  const tags = stringifyTags(item?.tags || arr(item?.skills).flatMap(s => s?.tags || []));
  const existing = await safeFirst(env, "SELECT id,score,status FROM lumen_opportunities WHERE id=? LIMIT 1", [id]);
  const nextStatus = existing?.status && !["new","watching","qualified"].includes(existing.status) ? existing.status : scored.fit === "A" ? "qualified" : "watching";
  const raw = { ...item, lumen_market_hunter: { strategyId: strategy.id, query: strategy.query, offerId: strategy.offer_id, version: VERSION } };
  await env.DB.prepare("INSERT INTO lumen_opportunities(id,discovered_at,updated_at,source,remote_id,name,endpoint,description,tags_json,score,fit,demand_signal,revenue_offer_id,status,evidence,raw_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,name=excluded.name,endpoint=CASE WHEN excluded.endpoint<>'' THEN excluded.endpoint ELSE lumen_opportunities.endpoint END,description=CASE WHEN excluded.description<>'' THEN excluded.description ELSE lumen_opportunities.description END,tags_json=excluded.tags_json,score=MAX(lumen_opportunities.score,excluded.score),fit=CASE WHEN excluded.score>lumen_opportunities.score THEN excluded.fit ELSE lumen_opportunities.fit END,demand_signal=MAX(lumen_opportunities.demand_signal,excluded.demand_signal),revenue_offer_id=CASE WHEN excluded.score>=lumen_opportunities.score THEN excluded.revenue_offer_id ELSE lumen_opportunities.revenue_offer_id END,evidence=excluded.evidence,raw_json=excluded.raw_json")
    .bind(id,now,now,"global_a2a_registry",rid,name,endpoint,description,JSON.stringify(tags),scored.score,scored.fit,scored.demandSignal,strategy.offer_id,nextStatus,clean(evidenceUrl,1600),JSON.stringify(raw).slice(0,12000)).run();
  const priorAttr = await safeFirst(env, "SELECT strategy_id FROM lumen_market_hunter_attribution WHERE opportunity_id=? LIMIT 1", [id]);
  await env.DB.prepare("INSERT INTO lumen_market_hunter_attribution(opportunity_id,strategy_id,first_seen_at,last_seen_at,engine_version) VALUES(?,?,?,?,?) ON CONFLICT(opportunity_id) DO UPDATE SET last_seen_at=excluded.last_seen_at,engine_version=excluded.engine_version")
    .bind(id,strategy.id,now,now,VERSION).run();
  return { skipped:false, inserted:!existing, updated:Boolean(existing), newAttribution:!priorAttr, opportunityId:id, score:scored.score, fit:scored.fit };
}

function strategyScore(x) {
  const runs = Math.max(0, num(x.runs));
  const discoveries = Math.max(0, num(x.discoveries));
  const actionable = Math.max(0, num(x.actionable));
  const proposals = Math.max(0, num(x.proposals));
  const qualified = Math.max(0, num(x.qualified_responses));
  const settlements = Math.max(0, num(x.settlements));
  const revenue = Math.max(0, num(x.revenue_usd));
  let score = 42;
  if (discoveries > 0) score += Math.min(18, actionable / discoveries * 18);
  if (discoveries > 0) score += Math.min(8, proposals / discoveries * 8);
  if (proposals > 0) score += Math.min(18, qualified / proposals * 18);
  if (settlements > 0) score += Math.min(22, settlements * 8) + Math.min(10, Math.log10(1 + revenue) * 4);
  if (runs >= 3 && actionable === 0) score -= Math.min(18, (runs - 2) * 3);
  score -= Math.min(12, Math.max(0, num(x.no_signal_runs)) * 2);
  score += Math.min(7, 7 / Math.sqrt(runs + 1));
  return Number(clamp(score, 0, 100).toFixed(2));
}

async function refreshLearning(env) {
  const strategies = await safeAll(env, "SELECT * FROM lumen_market_hunter_strategies WHERE active=1 ORDER BY id");
  const updated = [];
  for (const s of strategies) {
    const discoveries = await safeNumber(env, "SELECT COUNT(*) n FROM lumen_market_hunter_attribution WHERE strategy_id=?", [s.id]);
    const actionable = await safeNumber(env, "SELECT COUNT(*) n FROM lumen_market_hunter_attribution h JOIN lumen_opportunity_assessments a ON a.opportunity_id=h.opportunity_id WHERE h.strategy_id=? AND a.commercially_actionable=1 AND a.synthetic_or_test_only=0", [s.id]);
    const proposals = await safeNumber(env, "SELECT COUNT(*) n FROM lumen_market_hunter_attribution h JOIN lumen_proposal_drafts p ON p.opportunity_id=h.opportunity_id WHERE h.strategy_id=?", [s.id]);
    const qualified = await safeNumber(env, `SELECT COUNT(*) n FROM lumen_market_hunter_attribution h JOIN lumen_sales_pipeline s ON s.opportunity_id=h.opportunity_id WHERE h.strategy_id=? AND s.response_class IN ('${QUALIFIED_CLASSES.join("','")}')`, [s.id]);
    const settlements = await safeNumber(env, "SELECT COUNT(*) n FROM lumen_market_hunter_attribution h JOIN lumen_revenue_attributions r ON r.opportunity_id=h.opportunity_id WHERE h.strategy_id=?", [s.id]);
    const revenue = await safeNumber(env, "SELECT COALESCE(SUM(r.amount_usd),0) n FROM lumen_market_hunter_attribution h JOIN lumen_revenue_attributions r ON r.opportunity_id=h.opportunity_id WHERE h.strategy_id=?", [s.id]);
    const snapshot = { ...s, discoveries, actionable, proposals, qualified_responses:qualified, settlements, revenue_usd:revenue };
    const score = strategyScore(snapshot);
    const evidence = settlements > 0 ? "VERIFIED_REVENUE" : qualified > 0 ? "QUALIFIED_RESPONSE" : actionable > 0 ? "ACTIONABLE" : discoveries > 0 ? "DISCOVERY" : "COLD";
    const now = new Date().toISOString();
    await env.DB.prepare("UPDATE lumen_market_hunter_strategies SET updated_at=?,discoveries=?,actionable=?,proposals=?,qualified_responses=?,settlements=?,revenue_usd=?,score=?,evidence_level=?,engine_version=? WHERE id=?")
      .bind(now,discoveries,actionable,proposals,qualified,settlements,revenue,score,evidence,VERSION,s.id).run();
    updated.push({ id:s.id, query:s.query, offerId:s.offer_id, runs:num(s.runs), discoveries, actionable, proposals, qualifiedResponses:qualified, settlements, revenueUsd:revenue, score, evidenceLevel:evidence, noSignalRuns:num(s.no_signal_runs), generation:num(s.generation) });
  }
  return updated.sort((a,b)=>b.score-a.score || a.runs-b.runs || a.id.localeCompare(b.id));
}

function selectStrategies(rows) {
  const active = rows.filter(x => x && x.id);
  if (!active.length) return [];
  const evidenceExists = active.some(x => x.qualifiedResponses > 0 || x.settlements > 0);
  const exploitCount = evidenceExists ? 2 : 1;
  const selected = [];
  for (const row of [...active].sort((a,b)=>b.score-a.score || b.qualifiedResponses-a.qualifiedResponses || a.runs-b.runs)) {
    if (selected.length >= exploitCount) break;
    selected.push({ ...row, selectionMode:"EXPLOIT" });
  }
  const used = new Set(selected.map(x=>x.id));
  const explorers = active.filter(x=>!used.has(x.id)).sort((a,b)=>a.runs-b.runs || a.generation-b.generation || b.score-a.score || a.id.localeCompare(b.id));
  for (const row of explorers) {
    if (selected.length >= MAX_QUERIES_PER_RUN) break;
    selected.push({ ...row, selectionMode:"EXPLORE" });
  }
  return selected.slice(0, MAX_QUERIES_PER_RUN);
}

async function scanStrategy(env, strategy) {
  const url = `${REGISTRY_BASE}/public/agents?q=${encodeURIComponent(strategy.query)}`;
  let accepted = 0, inserted = 0, updated = 0, newAttributions = 0;
  try {
    const payload = await fetchJson(url);
    const items = registryItems(payload).slice(0, MAX_RESULTS_PER_QUERY);
    for (const item of items) {
      const r = await upsertOpportunity(env, item, { id:strategy.id, query:strategy.query, offer_id:strategy.offerId }, url);
      if (r?.skipped) continue;
      accepted += 1;
      if (r.inserted) inserted += 1;
      if (r.updated) updated += 1;
      if (r.newAttribution) newAttributions += 1;
    }
    const now = new Date().toISOString();
    await env.DB.prepare("UPDATE lumen_market_hunter_strategies SET runs=runs+1,updated_at=?,last_run_at=?,no_signal_runs=CASE WHEN ?>0 THEN 0 ELSE no_signal_runs+1 END,last_reason=?,engine_version=? WHERE id=?")
      .bind(now,now,accepted,`registry_ok accepted=${accepted} new_attributions=${newAttributions}`,VERSION,strategy.id).run();
    return { strategyId:strategy.id, query:strategy.query, offerId:strategy.offerId, mode:strategy.selectionMode, ok:true, accepted, inserted, updated, newAttributions };
  } catch (error) {
    const now = new Date().toISOString();
    await env.DB.prepare("UPDATE lumen_market_hunter_strategies SET runs=runs+1,updated_at=?,last_run_at=?,no_signal_runs=no_signal_runs+1,last_reason=?,engine_version=? WHERE id=?")
      .bind(now,now,`registry_error:${clean(error?.message || error,180)}`,VERSION,strategy.id).run();
    return { strategyId:strategy.id, query:strategy.query, offerId:strategy.offerId, mode:strategy.selectionMode, ok:false, accepted:0, inserted:0, updated:0, newAttributions:0, error:clean(error?.message || error,240) };
  }
}

function learnedTerms(rows, existingQuery) {
  const existing = new Set(clean(existingQuery,800).toLowerCase().split(/[^a-z0-9]+/).filter(Boolean));
  const counts = new Map();
  for (const row of rows) {
    const text = clean(`${row?.name || ""} ${row?.description || ""} ${row?.tags_json || ""}`, 12000).toLowerCase();
    for (const token of text.split(/[^a-z0-9-]+/)) {
      if (token.length < 5 || STOPWORDS.has(token) || existing.has(token) || /^\d+$/.test(token)) continue;
      counts.set(token, (counts.get(token) || 0) + 1);
    }
  }
  return [...counts.entries()].sort((a,b)=>b[1]-a[1] || a[0].localeCompare(b[0])).slice(0,2).map(x=>x[0]);
}

async function maybeGenerateChild(env, ranking) {
  const total = await safeNumber(env, "SELECT COUNT(*) n FROM lumen_market_hunter_strategies WHERE active=1");
  if (total >= MAX_ACTIVE_STRATEGIES) return null;
  const parents = ranking.filter(x => x.runs >= 2 && (x.actionable > 0 || x.qualifiedResponses > 0 || x.settlements > 0) && x.generation < 2);
  for (const parent of parents) {
    const childCount = await safeNumber(env, "SELECT COUNT(*) n FROM lumen_market_hunter_strategies WHERE parent_id=?", [parent.id]);
    if (childCount >= 2) continue;
    const samples = await safeAll(env, "SELECT o.name,o.description,o.tags_json FROM lumen_market_hunter_attribution h JOIN lumen_opportunities o ON o.id=h.opportunity_id WHERE h.strategy_id=? ORDER BY o.score DESC,o.updated_at DESC LIMIT 20", [parent.id]);
    const terms = learnedTerms(samples, parent.query);
    const modifier = INTENT_VARIANTS[(parent.runs + childCount) % INTENT_VARIANTS.length];
    const core = OFFER_CORE[parent.offerId] || "b2b demand procurement";
    const words = `${modifier} ${terms.join(" ")} ${core}`.toLowerCase().split(/[^a-z0-9-]+/).filter(Boolean);
    const unique = [];
    for (const w of words) if (!unique.includes(w)) unique.push(w);
    const query = unique.slice(0,8).join(" ");
    if (!query || query === parent.query) continue;
    const exists = await safeFirst(env, "SELECT id FROM lumen_market_hunter_strategies WHERE query=? LIMIT 1", [query]);
    if (exists) continue;
    const id = `MH-${(await sha256(query)).slice(0,12).toUpperCase()}`;
    const now = new Date().toISOString();
    await env.DB.prepare("INSERT INTO lumen_market_hunter_strategies(id,query,offer_id,parent_id,generation,active,created_at,updated_at,score,evidence_level,last_reason,engine_version) VALUES(?,?,?,?,?,1,?,?,50,'COLD',?,?)")
      .bind(id,query,parent.offerId,parent.id,parent.generation+1,now,now,`generated_from_${parent.id}_using_observed_terms`,VERSION).run();
    return { id, query, offerId:parent.offerId, parentId:parent.id, generation:parent.generation+1, learnedTerms:terms };
  }
  return null;
}

async function stateData(env) {
  await ensureSchema(env);
  const ranking = await refreshLearning(env);
  const lastRun = await safeFirst(env, "SELECT id,started_at,finished_at,status,selected_json,results_json,generated_strategy_id FROM lumen_market_hunter_runs ORDER BY started_at DESC LIMIT 1");
  const totals = {
    activeStrategies: ranking.length,
    strategiesWithActionable: ranking.filter(x=>x.actionable>0).length,
    strategiesWithQualifiedResponses: ranking.filter(x=>x.qualifiedResponses>0).length,
    strategiesWithVerifiedRevenue: ranking.filter(x=>x.settlements>0).length,
    attributedOpportunities: ranking.reduce((n,x)=>n+x.discoveries,0),
    qualifiedResponses: ranking.reduce((n,x)=>n+x.qualifiedResponses,0),
    verifiedSettlements: ranking.reduce((n,x)=>n+x.settlements,0),
    verifiedRevenueUsd: Number(ranking.reduce((n,x)=>n+x.revenueUsd,0).toFixed(2))
  };
  const parse = (v,f)=>{try{return JSON.parse(v||"");}catch{return f;}};
  return { version:VERSION, totals, ranking:ranking.slice(0,12), lastRun:lastRun ? { id:lastRun.id, startedAt:lastRun.started_at, finishedAt:lastRun.finished_at, status:lastRun.status, selected:parse(lastRun.selected_json,[]), results:parse(lastRun.results_json,[]), generatedStrategyId:lastRun.generated_strategy_id || null } : null };
}

export async function runAdaptiveMarketHunter(env) {
  if (!(await ensureSchema(env))) return { ok:false, error:"persistence_unavailable", version:VERSION };
  const startedAt = new Date().toISOString();
  const runId = `MHRUN-${crypto.randomUUID().replaceAll("-","").slice(0,14).toUpperCase()}`;
  const before = await refreshLearning(env);
  const selected = selectStrategies(before);
  await env.DB.prepare("INSERT INTO lumen_market_hunter_runs(id,started_at,status,selected_json,engine_version) VALUES(?,?,?,?,?)")
    .bind(runId,startedAt,"running",JSON.stringify(selected.map(x=>({id:x.id,query:x.query,offerId:x.offerId,mode:x.selectionMode,score:x.score}))),VERSION).run();
  const results = [];
  for (const strategy of selected) results.push(await scanStrategy(env,strategy));
  const after = await refreshLearning(env);
  const generated = await maybeGenerateChild(env, after);
  const finishedAt = new Date().toISOString();
  const okCount = results.filter(x=>x.ok).length;
  const status = okCount === results.length ? "complete" : okCount > 0 ? "partial" : "failed";
  await env.DB.prepare("UPDATE lumen_market_hunter_runs SET finished_at=?,status=?,results_json=?,generated_strategy_id=? WHERE id=?")
    .bind(finishedAt,status,JSON.stringify(results).slice(0,12000),generated?.id || null,runId).run();
  return {
    ok: okCount > 0,
    version:VERSION,
    runId,
    status,
    selectedStrategies:selected.map(x=>({id:x.id,query:x.query,offerId:x.offerId,mode:x.selectionMode,score:x.score,evidenceLevel:x.evidenceLevel})),
    results,
    generatedStrategy:generated,
    topLearning:after.slice(0,8),
    guardrails:{
      publicReadOnlyDiscovery:true,
      adaptiveStrategyLearning:true,
      adaptiveQueryGeneration:true,
      selfModifyingCode:false,
      maxQueriesPerRun:MAX_QUERIES_PER_RUN,
      maxResultsPerQuery:MAX_RESULTS_PER_QUERY,
      createsExternalMessages:false,
      autonomousSpend:false,
      autonomousPurchase:false,
      autonomousContract:false,
      verifiedRevenueOnly:true,
      bindingActionsHumanGated:true
    }
  };
}

export async function handleAdaptiveMarketHunter(request, env) {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/market-hunter/policy") return json({
    version:VERSION,
    name:"LUMEN Adaptive Market Hunter",
    objective:"learn_which_public_search_strategies_produce_actionable_opportunities_qualified_demand_and_verified_revenue",
    learningSignals:["commercially_actionable","proposal_created","qualified_commercial_response","verified_settlement","verified_revenue_usd"],
    selectionPolicy:"bounded_explore_exploit; before qualified evidence favor exploration, after evidence exploit two lanes and explore one",
    queryEvolution:"bounded_child_queries_generated_from_observed_terms_of_productive_strategies",
    selfModifyingCode:false,
    maxQueriesPerRun:MAX_QUERIES_PER_RUN,
    maxActiveStrategies:MAX_ACTIVE_STRATEGIES,
    createsExternalMessages:false,
    autonomousSpend:false,
    autonomousPurchase:false,
    autonomousContract:false,
    verifiedRevenueOnly:true,
    bindingActionsHumanGated:true
  });
  if (request.method === "GET" && url.pathname === "/market-hunter/state") return json(await stateData(env));
  if (request.method === "POST" && url.pathname === "/market-hunter/run") {
    if (!authorized(request, env)) return json({ ok:false, error:"admin_token_required" },403);
    return json(await runAdaptiveMarketHunter(env),202);
  }
  return null;
}
