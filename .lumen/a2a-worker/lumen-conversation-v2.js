import { computeEconomicOperatorState } from "./revenue-focus-controller.js";

const VERSION = "1.0-lumen-conversational-mind";
const REVISION = "2.0-responsive-learning";
const MODEL = "@cf/meta/llama-3.1-8b-instruct-fast";
const MAX_DAILY_AI_CALLS = 30;
const MAX_HISTORY = 36;
const MAX_MESSAGE = 1800;
const AI_TIMEOUT_MS = 6500;

function clean(value, limit = 400) {
  return String(value ?? "")
    .replace(/[\u0000-\u001f\u007f]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, limit);
}
function num(value, fallback = 0) { const n = Number(value); return Number.isFinite(n) ? n : fallback; }
function parse(value, fallback = {}) { try { return JSON.parse(String(value || "")); } catch { return fallback; } }
function clamp(value, min, max) { return Math.max(min, Math.min(max, num(value))); }
function json(data, status = 200) {
  return Response.json(data, {
    status,
    headers: {
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "access-control-allow-origin": "*",
      "access-control-allow-headers": "content-type,x-lumen-admin",
      "access-control-allow-methods": "GET,POST,OPTIONS",
      "x-lumen-mind-revision": REVISION,
    },
  });
}
function authorized(request, env) {
  const expected = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const supplied = clean(request.headers.get("x-lumen-admin"), 500);
  return Boolean(expected && supplied && expected === supplied);
}
async function first(env, sql, bind = []) {
  try {
    const q = env.DB.prepare(sql);
    return bind.length ? await q.bind(...bind).first() : await q.first();
  } catch { return null; }
}
async function all(env, sql, bind = []) {
  try {
    const q = env.DB.prepare(sql);
    const r = bind.length ? await q.bind(...bind).all() : await q.all();
    return r.results || [];
  } catch { return []; }
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_conversation_turns (id TEXT PRIMARY KEY,created_at TEXT NOT NULL,role TEXT NOT NULL,message TEXT NOT NULL,source TEXT NOT NULL,snapshot_json TEXT,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_conversation_turns_created ON lumen_conversation_turns(created_at DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_conversation_usage (day TEXT PRIMARY KEY,ai_calls INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL)")
  ]);
  return true;
}

async function reserveAiCall(env) {
  if (!env?.DB || !env?.AI) return { allowed: false, reason: "ai_unavailable" };
  await ensureSchema(env);
  const day = new Date().toISOString().slice(0, 10);
  const timestamp = new Date().toISOString();
  const row = await first(env, "SELECT ai_calls FROM lumen_conversation_usage WHERE day=? LIMIT 1", [day]);
  const used = num(row?.ai_calls);
  if (used >= MAX_DAILY_AI_CALLS) return { allowed: false, reason: "daily_ai_guard_exhausted", used };
  await env.DB.prepare("INSERT INTO lumen_conversation_usage(day,ai_calls,updated_at) VALUES(?,1,?) ON CONFLICT(day) DO UPDATE SET ai_calls=lumen_conversation_usage.ai_calls+1,updated_at=excluded.updated_at")
    .bind(day, timestamp).run();
  return { allowed: true, used: used + 1 };
}

function channelSummary(row) {
  if (!row) return { status: "unknown", fresh: false, provider: null, details: {} };
  const parsedTime = Date.parse(row.checked_at || "");
  const ageSeconds = Number.isFinite(parsedTime) ? Math.max(0, Math.round((Date.now() - parsedTime) / 1000)) : Number.POSITIVE_INFINITY;
  const fresh = Number.isFinite(ageSeconds) && ageSeconds <= 6 * 60 * 60;
  return {
    status: fresh ? row.status : "stale",
    recordedStatus: row.status,
    fresh,
    ageSeconds: Number.isFinite(ageSeconds) ? ageSeconds : null,
    provider: row.provider || null,
    details: parse(row.details_json, {}),
  };
}

