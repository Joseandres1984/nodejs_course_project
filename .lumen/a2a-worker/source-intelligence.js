const VERSION = "1.0-source-intelligence";
const FETCH_TIMEOUT_MS = 8000;
const MAX_SOURCE_SCANS_PER_CYCLE = 2;
const MAX_RESULTS_PER_SOURCE = 20;

const SOURCE_SEEDS = Object.freeze([
  {
    id: "global_a2a_registry",
    name: "A2A Global Registry",
    kind: "EXISTING_PIPELINE",
    scanMode: "OBSERVE_ONLY",
    basePriority: 70,
    protected: true
  },
  {
    id: "ted_eu_public_procurement",
    name: "TED EU Public Procurement",
    kind: "PUBLIC_PROCUREMENT",
    scanMode: "ACTIVE",
    basePriority: 62,
    protected: true
  },
  {
    id: "uk_contracts_finder",
    name: "UK Contracts Finder",
    kind: "PUBLIC_PROCUREMENT",
    scanMode: "ACTIVE",
    basePriority: 60,
    protected: true
  }
]);

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

function clean(value, limit = 5000) {
  return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit);
}

function authorized(request, env) {
  const configured = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const provided = clean(request.headers.get("x-lumen-admin"), 500);
  return Boolean(configured && provided && configured === provided);
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, Number(value || 0)));
}

function firstText(value) {
  if (typeof value === "string") return clean(value, 800);
  if (Array.isArray(value)) return firstText(value[0]);
  if (value && typeof value === "object") {
    const preferred = ["eng", "en", "spa", "es", "fra", "deu"];
    for (const key of preferred) {
      if (key in value) {
        const hit = firstText(value[key]);
        if (hit) return hit;
      }
    }
    for (const candidate of Object.values(value)) {
      const hit = firstText(candidate);
      if (hit) return hit;
    }
  }
  return "";
}

function isoDaysAgo(days) {
  const date = new Date(Date.now() - days * 86400000);
  return date.toISOString();
}

function compactDate(iso) {
  return String(iso).slice(0, 10).replaceAll("-", "");
}

async function sha256(text) {
  const data = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(String(text)));
  return [...new Uint8Array(data)].map(byte => byte.toString(16).padStart(2, "0")).join("");
}

async function fetchJson(url, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
      headers: {
        accept: "application/json",
        ...(options.headers || {})
      }
    });
    if (!response.ok) throw new Error(`http_${response.status}`);
    return await response.json();
  } finally {
    clearTimeout(timeout);
  }
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_market_sources (source_id TEXT PRIMARY KEY,name TEXT NOT NULL,kind TEXT NOT NULL,scan_mode TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1,protected INTEGER NOT NULL DEFAULT 1,base_priority INTEGER NOT NULL DEFAULT 50,runs INTEGER NOT NULL DEFAULT 0,successful_runs INTEGER NOT NULL DEFAULT 0,failed_runs INTEGER NOT NULL DEFAULT 0,discoveries INTEGER NOT NULL DEFAULT 0,actionable INTEGER NOT NULL DEFAULT 0,proposals INTEGER NOT NULL DEFAULT 0,verified_settlements INTEGER NOT NULL DEFAULT 0,verified_revenue_usd REAL NOT NULL DEFAULT 0,economic_score REAL NOT NULL DEFAULT 0,no_signal_runs INTEGER NOT NULL DEFAULT 0,last_run_at TEXT,last_success_at TEXT,last_error TEXT,updated_at TEXT NOT NULL,metadata_json TEXT)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_market_sources_rank ON lumen_market_sources(enabled,economic_score DESC,base_priority DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_source_intelligence_runs (id TEXT PRIMARY KEY,source_id TEXT NOT NULL,started_at TEXT NOT NULL,finished_at TEXT,status TEXT NOT NULL,discovered INTEGER NOT NULL DEFAULT 0,inserted INTEGER NOT NULL DEFAULT 0,updated INTEGER NOT NULL DEFAULT 0,error TEXT,metadata_json TEXT)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_source_runs_source ON lumen_source_intelligence_runs(source_id,started_at DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_source_signal_attribution (opportunity_id TEXT PRIMARY KEY,source_id TEXT NOT NULL,first_seen_at TEXT NOT NULL,last_seen_at TEXT NOT NULL,remote_id TEXT,evidence_url TEXT,metadata_json TEXT)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_source_signal_source ON lumen_source_signal_attribution(source_id,last_seen_at DESC)")
  ]);

  const now = new Date().toISOString();
  for (const source of SOURCE_SEEDS) {
    await env.DB.prepare("INSERT INTO lumen_market_sources(source_id,name,kind,scan_mode,enabled,protected,base_priority,updated_at,metadata_json) VALUES(?,?,?,?,1,?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET name=excluded.name,kind=excluded.kind,scan_mode=excluded.scan_mode,protected=excluded.protected,base_priority=excluded.base_priority,updated_at=excluded.updated_at")
      .bind(source.id, source.name, source.kind, source.scanMode, source.protected ? 1 : 0, source.basePriority, now, JSON.stringify({ seed: true, version: VERSION }))
      .run();
  }
  return true;
}

