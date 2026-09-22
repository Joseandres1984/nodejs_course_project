const SERVICE = "lumen-zero-cognitive";
const VERSION = "1.3-zero-cognitive-learning-calibrated";
const PRIMARY_MODEL = "@cf/google/gemma-4-26b-a4b-it";
const CF_DAILY_CALL_LIMIT = 50;
const MAX_CONTEXT_CHARS = 5000;
const MAX_COMPLETION_TOKENS = 400;
const ALLOW_PAID_AI = false;
const AI_MONETARY_BUDGET_USD = 0;
const MIN_LEARNING_SAMPLE = 5;
const MIN_PRIORITY_SAMPLE = 8;
const MAX_LEARNED_CONFIDENCE = 0.95;

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
  return String(value ?? "")
    .replace(/[\u0000-\u001f\u007f]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, limit);
}

function clamp(n, min, max) {
  return Math.max(min, Math.min(max, Number.isFinite(Number(n)) ? Number(n) : min));
}

function utcDay() {
  return new Date().toISOString().slice(0, 10);
}

async function ensureSchema(env) {
  if (!env.DB) return;
  // Keep the legacy openrouter_calls column for backwards-compatible D1 schema reads,
  // but this worker never calls OpenRouter or any paid/secondary inference provider.
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_cognitive_usage (day TEXT PRIMARY KEY, cf_calls INTEGER NOT NULL DEFAULT 0, openrouter_calls INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_cognitive_decisions (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, task TEXT NOT NULL, provider TEXT NOT NULL, model TEXT, decision TEXT NOT NULL, product_slug TEXT, priority TEXT NOT NULL, confidence REAL NOT NULL, technical_canary INTEGER NOT NULL DEFAULT 0, paid_ai_used INTEGER NOT NULL DEFAULT 0, monetary_cost_usd REAL NOT NULL DEFAULT 0, actions_executed INTEGER NOT NULL DEFAULT 0, payload TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_cognitive_decisions_created ON lumen_cognitive_decisions(created_at)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_cognitive_decisions_provider ON lumen_cognitive_decisions(provider,created_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_cognitive_learning_profiles (profile_key TEXT PRIMARY KEY, updated_at TEXT NOT NULL, current_product_slug TEXT, decision TEXT NOT NULL, samples INTEGER NOT NULL DEFAULT 0, finalized_samples INTEGER NOT NULL DEFAULT 0, checkout_rate REAL NOT NULL DEFAULT 0, settlement_rate REAL NOT NULL DEFAULT 0, observed_success_rate REAL NOT NULL DEFAULT 0, average_confidence REAL NOT NULL DEFAULT 0, calibration_error REAL NOT NULL DEFAULT 0, confidence_multiplier REAL NOT NULL DEFAULT 1, priority_adjustment INTEGER NOT NULL DEFAULT 0, authority TEXT NOT NULL DEFAULT 'calibration_only')"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_cognitive_learning_product ON lumen_cognitive_learning_profiles(current_product_slug,decision)"),
  ]);
}

async function reserveFreeCloudflareCall(env) {
  if (!env.DB) return { allowed: false, reason: "usage_counter_required" };
  await ensureSchema(env);
  const day = utcDay();
  const now = new Date().toISOString();
  await env.DB.prepare("INSERT OR IGNORE INTO lumen_cognitive_usage(day,cf_calls,openrouter_calls,updated_at) VALUES(?,0,0,?)").bind(day, now).run();
  const r = await env.DB.prepare("UPDATE lumen_cognitive_usage SET cf_calls=cf_calls+1,updated_at=? WHERE day=? AND cf_calls<?")
    .bind(now, day, CF_DAILY_CALL_LIMIT)
    .run();
  return {
    allowed: Number(r?.meta?.changes || 0) === 1,
    limit: CF_DAILY_CALL_LIMIT,
    reason: Number(r?.meta?.changes || 0) === 1 ? "reserved" : "cloudflare_free_guard_exhausted",
  };
}

async function usage(env) {
  if (!env.DB) return null;
  await ensureSchema(env);
  const row = await env.DB.prepare("SELECT day,cf_calls,updated_at FROM lumen_cognitive_usage WHERE day=?").bind(utcDay()).first();
  return row || { day: utcDay(), cf_calls: 0 };
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
    reason = decision === "qa_revise"
      ? "Hay señales textuales de evidencia insuficiente o inconsistencia que requieren revisión."
      : "No se detectaron señales obvias de error en el contexto aportado; mantener los controles deterministas de entrega.";
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
    next_action: decision === "contact" || decision === "prioritize"
      ? "Preparar la siguiente acción comercial para revisión del Governor."
      : decision === "qa_revise"
        ? "Revisar evidencia y corregir antes de entregar."
        : "Reunir más evidencia antes de actuar.",
  };
}

