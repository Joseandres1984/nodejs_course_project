const SERVICE = "lumen-zero-cognitive";
const VERSION = "1.0-zero-cognitive-engine";
const PRIMARY_MODEL = "@cf/zai-org/glm-4.7-flash";
const OPENROUTER_MODEL = "openrouter/free";
const CF_DAILY_CALL_LIMIT = 50;
const OPENROUTER_DAILY_CALL_LIMIT = 20;
const MAX_CONTEXT_CHARS = 5000;
const MAX_COMPLETION_TOKENS = 240;
const ALLOW_PAID_AI = false;
const AI_MONETARY_BUDGET_USD = 0;

const PRODUCTS = new Set([
  "supplier-snapshot",
  "quote-sanity",
  "tender-scan",
  "sourcing-5",
  "buyer-signals",
  "export-pulse",
]);
const TASKS = new Set(["sales_triage", "research_plan", "qa_review", "director"]);
const PRIORITIES = new Set(["low", "medium", "high"]);
const SAFE_DECISIONS = new Set(["contact", "research", "hold", "prioritize", "qa_pass", "qa_revise"]);
const FORBIDDEN_ACTION = /\b(spend|transfer|send money|pay|payment|purchase|buy crypto|settle|settlement mutation|wire|withdraw|private key|seed phrase)\b/i;

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

function clean(value, limit = 500) {
  return String(value ?? "").replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim().slice(0, limit);
}

function clamp(n, min, max) {
  return Math.max(min, Math.min(max, Number.isFinite(Number(n)) ? Number(n) : min));
}

function utcDay() {
  return new Date().toISOString().slice(0, 10);
}

async function ensureSchema(env) {
  if (!env.DB) return;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_cognitive_usage (day TEXT PRIMARY KEY, cf_calls INTEGER NOT NULL DEFAULT 0, openrouter_calls INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_cognitive_decisions (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, task TEXT NOT NULL, provider TEXT NOT NULL, model TEXT, decision TEXT NOT NULL, product_slug TEXT, priority TEXT NOT NULL, confidence REAL NOT NULL, technical_canary INTEGER NOT NULL DEFAULT 0, paid_ai_used INTEGER NOT NULL DEFAULT 0, monetary_cost_usd REAL NOT NULL DEFAULT 0, actions_executed INTEGER NOT NULL DEFAULT 0, payload TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_cognitive_decisions_created ON lumen_cognitive_decisions(created_at)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_cognitive_decisions_provider ON lumen_cognitive_decisions(provider,created_at)"),
  ]);
}

async function reserveFreeCall(env, provider) {
  if (!env.DB) return { allowed: true, reason: "no_db_counter" };
  await ensureSchema(env);
  const day = utcDay();
  const now = new Date().toISOString();
  await env.DB.prepare("INSERT OR IGNORE INTO lumen_cognitive_usage(day,cf_calls,openrouter_calls,updated_at) VALUES(?,0,0,?)").bind(day, now).run();
  if (provider === "cloudflare_ai") {
    const r = await env.DB.prepare("UPDATE lumen_cognitive_usage SET cf_calls=cf_calls+1,updated_at=? WHERE day=? AND cf_calls<?").bind(now, day, CF_DAILY_CALL_LIMIT).run();
    return { allowed: Number(r?.meta?.changes || 0) === 1, limit: CF_DAILY_CALL_LIMIT };
  }
  if (provider === "openrouter_free") {
    const r = await env.DB.prepare("UPDATE lumen_cognitive_usage SET openrouter_calls=openrouter_calls+1,updated_at=? WHERE day=? AND openrouter_calls<?").bind(now, day, OPENROUTER_DAILY_CALL_LIMIT).run();
    return { allowed: Number(r?.meta?.changes || 0) === 1, limit: OPENROUTER_DAILY_CALL_LIMIT };
  }
  return { allowed: false, reason: "unknown_provider" };
}