async function safeFirst(env, sql, bindings = []) {
  try {
    const stmt = env.DB.prepare(sql);
    return bindings.length ? await stmt.bind(...bindings).first() : await stmt.first();
  } catch {
    return null;
  }
}

async function safeAll(env, sql, bindings = []) {
  try {
    const stmt = env.DB.prepare(sql);
    const response = bindings.length ? await stmt.bind(...bindings).all() : await stmt.all();
    return response.results || [];
  } catch {
    return [];
  }
}

function valueAmount(value) {
  if (!value) return 0;
  if (typeof value === "number") return Math.max(0, value);
  if (Array.isArray(value)) return Math.max(0, ...value.map(valueAmount));
  if (typeof value === "object") {
    const candidate = value.amount ?? value.value ?? value.maxValue ?? value.minValue;
    if (candidate != null) return Math.max(0, Number(candidate) || 0);
  }
  return 0;
}

function futureDeadlineScore(deadline) {
  if (!deadline) return 0;
  const ms = Date.parse(deadline);
  if (!Number.isFinite(ms)) return 0;
  const days = (ms - Date.now()) / 86400000;
  if (days < 0) return -25;
  if (days <= 3) return 2;
  if (days <= 14) return 12;
  if (days <= 45) return 18;
  return 10;
}

function procurementScore({ deadline, value, title, description }) {
  const text = `${title || ""} ${description || ""}`.toLowerCase();
  let score = 54 + futureDeadlineScore(deadline);
  if (value >= 10000) score += 5;
  if (value >= 100000) score += 5;
  if (/(software|data|digital|consult|research|procurement|supplier|technology|engineering|maintenance|industrial|equipment)/i.test(text)) score += 8;
  return Math.round(clamp(score, 30, 92));
}

function opportunityId(sourceId, remoteId) {
  return `SRC-${sourceId.replace(/[^a-z0-9]+/gi, "-").toUpperCase().slice(0, 24)}-${String(remoteId).replace(/[^a-z0-9]+/gi, "").toUpperCase().slice(0, 30)}`;
}

function normalizeTedItem(item) {
  const remoteId = clean(item?.["publication-number"] ?? item?.publicationNumber ?? item?.id, 180);
  if (!remoteId) return null;
  const title = firstText(item?.["notice-title"] ?? item?.noticeTitle) || `TED notice ${remoteId}`;
  const buyer = firstText(item?.["buyer-name"] ?? item?.buyerName);
  const deadline = firstText(item?.deadline ?? item?.["deadline-receipt-tender"] ?? item?.["deadline-receipt-request"]);
  const contractNature = firstText(item?.["contract-nature"] ?? item?.contractNature);
  const value = valueAmount(item?.["total-value"] ?? item?.totalValue ?? item?.["estimated-value"]);
  const publicationDate = firstText(item?.["publication-date"] ?? item?.publicationDate);
  const description = clean([buyer ? `Buyer: ${buyer}.` : "", contractNature ? `Nature: ${contractNature}.` : "", deadline ? `Deadline: ${deadline}.` : "", value ? `Published value: ${value}.` : ""].filter(Boolean).join(" "), 1200);
  const url = `https://ted.europa.eu/en/notice/-/detail/${encodeURIComponent(remoteId)}`;
  return {
    remoteId,
    name: clean(title, 260),
    endpoint: url,
    description,
    score: procurementScore({ deadline, value, title, description }),
    fit: "PUBLIC_PROCUREMENT",
    demandSignal: "published_procurement_notice",
    revenueOfferId: "MP-TENDER-SCAN",
    evidence: url,
    raw: { publicationDate, deadline, value, buyer, contractNature }
  };
}