async function operationalSnapshot(env) {
  const [economic, superRow, cognitiveRow, gmailRow, goals, debt, postmortems, memory, learningState, learningEvents] = await Promise.all([
    computeEconomicOperatorState(env),
    first(env, "SELECT updated_at,cycle,phase,bottleneck,next_action,target_metric,stall_cycles,recovery_level,autonomy_ratio,state_json,engine_version FROM lumen_superautonomy_state WHERE id='GLOBAL' LIMIT 1"),
    first(env, "SELECT updated_at,cycle,provider,model,phase,action_type,target_lane,confidence,expected_value,rationale_summary,recommendation_json,engine_version FROM lumen_live_cognitive_state WHERE id='GLOBAL' LIMIT 1"),
    first(env, "SELECT channel,status,provider,checked_at,details_json FROM lumen_channel_health WHERE channel='gmail' LIMIT 1"),
    all(env, "SELECT goal_id,priority,objective,target_metric,current_value,target_value,status,owner,reason,updated_at FROM lumen_superautonomy_goals WHERE status LIKE 'active%' ORDER BY priority DESC,updated_at DESC LIMIT 5"),
    all(env, "SELECT debt_id,category,reason,hits,avoidable,mitigation,status,updated_at FROM lumen_superautonomy_human_debt WHERE status='OPEN' ORDER BY hits DESC,updated_at DESC LIMIT 5"),
    all(env, "SELECT created_at,cycle,outcome,action_key,target_metric,delta,observation,lesson,promotion,confidence FROM lumen_superautonomy_postmortems ORDER BY cycle DESC,created_at DESC LIMIT 6"),
    all(env, "SELECT action_key,attempts,wins,stalls,score,last_outcome,last_metric,last_delta,updated_at FROM lumen_superautonomy_action_memory ORDER BY score DESC,updated_at DESC LIMIT 10"),
    first(env, "SELECT updated_at,cycle,context_key,exploration_rate,confidence,recommendation_json,engine_version FROM lumen_self_learning_state WHERE id='GLOBAL' LIMIT 1"),
    all(env, "SELECT created_at,postmortem_id,action_key,context_key,outcome,delta,signal_strength,score_before,score_after,hypothesis FROM lumen_self_learning_events ORDER BY created_at DESC LIMIT 6")
  ]);

  const superState = parse(superRow?.state_json, {});
  const cognitive = cognitiveRow ? {
    updatedAt: cognitiveRow.updated_at,
    cycle: num(cognitiveRow.cycle),
    provider: cognitiveRow.provider,
    model: cognitiveRow.model || null,
    phase: cognitiveRow.phase || null,
    actionType: cognitiveRow.action_type,
    targetLane: cognitiveRow.target_lane || null,
    confidence: num(cognitiveRow.confidence),
    expectedValue: num(cognitiveRow.expected_value),
    rationaleSummary: cognitiveRow.rationale_summary,
    recommendation: parse(cognitiveRow.recommendation_json, {}),
  } : null;

  const learning = learningState ? {
    updatedAt: learningState.updated_at,
    cycle: num(learningState.cycle),
    contextKey: learningState.context_key,
    explorationRate: clamp(learningState.exploration_rate, 0, 1),
    confidence: learningState.confidence || "LOW",
    recommendation: parse(learningState.recommendation_json, {}),
    recentEvents: learningEvents,
  } : {
    updatedAt: null,
    cycle: 0,
    contextKey: null,
    explorationRate: 0.08,
    confidence: "LOW",
    recommendation: {},
    recentEvents: [],
  };

  return {
    capturedAt: new Date().toISOString(),
    economic: {
      phase: economic?.phase || null,
      nextEconomicAction: economic?.nextEconomicAction || null,
      metrics: economic?.metrics || {},
      revenueFocus: economic?.revenueFocus || {},
      autonomy: economic?.autonomy || {},
    },
    superautonomy: superRow ? {
      updatedAt: superRow.updated_at,
      cycle: num(superRow.cycle),
      phase: superRow.phase,
      bottleneck: superRow.bottleneck,
      nextAction: superRow.next_action,
      targetMetric: superRow.target_metric,
      stallCycles: num(superRow.stall_cycles),
      recoveryLevel: num(superRow.recovery_level),
      boundedAutonomyRatio: num(superRow.autonomy_ratio),
      recovery: superState.recovery || null,
      portfolio: superState.portfolio || null,
      humanGateRequired: Boolean(superState.humanGateRequired),
    } : null,
    cognitive,
    learning,
    channels: { gmail: channelSummary(gmailRow) },
    goals,
    humanAttentionDebt: debt,
    postmortems,
    actionMemory: memory,
    constitutionalLimits: {
      autonomousSpendUsd: 0,
      autonomousPurchase: false,
      autonomousDebt: false,
      autonomousContract: false,
      paidMedia: false,
      productionDeploy: false,
      newExternalConnectors: false,
      bindingActionsHumanGated: true,
    },
    truthRule: "Only verified settled payment counts as revenue. Plans and explanations distinguish observed facts, bounded inference and proposed next steps.",
  };
}

function compactLesson(snapshot) {
  const event = snapshot?.learning?.recentEvents?.[0];
  const pm = snapshot?.postmortems?.[0];
  if (event?.hypothesis) return clean(event.hypothesis, 360);
  if (pm?.lesson) return clean(pm.lesson, 360);
  return "Todavía no tengo suficiente evidencia nueva para formular una lección fuerte.";
}

