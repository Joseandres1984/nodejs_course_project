const VERSION = "1.0-context-meta-controller";
const MIN_SCORE = 0.35;
const MAX_SCORE = 1.75;
const CONTEXT_LEARNING_RATE = 0.09;
const CONTEXT_BLEND = 0.22;
const MAX_SCORE_NUDGE = 0.08;

function num(value, fallback = 0) { const n = Number(value); return Number.isFinite(n) ? n : fallback; }
function clean(value, limit = 320) { return String(value ?? "").replace(/[\r\n\t]+/g, " ").replace(/\s+/g, " ").trim().slice(0, limit); }
function clamp(value, min, max) { return Math.max(min, Math.min(max, num(value))); }
function parse(value, fallback = {}) { try { return JSON.parse(String(value || "")); } catch { return fallback; } }
function now() { return new Date().toISOString(); }
function json(data, status = 200) { return Response.json(data, { status, headers: { "cache-control":"no-store", "x-content-type-options":"nosniff", "access-control-allow-origin":"*", "access-control-allow-headers":"content-type,x-lumen-admin", "access-control-allow-methods":"GET,POST,OPTIONS" } }); }
function authorized(request, env) { const expected = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500), supplied = clean(request.headers.get("x-lumen-admin"), 500); return Boolean(expected && supplied && expected === supplied); }

async function first(env, sql, bind = []) {
  try { const q = env.DB.prepare(sql); return bind.length ? await q.bind(...bind).first() : await q.first(); }
  catch { return null; }
}
async function all(env, sql, bind = []) {
  try { const q = env.DB.prepare(sql), result = bind.length ? await q.bind(...bind).all() : await q.all(); return result.results || []; }
  catch { return []; }
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_meta_controller_state (id TEXT PRIMARY KEY,updated_at TEXT NOT NULL,cycle INTEGER NOT NULL DEFAULT 0,context_key TEXT,mode TEXT NOT NULL,preferred_action TEXT,challenger_action TEXT,confidence TEXT NOT NULL DEFAULT 'LOW',recommendation_json TEXT NOT NULL DEFAULT '{}',engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_meta_context_memory (context_key TEXT NOT NULL,action_key TEXT NOT NULL,updated_at TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,wins INTEGER NOT NULL DEFAULT 0,stalls INTEGER NOT NULL DEFAULT 0,score REAL NOT NULL DEFAULT 1,last_outcome TEXT,last_delta REAL NOT NULL DEFAULT 0,last_event_id TEXT,engine_version TEXT NOT NULL,PRIMARY KEY(context_key,action_key))"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_meta_context_score ON lumen_meta_context_memory(context_key,score DESC,updated_at DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_meta_ingested_events (event_id TEXT PRIMARY KEY,ingested_at TEXT NOT NULL,engine_version TEXT NOT NULL)")
  ]);
  return true;
}

function contextConfidence(rows = []) {
  const attempts = rows.reduce((sum, row) => sum + num(row.attempts), 0);
  const actions = rows.filter(row => num(row.attempts) > 0).length;
  if (attempts >= 10 && actions >= 2) return "MEDIUM_HIGH";
  if (attempts >= 6 && actions >= 2) return "MEDIUM";
  if (attempts >= 3) return "LOW_MEDIUM";
  return "LOW";
}