function normalizeUkRelease(release) {
  const remoteId = clean(release?.ocid ?? release?.id, 180);
  if (!remoteId) return null;
  const tender = release?.tender || {};
  const title = clean(tender?.title || release?.buyer?.name || release?.procuringEntity?.name || `UK procurement ${remoteId}`, 260);
  const buyer = clean(release?.buyer?.name || release?.procuringEntity?.name, 240);
  const descriptionText = firstText(tender?.description);
  const deadline = clean(tender?.tenderPeriod?.endDate || tender?.contractPeriod?.startDate, 100);
  const value = valueAmount(tender?.value);
  const documents = Array.isArray(tender?.documents) ? tender.documents : [];
  const docUrl = documents.map(d => clean(d?.url, 1000)).find(Boolean);
  const url = clean(docUrl || release?.uri || `https://www.contractsfinder.service.gov.uk/Search/Results?Keywords=${encodeURIComponent(title)}`, 1200);
  const description = clean([buyer ? `Buyer: ${buyer}.` : "", descriptionText, deadline ? `Deadline: ${deadline}.` : "", value ? `Published value: ${value}.` : ""].filter(Boolean).join(" "), 1600);
  return {
    remoteId,
    name: title,
    endpoint: url,
    description,
    score: procurementScore({ deadline, value, title, description }),
    fit: "PUBLIC_PROCUREMENT",
    demandSignal: "published_procurement_notice",
    revenueOfferId: "MP-TENDER-SCAN",
    evidence: url,
    raw: { deadline, value, buyer, tenderStatus: clean(tender?.status, 100) || null }
  };
}

async function scanTed() {
  const from = compactDate(isoDaysAgo(3));
  const to = compactDate(new Date().toISOString());
  const data = await fetchJson("https://api.ted.europa.eu/v3/notices/search", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      query: `PD = (${from} <> ${to}) SORT BY publication-date DESC`,
      fields: ["publication-number", "notice-title", "buyer-name", "publication-date", "deadline", "contract-nature", "total-value", "buyer-country"],
      page: 1,
      limit: MAX_RESULTS_PER_SOURCE,
      scope: "ACTIVE",
      checkQuerySyntax: false,
      paginationMode: "PAGE_NUMBER"
    })
  });
  const rows = Array.isArray(data?.notices) ? data.notices : Array.isArray(data?.results) ? data.results : Array.isArray(data?.items) ? data.items : [];
  return rows.map(normalizeTedItem).filter(Boolean).slice(0, MAX_RESULTS_PER_SOURCE);
}

async function scanUkContractsFinder() {
  const params = new URLSearchParams({
    publishedFrom: isoDaysAgo(3),
    publishedTo: new Date().toISOString(),
    stages: "tender",
    limit: String(MAX_RESULTS_PER_SOURCE)
  });
  const data = await fetchJson(`https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search?${params.toString()}`);
  const rows = Array.isArray(data?.releases) ? data.releases : [];
  return rows.map(normalizeUkRelease).filter(Boolean).slice(0, MAX_RESULTS_PER_SOURCE);
}

async function scanSource(sourceId) {
  if (sourceId === "ted_eu_public_procurement") return scanTed();
  if (sourceId === "uk_contracts_finder") return scanUkContractsFinder();
  return [];
}

