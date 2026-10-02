const NOW = () => new Date().toISOString();

const ARCHETYPES = [
  { id: "monitoring", rx: /monitor|alert|watch|track|price|status|availability/i, product: "paid monitoring + alert service", build: "API/worker + subscription or x402 checkout", margin: 0.88 },
  { id: "research", rx: /research|supplier|vendor|source|market|compare|quote|rfq|procure/i, product: "on-demand research/intelligence report", build: "research pipeline + report delivery + x402 checkout", margin: 0.9 },
  { id: "document", rx: /document|pdf|invoice|contract|form|extract|convert|summar/i, product: "document transformation microservice", build: "upload/API + transformation + paid delivery", margin: 0.93 },
  { id: "lead", rx: /lead|buyer|prospect|contact|sales|outreach|demand/i, product: "buyer-intent / qualified-lead intelligence", build: "signal collector + qualification + paid feed", margin: 0.86 },
  { id: "travel", rx: /travel|hotel|flight|tour|booking|trip/i, product: "B2B travel intelligence/broker service", build: "search + quote + human-gated booking handoff", margin: 0.72 },
  { id: "commerce", rx: /shop|store|product|catalog|stock|inventory|ecommerce|commerce/i, product: "commerce intelligence / merchandising service", build: "catalog watcher + recommendation + paid report/API", margin: 0.78 },
];

function textOf(row = {}) {
  return Object.values(row).filter((v) => typeof v === "string").join(" ").slice(0, 5000);
}

function num(v, fallback = 0) {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function archetypeFor(text) {
  return ARCHETYPES.find((x) => x.rx.test(text)) || {
    id: "custom",
    product: "narrow paid information/service product",
    build: "single-purpose landing/API + x402 checkout + measurable delivery",
    margin: 0.85,
  };
}

function scoreSignal(row, text, archetype) {
  const demand = Math.min(1, 0.35 + (text.length > 120 ? 0.15 : 0) + (/need|want|looking|request|buy|urgent|quote/i.test(text) ? 0.25 : 0) + Math.min(0.25, num(row.score || row.priority_score || row.intent_score) / 400));
  const urgency = /urgent|asap|today|now|deadline|immediate/i.test(text) ? 0.9 : 0.55;
  const evidence = Math.min(1, 0.4 + (row.url || row.source_url ? 0.2 : 0) + (row.buyer || row.company || row.domain ? 0.15 : 0) + (text.length > 250 ? 0.15 : 0));
  const buildEase = archetype.id === "custom" ? 0.55 : 0.82;
  const score = demand * 0.32 + urgency * 0.12 + evidence * 0.2 + buildEase * 0.16 + archetype.margin * 0.2;
  return { demand, urgency, evidence, buildEase, margin: archetype.margin, score: Number(score.toFixed(4)) };
}

async function ensureSchema(db) {
  if (!db?.prepare) return;
  await db.prepare(`CREATE TABLE IF NOT EXISTS lumen_venture_hunter_ideas (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    source_ref TEXT,
    title TEXT NOT NULL,
    product TEXT NOT NULL,
    build_plan TEXT NOT NULL,
    score REAL NOT NULL,
    status TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    policy_json TEXT NOT NULL
  )`).run();
}

async function readSignals(db, limit = 80) {
  if (!db?.prepare) return [];
  const queries = [
    ["source-intelligence", "SELECT * FROM lumen_source_observations ORDER BY rowid DESC LIMIT ?"],
    ["opportunity", "SELECT * FROM lumen_opportunities ORDER BY rowid DESC LIMIT ?"],
    ["market-hunter", "SELECT * FROM lumen_market_candidates ORDER BY rowid DESC LIMIT ?"],
    ["proposal", "SELECT * FROM lumen_proposals ORDER BY rowid DESC LIMIT ?"],
  ];
  const out = [];
  for (const [kind, sql] of queries) {
    try {
      const res = await db.prepare(sql).bind(limit).all();
      for (const row of res?.results || []) out.push({ kind, row });
    } catch (_) {}
  }
  return out.slice(0, limit);
}

function makeIdea(signal, index) {
  const text = textOf(signal.row);
  if (!text.trim()) return null;
  const archetype = archetypeFor(text);
  const metrics = scoreSignal(signal.row, text, archetype);
  const sourceRef = String(signal.row.id || signal.row.url || signal.row.source_url || `${signal.kind}-${index}`);
  const slug = `${archetype.id}-${sourceRef}`.replace(/[^a-zA-Z0-9_-]/g, "-").slice(0, 90);
  return {
    id: `vh1-${slug}`,
    createdAt: NOW(),
    sourceKind: signal.kind,
    sourceRef,
    title: `Opportunity: ${archetype.product}`,
    product: archetype.product,
    buildPlan: archetype.build,
    metrics,
    status: metrics.score >= 0.72 ? "BUILD_CANDIDATE" : metrics.score >= 0.6 ? "VALIDATE" : "WATCH",
    evidence: { excerpt: text.slice(0, 700), source: signal.kind },
  };
}

async function persist(db, ideas, policy) {
  if (!db?.prepare) return;
  for (const idea of ideas) {
    await db.prepare(`INSERT OR REPLACE INTO lumen_venture_hunter_ideas
      (id, created_at, source_kind, source_ref, title, product, build_plan, score, status, evidence_json, policy_json)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`)
      .bind(idea.id, idea.createdAt, idea.sourceKind, idea.sourceRef, idea.title, idea.product, idea.buildPlan, idea.metrics.score, idea.status, JSON.stringify(idea.evidence), JSON.stringify(policy)).run();
  }
}

export async function runVentureHunterV1(env, options = {}) {
  const policy = {
    mode: options.mode || "prepare_only",
    autonomousResearch: true,
    autonomousIdeaGeneration: true,
    autonomousBuildPreparation: true,
    autonomousExternalLaunch: false,
    autonomousSpending: false,
    autonomousContracting: false,
    bindingActionsHumanGated: true,
  };
  const db = env?.DB || env?.LUMEN_DB || null;
  await ensureSchema(db);
  const signals = Array.isArray(options.signals) ? options.signals.map((row) => ({ kind: "injected", row })) : await readSignals(db, options.limit || 80);
  const ideas = signals.map(makeIdea).filter(Boolean).sort((a, b) => b.metrics.score - a.metrics.score).slice(0, options.topK || 12);
  await persist(db, ideas, policy);
  return {
    ok: true,
    engine: "LUMEN Venture Hunter v1",
    generatedAt: NOW(),
    signalsExamined: signals.length,
    ideasGenerated: ideas.length,
    buildCandidates: ideas.filter((x) => x.status === "BUILD_CANDIDATE").length,
    topOpportunity: ideas[0] || null,
    ideas,
    policy,
    next: ideas[0]?.status === "BUILD_CANDIDATE" ? "prepare_mvp_and_validation_plan" : "keep_hunting",
  };
}
