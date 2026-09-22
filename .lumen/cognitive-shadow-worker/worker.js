const SERVICE = "lumen-zero-cognitive-shadow";
const VERSION = "1.1-cognitive-learning-loop";
const MAX_REAL_LEADS_PER_RUN = 2;
const RECENT_LEAD_HOURS = 24;
const MAX_OUTCOME_RECONCILIATIONS_PER_RUN = 100;
const NEGATIVE_OUTCOME_AFTER_HOURS = 72;
const MIN_LEARNING_SAMPLE = 5;
const MIN_PRIORITY_SAMPLE = 8;

function clean(value, limit = 500) {
  return String(value ?? "").replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim().slice(0, limit);
}

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-robots-tag": "noindex, nofollow",
    },
  });
}

function clamp(n, min, max) {
  return Math.max(min, Math.min(max, Number.isFinite(Number(n)) ? Number(n) : min));
}

function ageHours(value) {
  const ts = Date.parse(String(value || ""));
  if (!Number.isFinite(ts)) return 0;
  return Math.max(0, (Date.now() - ts) / 3600000);
}

async function ensureSchema(env) {
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_cognitive_shadow_links (lead_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, decision_id TEXT NOT NULL, provider TEXT NOT NULL, model TEXT, current_product_slug TEXT, recommended_product_slug TEXT, decision TEXT NOT NULL, priority TEXT NOT NULL, confidence REAL NOT NULL, status TEXT NOT NULL DEFAULT 'shadow_only', technical_canary INTEGER NOT NULL DEFAULT 0, monetary_cost_usd REAL NOT NULL DEFAULT 0, actions_executed INTEGER NOT NULL DEFAULT 0, payload TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_cognitive_shadow_created ON lumen_cognitive_shadow_links(created_at)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_cognitive_shadow_real ON lumen_cognitive_shadow_links(technical_canary,created_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_cognitive_outcomes (lead_id TEXT PRIMARY KEY, decision_id TEXT NOT NULL, observed_at TEXT NOT NULL, outcome_stage TEXT NOT NULL, outcome_score REAL NOT NULL, checkout_started INTEGER NOT NULL DEFAULT 0, settled_verified INTEGER NOT NULL DEFAULT 0, settled_amount_usd REAL NOT NULL DEFAULT 0, finalized INTEGER NOT NULL DEFAULT 0, evidence TEXT NOT NULL, technical_canary INTEGER NOT NULL DEFAULT 0)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_cognitive_outcomes_stage ON lumen_cognitive_outcomes(outcome_stage,observed_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_cognitive_learning_profiles (profile_key TEXT PRIMARY KEY, updated_at TEXT NOT NULL, current_product_slug TEXT, decision TEXT NOT NULL, samples INTEGER NOT NULL DEFAULT 0, finalized_samples INTEGER NOT NULL DEFAULT 0, checkout_rate REAL NOT NULL DEFAULT 0, settlement_rate REAL NOT NULL DEFAULT 0, observed_success_rate REAL NOT NULL DEFAULT 0, average_confidence REAL NOT NULL DEFAULT 0, calibration_error REAL NOT NULL DEFAULT 0, confidence_multiplier REAL NOT NULL DEFAULT 1, priority_adjustment INTEGER NOT NULL DEFAULT 0, authority TEXT NOT NULL DEFAULT 'calibration_only')"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_cognitive_learning_product ON lumen_cognitive_learning_profiles(current_product_slug,decision)"),
  ]);
}

async function tableExists(env, name) {
  const row = await env.DB.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name=? LIMIT 1").bind(name).first();
  return Boolean(row?.name);
}

async function cognitiveHealth(env) {
  if (!env.COGNITIVE) return { connected: false, reason: "binding_missing" };
  try {
    const r = await env.COGNITIVE.fetch("https://cognitive/health", { headers: { "accept": "application/json" } });
    const data = await r.json();
    return {
      connected: r.ok && data?.status === "ok",
      status: data?.status || null,
      version: data?.version || null,
      model: data?.primary_model || null,
      paid_ai_allowed: data?.paid_ai_allowed,
      monetary_budget_usd: data?.monetary_budget_usd,
      outgoing_spend_enabled: data?.outgoing_spend_enabled,
      usage_today: data?.usage_today || null,
      learning: data?.learning || null,
    };
  } catch (e) {
    return { connected: false, reason: clean(e?.message, 120) };
  }
}

