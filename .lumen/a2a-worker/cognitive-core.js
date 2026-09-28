import { computeEconomicOperatorState } from "./revenue-focus-controller.js";
import { runCognitiveEconomicSupervisor } from "./cognitive-economic-operator.js";

export const COGNITIVE_CORE_VERSION = "1.0-goal-task-memory";
const MAX_OPEN_TASKS = 8;
const MAX_HISTORY_DAYS = 45;

function json(data, status = 200) {
  return Response.json(data, {
    status,
    headers: {
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "access-control-allow-origin": "*",
    },
  });
}

function clean(value, limit = 240) {
  return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit);
}

function num(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function priorityScore(value) {
  if (value === "critical") return 100;
  if (value === "high") return 80;
  if (value === "medium") return 50;
  return 20;
}

function corePolicy() {
  return {
    version: COGNITIVE_CORE_VERSION,
    mode: "persistent_goal_task_memory",
    objective: "maximize_verified_net_revenue_with_bounded_reversible_autonomy",
    cycle: "observe_reason_choose_create_tasks_delegate_measure_learn",
    execution: {
      directToolExecutionByCore: false,
      delegatesToExistingGovernedModules: true,
      mayCreateInternalTasks: true,
      mayPrioritizeReversibleWork: true,
      mayCreateExternalMessages: false,
      maySpendMoney: false,
      mayPurchase: false,
      mayContract: false,
      mayAcceptBindingTerms: false,
      bindingActionsHumanGated: true,
    },
    truthRules: {
      verifiedRevenueOnly: true,
      cognitiveAdviceCannotFabricateEvidence: true,
      economicOperatorRemainsExecutionAuthority: true,
      conversionInventoryBeforeExploration: true,
    },
  };
}

async function ensureSchema(env) {
  if (!env?.DB) return;
  await env.DB.batch([
    env.DB.prepare(`CREATE TABLE IF NOT EXISTS lumen_cognitive_core_state (
      id TEXT PRIMARY KEY,
      updated_at TEXT NOT NULL,
      version TEXT NOT NULL,
      cycle INTEGER NOT NULL DEFAULT 0,
      objective TEXT NOT NULL,
      phase TEXT NOT NULL,
      focus_product TEXT,
      cognitive_mode TEXT NOT NULL,
      plan_json TEXT NOT NULL,
      metrics_json TEXT NOT NULL
    )`),
    env.DB.prepare(`CREATE TABLE IF NOT EXISTS lumen_cognitive_tasks (
      task_id TEXT PRIMARY KEY,
      task_key TEXT NOT NULL UNIQUE,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      status TEXT NOT NULL,
      priority TEXT NOT NULL,
      score INTEGER NOT NULL DEFAULT 0,
      kind TEXT NOT NULL,
      objective TEXT NOT NULL,
      rationale TEXT NOT NULL,
      delegated_module TEXT NOT NULL,
      execution_authority TEXT NOT NULL,
      source_cycle INTEGER NOT NULL DEFAULT 0,
      source_phase TEXT NOT NULL,
      product_focus TEXT,
      payload_json TEXT NOT NULL
    )`),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_cognitive_tasks_status_score ON lumen_cognitive_tasks(status,score DESC,updated_at DESC)"),
    env.DB.prepare(`CREATE TABLE IF NOT EXISTS lumen_cognitive_core_history (
      event_id TEXT PRIMARY KEY,
      created_at TEXT NOT NULL,
      cycle INTEGER NOT NULL DEFAULT 0,
      phase TEXT NOT NULL,
      event_type TEXT NOT NULL,
      payload_json TEXT NOT NULL
    )`),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_cognitive_core_history_created ON lumen_cognitive_core_history(created_at)"),
  ]);
}

function task(kind, priority, objective, rationale, delegatedModule, executionAuthority, productFocus = null, payload = {}) {
  return {
    kind,
    priority,
    score: priorityScore(priority),
    objective,
    rationale,
    delegatedModule,
    executionAuthority,
    productFocus: productFocus || null,
    payload,
  };
}

function buildTasks(economic, cognitive) {
  const phase = clean(economic?.phase, 80) || "UNKNOWN";
  const metrics = economic?.metrics || {};
  const plan = cognitive?.plan || {};
  const product = clean(plan?.productFocus, 80) || null;
  const hardAction = clean(plan?.hardEconomicAction || economic?.nextEconomicAction, 160) || "OBSERVE";
  const tasks = [];

  if (phase === "CLOSING") {
    tasks.push(task(
      "close_verified_intent",
      "critical",
      "Convert existing verified commercial intent before expanding discovery.",
      "The economic operator reports close-ready inventory; closing has higher expected value than new exploration.",
      "commercial-reply-engine/first-cash-closer",
      "existing_governed_execution",
      product,
      { hardAction }
    ));
  } else if (phase === "CONVERTING") {
    tasks.push(task(
      "qualify_and_reply",
      "critical",
      "Advance qualified commercial responses toward a concrete next step.",
      "Qualified responses already exist and must outrank new market discovery.",
      "commercial-reply-engine",
      "existing_governed_execution",
      product,
      { qualifiedResponses: num(metrics?.qualifiedCommercialResponses) }
    ));
  } else if (phase === "OUTBOUND_READY") {
    tasks.push(task(
      "send_quality_pass_outreach",
      "high",
      "Use already-approved commercial inventory before generating more.",
      "Quality-PASS proposals are waiting for the governed outbound slot.",
      "a2a-outreach",
      "existing_governed_execution",
      product,
      { approvedUnsent: num(metrics?.approvedUnsent) }
    ));
  } else if (phase === "REVENUE_VERIFIED_SCALE") {
    tasks.push(task(
      "scale_revenue_proven_lane",
      "high",
      "Allocate more reversible attention to the lane that produced verified revenue.",
      "Verified revenue is stronger evidence than activity volume and should guide resource allocation.",
      "portfolio-governor/profit-feedback-engine",
      "reversible_attention_only",
      product,
      { verifiedRevenueUsd: num(metrics?.verifiedRevenueUsd), verifiedSettlements: num(metrics?.verifiedSettlements) }
    ));
  } else {
    tasks.push(task(
      "discover_and_score",
      "high",
      "Find and rank new opportunities with short feedback loops and zero autonomous spend.",
      "There is no higher-value conversion inventory currently blocking exploration.",
      "adaptive-market-hunter/opportunity-factory/source-intelligence",
      "autonomous_research_only",
      product,
      { hardAction }
    ));
  }

  if (product && plan?.b2bDiscoveryBoost) {
    tasks.push(task(
      "research_product_focus",
      "high",
      `Deepen evidence for ${product} without increasing monetary risk.`,
      "The cognitive supervisor produced a safe product-focus signal strong enough for reversible B2B sensing.",
      "source-intelligence/adaptive-market-hunter",
      "autonomous_research_only",
      product,
      { confidence: num(plan?.confidence), cognitiveDecision: clean(plan?.cognitiveDecision, 40) }
    ));
  }

  if (num(metrics?.firstCashAttempts) > 0 && num(metrics?.firstCashResponded) === 0 && num(metrics?.verifiedRevenueUsd) === 0) {
    tasks.push(task(
      "diagnose_first_cash_friction",
      "medium",
      "Identify why first-cash attempts are not producing qualified responses or settlements.",
      "Repeated activity without downstream evidence should trigger diagnosis instead of blind repetition.",
      "revenue-director/profit-feedback-engine",
      "analysis_and_reversible_attention",
      product,
      { attempts: num(metrics?.firstCashAttempts), sent: num(metrics?.firstCashSent) }
    ));
  }

  tasks.push(task(
    "measure_and_learn",
    "medium",
    "Reconcile actions against verified funnel progress and revenue truth.",
    "Every cognitive cycle must compare expectation with observed commercial outcomes.",
    "profit-feedback-engine/cognitive-learning",
    "read_only_learning",
    product,
    { phase, hardAction }
  ));

  return tasks.slice(0, 5);
}

function makeTaskKey(sourceCycle, phase, item) {
  const product = clean(item.productFocus, 60) || "none";
  return `${sourceCycle}:${clean(phase, 40)}:${clean(item.kind, 80)}:${product}`;
}

async function persistCoreCycle(env, economic, cognitive, tasks) {
  if (!env?.DB) return { persisted: false, reason: "db_unavailable", cycle: 0 };
  await ensureSchema(env);
  const previous = await env.DB.prepare("SELECT cycle FROM lumen_cognitive_core_state WHERE id='GLOBAL' LIMIT 1").first();
  const cycle = Math.max(0, Number(previous?.cycle || 0)) + 1;
  const now = new Date().toISOString();
  const phase = clean(economic?.phase, 80) || "UNKNOWN";
  const product = clean(cognitive?.plan?.productFocus, 80) || null;
  const planJson = JSON.stringify(cognitive?.plan || {}).slice(0, 16000);
  const metricsJson = JSON.stringify(economic?.metrics || {}).slice(0, 16000);

  await env.DB.prepare(`INSERT INTO lumen_cognitive_core_state
    (id,updated_at,version,cycle,objective,phase,focus_product,cognitive_mode,plan_json,metrics_json)
    VALUES('GLOBAL',?,?,?,?,?,?,?,?,?)
    ON CONFLICT(id) DO UPDATE SET
      updated_at=excluded.updated_at, version=excluded.version, cycle=excluded.cycle,
      objective=excluded.objective, phase=excluded.phase, focus_product=excluded.focus_product,
      cognitive_mode=excluded.cognitive_mode, plan_json=excluded.plan_json, metrics_json=excluded.metrics_json`)
    .bind(
      now,
      COGNITIVE_CORE_VERSION,
      cycle,
      corePolicy().objective,
      phase,
      product,
      clean(cognitive?.plan?.mode, 80) || "UNKNOWN",
      planJson,
      metricsJson,
    ).run();

  for (const item of tasks) {
    const taskKey = makeTaskKey(cycle, phase, item);
    const taskId = `COGTASK-${crypto.randomUUID().replaceAll("-", "").slice(0, 20).toUpperCase()}`;
    await env.DB.prepare(`INSERT OR IGNORE INTO lumen_cognitive_tasks
      (task_id,task_key,created_at,updated_at,status,priority,score,kind,objective,rationale,delegated_module,execution_authority,source_cycle,source_phase,product_focus,payload_json)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`)
      .bind(
        taskId,
        taskKey,
        now,
        now,
        "OPEN",
        item.priority,
        item.score,
        item.kind,
        item.objective,
        item.rationale,
        item.delegatedModule,
        item.executionAuthority,
        cycle,
        phase,
        item.productFocus,
        JSON.stringify(item.payload || {}).slice(0, 8000),
      ).run();
  }

  await env.DB.prepare(`UPDATE lumen_cognitive_tasks SET status='SUPERSEDED',updated_at=?
    WHERE status='OPEN' AND task_id NOT IN (
      SELECT task_id FROM lumen_cognitive_tasks WHERE status='OPEN' ORDER BY score DESC, updated_at DESC LIMIT ?
    )`).bind(now, MAX_OPEN_TASKS).run();

  const eventId = `COGEVT-${crypto.randomUUID().replaceAll("-", "").slice(0, 20).toUpperCase()}`;
  await env.DB.prepare(`INSERT INTO lumen_cognitive_core_history(event_id,created_at,cycle,phase,event_type,payload_json)
    VALUES(?,?,?,?,?,?)`)
    .bind(eventId, now, cycle, phase, "cycle_planned", JSON.stringify({ tasks, cognitiveStatus: cognitive?.status || null }).slice(0, 16000))
    .run();

  try {
    await env.DB.prepare(`DELETE FROM lumen_cognitive_core_history WHERE created_at < datetime('now','-${MAX_HISTORY_DAYS} days')`).run();
  } catch {}

  return { persisted: true, cycle, updatedAt: now };
}

async function readCoreState(env) {
  if (!env?.DB) return null;
  await ensureSchema(env);
  const state = await env.DB.prepare("SELECT updated_at,version,cycle,objective,phase,focus_product,cognitive_mode,plan_json,metrics_json FROM lumen_cognitive_core_state WHERE id='GLOBAL' LIMIT 1").first();
  if (!state) return null;
  const openTasks = await env.DB.prepare("SELECT task_id,updated_at,status,priority,score,kind,objective,rationale,delegated_module,execution_authority,source_cycle,source_phase,product_focus,payload_json FROM lumen_cognitive_tasks WHERE status='OPEN' ORDER BY score DESC, updated_at DESC LIMIT ?").bind(MAX_OPEN_TASKS).all();
  const tasks = Array.isArray(openTasks?.results) ? openTasks.results.map((row) => {
    let payload = {};
    try { payload = JSON.parse(row.payload_json || "{}"); } catch {}
    return {
      taskId: row.task_id,
      updatedAt: row.updated_at,
      status: row.status,
      priority: row.priority,
      score: num(row.score),
      kind: row.kind,
      objective: row.objective,
      rationale: row.rationale,
      delegatedModule: row.delegated_module,
      executionAuthority: row.execution_authority,
      sourceCycle: num(row.source_cycle),
      sourcePhase: row.source_phase,
      productFocus: row.product_focus || null,
      payload,
    };
  }) : [];
  let plan = {};
  let metrics = {};
  try { plan = JSON.parse(state.plan_json || "{}"); } catch {}
  try { metrics = JSON.parse(state.metrics_json || "{}"); } catch {}
  return {
    updatedAt: state.updated_at,
    version: state.version,
    cycle: num(state.cycle),
    objective: state.objective,
    phase: state.phase,
    focusProduct: state.focus_product || null,
    cognitiveMode: state.cognitive_mode,
    plan,
    metrics,
    openTasks: tasks,
  };
}

export async function runCognitiveCore(env, options = {}) {
  const economic = await computeEconomicOperatorState(env);
  const cognitive = options.cognitive && typeof options.cognitive === "object"
    ? options.cognitive
    : await runCognitiveEconomicSupervisor(env);
  const tasks = buildTasks(economic, cognitive);
  const persistence = await persistCoreCycle(env, economic, cognitive, tasks);
  return {
    ok: true,
    version: COGNITIVE_CORE_VERSION,
    status: "active",
    objective: corePolicy().objective,
    phase: economic?.phase || null,
    cognitiveStatus: cognitive?.status || null,
    cognitiveProvider: cognitive?.cognitiveProvider || null,
    plan: cognitive?.plan || null,
    tasksCreated: tasks,
    persistence,
    execution: corePolicy().execution,
  };
}

function adminAuthorized(request, env) {
  const expected = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const supplied = clean(request.headers.get("x-lumen-admin"), 500);
  return Boolean(expected) && supplied === expected;
}

export async function handleCognitiveCore(request, env) {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/cognitive-core/policy") return json(corePolicy());
  if (request.method === "GET" && url.pathname === "/cognitive-core/state") {
    try {
      const state = await readCoreState(env);
      return json({ ok: true, initialized: Boolean(state), state, policy: corePolicy() });
    } catch (error) {
      return json({ ok: false, error: clean(error?.message || error, 180) || "state_read_failed" }, 500);
    }
  }
  if (request.method === "POST" && url.pathname === "/cognitive-core/run") {
    if (!clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500)) return json({ ok: false, error: "admin_not_configured" }, 503);
    if (!adminAuthorized(request, env)) return json({ ok: false, error: "unauthorized" }, 401);
    try {
      return json(await runCognitiveCore(env));
    } catch (error) {
      return json({ ok: false, error: clean(error?.message || error, 180) || "cognitive_core_failed" }, 500);
    }
  }
  return null;
}
