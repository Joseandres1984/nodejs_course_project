const VERSION = "1.0-self-learning-engine";
const MIN_SCORE = 0.35;
const MAX_SCORE = 1.75;
const BASE_LEARNING_RATE = 0.06;

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
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_self_learning_state (id TEXT PRIMARY KEY,updated_at TEXT NOT NULL,cycle INTEGER NOT NULL DEFAULT 0,context_key TEXT,exploration_rate REAL NOT NULL DEFAULT 0.08,confidence TEXT NOT NULL DEFAULT 'LOW',recommendation_json TEXT NOT NULL DEFAULT '{}',engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_self_learning_events (event_id TEXT PRIMARY KEY,created_at TEXT NOT NULL,postmortem_id TEXT NOT NULL UNIQUE,action_key TEXT NOT NULL,context_key TEXT,outcome TEXT NOT NULL,delta REAL NOT NULL DEFAULT 0,signal_strength REAL NOT NULL DEFAULT 0,score_before REAL NOT NULL DEFAULT 1,score_after REAL NOT NULL DEFAULT 1,hypothesis TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_self_learning_events_created ON lumen_self_learning_events(created_at DESC)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_self_learning_events_action ON lumen_self_learning_events(action_key,created_at DESC)")
  ]);
  return true;
}

function confidenceWeight(confidence) {
  const value = String(confidence || "").toUpperCase();
  if (value === "HIGH") return 1;
  if (value === "MEDIUM") return 0.72;
  return 0.35;
}

function outcomeSignal(row) {
  const outcome = String(row?.outcome || "").toUpperCase();
  const delta = num(row?.delta);
  const direction = outcome.includes("PROGRESS") || delta > 0 ? 1 : -1;
  const magnitude = Math.min(1, 0.45 + Math.abs(delta) * 0.15);
  return direction * magnitude * confidenceWeight(row?.confidence);
}

function explorationRate(stallCycles) {
  const stalls = num(stallCycles);
  if (stalls >= 10) return 0.28;
  if (stalls >= 6) return 0.24;
  if (stalls >= 3) return 0.20;
  if (stalls >= 1) return 0.14;
  return 0.08;
}

function confidenceLabel(processed, evidenceRows) {
  if (processed >= 4 && evidenceRows >= 8) return "MEDIUM";
  if (processed >= 2 && evidenceRows >= 4) return "LOW_MEDIUM";
  return "LOW";
}

async function applyPostmortem(env, row, contextKey) {
  if (!row?.postmortem_id || !row?.action_key) return null;
  const seen = await first(env, "SELECT event_id FROM lumen_self_learning_events WHERE postmortem_id=? LIMIT 1", [row.postmortem_id]);
  if (seen) return null;

  const memory = await first(env, "SELECT action_key,score,attempts,wins,stalls FROM lumen_superautonomy_action_memory WHERE action_key=? LIMIT 1", [row.action_key]);
  const before = clamp(memory?.score || 1, MIN_SCORE, MAX_SCORE);
  const signal = outcomeSignal(row);
  const learningRate = BASE_LEARNING_RATE * (1 / Math.sqrt(Math.max(1, num(memory?.attempts, 1))));
  const after = clamp(before + signal * learningRate, MIN_SCORE, MAX_SCORE);

  if (memory) {
    await env.DB.prepare("UPDATE lumen_superautonomy_action_memory SET score=?,updated_at=?,engine_version=engine_version WHERE action_key=?")
      .bind(after, now(), row.action_key).run();
  }

  const positive = signal > 0;
  const hypothesis = positive
    ? `La táctica ${clean(row.action_key, 120)} merece algo más de preferencia porque el último postmortem mostró progreso verificable. Mantengo la atribución como observacional hasta repetir el resultado.`
    : `La táctica ${clean(row.action_key, 120)} pierde algo de preferencia porque el último postmortem no mostró progreso verificable. Conviene rotar o comparar con una alternativa antes de insistir.`;

  const eventId = `SL-${crypto.randomUUID()}`;
  await env.DB.prepare("INSERT INTO lumen_self_learning_events(event_id,created_at,postmortem_id,action_key,context_key,outcome,delta,signal_strength,score_before,score_after,hypothesis,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)")
    .bind(eventId, now(), row.postmortem_id, clean(row.action_key, 160), contextKey, clean(row.outcome, 80), num(row.delta), signal, before, after, hypothesis, VERSION).run();

  return { eventId, actionKey: row.action_key, signal, scoreBefore: before, scoreAfter: after, hypothesis };
}

function chooseExperiment(memoryRows, stallCycles, currentAction) {
  const rows = (memoryRows || []).map(row => ({
    actionKey: row.action_key,
    attempts: num(row.attempts),
    wins: num(row.wins),
    stalls: num(row.stalls),
    score: clamp(row.score || 1, MIN_SCORE, MAX_SCORE),
    lastOutcome: row.last_outcome || null,
  }));
  if (!rows.length) return null;

  const alternatives = rows
    .filter(row => row.actionKey && row.actionKey !== currentAction)
    .sort((a, b) => a.attempts - b.attempts || b.score - a.score || a.actionKey.localeCompare(b.actionKey));

  if (num(stallCycles) >= 3 && alternatives[0]) {
    return `comparar ${alternatives[0].actionKey} contra la táctica actual con una ejecución reversible y medir el mismo indicador antes de volver a insistir`;
  }

  const best = [...rows].sort((a, b) => b.score - a.score || b.wins - a.wins || a.attempts - b.attempts)[0];
  return best ? `repetir ${best.actionKey} sólo si el contexto es comparable y verificar si vuelve a producir progreso antes de subir más su preferencia` : null;
}