async function usage(env) {
  if (!env.DB) return null;
  await ensureSchema(env);
  const row = await env.DB.prepare("SELECT day,cf_calls,openrouter_calls,updated_at FROM lumen_cognitive_usage WHERE day=?").bind(utcDay()).first();
  return row || { day: utcDay(), cf_calls: 0, openrouter_calls: 0 };
}

function flattenEvidence(body) {
  const safe = {
    task: clean(body.task, 60),
    subject: body.subject && typeof body.subject === "object" ? body.subject : {},
    context: body.context && typeof body.context === "object" ? body.context : {},
  };
  return JSON.stringify(safe).slice(0, MAX_CONTEXT_CHARS);
}

function deterministicDecision(body) {
  const hay = flattenEvidence(body).toLowerCase();
  let product = null;
  let priority = "medium";
  let decision = "research";
  let reason = "No hay evidencia suficiente para automatizar una acción comercial; conviene ampliar información.";

  if (/licitaci|tender|procurement notice|pliego|adjudic/.test(hay)) {
    product = "tender-scan";
    decision = "contact";
    priority = "high";
    reason = "Se detectaron señales explícitas vinculadas con licitaciones u oportunidades públicas.";
  } else if (/export|importador|distribuidor.*(chile|brasil|uruguay|paraguay|mercado)|international sales|comercio exterior/.test(hay)) {
    product = "export-pulse";
    decision = "contact";
    priority = "high";
    reason = "Se detectaron señales de expansión, exportación o búsqueda de mercado internacional.";
  } else if (/cotiz|quotation|quote|precio|price|presupuesto/.test(hay)) {
    product = "quote-sanity";
    decision = "contact";
    reason = "La necesidad observada está asociada a revisar una cotización o referencia de precio.";
  } else if (/buscar proveedor|busca proveedor|sourcing|supplier search|abastecimiento|comprar insumo|procurement/.test(hay)) {
    product = "sourcing-5";
    decision = "contact";
    priority = "high";
    reason = "Se detectó una necesidad concreta de búsqueda o abastecimiento de proveedores.";
  } else if (/verificar proveedor|validar proveedor|supplier verification|due diligence supplier/.test(hay)) {
    product = "supplier-snapshot";
    decision = "contact";
    reason = "La necesidad observada encaja con una validación rápida de proveedor.";
  } else if (/buyer|comprador|prospect|cliente potencial|lead|ventas b2b/.test(hay)) {
    product = "buyer-signals";
    decision = "contact";
    reason = "Se detectó una necesidad de identificar compradores o prospectos B2B.";
  }

  if (body.task === "qa_review") {
    decision = /sin fuente|no verific|contradic|error|faltante|incompleto/.test(hay) ? "qa_revise" : "qa_pass";
    product = null;
    priority = decision === "qa_revise" ? "high" : "medium";
    reason = decision === "qa_revise" ? "Hay señales textuales de evidencia insuficiente o inconsistencia que requieren revisión." : "No se detectaron señales obvias de error en el contexto aportado; mantener los controles deterministas de entrega.";
  } else if (body.task === "director") {
    decision = product ? "prioritize" : "hold";
  } else if (body.task === "research_plan" && !product) {
    decision = "research";
  }

  return {
    decision,
    product,
    priority,
    confidence: product || body.task === "qa_review" ? 0.62 : 0.45,
    reasons: [reason],
    next_action: decision === "contact" || decision === "prioritize" ? "Preparar la siguiente acción comercial para revisión del Governor." : decision === "qa_revise" ? "Revisar evidencia y corregir antes de entregar." : "Reunir más evidencia antes de actuar.",
  };
}