function assertSafeDecision(data) {
  if (!data || typeof data !== "object") throw new Error("cognitive_response_missing");
  if (data.paid_ai_used !== false) throw new Error("paid_ai_not_allowed");
  if (Number(data.monetary_cost_usd || 0) !== 0) throw new Error("nonzero_ai_cost_blocked");
  if (data.actions_executed !== false) throw new Error("cognitive_side_effect_blocked");
  if (data.outgoing_spend_enabled !== false) throw new Error("outgoing_spend_blocked");
  if (data.governor_required !== true) throw new Error("governor_bypass_blocked");
  if (!data.id || !data.decision || !data.priority || !data.provider) throw new Error("cognitive_response_incomplete");
}

async function analyze(env, lead, { technicalCanary = false } = {}) {
  const body = {
    task: "sales_triage",
    technical_canary: Boolean(technicalCanary),
    subject: {
      company: clean(lead.company, 180) || "No informado",
      current_product: clean(lead.product_slug, 80) || null,
      request: clean(lead.details, 1800),
      source: clean(lead.source, 80),
      medium: clean(lead.medium, 80),
      campaign: clean(lead.campaign, 120),
    },
    context: {
      lead_id: clean(lead.id, 100),
      instruction: "Evaluá si el requerimiento es comercialmente relevante, si el microproducto actual encaja y cuál sería el siguiente paso. Solo recomendar; no ejecutar nada.",
    },
  };

  const response = await env.COGNITIVE.fetch("https://cognitive/decide", {
    method: "POST",
    headers: { "content-type": "application/json", "accept": "application/json" },
    body: JSON.stringify(body),
  });
  const decision = await response.json();
  if (!response.ok) throw new Error(`cognitive_http_${response.status}:${clean(decision?.error, 80)}`);
  assertSafeDecision(decision);
  return decision;
}