export async function runSelfLearningCycle(env, { trigger = "scheduled" } = {}) {
  if (!(await ensureSchema(env))) return { ok:false, error:"db_unavailable", version:VERSION };

  const [stateRow, postmortems, memoryRows, evidenceRows] = await Promise.all([
    first(env, "SELECT cycle,phase,bottleneck,next_action,stall_cycles,state_json FROM lumen_superautonomy_state WHERE id='GLOBAL' LIMIT 1"),
    all(env, "SELECT postmortem_id,created_at,cycle,outcome,action_key,target_metric,delta,observation,lesson,promotion,confidence FROM lumen_superautonomy_postmortems ORDER BY cycle DESC,created_at DESC LIMIT 10"),
    all(env, "SELECT action_key,attempts,wins,stalls,score,last_outcome,last_metric,last_delta,updated_at FROM lumen_superautonomy_action_memory ORDER BY updated_at DESC LIMIT 30"),
    all(env, "SELECT event_id FROM lumen_self_learning_events ORDER BY created_at DESC LIMIT 100")
  ]);

  const cycle = num(stateRow?.cycle);
  const contextKey = `${clean(stateRow?.phase || "UNKNOWN", 60)}:${clean(stateRow?.bottleneck || "unknown", 100)}`;
  const processed = [];
  for (const row of [...postmortems].reverse()) {
    const event = await applyPostmortem(env, row, contextKey);
    if (event) processed.push(event);
  }

  const refreshedMemory = await all(env, "SELECT action_key,attempts,wins,stalls,score,last_outcome,last_metric,last_delta,updated_at FROM lumen_superautonomy_action_memory ORDER BY score DESC,updated_at DESC LIMIT 30");
  const rate = explorationRate(stateRow?.stall_cycles);
  const nextExperiment = chooseExperiment(refreshedMemory, stateRow?.stall_cycles, clean(stateRow?.next_action, 160));
  const strongest = refreshedMemory[0] || null;
  const weakest = [...refreshedMemory].sort((a,b) => num(a.score) - num(b.score))[0] || null;
  const lastLearning = processed.at(-1) || null;
  const confidence = confidenceLabel(processed.length, evidenceRows.length + processed.length);

  const recommendation = {
    nextExperiment,
    strongestKnownTactic: strongest ? { actionKey: strongest.action_key, score: num(strongest.score), attempts: num(strongest.attempts), wins: num(strongest.wins) } : null,
    weakestKnownTactic: weakest ? { actionKey: weakest.action_key, score: num(weakest.score), attempts: num(weakest.attempts), stalls: num(weakest.stalls) } : null,
    latestHypothesis: lastLearning?.hypothesis || null,
    trigger,
    rules: {
      verifiedProgressRequiredForPromotion: true,
      observationalAttributionOnly: true,
      selfModifyingCode: false,
      reversibleInternalAdaptationOnly: true,
      autonomousSpendUsd: 0,
      bindingActionsHumanGated: true,
    }
  };

  await env.DB.prepare("INSERT INTO lumen_self_learning_state(id,updated_at,cycle,context_key,exploration_rate,confidence,recommendation_json,engine_version) VALUES('GLOBAL',?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,cycle=excluded.cycle,context_key=excluded.context_key,exploration_rate=excluded.exploration_rate,confidence=excluded.confidence,recommendation_json=excluded.recommendation_json,engine_version=excluded.engine_version")
    .bind(now(), cycle, contextKey, rate, confidence, JSON.stringify(recommendation), VERSION).run();

  return {
    ok:true,
    version:VERSION,
    cycle,
    contextKey,
    processedPostmortems:processed.length,
    explorationRate:rate,
    confidence,
    recommendation,
    guardrails:recommendation.rules,
  };
}

export async function selfLearningStatus(env) {
  await ensureSchema(env);
  const [state, events] = await Promise.all([
    first(env, "SELECT id,updated_at,cycle,context_key,exploration_rate,confidence,recommendation_json,engine_version FROM lumen_self_learning_state WHERE id='GLOBAL' LIMIT 1"),
    all(env, "SELECT event_id,created_at,postmortem_id,action_key,context_key,outcome,delta,signal_strength,score_before,score_after,hypothesis FROM lumen_self_learning_events ORDER BY created_at DESC LIMIT 20")
  ]);
  return {
    ok:true,
    version:VERSION,
    state: state ? { ...state, recommendation: parse(state.recommendation_json, {}) } : null,
    events,
  };
}

export async function handleSelfLearning(request, env) {
  const url = new URL(request.url);
  if (request.method === "OPTIONS" && url.pathname.startsWith("/self-learning")) return new Response(null, { status:204, headers:{"access-control-allow-origin":"*","access-control-allow-headers":"content-type,x-lumen-admin","access-control-allow-methods":"GET,POST,OPTIONS"} });
  if (request.method === "GET" && url.pathname === "/self-learning/policy") return json({
    ok:true,
    version:VERSION,
    cycle:"observe_measure_postmortem_update_weights_choose_bounded_experiment_repeat",
    adaptation:"confidence_weighted_action_preference",
    exploration:"bounded_by_verified_stagnation",
    selfModifyingCode:false,
    autonomousSpendUsd:0,
    createsExternalMessages:false,
    bindingActionsHumanGated:true,
    verifiedProgressRequiredForPromotion:true,
    attribution:"observational_until_repeated_evidence",
  });
  if (request.method === "GET" && url.pathname === "/self-learning/status") {
    if (!authorized(request, env)) return json({ok:false,error:"unauthorized"},401);
    return json(await selfLearningStatus(env));
  }
  if (request.method === "POST" && url.pathname === "/self-learning/run") {
    if (!authorized(request, env)) return json({ok:false,error:"unauthorized"},401);
    return json(await runSelfLearningCycle(env,{trigger:"admin_run"}),202);
  }
  return null;
}