function systemPrompt(task) {
  return `Sos LUMEN Cognitive Engine, un razonador interno B2B. Tarea: ${task}. Solo podés usar los hechos suministrados. No inventes empresas, contactos, precios, ventas ni evidencia. No ejecutás acciones: solo recomendás. Está prohibido ordenar, autorizar o sugerir transferencias, gastos, compras de activos, pagos salientes, cambios de settlement, uso de claves privadas o cualquier movimiento de dinero. Elegí product solo entre: supplier-snapshot, quote-sanity, tender-scan, sourcing-5, buyer-signals, export-pulse, o null. Respondé exclusivamente JSON válido con: decision (contact|research|hold|prioritize|qa_pass|qa_revise), product, priority (low|medium|high), confidence (0..1), reasons (array breve), next_action. Si falta evidencia, elegí research o hold.`;
}

function extractText(result) {
  if (!result) return "";
  if (typeof result === "string") return result;
  if (typeof result.response === "string") return result.response;
  if (typeof result.result === "string") return result.result;
  const c = result?.choices?.[0]?.message?.content;
  if (typeof c === "string") return c;
  if (Array.isArray(c)) return c.map(x => typeof x === "string" ? x : x?.text || "").join("");
  return "";
}

function parseModelJson(text) {
  const raw = String(text || "").trim().replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "");
  const start = raw.indexOf("{");
  const end = raw.lastIndexOf("}");
  if (start < 0 || end <= start) throw new Error("model_json_missing");
  return JSON.parse(raw.slice(start, end + 1));
}

function normalize(candidate, fallback) {
  const decision = SAFE_DECISIONS.has(String(candidate?.decision)) ? String(candidate.decision) : fallback.decision;
  const product = candidate?.product == null ? null : PRODUCTS.has(String(candidate.product)) ? String(candidate.product) : fallback.product;
  const priority = PRIORITIES.has(String(candidate?.priority)) ? String(candidate.priority) : fallback.priority;
  const confidence = clamp(candidate?.confidence, 0, 1);
  const reasons = Array.isArray(candidate?.reasons) ? candidate.reasons.map(x => clean(x, 260)).filter(Boolean).slice(0, 4) : fallback.reasons;
  const nextAction = clean(candidate?.next_action || fallback.next_action, 320);
  if (FORBIDDEN_ACTION.test(nextAction) || reasons.some(x => FORBIDDEN_ACTION.test(x))) {
    return { ...fallback, confidence: Math.min(fallback.confidence, 0.5), safety_override: "forbidden_action_removed" };
  }
  return { decision, product, priority, confidence, reasons: reasons.length ? reasons : fallback.reasons, next_action: nextAction || fallback.next_action };
}

async function cloudflareReason(env, body) {
  if (!env.AI) throw new Error("ai_binding_unavailable");
  const budget = await reserveFreeCall(env, "cloudflare_ai");
  if (!budget.allowed) throw new Error("cloudflare_free_guard_exhausted");
  const result = await env.AI.run(PRIMARY_MODEL, {
    messages: [
      { role: "system", content: systemPrompt(body.task) },
      { role: "user", content: flattenEvidence(body) },
    ],
    temperature: 0.2,
    max_tokens: MAX_COMPLETION_TOKENS,
  });
  return parseModelJson(extractText(result));
}

async function openRouterReason(env, body) {
  if (!env.OPENROUTER_API_KEY) throw new Error("openrouter_not_configured");
  const budget = await reserveFreeCall(env, "openrouter_free");
  if (!budget.allowed) throw new Error("openrouter_free_guard_exhausted");
  const response = await fetch("https://openrouter.ai/api/v1/chat/completions", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "authorization": `Bearer ${env.OPENROUTER_API_KEY}`,
      "x-title": "LUMEN Cognitive Engine",
    },
    body: JSON.stringify({
      model: OPENROUTER_MODEL,
      messages: [
        { role: "system", content: systemPrompt(body.task) },
        { role: "user", content: flattenEvidence(body) },
      ],
      max_tokens: MAX_COMPLETION_TOKENS,
      temperature: 0.2,
    }),
  });
  if (!response.ok) throw new Error(`openrouter_http_${response.status}`);
  return parseModelJson(extractText(await response.json()));
}