async function storeLink(env, lead, decision, technicalCanary) {
  await ensureSchema(env);
  const payload = {
    reasons: Array.isArray(decision.reasons) ? decision.reasons.slice(0, 4) : [],
    next_action: clean(decision.next_action, 320),
    attempted_providers: Array.isArray(decision.attempted_providers) ? decision.attempted_providers.slice(0, 4) : [],
    learning_calibration: decision.learning_calibration || null,
    governor_required: true,
    shadow_only: true,
  };
  const result = await env.DB.prepare("INSERT OR IGNORE INTO lumen_cognitive_shadow_links(lead_id,created_at,decision_id,provider,model,current_product_slug,recommended_product_slug,decision,priority,confidence,status,technical_canary,monetary_cost_usd,actions_executed,payload) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
    .bind(
      clean(lead.id, 100),
      new Date().toISOString(),
      clean(decision.id, 100),
      clean(decision.provider, 80),
      clean(decision.model, 180) || null,
      clean(lead.product_slug, 80) || null,
      clean(decision.product, 80) || null,
      clean(decision.decision, 40),
      clean(decision.priority, 20),
      Number(decision.confidence || 0),
      "shadow_only",
      technicalCanary ? 1 : 0,
      0,
      0,
      JSON.stringify(payload),
    ).run();
  return Number(result?.meta?.changes || 0) === 1;
}

async function processRecentLeads(env) {
  await ensureSchema(env);
  const cutoff = new Date(Date.now() - RECENT_LEAD_HOURS * 60 * 60 * 1000).toISOString();
  const rows = await env.DB.prepare(`
    SELECT l.id,l.created_at,l.product_slug,l.company,l.details,l.source,l.medium,l.campaign
    FROM lumen_conversion_leads l
    LEFT JOIN lumen_cognitive_shadow_links s ON s.lead_id=l.id
    WHERE l.technical_canary=0
      AND l.created_at>=?
      AND LENGTH(TRIM(COALESCE(l.details,'')))>=8
      AND s.lead_id IS NULL
    ORDER BY l.created_at ASC
    LIMIT ?
  `).bind(cutoff, MAX_REAL_LEADS_PER_RUN).all();

  const processed = [];
  for (const lead of rows.results || []) {
    try {
      const decision = await analyze(env, lead, { technicalCanary: false });
      const stored = await storeLink(env, lead, decision, false);
      processed.push({ lead_id: lead.id, stored, decision_id: decision.id, provider: decision.provider, decision: decision.decision, recommended_product: decision.product, priority: decision.priority, confidence: decision.confidence, learning_calibration: decision.learning_calibration || null });
    } catch (e) {
      processed.push({ lead_id: lead.id, stored: false, error: clean(e?.message, 180) });
    }
  }
  return { candidates: (rows.results || []).length, processed };
}

async function findCheckout(env, lead) {
  let row = await env.DB.prepare("SELECT id,created_at FROM lumen_conversion_events WHERE technical_canary=0 AND event_type='checkout_started' AND json_extract(metadata,'$.brief_id')=? ORDER BY created_at DESC LIMIT 1")
    .bind(lead.lead_id).first();
  if (row) return { ...row, attribution: "brief_id" };
  if (!lead.session_id || !lead.product_slug) return null;
  row = await env.DB.prepare("SELECT id,created_at FROM lumen_conversion_events WHERE technical_canary=0 AND event_type='checkout_started' AND session_id=? AND product_slug=? AND created_at>=? ORDER BY created_at DESC LIMIT 1")
    .bind(lead.session_id, lead.product_slug, lead.lead_created_at).first();
  return row ? { ...row, attribution: "session_product" } : null;
}

async function findSettlement(env, lead) {
  let row = await env.DB.prepare("SELECT id,created_at,amount_usd,status FROM lumen_x402_receipts WHERE status IN ('settled_verified','redeemed_queued') AND json_extract(request_metadata,'$.conversion.brief_id')=? ORDER BY created_at DESC LIMIT 1")
    .bind(lead.lead_id).first();
  if (row) return { ...row, attribution: "brief_id" };
  if (!lead.session_id || !lead.product_id) return null;
  row = await env.DB.prepare("SELECT id,created_at,amount_usd,status FROM lumen_x402_receipts WHERE status IN ('settled_verified','redeemed_queued') AND product_id=? AND json_extract(request_metadata,'$.conversion.session_id')=? ORDER BY created_at DESC LIMIT 1")
    .bind(lead.product_id, lead.session_id).first();
  return row ? { ...row, attribution: "session_product" } : null;
}

async function upsertOutcome(env, outcome) {
  await env.DB.prepare(`
    INSERT INTO lumen_cognitive_outcomes(lead_id,decision_id,observed_at,outcome_stage,outcome_score,checkout_started,settled_verified,settled_amount_usd,finalized,evidence,technical_canary)
    VALUES(?,?,?,?,?,?,?,?,?,?,0)
    ON CONFLICT(lead_id) DO UPDATE SET
      decision_id=excluded.decision_id,
      observed_at=CASE WHEN excluded.outcome_score>=lumen_cognitive_outcomes.outcome_score THEN excluded.observed_at ELSE lumen_cognitive_outcomes.observed_at END,
      outcome_stage=CASE WHEN excluded.outcome_score>=lumen_cognitive_outcomes.outcome_score THEN excluded.outcome_stage ELSE lumen_cognitive_outcomes.outcome_stage END,
      outcome_score=MAX(lumen_cognitive_outcomes.outcome_score,excluded.outcome_score),
      checkout_started=MAX(lumen_cognitive_outcomes.checkout_started,excluded.checkout_started),
      settled_verified=MAX(lumen_cognitive_outcomes.settled_verified,excluded.settled_verified),
      settled_amount_usd=MAX(lumen_cognitive_outcomes.settled_amount_usd,excluded.settled_amount_usd),
      finalized=MAX(lumen_cognitive_outcomes.finalized,excluded.finalized),
      evidence=CASE WHEN excluded.outcome_score>=lumen_cognitive_outcomes.outcome_score THEN excluded.evidence ELSE lumen_cognitive_outcomes.evidence END
  `).bind(
    outcome.lead_id,
    outcome.decision_id,
    outcome.observed_at,
    outcome.outcome_stage,
    outcome.outcome_score,
    outcome.checkout_started ? 1 : 0,
    outcome.settled_verified ? 1 : 0,
    Number(outcome.settled_amount_usd || 0),
    outcome.finalized ? 1 : 0,
    JSON.stringify(outcome.evidence || {}),
  ).run();
}

async function reconcileOutcomes(env) {
  await ensureSchema(env);
  const hasEvents = await tableExists(env, "lumen_conversion_events");
  const hasReceipts = await tableExists(env, "lumen_x402_receipts");
  if (!hasEvents && !hasReceipts) return { checked: 0, updated: 0, skipped: "conversion_and_receipt_tables_missing" };

  const rows = await env.DB.prepare(`
    SELECT s.lead_id,s.decision_id,s.created_at AS decision_created_at,s.current_product_slug,s.decision,s.confidence,
           l.created_at AS lead_created_at,l.session_id,l.product_id,l.product_slug
    FROM lumen_cognitive_shadow_links s
    JOIN lumen_conversion_leads l ON l.id=s.lead_id
    WHERE s.technical_canary=0 AND l.technical_canary=0
    ORDER BY s.created_at ASC
    LIMIT ?
  `).bind(MAX_OUTCOME_RECONCILIATIONS_PER_RUN).all();

  let updated = 0;
  const stages = {};
  for (const lead of rows.results || []) {
    const settlement = hasReceipts ? await findSettlement(env, lead) : null;
    const checkout = hasEvents ? await findCheckout(env, lead) : null;
    let outcome = null;

    if (settlement) {
      outcome = {
        lead_id: lead.lead_id,
        decision_id: lead.decision_id,
        observed_at: settlement.created_at || new Date().toISOString(),
        outcome_stage: "settled_verified",
        outcome_score: 1,
        checkout_started: Boolean(checkout) || true,
        settled_verified: true,
        settled_amount_usd: Number(settlement.amount_usd || 0),
        finalized: true,
        evidence: { receipt_id: settlement.id, receipt_status: settlement.status, attribution: settlement.attribution, checkout_event_id: checkout?.id || null },
      };
    } else if (checkout) {
      outcome = {
        lead_id: lead.lead_id,
        decision_id: lead.decision_id,
        observed_at: checkout.created_at || new Date().toISOString(),
        outcome_stage: "checkout_started",
        outcome_score: 0.65,
        checkout_started: true,
        settled_verified: false,
        settled_amount_usd: 0,
        finalized: false,
        evidence: { checkout_event_id: checkout.id, attribution: checkout.attribution },
      };
    } else if (hasEvents && hasReceipts && ageHours(lead.lead_created_at || lead.decision_created_at) >= NEGATIVE_OUTCOME_AFTER_HOURS) {
      outcome = {
        lead_id: lead.lead_id,
        decision_id: lead.decision_id,
        observed_at: new Date().toISOString(),
        outcome_stage: "no_progress_72h",
        outcome_score: 0,
        checkout_started: false,
        settled_verified: false,
        settled_amount_usd: 0,
        finalized: true,
        evidence: { rule: "no_checkout_or_settlement_after_72h", source_tables_verified: true },
      };
    }

    if (outcome) {
      await upsertOutcome(env, outcome);
      updated += 1;
      stages[outcome.outcome_stage] = Number(stages[outcome.outcome_stage] || 0) + 1;
    }
  }
  return { checked: (rows.results || []).length, updated, stages, source_tables: { conversion_events: hasEvents, x402_receipts: hasReceipts } };
}

function calibrationMultiplier(samples, averageConfidence, observedSuccessRate) {
  if (samples < MIN_LEARNING_SAMPLE) return 1;
  const gap = averageConfidence - observedSuccessRate;
  if (gap > 0.20) return 0.78;
  if (gap > 0.10) return 0.90;
  if (gap < -0.18) return 1.05;
  return 1;
}

function priorityAdjustment(samples, observedSuccessRate) {
  if (samples < MIN_PRIORITY_SAMPLE) return 0;
  if (observedSuccessRate >= 0.72) return 1;
  if (observedSuccessRate <= 0.25) return -1;
  return 0;
}

async function rebuildLearningProfiles(env) {
  await ensureSchema(env);
  const rows = await env.DB.prepare(`
    SELECT o.outcome_score,o.checkout_started,o.settled_verified,o.finalized,
           s.current_product_slug,s.decision,s.confidence
    FROM lumen_cognitive_outcomes o
    JOIN lumen_cognitive_shadow_links s ON s.lead_id=o.lead_id
    WHERE o.technical_canary=0 AND s.technical_canary=0
  `).all();

  const groups = new Map();
  for (const row of rows.results || []) {
    const product = clean(row.current_product_slug, 80) || "unknown";
    const decision = clean(row.decision, 40) || "unknown";
    const key = `${product}|${decision}`;
    if (!groups.has(key)) groups.set(key, { key, product, decision, rows: [] });
    groups.get(key).rows.push(row);
  }

  const profiles = [];
  for (const group of groups.values()) {
    const n = group.rows.length;
    if (!n) continue;
    const finalizedSamples = group.rows.filter(x => Number(x.finalized || 0) === 1).length;
    const checkoutRate = group.rows.filter(x => Number(x.checkout_started || 0) === 1 || Number(x.settled_verified || 0) === 1).length / n;
    const settlementRate = group.rows.filter(x => Number(x.settled_verified || 0) === 1).length / n;
    const observedSuccess = group.rows.reduce((sum, x) => sum + clamp(x.outcome_score, 0, 1), 0) / n;
    const averageConfidence = group.rows.reduce((sum, x) => sum + clamp(x.confidence, 0, 1), 0) / n;
    const calibrationError = group.rows.reduce((sum, x) => {
      const delta = clamp(x.confidence, 0, 1) - clamp(x.outcome_score, 0, 1);
      return sum + delta * delta;
    }, 0) / n;
    const multiplier = calibrationMultiplier(n, averageConfidence, observedSuccess);
    const priority = priorityAdjustment(n, observedSuccess);
    const profile = {
      profile_key: group.key,
      updated_at: new Date().toISOString(),
      current_product_slug: group.product,
      decision: group.decision,
      samples: n,
      finalized_samples: finalizedSamples,
      checkout_rate: Number(checkoutRate.toFixed(4)),
      settlement_rate: Number(settlementRate.toFixed(4)),
      observed_success_rate: Number(observedSuccess.toFixed(4)),
      average_confidence: Number(averageConfidence.toFixed(4)),
      calibration_error: Number(calibrationError.toFixed(4)),
      confidence_multiplier: Number(multiplier.toFixed(4)),
      priority_adjustment: priority,
      authority: "calibration_only",
    };
    await env.DB.prepare(`
      INSERT INTO lumen_cognitive_learning_profiles(profile_key,updated_at,current_product_slug,decision,samples,finalized_samples,checkout_rate,settlement_rate,observed_success_rate,average_confidence,calibration_error,confidence_multiplier,priority_adjustment,authority)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
      ON CONFLICT(profile_key) DO UPDATE SET
        updated_at=excluded.updated_at,
        current_product_slug=excluded.current_product_slug,
        decision=excluded.decision,
        samples=excluded.samples,
        finalized_samples=excluded.finalized_samples,
        checkout_rate=excluded.checkout_rate,
        settlement_rate=excluded.settlement_rate,
        observed_success_rate=excluded.observed_success_rate,
        average_confidence=excluded.average_confidence,
        calibration_error=excluded.calibration_error,
        confidence_multiplier=excluded.confidence_multiplier,
        priority_adjustment=excluded.priority_adjustment,
        authority=excluded.authority
    `).bind(
      profile.profile_key, profile.updated_at, profile.current_product_slug, profile.decision,
      profile.samples, profile.finalized_samples, profile.checkout_rate, profile.settlement_rate,
      profile.observed_success_rate, profile.average_confidence, profile.calibration_error,
      profile.confidence_multiplier, profile.priority_adjustment, profile.authority,
    ).run();
    profiles.push(profile);
  }
  profiles.sort((a, b) => b.samples - a.samples || a.profile_key.localeCompare(b.profile_key));
  return profiles;
}

async function canary(env) {
  const lead = {
    id: `CANARY-${crypto.randomUUID().replaceAll("-", "").slice(0, 16).toUpperCase()}`,
    product_slug: "export-pulse",
    company: "LUMEN Cognitive Shadow Canary",
    details: "Empresa industrial argentina publicó nueva página de exportación y busca distribuidores en Chile.",
    source: "technical-canary",
    medium: "deploy",
    campaign: "cognitive-shadow-canary",
  };
  const decision = await analyze(env, lead, { technicalCanary: true });
  const stored = await storeLink(env, lead, decision, true);
  return {
    ok: true,
    stored,
    lead_id: lead.id,
    decision_id: decision.id,
    provider: decision.provider,
    model: decision.model,
    decision: decision.decision,
    recommended_product: decision.product,
    priority: decision.priority,
    confidence: decision.confidence,
    learning_calibration: decision.learning_calibration || null,
    paid_ai_used: false,
    monetary_cost_usd: 0,
    actions_executed: false,
    outgoing_spend_enabled: false,
    governor_required: true,
    mode: "shadow_only",
  };
}

async function stats(env) {
  await ensureSchema(env);
  const real = await env.DB.prepare("SELECT COUNT(*) AS n FROM lumen_cognitive_shadow_links WHERE technical_canary=0").first();
  const canaries = await env.DB.prepare("SELECT COUNT(*) AS n FROM lumen_cognitive_shadow_links WHERE technical_canary=1").first();
  const providers = await env.DB.prepare("SELECT provider,COUNT(*) AS n FROM lumen_cognitive_shadow_links WHERE technical_canary=0 GROUP BY provider ORDER BY provider").all();
  const outcomes = await env.DB.prepare("SELECT outcome_stage,COUNT(*) AS n FROM lumen_cognitive_outcomes WHERE technical_canary=0 GROUP BY outcome_stage ORDER BY outcome_stage").all();
  const outcomeTotal = await env.DB.prepare("SELECT COUNT(*) AS n FROM lumen_cognitive_outcomes WHERE technical_canary=0").first();
  const profiles = await env.DB.prepare("SELECT profile_key,current_product_slug,decision,samples,finalized_samples,checkout_rate,settlement_rate,observed_success_rate,average_confidence,calibration_error,confidence_multiplier,priority_adjustment,authority,updated_at FROM lumen_cognitive_learning_profiles ORDER BY samples DESC,profile_key LIMIT 50").all();
  return {
    ok: true,
    real_shadow_decisions: Number(real?.n || 0),
    technical_canaries: Number(canaries?.n || 0),
    real_by_provider: providers.results || [],
    learning: {
      mode: "outcome_calibration_v1",
      resolved_or_provisional_outcomes: Number(outcomeTotal?.n || 0),
      by_stage: outcomes.results || [],
      profiles: profiles.results || [],
      min_learning_sample: MIN_LEARNING_SAMPLE,
      min_priority_sample: MIN_PRIORITY_SAMPLE,
      negative_outcome_after_hours: NEGATIVE_OUTCOME_AFTER_HOURS,
      authority: "confidence_and_one_step_priority_only",
      decision_or_product_rewrite: false,
    },
    actions_executed: 0,
    monetary_cost_usd: 0,
    mode: "shadow_only",
  };
}

async function runCycle(env) {
  const processed = await processRecentLeads(env);
  const reconciled = await reconcileOutcomes(env);
  const profiles = await rebuildLearningProfiles(env);
  return { processed, reconciled, profiles_updated: profiles.length };
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    try {
      if (request.method === "GET" && (url.pathname === "/" || url.pathname === "/health")) {
        await ensureSchema(env);
        const cognitive = await cognitiveHealth(env);
        return json({
          ok: true,
          service: SERVICE,
          version: VERSION,
          mode: "shadow_only_learning",
          scheduled: true,
          max_real_leads_per_run: MAX_REAL_LEADS_PER_RUN,
          recent_lead_hours: RECENT_LEAD_HOURS,
          cognitive,
          learning: {
            enabled: true,
            outcome_sources: ["conversion_checkout", "x402_settlement"],
            min_learning_sample: MIN_LEARNING_SAMPLE,
            min_priority_sample: MIN_PRIORITY_SAMPLE,
            negative_outcome_after_hours: NEGATIVE_OUTCOME_AFTER_HOURS,
            authority: "calibration_only",
          },
          paid_ai_allowed: false,
          monetary_budget_usd: 0,
          actions_executed: false,
          outgoing_spend_enabled: false,
          governor_required: true,
        });
      }
      if (request.method === "GET" && url.pathname === "/stats") return json(await stats(env));
      if (request.method === "POST" && url.pathname === "/canary") return json(await canary(env));
      if (request.method === "POST" && url.pathname === "/learning/reconcile") {
        const reconciled = await reconcileOutcomes(env);
        const profiles = await rebuildLearningProfiles(env);
        return json({ ok: true, reconciled, profiles_updated: profiles.length, monetary_cost_usd: 0, actions_executed: false });
      }
      return json({ error: "not_found" }, 404);
    } catch (e) {
      return json({ ok: false, error: clean(e?.message || "shadow_error", 180), monetary_cost_usd: 0, actions_executed: false, outgoing_spend_enabled: false }, 500);
    }
  },

  async scheduled(_controller, env, ctx) {
    ctx.waitUntil(runCycle(env));
  },
};