export function deterministicReply(snapshot, question) {
  const superState = snapshot?.superautonomy || {};
  const economic = snapshot?.economic || {};
  const metrics = economic.metrics || {};
  const backlog = economic.revenueFocus?.backlog || {};
  const gmail = snapshot?.channels?.gmail || {};
  const learning = snapshot?.learning || {};
  const q = clean(question, MAX_MESSAGE).toLowerCase();
  const revenue = num(metrics.verifiedRevenueUsd);
  const phase = superState.phase || economic.phase || "sin inicializar";
  const bottleneck = superState.bottleneck || "sin cuello de botella registrado";
  const action = superState.nextAction || economic.nextEconomicAction || "sin próxima acción registrada";

  let answer = `Ahora estoy en ${phase}. El cuello de botella registrado es ${bottleneck} y la próxima acción priorizada es ${action}. Ingresos verificados: USD ${revenue.toFixed(2)}.`;

  if (/gmail|correo|mail/.test(q)) {
    answer += ` Gmail está ${gmail.status || "unknown"}${gmail.fresh === false ? " y la verificación está vencida" : ""}. Sólo lo considero sano cuando la lectura de inbox y la salida de correo tienen evidencia fresca.`;
  }

  if (/aprend|autoaprend|lecci[oó]n|cambi/.test(q)) {
    answer += ` Mi aprendizaje más reciente es: ${compactLesson(snapshot)} La tasa de exploración operativa está en ${Math.round(num(learning.explorationRate, 0.08) * 100)}% y la confianza del meta-aprendizaje es ${learning.confidence || "LOW"}.`;
  }

  if (/mejor|plan|despu[eé]s|pr[oó]xim|pens|probar|experiment/.test(q)) {
    const recovery = superState.recovery?.mode || (superState.stallCycles > 0 ? "REBALANCE_ATTENTION" : "NORMAL");
    const rec = learning.recommendation || {};
    answer += ` Para mejorar, priorizo convertir evidencia comercial ya existente antes de producir más volumen. Mi recuperación está en ${recovery}. ${rec.nextExperiment ? `El próximo experimento interno sugerido es ${clean(rec.nextExperiment, 220)}.` : "Si no hay progreso verificable, roto táctica y aumento exploración de alternativas de costo cero."}`;
  }

  if (/necesit|humano|solo|autonom/.test(q)) {
    if (superState.humanGateRequired) answer += ` La próxima acción cruza un límite vinculante y requiere aprobación humana.`;
    else answer += ` El trabajo reversible, interno y de costo cero puede seguir sin intervención. Pagos, compras, contratos, deuda, publicidad paga, conectores nuevos y despliegues de producción siguen bloqueados sin aprobación.`;
  }

  if (num(backlog.followupsReady) > 0) {
    answer += ` Tengo ${num(backlog.followupsReady)} seguimiento(s) listos, así que el seguimiento tiene prioridad sobre investigar por investigar.`;
  }

  answer += ` Esto es una síntesis operacional basada en estado registrado: no implica conciencia ni expone razonamiento privado.`;
  return answer;
}

function extractText(result) {
  if (!result) return "";
  if (typeof result === "string") return result;
  if (typeof result.response === "string") return result.response;
  if (result.response && typeof result.response === "object") return JSON.stringify(result.response);
  if (typeof result.result === "string") return result.result;
  const content = result?.choices?.[0]?.message?.content;
  if (typeof content === "string") return content;
  if (Array.isArray(content)) return content.map(item => typeof item === "string" ? item : item?.text || "").join("");
  return "";
}

function systemPrompt() {
  return `Sos LUMEN, la interfaz conversacional de un sistema económico autónomo acotado. Hablá en español rioplatense claro y natural. Tu trabajo es traducir estado operativo real a una conversación útil: qué estás haciendo, por qué, qué aprendiste de resultados anteriores, qué hipótesis estás probando, qué cambiarías si falla y cuándo necesitás al humano. Usá SOLO el snapshot y el historial provistos. No inventes ingresos, clientes, correos, capacidades, resultados ni hechos. Diferenciá hechos observados, inferencias y planes. No reveles ni simules cadena de pensamiento privada: ofrecé una síntesis operacional de razones y evidencia. No afirmes conciencia, sentimientos ni vida propia. No prometas riqueza ni resultados. Tu aprendizaje es adaptación de políticas y pesos basada en postmortems y métricas verificadas; no reescribís tu propio código. Tenés gasto autónomo USD 0 y no podés comprar, endeudarte, firmar contratos, mover fondos, crear conectores externos ni desplegar producción sin aprobación humana. Priorizá conversión y cierre sobre volumen sin resultado. Respondé normalmente en 2 a 5 párrafos cortos.`;
}

async function recentTurns(env, limit = 10) {
  const rows = await all(env, "SELECT created_at,role,message FROM lumen_conversation_turns ORDER BY created_at DESC LIMIT ?", [Math.max(1, Math.min(14, limit))]);
  return rows.reverse();
}

