const VERSION = "1.0-teacher-self-critic";
const MIN_SCORE = 0.35;
const MAX_SCORE = 1.75;
const MAX_TEACHER_NUDGE = 0.04;
const FEEDBACK_TYPES = new Set(["PRAISE","CORRECT","SUGGEST","PRINCIPLE","WARNING"]);

function num(v, fallback = 0) { const n = Number(v); return Number.isFinite(n) ? n : fallback; }
function clean(v, n = 500) { return String(v ?? "").replace(/[\r\n\t]+/g, " ").replace(/\s+/g, " ").trim().slice(0, n); }
function clamp(v, min, max) { return Math.max(min, Math.min(max, num(v))); }
function parse(v, fallback = {}) { try { return JSON.parse(String(v || "")); } catch { return fallback; } }
function now() { return new Date().toISOString(); }
function json(data, status = 200) { return Response.json(data, { status, headers: { "cache-control":"no-store", "x-content-type-options":"nosniff", "access-control-allow-origin":"*", "access-control-allow-headers":"content-type,x-lumen-admin", "access-control-allow-methods":"GET,POST,OPTIONS" } }); }
function authorized(request, env) { const expected = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500), supplied = clean(request.headers.get("x-lumen-admin"), 500); return Boolean(expected && supplied && expected === supplied); }