async function upsertOpportunity(env, sourceId, signal) {
  const id = opportunityId(sourceId, signal.remoteId);
  const existing = await safeFirst(env, "SELECT id FROM lumen_opportunities WHERE source=? AND remote_id=? LIMIT 1", [sourceId, signal.remoteId]);
  const now = new Date().toISOString();
  const targetId = existing?.id || id;
  const tags = ["multisource", "public-demand", signal.fit].filter(Boolean);
  await env.DB.prepare("INSERT INTO lumen_opportunities(id,discovered_at,updated_at,source,remote_id,name,endpoint,description,tags_json,score,fit,demand_signal,revenue_offer_id,status,evidence,raw_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source,remote_id) DO UPDATE SET updated_at=excluded.updated_at,name=excluded.name,endpoint=excluded.endpoint,description=excluded.description,tags_json=excluded.tags_json,score=MAX(lumen_opportunities.score,excluded.score),fit=excluded.fit,demand_signal=excluded.demand_signal,revenue_offer_id=excluded.revenue_offer_id,evidence=excluded.evidence,raw_json=excluded.raw_json")
    .bind(targetId, now, now, sourceId, signal.remoteId, signal.name, signal.endpoint || null, signal.description || "", JSON.stringify(tags), signal.score, signal.fit, signal.demandSignal, signal.revenueOfferId, existing ? "DISCOVERED" : "SOURCE_SIGNAL", signal.evidence || null, JSON.stringify({ ...signal.raw, source_intelligence_version: VERSION }))
    .run();
  await env.DB.prepare("INSERT INTO lumen_source_signal_attribution(opportunity_id,source_id,first_seen_at,last_seen_at,remote_id,evidence_url,metadata_json) VALUES(?,?,?,?,?,?,?) ON CONFLICT(opportunity_id) DO UPDATE SET last_seen_at=excluded.last_seen_at,evidence_url=excluded.evidence_url,metadata_json=excluded.metadata_json")
    .bind(targetId, sourceId, now, now, signal.remoteId, signal.evidence || null, JSON.stringify({ score: signal.score, demandSignal: signal.demandSignal, version: VERSION }))
    .run();
  return { inserted: !existing, id: targetId };
}

async function recomputeSourceMetrics(env, sourceId) {
  const opp = await safeFirst(env, "SELECT COUNT(*) discoveries FROM lumen_opportunities WHERE source=?", [sourceId]);
  const actionable = await safeFirst(env, "SELECT COUNT(*) actionable FROM lumen_opportunities o JOIN lumen_opportunity_assessments a ON a.opportunity_id=o.id WHERE o.source=? AND a.commercially_actionable=1 AND a.synthetic_or_test_only=0", [sourceId]);
  const proposals = await safeFirst(env, "SELECT COUNT(*) proposals FROM lumen_opportunities o JOIN lumen_proposal_drafts p ON p.opportunity_id=o.id WHERE o.source=?", [sourceId]);
  const revenue = await safeFirst(env, "SELECT COUNT(*) settlements,COALESCE(SUM(r.amount_usd),0) revenue FROM lumen_opportunities o JOIN lumen_revenue_attributions r ON r.opportunity_id=o.id WHERE o.source=?", [sourceId]);

  const discoveries = Number(opp?.discoveries || 0);
  const actionableCount = Number(actionable?.actionable || 0);
  const proposalCount = Number(proposals?.proposals || 0);
  const settlements = Number(revenue?.settlements || 0);
  const revenueUsd = Math.max(0, Number(revenue?.revenue || 0));
  const row = await safeFirst(env, "SELECT runs,successful_runs,failed_runs,base_priority,no_signal_runs FROM lumen_market_sources WHERE source_id=?", [sourceId]);
  const runs = Math.max(0, Number(row?.runs || 0));
  const successfulRuns = Math.max(0, Number(row?.successful_runs || 0));
  const failedRuns = Math.max(0, Number(row?.failed_runs || 0));
  const conversion = discoveries ? actionableCount / discoveries : 0;
  const proposalYield = discoveries ? proposalCount / discoveries : 0;
  const reliability = runs ? successfulRuns / runs : 1;
  const score = clamp(
    Number(row?.base_priority || 50) * 0.15 +
    Math.min(18, discoveries * 0.5) +
    Math.min(18, conversion * 36) +
    Math.min(12, proposalYield * 30) +
    Math.min(22, settlements * 11) +
    Math.min(30, revenueUsd * 2.5) +
    reliability * 8 -
    Math.min(12, failedRuns * 2),
    0,
    100
  );
  await env.DB.prepare("UPDATE lumen_market_sources SET discoveries=?,actionable=?,proposals=?,verified_settlements=?,verified_revenue_usd=?,economic_score=?,updated_at=? WHERE source_id=?")
    .bind(discoveries, actionableCount, proposalCount, settlements, revenueUsd, Number(score.toFixed(2)), new Date().toISOString(), sourceId)
    .run();
  return { discoveries, actionable: actionableCount, proposals: proposalCount, verifiedSettlements: settlements, verifiedRevenueUsd: revenueUsd, economicScore: Number(score.toFixed(2)) };
}