function systemPrompt(task) {
  return `Sos LUMEN Cognitive Engine, un razonador interno B2B. Tarea: ${task}. Solo podés usar los hechos suministrados. No inventes empresas, contactos, precios, ventas ni evidencia. No ejecutás acciones: solo recomendás. Está prohibido ordenar, autorizar o sugerir transferencias, gastos, compras de activos, pagos salientes, cambios de settlement, uso de claves privadas o cualquier movimiento de dinero. Elegí product solo entre: supplier-snapshot, quote-sanity, tender-scan, sourcing-5, buyer-signals, export-pulse, o null. Respondé exclusivamente JSON válido con: decision (contact|research|hold|prioritize|qa_pass|qa_revise), product, priority (low|medium|high), confidence (0..1), reasons (array breve), next_action. Si falta evidencia, elegí research o hold.`;
}

function extractText(result) {
  if (!result) return "";
  if (typeof result === "string") return result;
  if (typeof result.response === "string") return result.response;
  if (result.response && typeof result.response === "object") return JSON.stringify(result.response);
  if (typeof result.result === "string") return result.result;
  const message = result?.choices?.[0]?.message;
  if (message?.parsed && typeof message.parsed === "object") return JSON.stringify(message.parsed);
  const c = message?.content;
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
  const product = candidate?.product == null
    ? null
    : PRODUCTS.has(String(candidate.product))
      ? String(candidate.product)
      : fallback.product;
  const priority = PRIORITIES.has(String(candidate?.priority)) ? String(candidate.priority) : fallback.priority;
  const confidence = clamp(candidate?.confidence, 0, 1);
  const reasons = Array.isArray(candidate?.reasons)
    ? candidate.reasons.map(x => clean(x, 260)).filter(Boolean).slice(0, 4)
    : fallback.reasons;
  const nextAction = clean(candidate?.next_action || fallback.next_action, 320);
  if (FORBIDDEN_ACTION.test(nextAction) || reasons.some(x => FORBIDDEN_ACTION.test(x))) {
    return {
      ...fallback,
      confidence: Math.min(fallback.confidence, 0.5),
      safety_override: "forbidden_action_removed",
    };
  }
  return {
    decision,
    product,
    priority,
    confidence,
    reasons: reasons.length ? reasons : fallback.reasons,
    next_action: nextAction || fallback.next_action,
  };
}

async function cloudflareReason(env, body) {
  if (!env.AI) throw new Error("ai_binding_unavailable");
  const budget = await reserveFreeCloudflareCall(env);
  if (!budget.allowed) throw new Error(budget.reason || "cloudflare_free_guard_exhausted");
  const result = await env.AI.run(PRIMARY_MODEL, {
    messages: [
      { role: "system", content: systemPrompt(body.task) },
      { role: "user", content: flattenEvidence(body) },
    ],
    temperature: 0.1,
    max_completion_tokens: MAX_COMPLETION_TOKENS,
    chat_template_kwargs: { enable_thinking: false },
  });
  return parseModelJson(extractText(result));
}

function shiftPriority(priority, adjustment) {
  const levels = ["low", "medium", "high"];
  const index = levels.indexOf(priority);
  if (index < 0 || !adjustment) return priority;
  return levels[Math.max(0, Math.min(levels.length - 1, index + Math.sign(adjustment)))];
}

async function loadLearningProfile(env, body, result) {
  if (!env.DB || !["sales_triage", "director"].includes(String(body.task || ""))) return null;
  const currentProduct = clean(body?.subject?.current_product, 80);
  const decision = clean(result?.decision, 40);
  if (!PRODUCTS.has(currentProduct) || !decision) return null;
  await ensureSchema(env);
  return await env.DB.prepare("SELECT profile_key,updated_at,current_product_slug,decision,samples,finalized_samples,checkout_rate,settlement_rate,observed_success_rate,average_confidence,calibration_error,confidence_multiplier,priority_adjustment,authority FROM lumen_cognitive_learning_profiles WHERE profile_key=? LIMIT 1")
    .bind(`${currentProduct}|${decision}`).first();
}

