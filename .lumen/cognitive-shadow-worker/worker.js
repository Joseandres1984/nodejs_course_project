const SERVICE = "lumen-zero-cognitive-shadow";
const VERSION = "1.0-cognitive-shadow-loop";
const MAX_REAL_LEADS_PER_RUN = 2;
const RECENT_LEAD_HOURS = 24;

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

async function ensureSchema(env) {
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_cognitive_shadow_links (lead_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, decision_id TEXT NOT NULL, provider TEXT NOT NULL, model TEXT, current_product_slug TEXT, recommended_product_slug TEXT, decision TEXT NOT NULL, priority TEXT NOT NULL, confidence REAL NOT NULL, status TEXT NOT NULL DEFAULT 'shadow_only', technical_canary INTEGER NOT NULL DEFAULT 0, monetary_cost_usd REAL NOT NULL DEFAULT 0, actions_executed INTEGER NOT NULL DEFAULT 0, payload TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_cognitive_shadow_created ON lumen_cognitive_shadow_links(created_at)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_cognitive_shadow_real ON lumen_cognitive_shadow_links(technical_canary,created_at)"),
  ]);
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
      processed.push({ lead_id: lead.id, stored, decision_id: decision.id, provider: decision.provider, decision: decision.decision, recommended_product: decision.product, priority: decision.priority, confidence: decision.confidence });
    } catch (e) {
      processed.push({ lead_id: lead.id, stored: false, error: clean(e?.message, 180) });
    }
  }
  return { candidates: (rows.results || []).length, processed };
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
  return {
    ok: true,
    real_shadow_decisions: Number(real?.n || 0),
    technical_canaries: Number(canaries?.n || 0),
    real_by_provider: providers.results || [],
    actions_executed: 0,
    monetary_cost_usd: 0,
    mode: "shadow_only",
  };
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
          mode: "shadow_only",
          scheduled: true,
          max_real_leads_per_run: MAX_REAL_LEADS_PER_RUN,
          recent_lead_hours: RECENT_LEAD_HOURS,
          cognitive,
          paid_ai_allowed: false,
          monetary_budget_usd: 0,
          actions_executed: false,
          outgoing_spend_enabled: false,
          governor_required: true,
        });
      }
      if (request.method === "GET" && url.pathname === "/stats") return json(await stats(env));
      if (request.method === "POST" && url.pathname === "/canary") return json(await canary(env));
      return json({ error: "not_found" }, 404);
    } catch (e) {
      return json({ ok: false, error: clean(e?.message || "shadow_error", 180), monetary_cost_usd: 0, actions_executed: false, outgoing_spend_enabled: false }, 500);
    }
  },

  async scheduled(_controller, env, ctx) {
    ctx.waitUntil(processRecentLeads(env));
  },
};