function selectionScore(source) {
  const economic = Number(source.economic_score || 0);
  const base = Number(source.base_priority || 50);
  const runs = Number(source.runs || 0);
  const noSignal = Number(source.no_signal_runs || 0);
  const exploration = Math.max(0, 24 - Math.min(24, runs * 3));
  const staleness = source.last_run_at ? Math.min(12, Math.max(0, (Date.now() - Date.parse(source.last_run_at)) / 86400000 * 2)) : 12;
  return economic * 0.58 + base * 0.22 + exploration + staleness - Math.min(15, noSignal * 2);
}

async function pickSources(env) {
  const rows = await safeAll(env, "SELECT * FROM lumen_market_sources WHERE enabled=1 AND scan_mode='ACTIVE'");
  return rows
    .map(row => ({ ...row, selectionScore: Number(selectionScore(row).toFixed(2)) }))
    .sort((a, b) => b.selectionScore - a.selectionScore)
    .slice(0, MAX_SOURCE_SCANS_PER_CYCLE);
}

async function runOneSource(env, source) {
  const startedAt = new Date().toISOString();
  const runId = `SRC-RUN-${(await sha256(`${source.source_id}:${startedAt}`)).slice(0, 20).toUpperCase()}`;
  await env.DB.prepare("INSERT INTO lumen_source_intelligence_runs(id,source_id,started_at,status,metadata_json) VALUES(?,?,?,?,?)")
    .bind(runId, source.source_id, startedAt, "RUNNING", JSON.stringify({ selectionScore: source.selectionScore, version: VERSION }))
    .run();

  try {
    const signals = await scanSource(source.source_id);
    let inserted = 0;
    let updated = 0;
    for (const signal of signals) {
      const result = await upsertOpportunity(env, source.source_id, signal);
      if (result.inserted) inserted += 1;
      else updated += 1;
    }
    const finishedAt = new Date().toISOString();
    const meaningfulSignal = inserted > 0;
    await env.DB.prepare("UPDATE lumen_source_intelligence_runs SET finished_at=?,status='SUCCESS',discovered=?,inserted=?,updated=?,error=NULL WHERE id=?")
      .bind(finishedAt, signals.length, inserted, updated, runId).run();
    await env.DB.prepare("UPDATE lumen_market_sources SET runs=runs+1,successful_runs=successful_runs+1,no_signal_runs=?,last_run_at=?,last_success_at=?,last_error=NULL,updated_at=? WHERE source_id=?")
      .bind(meaningfulSignal ? 0 : Number(source.no_signal_runs || 0) + 1, finishedAt, finishedAt, finishedAt, source.source_id).run();
    const metrics = await recomputeSourceMetrics(env, source.source_id);
    return { sourceId: source.source_id, status: "SUCCESS", discovered: signals.length, inserted, updated, metrics };
  } catch (error) {
    const finishedAt = new Date().toISOString();
    const message = clean(error?.message || error, 500);
    await env.DB.prepare("UPDATE lumen_source_intelligence_runs SET finished_at=?,status='FAILED',error=? WHERE id=?")
      .bind(finishedAt, message, runId).run();
    await env.DB.prepare("UPDATE lumen_market_sources SET runs=runs+1,failed_runs=failed_runs+1,no_signal_runs=no_signal_runs+1,last_run_at=?,last_error=?,updated_at=? WHERE source_id=?")
      .bind(finishedAt, message, finishedAt, source.source_id).run();
    await recomputeSourceMetrics(env, source.source_id);
    return { sourceId: source.source_id, status: "FAILED", error: message };
  }
}