async function first(env, sql, bind = []) {
  try { const q = env.DB.prepare(sql); return bind.length ? await q.bind(...bind).first() : await q.first(); }
  catch { return null; }
}
async function all(env, sql, bind = []) {
  try { const q = env.DB.prepare(sql), r = bind.length ? await q.bind(...bind).all() : await q.all(); return r.results || []; }
  catch { return []; }
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_human_feedback (feedback_id TEXT PRIMARY KEY,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,feedback_type TEXT NOT NULL,context_key TEXT,target_action TEXT,message TEXT NOT NULL,rationale TEXT,status TEXT NOT NULL,evidence_required TEXT NOT NULL,applied_nudge REAL NOT NULL DEFAULT 0,source TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_human_feedback_status ON lumen_human_feedback(status,updated_at DESC)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_human_feedback_context ON lumen_human_feedback(context_key,updated_at DESC)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_self_critic_state (id TEXT PRIMARY KEY,updated_at TEXT NOT NULL,cycle INTEGER NOT NULL DEFAULT 0,context_key TEXT,verdict TEXT NOT NULL,severity TEXT NOT NULL,recommendation_json TEXT NOT NULL DEFAULT '{}',engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_self_critic_reviews (review_id TEXT PRIMARY KEY,created_at TEXT NOT NULL,cycle INTEGER NOT NULL DEFAULT 0,context_key TEXT,selected_action TEXT,challenger_action TEXT,verdict TEXT NOT NULL,severity TEXT NOT NULL,flags_json TEXT NOT NULL,recommendation_json TEXT NOT NULL,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_self_critic_reviews_created ON lumen_self_critic_reviews(created_at DESC)")
  ]);
  return true;
}

async function currentContext(env) {
  const [superRow, metaRow, learningRow] = await Promise.all([
    first(env, "SELECT cycle,phase,bottleneck,next_action,target_metric,stall_cycles,state_json FROM lumen_superautonomy_state WHERE id='GLOBAL' LIMIT 1"),
    first(env, "SELECT context_key,mode,preferred_action,challenger_action,confidence,recommendation_json FROM lumen_meta_controller_state WHERE id='GLOBAL' LIMIT 1"),
    first(env, "SELECT context_key,exploration_rate,confidence,recommendation_json FROM lumen_self_learning_state WHERE id='GLOBAL' LIMIT 1")
  ]);
  const state = parse(superRow?.state_json, {});
  const phase = clean(superRow?.phase || "UNKNOWN", 80);
  const bottleneck = clean(superRow?.bottleneck || "unknown", 120);
  return {
    cycle: num(superRow?.cycle),
    phase,
    bottleneck,
    contextKey: clean(metaRow?.context_key || learningRow?.context_key || `${phase}:${bottleneck}`, 220),
    selectedAction: clean(state?.selectedTactic || metaRow?.preferred_action || superRow?.next_action || "", 180) || null,
    challengerAction: clean(metaRow?.challenger_action || "", 180) || null,
    targetMetric: clean(superRow?.target_metric || "", 140) || null,
    stallCycles: num(superRow?.stall_cycles),
    metaConfidence: clean(metaRow?.confidence || "LOW", 40),
    metaRecommendation: parse(metaRow?.recommendation_json, {}),
    learningConfidence: clean(learningRow?.confidence || "LOW", 40),
    explorationRate: clamp(learningRow?.exploration_rate || 0.08, 0, 1),
    learningRecommendation: parse(learningRow?.recommendation_json, {})
  };
}

function evidenceRule(type, targetAction) {
  const action = targetAction || "la acción indicada";
  if (type === "PRAISE") return `Promover ${action} sólo si hay progreso verificable repetido en un contexto comparable.`;
  if (type === "CORRECT" || type === "WARNING") return `Reducir preferencia por ${action} sólo si postmortems o señales verificadas confirman estancamiento o retroceso.`;
  if (type === "SUGGEST") return `Tratar ${action} como challenger hasta observar al menos una comparación verificable.`;
  return "Tratar el principio humano como hipótesis; conservarlo sólo mientras no contradiga evidencia operativa verificable.";
}

export async function submitHumanFeedback(env, payload = {}, source = "admin") {
  if (!(await ensureSchema(env))) return { ok:false, error:"db_unavailable", version:VERSION };
  const context = await currentContext(env);
  const type = clean(payload.feedbackType || payload.type || "SUGGEST", 30).toUpperCase();
  if (!FEEDBACK_TYPES.has(type)) return { ok:false, error:"invalid_feedback_type", allowed:[...FEEDBACK_TYPES] };
  const message = clean(payload.message, 1200);
  if (!message) return { ok:false, error:"message_required" };
  const targetAction = clean(payload.targetAction || context.selectedAction || "", 180) || null;
  const contextKey = clean(payload.contextKey || context.contextKey, 220) || null;
  const rationale = clean(payload.rationale || "", 900) || null;
  const feedbackId = `HT-${crypto.randomUUID()}`;
  const evidenceRequired = evidenceRule(type, targetAction);
  await env.DB.prepare("INSERT INTO lumen_human_feedback(feedback_id,created_at,updated_at,feedback_type,context_key,target_action,message,rationale,status,evidence_required,applied_nudge,source,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)")
    .bind(feedbackId, now(), now(), type, contextKey, targetAction, message, rationale, "PROVISIONAL", evidenceRequired, 0, clean(source, 80), VERSION).run();
  return { ok:true, version:VERSION, feedbackId, status:"PROVISIONAL", feedbackType:type, contextKey, targetAction, message, evidenceRequired, policy:"human_feedback_is_hypothesis_not_ground_truth" };
}

async function evidenceFor(env, contextKey, actionKey) {
  if (!actionKey) return { count:0, signalSum:0, positive:0, negative:0, latest:null };
  const rows = await all(env, "SELECT created_at,outcome,delta,signal_strength,hypothesis FROM lumen_self_learning_events WHERE action_key=? AND (? IS NULL OR context_key=?) ORDER BY created_at DESC LIMIT 12", [actionKey, contextKey, contextKey]);
  const signalSum = rows.reduce((s, r) => s + clamp(r.signal_strength, -1, 1), 0);
  return {
    count: rows.length,
    signalSum,
    positive: rows.filter(r => num(r.signal_strength) > 0.2).length,
    negative: rows.filter(r => num(r.signal_strength) < -0.2).length,
    latest: rows[0] || null
  };
}

function classifyFeedback(feedback, evidence) {
  const type = feedback.feedback_type;
  const positive = evidence.positive >= 2 || evidence.signalSum >= 0.9;
  const negative = evidence.negative >= 2 || evidence.signalSum <= -0.9;
  if (type === "PRAISE") return positive ? "SUPPORTED" : negative ? "CONTRADICTED" : "PROVISIONAL";
  if (type === "CORRECT" || type === "WARNING") return negative ? "SUPPORTED" : positive ? "CONTRADICTED" : "PROVISIONAL";
  if (type === "SUGGEST") return positive ? "SUPPORTED" : negative ? "CONTRADICTED" : "PROVISIONAL";
  return evidence.count >= 2 ? "EVIDENCE_CHECKED" : "PROVISIONAL";
}

async function reconcileHumanFeedback(env) {
  const rows = await all(env, "SELECT * FROM lumen_human_feedback WHERE status IN ('PROVISIONAL','EVIDENCE_CHECKED') ORDER BY created_at ASC LIMIT 40");
  const results = [];
  for (const row of rows) {
    const evidence = await evidenceFor(env, row.context_key, row.target_action);
    const status = classifyFeedback(row, evidence);
    let appliedNudge = num(row.applied_nudge);
    if (status === "SUPPORTED" && row.target_action && Math.abs(appliedNudge) < 0.0001) {
      const mem = await first(env, "SELECT score FROM lumen_superautonomy_action_memory WHERE action_key=? LIMIT 1", [row.target_action]);
      if (mem) {
        const direction = (row.feedback_type === "CORRECT" || row.feedback_type === "WARNING") ? -1 : 1;
        const delta = direction * MAX_TEACHER_NUDGE;
        const before = clamp(mem.score || 1, MIN_SCORE, MAX_SCORE);
        const after = clamp(before + delta, MIN_SCORE, MAX_SCORE);
        await env.DB.prepare("UPDATE lumen_superautonomy_action_memory SET score=?,updated_at=? WHERE action_key=?")
          .bind(after, now(), row.target_action).run();
        appliedNudge = after - before;
      }
    }
    await env.DB.prepare("UPDATE lumen_human_feedback SET updated_at=?,status=?,applied_nudge=? WHERE feedback_id=?")
      .bind(now(), status, appliedNudge, row.feedback_id).run();
    results.push({ feedbackId:row.feedback_id, status, targetAction:row.target_action, evidence, appliedNudge });
  }
  return results;
}

function criticFlags(context, selectedEvidence, challengerEvidence, feedbackRows) {
  const flags = [];
  if (!context.selectedAction) flags.push({ code:"NO_SELECTED_ACTION", severity:"MEDIUM", reason:"No hay una táctica seleccionada para criticar." });
  if (context.stallCycles >= 3) flags.push({ code:"REPEATED_STALL", severity:"HIGH", reason:`La métrica objetivo acumula ${context.stallCycles} ciclos sin progreso comparable.` });
  else if (context.stallCycles >= 1) flags.push({ code:"EARLY_STALL", severity:"LOW", reason:"Hay estancamiento temprano; conviene mantener un challenger listo." });
  if (selectedEvidence.negative >= 2) flags.push({ code:"REPEATED_NEGATIVE_EVIDENCE", severity:"HIGH", reason:"La táctica elegida acumula evidencia negativa repetida." });
  if (context.challengerAction && challengerEvidence.signalSum > selectedEvidence.signalSum + 0.5) flags.push({ code:"CHALLENGER_STRONGER", severity:"MEDIUM", reason:"El challenger tiene mejor señal observada que la táctica preferida." });
  const contraryHuman = feedbackRows.find(row => ["CORRECT","WARNING"].includes(row.feedback_type) && row.target_action === context.selectedAction && row.status !== "CONTRADICTED");
  if (contraryHuman) flags.push({ code:"HUMAN_CHALLENGE_PENDING", severity:"MEDIUM", reason:"Existe una corrección humana pendiente de contrastar con evidencia." });
  if (context.metaConfidence === "LOW" || context.learningConfidence === "LOW") flags.push({ code:"LOW_CONFIDENCE", severity:"LOW", reason:"La evidencia todavía es insuficiente para una preferencia fuerte." });
  return flags;
}

function chooseVerdict(context, flags, selectedEvidence, challengerEvidence) {
  const high = flags.some(f => f.severity === "HIGH");
  const challengerStronger = flags.some(f => f.code === "CHALLENGER_STRONGER");
  if (high && context.challengerAction) return "ROTATE_TO_CHALLENGER";
  if (high) return "CHALLENGE_CURRENT_ASSUMPTION";
  if (challengerStronger) return "RUN_COMPARATIVE_TEST";
  if (context.stallCycles >= 1) return "CONTINUE_WITH_FALSIFICATION_TEST";
  if (selectedEvidence.count < 2) return "CONTINUE_AND_GATHER_EVIDENCE";
  return "CONTINUE_CURRENT_TACTIC";
}

function severityFrom(flags) {
  if (flags.some(f => f.severity === "HIGH")) return "HIGH";
  if (flags.some(f => f.severity === "MEDIUM")) return "MEDIUM";
  return flags.length ? "LOW" : "INFO";
}

export async function runSelfCriticCycle(env, { trigger = "scheduled" } = {}) {
  if (!(await ensureSchema(env))) return { ok:false, error:"db_unavailable", version:VERSION };
  const reconciled = await reconcileHumanFeedback(env);
  const context = await currentContext(env);
  const [selectedEvidence, challengerEvidence, feedbackRows] = await Promise.all([
    evidenceFor(env, context.contextKey, context.selectedAction),
    evidenceFor(env, context.contextKey, context.challengerAction),
    all(env, "SELECT feedback_id,feedback_type,context_key,target_action,message,status,evidence_required,applied_nudge,updated_at FROM lumen_human_feedback WHERE (? IS NULL OR context_key=?) ORDER BY updated_at DESC LIMIT 20", [context.contextKey, context.contextKey])
  ]);
  const flags = criticFlags(context, selectedEvidence, challengerEvidence, feedbackRows);
  const verdict = chooseVerdict(context, flags, selectedEvidence, challengerEvidence);
  const severity = severityFrom(flags);
  const recommendation = {
    trigger,
    verdict,
    selectedAction:context.selectedAction,
    challengerAction:context.challengerAction,
    targetMetric:context.targetMetric,
    reason: flags.length ? flags.map(f => f.reason).join(" ") : "No aparece evidencia suficiente para invalidar la táctica actual.",
    whatWouldChangeMyMind: context.metaRecommendation?.whatWouldChangeMyMind || `Cambiar la preferencia si ${context.selectedAction || "la táctica actual"} acumula dos resultados comparables sin progreso o si un challenger produce evidencia superior repetida.`,
    nextTest: verdict === "ROTATE_TO_CHALLENGER" ? `Probar ${context.challengerAction} de forma reversible y medir ${context.targetMetric || "la misma métrica"}.` : verdict === "RUN_COMPARATIVE_TEST" ? `Comparar ${context.selectedAction} contra ${context.challengerAction} con la misma métrica y contexto.` : `Mantener ${context.selectedAction || "la acción actual"} sólo mientras la evidencia no contradiga la hipótesis.`,
    selectedEvidence,
    challengerEvidence,
    humanFeedbackReviewed:feedbackRows.length,
    reconciledFeedback:reconciled,
    guardrails:{ humanAdviceIsNotGroundTruth:true, verifiedEvidenceOverridesAdvice:true, selfModifyingCode:false, autonomousSpendUsd:0, externalBindingActions:false, bindingActionsHumanGated:true, maxTeacherNudge:MAX_TEACHER_NUDGE }
  };
  const reviewId = `SC-${crypto.randomUUID()}`;
  await env.DB.prepare("INSERT INTO lumen_self_critic_reviews(review_id,created_at,cycle,context_key,selected_action,challenger_action,verdict,severity,flags_json,recommendation_json,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?)")
    .bind(reviewId, now(), context.cycle, context.contextKey, context.selectedAction, context.challengerAction, verdict, severity, JSON.stringify(flags), JSON.stringify(recommendation), VERSION).run();
  await env.DB.prepare("INSERT INTO lumen_self_critic_state(id,updated_at,cycle,context_key,verdict,severity,recommendation_json,engine_version) VALUES('GLOBAL',?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,cycle=excluded.cycle,context_key=excluded.context_key,verdict=excluded.verdict,severity=excluded.severity,recommendation_json=excluded.recommendation_json,engine_version=excluded.engine_version")
    .bind(now(), context.cycle, context.contextKey, verdict, severity, JSON.stringify(recommendation), VERSION).run();
  return { ok:true, version:VERSION, reviewId, context, verdict, severity, flags, recommendation };
}

export async function teacherCriticStatus(env) {
  await ensureSchema(env);
  const [critic, feedback, reviews] = await Promise.all([
    first(env, "SELECT * FROM lumen_self_critic_state WHERE id='GLOBAL' LIMIT 1"),
    all(env, "SELECT feedback_id,created_at,updated_at,feedback_type,context_key,target_action,message,rationale,status,evidence_required,applied_nudge,source FROM lumen_human_feedback ORDER BY updated_at DESC LIMIT 30"),
    all(env, "SELECT review_id,created_at,cycle,context_key,selected_action,challenger_action,verdict,severity,flags_json,recommendation_json FROM lumen_self_critic_reviews ORDER BY created_at DESC LIMIT 20")
  ]);
  return {
    ok:true,
    version:VERSION,
    critic: critic ? { ...critic, recommendation:parse(critic.recommendation_json,{}) } : null,
    humanFeedback:feedback,
    reviews:reviews.map(row => ({...row, flags:parse(row.flags_json,[]), recommendation:parse(row.recommendation_json,{})}))
  };
}

export async function handleTeacherSelfCritic(request, env) {
  const url = new URL(request.url);
  if (request.method === "OPTIONS" && (url.pathname.startsWith("/teacher") || url.pathname.startsWith("/self-critic"))) return new Response(null,{status:204,headers:{"access-control-allow-origin":"*","access-control-allow-headers":"content-type,x-lumen-admin","access-control-allow-methods":"GET,POST,OPTIONS"}});
  if (request.method === "GET" && url.pathname === "/teacher/policy") return json({ ok:true, version:VERSION, role:"human_teacher", principle:"human_feedback_is_a_hypothesis_not_ground_truth", feedbackTypes:[...FEEDBACK_TYPES], evidenceRequiredBeforePreferenceChange:true, maxTeacherNudge:MAX_TEACHER_NUDGE, selfModifyingCode:false, autonomousSpendUsd:0, bindingActionsHumanGated:true });
  if (request.method === "POST" && url.pathname === "/teacher/feedback") {
    if (!authorized(request, env)) return json({ok:false,error:"unauthorized"},401);
    let body = {}; try { body = await request.json(); } catch { return json({ok:false,error:"invalid_json"},400); }
    const result = await submitHumanFeedback(env, body, "human_teacher_api");
    return json(result, result.ok ? 201 : 400);
  }
  if (request.method === "GET" && url.pathname === "/teacher/status") {
    if (!authorized(request, env)) return json({ok:false,error:"unauthorized"},401);
    const status = await teacherCriticStatus(env); return json({ok:true,version:VERSION,humanFeedback:status.humanFeedback});
  }
  if (request.method === "GET" && url.pathname === "/self-critic/policy") return json({ ok:true, version:VERSION, role:"self_critic", checks:["repeated_stall","negative_verified_evidence","stronger_challenger","pending_human_challenge","low_confidence"], falsificationRequired:true, verifiedEvidenceOverridesAdvice:true, selfModifyingCode:false, autonomousSpendUsd:0, externalBindingActions:false, bindingActionsHumanGated:true });
  if (request.method === "GET" && url.pathname === "/self-critic/status") {
    if (!authorized(request, env)) return json({ok:false,error:"unauthorized"},401);
    return json(await teacherCriticStatus(env));
  }
  if (request.method === "POST" && url.pathname === "/self-critic/run") {
    if (!authorized(request, env)) return json({ok:false,error:"unauthorized"},401);
    return json(await runSelfCriticCycle(env,{trigger:"admin_run"}),202);
  }
  return null;
}