async function ingestLearningEvents(env) {
  const rows = await all(env, "SELECT event_id,created_at,action_key,context_key,outcome,delta,signal_strength FROM lumen_self_learning_events ORDER BY created_at ASC LIMIT 200");
  const ingested = [];
  for (const row of rows) {
    const eventId = clean(row.event_id, 180);
    const contextKey = clean(row.context_key, 180);
    const actionKey = clean(row.action_key, 160);
    if (!eventId || !contextKey || !actionKey) continue;
    const seen = await first(env, "SELECT event_id FROM lumen_meta_ingested_events WHERE event_id=? LIMIT 1", [eventId]);
    if (seen) continue;

    const current = await first(env, "SELECT attempts,wins,stalls,score FROM lumen_meta_context_memory WHERE context_key=? AND action_key=? LIMIT 1", [contextKey, actionKey]);
    const attemptsBefore = num(current?.attempts);
    const scoreBefore = clamp(current?.score || 1, MIN_SCORE, MAX_SCORE);
    const signal = clamp(row.signal_strength, -1, 1);
    const learningRate = CONTEXT_LEARNING_RATE / Math.sqrt(Math.max(1, attemptsBefore + 1));
    const scoreAfter = clamp(scoreBefore + signal * learningRate, MIN_SCORE, MAX_SCORE);
    const win = signal > 0 ? 1 : 0;
    const stall = signal <= 0 ? 1 : 0;

    await env.DB.prepare("INSERT INTO lumen_meta_context_memory(context_key,action_key,updated_at,attempts,wins,stalls,score,last_outcome,last_delta,last_event_id,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(context_key,action_key) DO UPDATE SET updated_at=excluded.updated_at,attempts=lumen_meta_context_memory.attempts+1,wins=lumen_meta_context_memory.wins+excluded.wins,stalls=lumen_meta_context_memory.stalls+excluded.stalls,score=excluded.score,last_outcome=excluded.last_outcome,last_delta=excluded.last_delta,last_event_id=excluded.last_event_id,engine_version=excluded.engine_version")
      .bind(contextKey, actionKey, now(), 1, win, stall, scoreAfter, clean(row.outcome, 80), num(row.delta), eventId, VERSION).run();
    await env.DB.prepare("INSERT INTO lumen_meta_ingested_events(event_id,ingested_at,engine_version) VALUES(?,?,?)")
      .bind(eventId, now(), VERSION).run();
    ingested.push({ eventId, contextKey, actionKey, signal, scoreBefore, scoreAfter });
  }
  return ingested;
}

async function currentOperationalContext(env) {
  const row = await first(env, "SELECT cycle,phase,bottleneck,next_action,target_metric,stall_cycles,state_json FROM lumen_superautonomy_state WHERE id='GLOBAL' LIMIT 1");
  if (!row) return { cycle:0, phase:"UNKNOWN", bottleneck:"unknown", contextKey:"UNKNOWN:unknown", selectedTactic:null, targetMetric:null, stallCycles:0 };
  const state = parse(row.state_json, {});
  const phase = clean(row.phase || "UNKNOWN", 60);
  const bottleneck = clean(row.bottleneck || "unknown", 100);
  return {
    cycle: num(row.cycle),
    phase,
    bottleneck,
    contextKey: `${phase}:${bottleneck}`,
    selectedTactic: clean(state?.selectedTactic || row.next_action || "", 160) || null,
    targetMetric: clean(row.target_metric, 120) || null,
    stallCycles: num(row.stall_cycles),
  };
}

async function rankContext(env, contextKey) {
  const [contextRows, globalRows] = await Promise.all([
    all(env, "SELECT context_key,action_key,attempts,wins,stalls,score,last_outcome,last_delta,updated_at FROM lumen_meta_context_memory WHERE context_key=? ORDER BY score DESC,updated_at DESC LIMIT 30", [contextKey]),
    all(env, "SELECT action_key,attempts,wins,stalls,score,last_outcome,last_delta,updated_at FROM lumen_superautonomy_action_memory ORDER BY score DESC,updated_at DESC LIMIT 50")
  ]);
  const global = new Map(globalRows.map(row => [String(row.action_key), row]));
  const ranked = contextRows.map(row => {
    const g = global.get(String(row.action_key));
    const contextScore = clamp(row.score || 1, MIN_SCORE, MAX_SCORE);
    const globalScore = clamp(g?.score || 1, MIN_SCORE, MAX_SCORE);
    const evidence = num(row.attempts);
    const evidenceWeight = Math.min(0.82, 0.45 + Math.log1p(evidence) * 0.16);
    const blendedScore = clamp(contextScore * evidenceWeight + globalScore * (1 - evidenceWeight), MIN_SCORE, MAX_SCORE);
    return {
      actionKey: row.action_key,
      contextScore,
      globalScore,
      blendedScore,
      attempts: evidence,
      wins: num(row.wins),
      stalls: num(row.stalls),
      lastOutcome: row.last_outcome || null,
      lastDelta: num(row.last_delta),
    };
  }).sort((a, b) => b.blendedScore - a.blendedScore || b.wins - a.wins || a.stalls - b.stalls || a.actionKey.localeCompare(b.actionKey));
  return { ranked, global };
}