async function refreshAllMetrics(env) {
  const rows = await safeAll(env, "SELECT source_id FROM lumen_market_sources");
  const out = [];
  for (const row of rows) out.push({ sourceId: row.source_id, ...(await recomputeSourceMetrics(env, row.source_id)) });
  return out;
}

export async function runSourceIntelligence(env) {
  if (!(await ensureSchema(env))) return { ok: false, error: "persistence_unavailable", version: VERSION };
  await refreshAllMetrics(env);
  const selected = await pickSources(env);
  const results = [];
  for (const source of selected) results.push(await runOneSource(env, source));
  const state = await sourceState(env);
  return {
    ok: true,
    version: VERSION,
    selectedSources: selected.map(s => ({ sourceId: s.source_id, selectionScore: s.selectionScore })),
    results,
    state,
    guardrails: {
      autonomousSpendUsd: 0,
      purchases: false,
      contracts: false,
      externalMessagesAdded: false,
      sourceCreditRequiresDirectOpportunityLink: true,
      revenueCreditRequiresVerifiedSettlementAttribution: true,
      maxExternalSourcesPerCycle: MAX_SOURCE_SCANS_PER_CYCLE,
      maxResultsPerSource: MAX_RESULTS_PER_SOURCE
    }
  };
}

async function sourceState(env) {
  await ensureSchema(env);
  const rows = await safeAll(env, "SELECT source_id,name,kind,scan_mode,enabled,protected,base_priority,runs,successful_runs,failed_runs,discoveries,actionable,proposals,verified_settlements,verified_revenue_usd,economic_score,no_signal_runs,last_run_at,last_success_at,last_error FROM lumen_market_sources ORDER BY economic_score DESC,base_priority DESC");
  const totals = rows.reduce((acc, row) => {
    acc.sources += 1;
    acc.discoveries += Number(row.discoveries || 0);
    acc.actionable += Number(row.actionable || 0);
    acc.proposals += Number(row.proposals || 0);
    acc.verifiedSettlements += Number(row.verified_settlements || 0);
    acc.verifiedRevenueUsd += Number(row.verified_revenue_usd || 0);
    return acc;
  }, { sources: 0, discoveries: 0, actionable: 0, proposals: 0, verifiedSettlements: 0, verifiedRevenueUsd: 0 });
  totals.verifiedRevenueUsd = Number(totals.verifiedRevenueUsd.toFixed(2));
  return { sources: rows, totals };
}

export async function handleSourceIntelligence(request, env) {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/source-intelligence/status") {
    return json({ version: VERSION, ...(await sourceState(env)), autonomousSpendUsd: 0, externalMessagesAdded: false });
  }
  if (request.method === "POST" && url.pathname === "/source-intelligence/cycle") {
    if (!authorized(request, env)) return json({ ok: false, error: "admin_token_required" }, 403);
    return json(await runSourceIntelligence(env), 202);
  }
  if (request.method === "GET" && url.pathname === "/source-intelligence/signals") {
    if (!authorized(request, env)) return json({ ok: false, error: "admin_token_required" }, 403);
    await ensureSchema(env);
    const signals = await safeAll(env, "SELECT a.source_id,a.opportunity_id,a.remote_id,a.first_seen_at,a.last_seen_at,a.evidence_url,o.name,o.score,o.fit,o.demand_signal,o.revenue_offer_id,o.status FROM lumen_source_signal_attribution a JOIN lumen_opportunities o ON o.id=a.opportunity_id ORDER BY a.last_seen_at DESC LIMIT 200");
    return json({ version: VERSION, signals });
  }
  return null;
}

export const __test = {
  firstText,
  normalizeTedItem,
  normalizeUkRelease,
  procurementScore,
  selectionScore,
  compactDate
};