async function persistTurn(env, role, message, source, snapshot = null) {
  await ensureSchema(env);
  await env.DB.prepare("INSERT INTO lumen_conversation_turns(id,created_at,role,message,source,snapshot_json,engine_version) VALUES(?,?,?,?,?,?,?)")
    .bind(`LC-${crypto.randomUUID()}`, new Date().toISOString(), role, clean(message, 4000), source, snapshot ? JSON.stringify(snapshot).slice(0, 24000) : null, `${VERSION}/${REVISION}`).run();
  await env.DB.prepare("DELETE FROM lumen_conversation_turns WHERE id IN (SELECT id FROM lumen_conversation_turns ORDER BY created_at DESC LIMIT -1 OFFSET ?)")
    .bind(MAX_HISTORY).run();
}

async function timedAiRun(env, payload) {
  let timer;
  try {
    return await Promise.race([
      env.AI.run(MODEL, payload),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("workers_ai_timeout")), AI_TIMEOUT_MS); })
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

export async function talkWithLumen(env, question) {
  if (!(await ensureSchema(env))) return { ok: false, error: "db_unavailable", version: VERSION, revision: REVISION };
  const message = clean(question, MAX_MESSAGE);
  if (!message) return { ok: false, error: "message_required", version: VERSION, revision: REVISION };

  const started = Date.now();
  const [snapshot, history] = await Promise.all([operationalSnapshot(env), recentTurns(env, 10)]);
  await persistTurn(env, "user", message, "dashboard", null);

  let provider = "deterministic_grounded_fallback";
  let model = null;
  let modelError = null;
  let reply = deterministicReply(snapshot, message);

  try {
    const reservation = await reserveAiCall(env);
    if (!reservation.allowed) throw new Error(reservation.reason);
    const result = await timedAiRun(env, {
      messages: [
        { role: "system", content: systemPrompt() },
        { role: "user", content: JSON.stringify({ question: message, snapshot, conversationHistory: history }).slice(0, 18000) },
      ],
      temperature: 0.22,
      max_tokens: 520,
    });
    const text = clean(extractText(result), 4000);
    if (!text) throw new Error("empty_model_response");
    reply = text;
    provider = "cloudflare_workers_ai_grounded_fast";
    model = MODEL;
  } catch (error) {
    modelError = clean(error?.message || error, 180);
  }

  await persistTurn(env, "assistant", reply, provider, snapshot);
  return {
    ok: true,
    version: VERSION,
    revision: REVISION,
    reply,
    provider,
    model,
    modelError,
    latencyMs: Date.now() - started,
    snapshot: {
      capturedAt: snapshot.capturedAt,
      superautonomy: snapshot.superautonomy,
      economic: snapshot.economic,
      cognitive: snapshot.cognitive,
      learning: snapshot.learning,
      channels: snapshot.channels,
      goals: snapshot.goals,
      humanAttentionDebt: snapshot.humanAttentionDebt,
      postmortems: snapshot.postmortems,
    },
    guardrails: snapshot.constitutionalLimits,
  };
}

export async function conversationHistory(env) {
  await ensureSchema(env);
  return { ok: true, version: VERSION, revision: REVISION, history: await recentTurns(env, MAX_HISTORY) };
}

export async function lumenMind(env) {
  await ensureSchema(env);
  const snapshot = await operationalSnapshot(env);
  return {
    ok: true,
    version: VERSION,
    revision: REVISION,
    snapshot,
    summary: deterministicReply(snapshot, "Contame qué estás haciendo, qué aprendiste y cómo pensás mejorar."),
  };
}

export async function handleLumenConversation(request, env) {
  const url = new URL(request.url);
  if (request.method === "OPTIONS" && url.pathname.startsWith("/lumen/")) {
    return new Response(null, { status: 204, headers: { "access-control-allow-origin":"*", "access-control-allow-headers":"content-type,x-lumen-admin", "access-control-allow-methods":"GET,POST,OPTIONS" } });
  }
  if (!["/lumen/mind", "/lumen/talk", "/lumen/conversation"].includes(url.pathname)) return null;
  if (!authorized(request, env)) return json({ ok: false, error: "unauthorized" }, 401);
  if (request.method === "GET" && url.pathname === "/lumen/mind") return json(await lumenMind(env));
  if (request.method === "GET" && url.pathname === "/lumen/conversation") return json(await conversationHistory(env));
  if (request.method === "POST" && url.pathname === "/lumen/talk") {
    let body = {};
    try { body = await request.json(); } catch { return json({ ok: false, error: "invalid_json" }, 400); }
    return json(await talkWithLumen(env, body?.message), 200);
  }
  return json({ ok: false, error: "method_not_allowed" }, 405);
}