function falsificationRule(context, preferred) {
  if (!preferred) return "Todavía no hay evidencia contextual suficiente. La primera evidencia comparable debe poder cambiar la preferencia.";
  if (preferred.attempts < 2) return `La preferencia por ${preferred.actionKey} es provisional: si una repetición comparable no mejora ${context.targetMetric || "la métrica objetivo"}, debe bajar su peso.`;
  if (context.stallCycles >= 3) return `La hipótesis actual está bajo presión: si ${context.targetMetric || "la métrica objetivo"} vuelve a quedar sin progreso en el próximo ciclo comparable, rotar al challenger y reducir confianza.`;
  return `Cambiar de opinión si ${preferred.actionKey} acumula dos resultados comparables sin progreso o si el challenger supera su score contextual con evidencia repetida.`;
}

async function applyContextNudge(env, ranked = []) {
  const nudges = [];
  for (const row of ranked.slice(0, 4)) {
    const global = await first(env, "SELECT action_key,score FROM lumen_superautonomy_action_memory WHERE action_key=? LIMIT 1", [row.actionKey]);
    if (!global) continue;
    const before = clamp(global.score || 1, MIN_SCORE, MAX_SCORE);
    const target = clamp(before * (1 - CONTEXT_BLEND) + row.contextScore * CONTEXT_BLEND, MIN_SCORE, MAX_SCORE);
    const delta = clamp(target - before, -MAX_SCORE_NUDGE, MAX_SCORE_NUDGE);
    if (Math.abs(delta) < 0.0001) continue;
    const after = clamp(before + delta, MIN_SCORE, MAX_SCORE);
    await env.DB.prepare("UPDATE lumen_superautonomy_action_memory SET score=?,updated_at=? WHERE action_key=?")
      .bind(after, now(), row.actionKey).run();
    nudges.push({ actionKey: row.actionKey, before, after, delta });
  }
  return nudges;
}