async function applyLearningCalibration(env, body, result) {
  try {
    const profile = await loadLearningProfile(env, body, result);
    if (!profile) return { result, learning: null };
    const samples = Number(profile.samples || 0);
    const rawMultiplier = clamp(profile.confidence_multiplier, 0.75, 1.05);
    const canCalibrate = samples >= MIN_LEARNING_SAMPLE && profile.authority === "calibration_only";
    const multiplier = canCalibrate ? rawMultiplier : 1;
    const confidenceBefore = clamp(result.confidence, 0, 1);
    const confidenceAfter = canCalibrate
      ? Number(clamp(confidenceBefore * multiplier, 0, MAX_LEARNED_CONFIDENCE).toFixed(4))
      : confidenceBefore;

    let priorityAfter = result.priority;
    let appliedPriorityAdjustment = 0;
    const canAdjustPriority = canCalibrate
      && samples >= MIN_PRIORITY_SAMPLE
      && ["contact", "prioritize"].includes(String(result.decision || ""));
    if (canAdjustPriority) {
      appliedPriorityAdjustment = Math.max(-1, Math.min(1, Number(profile.priority_adjustment || 0)));
      priorityAfter = shiftPriority(result.priority, appliedPriorityAdjustment);
    }

    return {
      result: { ...result, confidence: confidenceAfter, priority: priorityAfter },
      learning: {
        applied: canCalibrate,
        profile_key: profile.profile_key,
        samples,
        finalized_samples: Number(profile.finalized_samples || 0),
        checkout_rate: Number(profile.checkout_rate || 0),
        settlement_rate: Number(profile.settlement_rate || 0),
        observed_success_rate: Number(profile.observed_success_rate || 0),
        historical_average_confidence: Number(profile.average_confidence || 0),
        calibration_error: Number(profile.calibration_error || 0),
        confidence_multiplier: multiplier,
        confidence_before: confidenceBefore,
        confidence_after: confidenceAfter,
        priority_before: result.priority,
        priority_after: priorityAfter,
        priority_adjustment: appliedPriorityAdjustment,
        authority: "confidence_and_one_step_priority_only",
        decision_changed: false,
        product_changed: false,
      },
    };
  } catch (e) {
    return {
      result,
      learning: {
        applied: false,
        error: clean(e?.message || "learning_profile_error", 120),
        authority: "fail_open_to_original_recommendation_without_extra_authority",
        decision_changed: false,
        product_changed: false,
      },
    };
  }
}

async function listLearningProfiles(env) {
  if (!env.DB) return [];
  await ensureSchema(env);
  const rows = await env.DB.prepare("SELECT profile_key,updated_at,current_product_slug,decision,samples,finalized_samples,checkout_rate,settlement_rate,observed_success_rate,average_confidence,calibration_error,confidence_multiplier,priority_adjustment,authority FROM lumen_cognitive_learning_profiles ORDER BY samples DESC,profile_key LIMIT 100").all();
  return rows.results || [];
}

async function storeDecision(env, record) {
  if (!env.DB) return;
  await ensureSchema(env);
  await env.DB.prepare("INSERT INTO lumen_cognitive_decisions(id,created_at,task,provider,model,decision,product_slug,priority,confidence,technical_canary,paid_ai_used,monetary_cost_usd,actions_executed,payload) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
    .bind(
      record.id,
      record.created_at,
      record.task,
      record.provider,
      record.model || null,
      record.decision,
      record.product || null,
      record.priority,
      record.confidence,
      record.technical_canary ? 1 : 0,
      0,
      0,
      0,
      JSON.stringify({
        reasons: record.reasons,
        next_action: record.next_action,
        attempted_providers: record.attempted_providers,
        safety_override: record.safety_override || null,
        learning_calibration: record.learning_calibration || null,
      }),
    )
    .run();
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
      result = fallback;
      provider = "deterministic";
      model = null;
    }
  }

  const calibrated = await applyLearningCalibration(env, body, result);
  result = calibrated.result;

  const record = {
    id: `CD-${crypto.randomUUID().replaceAll("-", "").slice(0, 20).toUpperCase()}`,
    created_at: new Date().toISOString(),
    task: body.task,
    provider,
    model,
    ...result,
    attempted_providers: attempted,
    learning_calibration: calibrated.learning,
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
        architecture: "cloudflare_ai_free_only -> deterministic -> bounded_outcome_calibration",
        primary_provider: "cloudflare_ai",
        primary_model: PRIMARY_MODEL,
        ai_binding_available: Boolean(env.AI),
        free_only: true,
        free_guard: {
          cloudflare_calls_per_utc_day: CF_DAILY_CALL_LIMIT,
          max_context_chars: MAX_CONTEXT_CHARS,
          max_completion_tokens: MAX_COMPLETION_TOKENS,
          fallback: "deterministic",
          external_paid_fallbacks: 0,
        },
        learning: {
          enabled: true,
          mode: "historical_outcome_calibration",
          min_learning_sample: MIN_LEARNING_SAMPLE,
          min_priority_sample: MIN_PRIORITY_SAMPLE,
          max_learned_confidence: MAX_LEARNED_CONFIDENCE,
          authority: "confidence_and_one_step_priority_only",
          may_change_decision: false,
          may_change_product: false,
          may_expand_execution_authority: false,
        },
        usage_today: await usage(env),
        paid_ai_allowed: ALLOW_PAID_AI,
        monetary_budget_usd: AI_MONETARY_BUDGET_USD,
        paid_ai_used: false,
        outgoing_spend_enabled: false,
        actions_executed: false,
        governor_required: true,
      });
    }

    if (request.method === "GET" && url.pathname === "/learning") {
      return json({
        ok: true,
        profiles: await listLearningProfiles(env),
        monetary_cost_usd: 0,
        actions_executed: false,
        outgoing_spend_enabled: false,
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
        return json({
          error: clean(e?.message || "decision_failed", 120),
          paid_ai_used: false,
          monetary_cost_usd: 0,
          actions_executed: false,
          outgoing_spend_enabled: false,
        }, e?.status || 500);
      }
    }

    return json({ error: "not_found" }, 404);
  },
};
