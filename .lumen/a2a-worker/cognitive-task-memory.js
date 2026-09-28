import { computeEconomicOperatorState } from "./revenue-focus-controller.js";

export const COGNITIVE_TASK_MEMORY_VERSION = "1.0-persistent-agenda";
const MAX_OPEN_TASKS = 8;
const MAX_HISTORY = 300;

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
  return String(value ?? "")
    .replace(/[\u0000-\u001f\u007f]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, limit);
}

function num(value, fallback = 0) {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function clamp(value, min = 0, max = 1) {
  return Math.max(min, Math.min(max, num(value, min)));
}

function policy() {
  return {
    version: COGNITIVE_TASK_MEMORY_VERSION,
    mode: "persistent_internal_agenda",
    objective: "preserve_and_refresh_the_highest_value_nonbinding_work_across_cycles",
    cycle: "observe_prioritize_refresh_supersede_measure",
    authority: {
      mayCreateInternalTasks: true,
      mayPrioritizeInternalTasks: true,
      mayDelegateLabelsToExistingModules: true,
      directToolExecution: false,
      externalMessagesCreated: false,
      autonomousSpendUsd: 0,
      autonomousPurchase: false,
      autonomousDebt: false,
      autonomousContract: false,
      bindingActionsHumanGated: true,
    },
    truthRules: {
      verifiedRevenueOnly: true,
      conversionInventoryBeforeExploration: true,
      liveCognitiveOutputIsGuidanceNotEvidence: true,
      existingEconomicOperatorRemainsExecutionAuthority: true,
    },
  };
}

async function ensureSchema(env) {
  if (!env?.DB) return;
  await env.DB.batch([
    env.DB.prepare(`CREATE TABLE IF NOT EXISTS lumen_cognitive_task_memory_state (
      id TEXT PRIMARY KEY,
      updated_at TEXT NOT NULL,
      cycle INTEGER NOT NULL DEFAULT 0,
      phase TEXT NOT NULL,
      top_task_key TEXT,
      task_count INTEGER NOT NULL DEFAULT 0,
      snapshot_json TEXT NOT NULL,
      engine_version TEXT NOT NULL
    )`),
    env.DB.prepare(`CREATE TABLE IF NOT EXISTS lumen_cognitive_task_memory (
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
      target_lane TEXT,
      cognitive_confidence REAL NOT NULL DEFAULT 0,
      payload_json TEXT NOT NULL,
      engine_version TEXT NOT NULL
    )`),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_cognitive_task_memory_open ON lumen_cognitive_task_memory(status,score DESC,updated_at DESC)"),
    env.DB.prepare(`CREATE TABLE IF NOT EXISTS lumen_cognitive_task_memory_events (
      event_id TEXT PRIMARY KEY,
      created_at TEXT NOT NULL,
      cycle INTEGER NOT NULL,
      phase TEXT NOT NULL,
      event_type TEXT NOT NULL,
      payload_json TEXT NOT NULL,
      engine_version TEXT NOT NULL
    )`),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_cognitive_task_memory_events_created ON lumen_cognitive_task_memory_events(created_at)"),
  ]);
}

async function previousCycle(env) {
  if (!env?.DB) return 0;
  await ensureSchema(env);
  const row = await env.DB.prepare("SELECT cycle FROM lumen_cognitive_task_memory_state WHERE id='GLOBAL' LIMIT 1").first();
  return Math.max(0, num(row?.cycle));
}

async function readLiveCognitiveHint(env) {
  if (!env?.DB) return null;
  await ensureSchema(env);
  try {
    const row = await env.DB.prepare("SELECT updated_at,cycle,provider,phase,action_type,target_lane,confidence,expected_value,rationale_summary FROM lumen_live_cognitive_state WHERE id='GLOBAL' LIMIT 1").first();
    if (!row) return null;
    return {
      updatedAt: row.updated_at || null,
      cycle: num(row.cycle),
      provider: row.provider || null,
      phase: row.phase || null,
      actionType: clean(row.action_type, 80) || null,
      targetLane: clean(row.target_lane, 40) || null,
      confidence: clamp(row.confidence),
      expectedValue: clamp(row.expected_value),
      rationale: clean(row.rationale_summary, 300),
    };
  } catch {
    return null;
  }
}

function makeTask(kind, priority, score, objective, rationale, delegatedModule, authority, lane = null, confidence = 0, payload = {}) {
  return {
    kind,
    priority,
    score,
    objective,
    rationale,
    delegatedModule,
    authority,
    lane: clean(lane, 40) || null,
    confidence: clamp(confidence),
    payload,
  };
}

function buildAgenda(operator, hint) {
  const phase = clean(operator?.phase, 80) || "UNKNOWN";
  const metrics = operator?.metrics || {};
  const backlog = operator?.revenueFocus?.backlog || {};
  const lane = clean(hint?.targetLane || operator?.portfolio?.recommendedLane, 40) || "B2B_A2A";
  const confidence = clamp(hint?.confidence || 0);
  const agenda = [];

  if (num(backlog?.closeIntent) > 0 || num(metrics?.negotiating) > 0 || phase === "CLOSING") {
    agenda.push(makeTask(
      "close_nonbinding_intent",
      "critical",
      100,
      "Advance the closest verified commercial intent toward settlement without creating binding obligations.",
      "Close-ready commercial inventory has the shortest path to verified revenue and outranks new discovery.",
      "commercial-reply-engine/first-cash-closer",
      "existing_governed_execution",
      lane,
      confidence,
      { closeIntent: num(backlog?.closeIntent), negotiating: num(metrics?.negotiating) }
    ));
  } else if (num(metrics?.qualifiedCommercialResponses) > 0 || phase === "CONVERTING") {
    agenda.push(makeTask(
      "qualify_reply",
      "critical",
      96,
      "Convert qualified commercial replies into a concrete nonbinding next step.",
      "Observed buyer-side engagement is stronger evidence than additional top-of-funnel activity.",
      "commercial-reply-engine",
      "existing_governed_execution",
      lane,
      confidence,
      { qualifiedResponses: num(metrics?.qualifiedCommercialResponses) }
    ));
  } else if (num(backlog?.followupsReady) > 0) {
    agenda.push(makeTask(
      "follow_up",
      "high",
      88,
      "Use ready follow-up inventory before creating more outreach volume.",
      "The system already has a shorter feedback-loop action available.",
      "followup-engine",
      "existing_governed_execution",
      lane,
      confidence,
      { followupsReady: num(backlog?.followupsReady) }
    ));
  } else if (num(metrics?.approvedUnsent) > 0 || phase === "OUTBOUND_READY") {
    agenda.push(makeTask(
      "quality_pass_outreach",
      "high",
      84,
      "Use quality-passed unsent proposals in the governed outbound slot.",
      "Approved commercial inventory should be exploited before expanding search.",
      "a2a-outreach",
      "existing_governed_execution",
      lane,
      confidence,
      { approvedUnsent: num(metrics?.approvedUnsent) }
    ));
  } else if (num(metrics?.verifiedRevenueUsd) > 0 || phase === "REVENUE_VERIFIED_SCALE") {
    agenda.push(makeTask(
      "scale_verified_lane",
      "high",
      82,
      "Increase reversible attention to the lane that produced verified revenue.",
      "Verified settlements are the strongest available economic evidence.",
      "portfolio-governor/profit-feedback-engine",
      "reversible_attention_only",
      lane,
      confidence,
      { verifiedRevenueUsd: num(metrics?.verifiedRevenueUsd), verifiedSettlements: num(metrics?.verifiedSettlements) }
    ));
  } else {
    const hintAction = clean(hint?.actionType, 80);
    if (hintAction === "DISCOVER_COMMERCE" || lane === "COMMERCE") {
      agenda.push(makeTask(
        "discover_commerce",
        "high",
        76,
        "Search for commerce opportunities with evidence-backed supply and zero autonomous purchasing.",
        "No stronger downstream conversion inventory is currently visible and the cognitive lane preference is commerce.",
        "product-commerce-radar/commerce-machine",
        "autonomous_research_only",
        "COMMERCE",
        confidence,
        { cognitiveAction: hintAction || null }
      ));
    } else {
      agenda.push(makeTask(
        "discover_b2b",
        "high",
        78,
        "Find and score new B2B/A2A opportunities with short feedback loops.",
        "No stronger downstream conversion inventory is currently visible.",
        "source-intelligence/adaptive-market-hunter/opportunity-factory",
        "autonomous_research_only",
        lane,
        confidence,
        { cognitiveAction: hintAction || null }
      ));
    }
  }

  if (hint?.actionType === "SCORE_OPPORTUNITIES" || num(metrics?.actionableOpportunities) > 0 || num(metrics?.activeCandidates) > 0) {
    agenda.push(makeTask(
      "score_opportunities",
      "high",
      74,
      "Rank current opportunity inventory by expected verified economic value and execution friction.",
      "Existing opportunity inventory should be filtered before adding unnecessary complexity.",
      "opportunity-factory/portfolio-governor",
      "analysis_and_reversible_attention",
      lane,
      confidence,
      { actionable: num(metrics?.actionableOpportunities), activeCandidates: num(metrics?.activeCandidates) }
    ));
  }

  if (num(metrics?.firstCashAttempts) > 0 && num(metrics?.firstCashResponded) === 0 && num(metrics?.verifiedRevenueUsd) === 0) {
    agenda.push(makeTask(
      "diagnose_first_cash_friction",
      "medium",
      62,
      "Diagnose why first-cash attempts are not producing downstream evidence.",
      "Repeated activity without qualified responses or settlements should trigger diagnosis instead of blind repetition.",
      "revenue-director/profit-feedback-engine",
      "analysis_only",
      lane,
      confidence,
      { attempts: num(metrics?.firstCashAttempts), sent: num(metrics?.firstCashSent), responded: num(metrics?.firstCashResponded) }
    ));
  }

  agenda.push(makeTask(
    "measure_and_learn",
    "medium",
    58,
    "Compare expected progress with observed funnel movement and verified revenue truth.",
    "The cognitive agenda must refresh from outcomes rather than activity counts alone.",
    "profit-feedback-engine/live-cognitive-core",
    "read_only_learning",
    lane,
    confidence,
    { phase, cognitiveAction: hint?.actionType || null, cognitiveExpectedValue: clamp(hint?.expectedValue || 0) }
  ));

  return agenda.slice(0, 5);
}

function taskKey(item) {
  return `${clean(item.kind, 80)}:${clean(item.lane || "NONE", 40)}`;
}

async function persistAgenda(env, cycle, phase, agenda, operator, hint) {
  if (!env?.DB) return { persisted: false, reason: "db_unavailable" };
  await ensureSchema(env);
  const now = new Date().toISOString();
  const refreshedKeys = [];

  for (const item of agenda) {
    const key = taskKey(item);
    refreshedKeys.push(key);
    const id = `CTM-${crypto.randomUUID()}`;
    await env.DB.prepare(`INSERT INTO lumen_cognitive_task_memory
      (task_id,task_key,created_at,updated_at,status,priority,score,kind,objective,rationale,delegated_module,execution_authority,source_cycle,source_phase,target_lane,cognitive_confidence,payload_json,engine_version)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
      ON CONFLICT(task_key) DO UPDATE SET
        updated_at=excluded.updated_at,status='OPEN',priority=excluded.priority,score=excluded.score,
        objective=excluded.objective,rationale=excluded.rationale,delegated_module=excluded.delegated_module,
        execution_authority=excluded.execution_authority,source_cycle=excluded.source_cycle,source_phase=excluded.source_phase,
        target_lane=excluded.target_lane,cognitive_confidence=excluded.cognitive_confidence,payload_json=excluded.payload_json,
        engine_version=excluded.engine_version`)
      .bind(
        id,
        key,
        now,
        now,
        "OPEN",
        item.priority,
        item.score,
        item.kind,
        item.objective,
        item.rationale,
        item.delegatedModule,
        item.authority,
        cycle,
        phase,
        item.lane,
        item.confidence,
        JSON.stringify(item.payload || {}).slice(0, 8000),
        COGNITIVE_TASK_MEMORY_VERSION,
      ).run();
  }

  await env.DB.prepare("UPDATE lumen_cognitive_task_memory SET status='SUPERSEDED',updated_at=? WHERE status='OPEN' AND source_cycle<?")
    .bind(now, cycle).run();

  await env.DB.prepare(`UPDATE lumen_cognitive_task_memory SET status='SUPERSEDED',updated_at=?
    WHERE status='OPEN' AND task_id NOT IN (
      SELECT task_id FROM lumen_cognitive_task_memory WHERE status='OPEN' ORDER BY score DESC,updated_at DESC LIMIT ?
    )`).bind(now, MAX_OPEN_TASKS).run();

  const top = agenda[0] || null;
  const snapshot = {
    objective: policy().objective,
    phase,
    topTask: top,
    agenda,
    cognitiveHint: hint || null,
    economicMetrics: operator?.metrics || {},
  };

  await env.DB.prepare(`INSERT INTO lumen_cognitive_task_memory_state(id,updated_at,cycle,phase,top_task_key,task_count,snapshot_json,engine_version)
    VALUES('GLOBAL',?,?,?,?,?,?,?)
    ON CONFLICT(id) DO UPDATE SET
      updated_at=excluded.updated_at,cycle=excluded.cycle,phase=excluded.phase,top_task_key=excluded.top_task_key,
      task_count=excluded.task_count,snapshot_json=excluded.snapshot_json,engine_version=excluded.engine_version`)
    .bind(now, cycle, phase, top ? taskKey(top) : null, agenda.length, JSON.stringify(snapshot).slice(0, 20000), COGNITIVE_TASK_MEMORY_VERSION)
    .run();

  const eventId = `CTMEVT-${crypto.randomUUID()}`;
  await env.DB.prepare("INSERT INTO lumen_cognitive_task_memory_events(event_id,created_at,cycle,phase,event_type,payload_json,engine_version) VALUES(?,?,?,?,?,?,?)")
    .bind(eventId, now, cycle, phase, "agenda_refreshed", JSON.stringify({ refreshedKeys, topTask: top }).slice(0, 12000), COGNITIVE_TASK_MEMORY_VERSION)
    .run();

  await env.DB.prepare("DELETE FROM lumen_cognitive_task_memory_events WHERE event_id IN (SELECT event_id FROM lumen_cognitive_task_memory_events ORDER BY created_at DESC LIMIT -1 OFFSET ?)")
    .bind(MAX_HISTORY).run();

  return { persisted: true, cycle, updatedAt: now, topTaskKey: top ? taskKey(top) : null };
}

export async function runCognitiveTaskMemory(env, options = {}) {
  await ensureSchema(env);
  const cycle = (await previousCycle(env)) + 1;
  const [operator, storedHint] = await Promise.all([
    computeEconomicOperatorState(env),
    options.cognitiveHint ? Promise.resolve(null) : readLiveCognitiveHint(env),
  ]);
  const hint = options.cognitiveHint || storedHint;
  const phase = clean(operator?.phase, 80) || "UNKNOWN";
  const agenda = buildAgenda(operator, hint);
  const persistence = await persistAgenda(env, cycle, phase, agenda, operator, hint);
  return {
    ok: true,
    version: COGNITIVE_TASK_MEMORY_VERSION,
    cycle,
    phase,
    topTask: agenda[0] || null,
    agenda,
    cognitiveHintUsed: hint || null,
    persistence,
    authority: policy().authority,
  };
}

async function readState(env) {
  if (!env?.DB) return null;
  await ensureSchema(env);
  const row = await env.DB.prepare("SELECT updated_at,cycle,phase,top_task_key,task_count,snapshot_json,engine_version FROM lumen_cognitive_task_memory_state WHERE id='GLOBAL' LIMIT 1").first();
  if (!row) return null;
  let snapshot = {};
  try { snapshot = JSON.parse(row.snapshot_json || "{}"); } catch {}
  const tasksResult = await env.DB.prepare("SELECT task_id,task_key,updated_at,status,priority,score,kind,objective,rationale,delegated_module,execution_authority,source_cycle,source_phase,target_lane,cognitive_confidence,payload_json FROM lumen_cognitive_task_memory WHERE status='OPEN' ORDER BY score DESC,updated_at DESC LIMIT ?")
    .bind(MAX_OPEN_TASKS).all();
  const openTasks = (tasksResult?.results || []).map(rowTask => {
    let payload = {};
    try { payload = JSON.parse(rowTask.payload_json || "{}"); } catch {}
    return {
      taskId: rowTask.task_id,
      taskKey: rowTask.task_key,
      updatedAt: rowTask.updated_at,
      status: rowTask.status,
      priority: rowTask.priority,
      score: num(rowTask.score),
      kind: rowTask.kind,
      objective: rowTask.objective,
      rationale: rowTask.rationale,
      delegatedModule: rowTask.delegated_module,
      executionAuthority: rowTask.execution_authority,
      sourceCycle: num(rowTask.source_cycle),
      sourcePhase: rowTask.source_phase,
      targetLane: rowTask.target_lane || null,
      cognitiveConfidence: clamp(rowTask.cognitive_confidence),
      payload,
    };
  });
  return {
    initialized: true,
    updatedAt: row.updated_at,
    cycle: num(row.cycle),
    phase: row.phase,
    topTaskKey: row.top_task_key || null,
    taskCount: num(row.task_count),
    snapshot,
    openTasks,
    engineVersion: row.engine_version,
  };
}

function authorized(request, env) {
  const expected = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 300);
  const supplied = clean(request.headers.get("x-lumen-admin"), 300);
  return Boolean(expected && supplied && expected === supplied);
}

export async function handleCognitiveTaskMemory(request, env) {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/cognitive/tasks/policy") return json(policy());
  if (request.method === "GET" && url.pathname === "/cognitive/tasks/state") {
    const state = await readState(env);
    return json(state || { initialized: false, version: COGNITIVE_TASK_MEMORY_VERSION, openTasks: [] });
  }
  if (request.method === "POST" && url.pathname === "/cognitive/tasks/run") {
    if (!authorized(request, env)) return json({ ok: false, error: "unauthorized" }, 401);
    return json(await runCognitiveTaskMemory(env));
  }
  return null;
}