export async function runMetaControllerCycle(env, { trigger = "scheduled", applyNudge = true } = {}) {
  if (!(await ensureSchema(env))) return { ok:false, error:"db_unavailable", version:VERSION };
  const ingested = await ingestLearningEvents(env);
  const context = await currentOperationalContext(env);
  const { ranked } = await rankContext(env, context.contextKey);
  const preferred = ranked[0] || null;
  const challenger = ranked[1] || null;
  const confidence = contextConfidence(ranked);
  const nudges = applyNudge ? await applyContextNudge(env, ranked) : [];
  const mode = ranked.length ? (context.stallCycles >= 3 ? "EXPLORE_CHALLENGER" : "CONTEXTUAL_EXPLOIT") : "LEARN_CONTEXT";
  const recommendation = {
    preferredAction: preferred?.actionKey || null,
    challengerAction: challenger?.actionKey || null,
    mode,
    reason: preferred ? `La preferencia combina evidencia del contexto ${context.contextKey} con memoria global y evita asumir que una táctica funciona igual en todas las fases.` : "Aún no existe evidencia suficiente en este contexto; mantener exploración y registrar resultados comparables.",
    whatWouldChangeMyMind: falsificationRule(context, preferred),
    evidence: preferred ? { attempts:preferred.attempts, wins:preferred.wins, stalls:preferred.stalls, contextScore:preferred.contextScore, globalScore:preferred.globalScore, blendedScore:preferred.blendedScore } : null,
    challengerEvidence: challenger ? { attempts:challenger.attempts, wins:challenger.wins, stalls:challenger.stalls, contextScore:challenger.contextScore, globalScore:challenger.globalScore, blendedScore:challenger.blendedScore } : null,
    trigger,
    guardrails: {
      contextAwareLearning:true,
      selfModifyingCode:false,
      autonomousSpendUsd:0,
      bindingActionsHumanGated:true,
      externalBindingActions:false,
      reversibleInternalPreferenceNudgesOnly:true,
      maxScoreNudgePerCycle:MAX_SCORE_NUDGE,
      falsificationRequired:true,
    }
  };

  await env.DB.prepare("INSERT INTO lumen_meta_controller_state(id,updated_at,cycle,context_key,mode,preferred_action,challenger_action,confidence,recommendation_json,engine_version) VALUES('GLOBAL',?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,cycle=excluded.cycle,context_key=excluded.context_key,mode=excluded.mode,preferred_action=excluded.preferred_action,challenger_action=excluded.challenger_action,confidence=excluded.confidence,recommendation_json=excluded.recommendation_json,engine_version=excluded.engine_version")
    .bind(now(), context.cycle, context.contextKey, mode, preferred?.actionKey || null, challenger?.actionKey || null, confidence, JSON.stringify(recommendation), VERSION).run();

  return {
    ok:true,
    version:VERSION,
    context,
    mode,
    confidence,
    ingestedLearningEvents:ingested.length,
    preferredAction:preferred?.actionKey || null,
    challengerAction:challenger?.actionKey || null,
    nudges,
    recommendation,
  };
}

export async function metaControllerStatus(env) {
  await ensureSchema(env);
  const [state, contexts] = await Promise.all([
    first(env, "SELECT id,updated_at,cycle,context_key,mode,preferred_action,challenger_action,confidence,recommendation_json,engine_version FROM lumen_meta_controller_state WHERE id='GLOBAL' LIMIT 1"),
    all(env, "SELECT context_key,action_key,attempts,wins,stalls,score,last_outcome,last_delta,updated_at FROM lumen_meta_context_memory ORDER BY updated_at DESC LIMIT 40")
  ]);
  return {
    ok:true,
    version:VERSION,
    state: state ? { ...state, recommendation: parse(state.recommendation_json, {}) } : null,
    contextMemory:contexts,
  };
}

export async function handleMetaController(request, env) {
  const url = new URL(request.url);
  if (request.method === "OPTIONS" && url.pathname.startsWith("/meta-controller")) return new Response(null, { status:204, headers:{"access-control-allow-origin":"*","access-control-allow-headers":"content-type,x-lumen-admin","access-control-allow-methods":"GET,POST,OPTIONS"} });
  if (request.method === "GET" && url.pathname === "/meta-controller/policy") return json({
    ok:true,
    version:VERSION,
    purpose:"learn_which_tactic_works_in_which_operational_context",
    cycle:"ingest_verified_learning_events_build_context_memory_rank_preferred_and_challenger_nudge_internal_preferences_measure_again",
    contextualBanditStyle:true,
    falsificationRequired:true,
    selfModifyingCode:false,
    autonomousSpendUsd:0,
    bindingActionsHumanGated:true,
    externalBindingActions:false,
    maxScoreNudgePerCycle:MAX_SCORE_NUDGE,
  });
  if (request.method === "GET" && url.pathname === "/meta-controller/status") {
    if (!authorized(request, env)) return json({ok:false,error:"unauthorized"},401);
    return json(await metaControllerStatus(env));
  }
  if (request.method === "POST" && url.pathname === "/meta-controller/run") {
    if (!authorized(request, env)) return json({ok:false,error:"unauthorized"},401);
    return json(await runMetaControllerCycle(env,{trigger:"admin_run",applyNudge:true}),202);
  }
  return null;
}