async function storeDecision(env, record) {
  if (!env.DB) return;
  await ensureSchema(env);
  await env.DB.prepare("INSERT INTO lumen_cognitive_decisions(id,created_at,task,provider,model,decision,product_slug,priority,confidence,technical_canary,paid_ai_used,monetary_cost_usd,actions_executed,payload) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
    .bind(record.id, record.created_at, record.task, record.provider, record.model || null, record.decision, record.product || null, record.priority, record.confidence, record.technical_canary ? 1 : 0, 0, 0, 0, JSON.stringify({ reasons: record.reasons, next_action: record.next_action, attempted_providers: record.attempted_providers, safety_override: record.safety_override || null })).run();
}

async function decide(env, body) {
  if (!TASKS.has(body.task)) throw Object.assign(new Error("unsupported_task"), { status: 400 });
  const fallback = deterministicDecision(body);
  const attempted = [];
  let provider = "deterministic";
  let model = null;
  let result = fallback;
  const useAi = body.use_ai !== false;

  if (useAi) {
    try {
      attempted.push("cloudflare_ai");
      result = normalize(await cloudflareReason(env, body), fallback);
      provider = "cloudflare_ai";
      model = PRIMARY_MODEL;
    } catch (e) {
      attempted.push(`cloudflare_ai:${clean(e?.message, 100)}`);
      try {
        attempted.push("openrouter_free");
        result = normalize(await openRouterReason(env, body), fallback);
        provider = "openrouter_free";
        model = OPENROUTER_MODEL;
      } catch (e2) {
        attempted.push(`openrouter_free:${clean(e2?.message, 100)}`);
        result = fallback;
        provider = "deterministic";
      }
    }
  }

  const record = {
    id: `CD-${crypto.randomUUID().replaceAll("-", "").slice(0, 20).toUpperCase()}`,
    created_at: new Date().toISOString(),
    task: body.task,
    provider,
    model,
    ...result,
    attempted_providers: attempted,
    technical_canary: Boolean(body.technical_canary),
    paid_ai_used: false,
    monetary_cost_usd: 0,
    actions_executed: false,
    governor_required: true,
    outgoing_spend_enabled: false,
  };
  await storeDecision(env, record);
  return record;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "GET" && (url.pathname === "/" || url.pathname === "/health")) {
      return json({
        service: SERVICE,
        version: VERSION,
        status: "ok",
        architecture: "cloudflare_ai -> openrouter_free(optional) -> deterministic",
        primary_provider: "cloudflare_ai",
        primary_model: PRIMARY_MODEL,
        openrouter_model: OPENROUTER_MODEL,
        ai_binding_available: Boolean(env.AI),
        openrouter_configured: Boolean(env.OPENROUTER_API_KEY),
        free_guard: { cloudflare_calls_per_utc_day: CF_DAILY_CALL_LIMIT, openrouter_calls_per_utc_day: OPENROUTER_DAILY_CALL_LIMIT, max_context_chars: MAX_CONTEXT_CHARS, max_completion_tokens: MAX_COMPLETION_TOKENS },
        usage_today: await usage(env),
        paid_ai_allowed: ALLOW_PAID_AI,
        monetary_budget_usd: AI_MONETARY_BUDGET_USD,
        paid_ai_used: false,
        outgoing_spend_enabled: false,
        actions_executed: false,
        governor_required: true,
      });
    }
    if (request.method === "POST" && url.pathname === "/decide") {
      let body;
      try {
        const raw = await request.text();
        if (raw.length > 16000) return json({ error: "payload_too_large" }, 413);
        body = JSON.parse(raw || "{}");
      } catch {
        return json({ error: "invalid_json" }, 400);
      }
      try {
        return json(await decide(env, body));
      } catch (e) {
        return json({ error: clean(e?.message || "decision_failed", 120), paid_ai_used: false, monetary_cost_usd: 0, actions_executed: false, outgoing_spend_enabled: false }, e?.status || 500);
      }
    }
    return json({ error: "not_found" }, 404);
  },
};
