const VERSION = "1.0-delegation-engine";

function json(data, status = 200) {
  return Response.json(data, {
    status,
    headers: {
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "access-control-allow-origin": "*"
    }
  });
}

function clean(value, limit = 12000) {
  return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit);
}

function parse(value, fallback = null) {
  try { return JSON.parse(value || ""); } catch { return fallback; }
}

function authorized(request, env) {
  const expected = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const supplied = clean(request.headers.get("x-lumen-admin"), 500);
  return Boolean(expected && supplied && expected === supplied);
}

function bool(value) {
  return String(value ?? "false").toLowerCase() === "true";
}

async function sha256(text) {
  const bytes = new TextEncoder().encode(String(text));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, "0")).join("");
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_delegation_tasks (id TEXT PRIMARY KEY,room_id TEXT NOT NULL,opportunity_id TEXT NOT NULL,partner_id TEXT NOT NULL,partner_name TEXT NOT NULL,role TEXT NOT NULL,title TEXT NOT NULL,objective TEXT NOT NULL,expected_output TEXT NOT NULL,evidence_required TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,dispatched_at TEXT,completed_at TEXT,remote_task_id TEXT,context_id TEXT,response_text TEXT,quality_score INTEGER,error TEXT,binding_allowed INTEGER NOT NULL DEFAULT 0,spend_allowed INTEGER NOT NULL DEFAULT 0,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE UNIQUE INDEX IF NOT EXISTS idx_lumen_delegation_unique ON lumen_delegation_tasks(room_id,partner_id,role)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_delegation_status ON lumen_delegation_tasks(status,updated_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_delegation_events (id TEXT PRIMARY KEY,task_id TEXT NOT NULL,created_at TEXT NOT NULL,event_type TEXT NOT NULL,detail TEXT)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_delegation_events_task ON lumen_delegation_events(task_id,created_at)")
  ]);
  return true;
}

const ROLE_BLUEPRINTS = {
  verification: {
    title: "Verify claims and evidence",
    objective: "Independently verify the material claims relevant to the opportunity and identify what is proven, unproven, or contradictory.",
    expected: "A concise verification report with evidence references, confidence, gaps, risks, and a recommended next check."
  },
  research: {
    title: "Research evidence and context",
    objective: "Research the opportunity context, supporting evidence, assumptions, alternatives, and important unknowns.",
    expected: "A structured research brief separating observed facts, assumptions, sources, risks, and recommended next actions."
  },
  sourcing: {
    title: "Source viable options",
    objective: "Identify relevant suppliers, providers, routes, or execution options that match the exact scope without inventing substitutes.",
    expected: "A shortlist of viable options with fit rationale, evidence, constraints, unknowns, and explicit no-match guidance when appropriate."
  },
  pricing: {
    title: "Validate pricing and commercial reasonableness",
    objective: "Compare available pricing signals and determine whether proposed values appear commercially reasonable for the stated scope.",
    expected: "A price comparison with evidence, ranges, assumptions, outliers, and a reasonableness conclusion."
  },
  tender: {
    title: "Analyze tender or RFQ requirements",
    objective: "Extract the binding requirements, deadlines, qualification criteria, and commercial risks from the opportunity.",
    expected: "A requirement matrix with must-have criteria, gaps, risks, and recommended actions."
  },
  logistics: {
    title: "Assess logistics feasibility",
    objective: "Assess delivery, transport, timing, routing, and operational constraints relevant to fulfillment.",
    expected: "A logistics feasibility note with dependencies, timing risks, evidence, and recommended route."
  },
  sales: {
    title: "Assess buyer intent and commercial path",
    objective: "Evaluate the buyer signal, likely need, objections, qualification gaps, and best non-binding commercial next step.",
    expected: "A buyer-intent brief with evidence, qualification, objections, next action, and no fabricated buyer claims."
  },
  payments: {
    title: "Assess payment and settlement path",
    objective: "Assess the available payment or settlement path without authorizing or executing any outgoing payment.",
    expected: "A payment-readiness report with supported rails, constraints, evidence, and risks."
  },
  automation: {
    title: "Design execution workflow",
    objective: "Design a safe machine-executable workflow for the agreed non-binding plan, including controls and failure handling.",
    expected: "A workflow plan with steps, inputs, outputs, checks, failure modes, and human gates."
  }
};

function blueprint(role) {
  const key = clean(role, 80).toLowerCase();
  return ROLE_BLUEPRINTS[key] || {
    title: `Specialist analysis: ${key || "general"}`,
    objective: "Perform a specialist analysis of the synthesized council plan and return evidence-backed findings.",
    expected: "A concise specialist report separating evidence, assumptions, risks, and recommended next actions."
  };
}

async function latestSynthesizedRoom(env, roomId = "") {
  if (roomId) return env.DB.prepare("SELECT * FROM lumen_council_rooms WHERE id=? LIMIT 1").bind(roomId).first();
  return env.DB.prepare("SELECT * FROM lumen_council_rooms WHERE status='SYNTHESIZED' ORDER BY updated_at DESC LIMIT 1").first();
}

async function passingContributors(env, roomId) {
  try {
    const result = await env.DB.prepare("SELECT m.partner_id,m.name,m.role,m.room_status,m.contribution_text,q.score FROM lumen_council_room_members m JOIN lumen_council_contribution_quality q ON q.room_id=m.room_id AND q.partner_id=m.partner_id WHERE m.room_id=? AND q.status='PASS' AND m.room_status NOT IN ('REPLACED','LOW_QUALITY_REPLACED','FAILED','DECLINED') ORDER BY q.score DESC,m.match_score DESC").bind(roomId).all();
    return result.results || [];
  } catch {
    return [];
  }
}

async function logEvent(env, taskId, eventType, detail = "") {
  const id = `DE-${(await sha256(`${taskId}|${eventType}|${Date.now()}|${crypto.randomUUID()}`)).slice(0, 20).toUpperCase()}`;
  await env.DB.prepare("INSERT INTO lumen_delegation_events(id,task_id,created_at,event_type,detail) VALUES(?,?,?,?,?)")
    .bind(id, taskId, new Date().toISOString(), clean(eventType, 100), clean(detail, 4000) || null).run();
}

export async function planDelegationFromCouncil(env, roomId = "") {
  if (!(await ensureSchema(env))) return { ok: false, error: "persistence_unavailable", version: VERSION };
  const room = await latestSynthesizedRoom(env, roomId);
  if (!room) return { ok: true, planned: false, reason: "no_synthesized_room", version: VERSION };
  if (room.status !== "SYNTHESIZED") {
    return { ok: true, planned: false, roomId: room.id, roomStatus: room.status, reason: "room_not_synthesized", requiredStatus: "SYNTHESIZED", version: VERSION };
  }

  const contributors = await passingContributors(env, room.id);
  if (contributors.length < 2) {
    return { ok: true, planned: false, roomId: room.id, reason: "insufficient_quality_contributors", required: 2, available: contributors.length, version: VERSION };
  }

  const synthesis = parse(room.synthesis_json, {}) || {};
  const context = clean([
    `Council objective: ${room.objective || ""}`,
    `Shared context: ${room.shared_context || ""}`,
    `Key points: ${(synthesis.keyPoints || []).join(" | ")}`,
    `Action signals: ${(synthesis.actionSignals || []).join(" | ")}`,
    `Risk signals: ${(synthesis.riskSignals || []).join(" | ")}`
  ].join(" "), 7000);

  const now = new Date().toISOString();
  const tasks = [];
  for (const contributor of contributors.slice(0, 4)) {
    const bp = blueprint(contributor.role);
    const id = `DT-${(await sha256(`${room.id}|${contributor.partner_id}|${contributor.role}`)).slice(0, 20).toUpperCase()}`;
    const objective = clean(`${bp.objective} Work only within this synthesized council scope: ${context}`, 7000);
    const evidenceRequired = "Separate observed evidence from assumptions. Include reproducible public references where available. Never invent facts, prices, availability, customers, authorization, or completed actions.";

    await env.DB.prepare("INSERT INTO lumen_delegation_tasks(id,room_id,opportunity_id,partner_id,partner_name,role,title,objective,expected_output,evidence_required,status,created_at,updated_at,binding_allowed,spend_allowed,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?, ?,?,0,0,?) ON CONFLICT(room_id,partner_id,role) DO UPDATE SET title=excluded.title,objective=excluded.objective,expected_output=excluded.expected_output,evidence_required=excluded.evidence_required,updated_at=excluded.updated_at,engine_version=excluded.engine_version")
      .bind(id, room.id, room.opportunity_id, contributor.partner_id, contributor.name, clean(contributor.role, 80), bp.title, objective, bp.expected, evidenceRequired, "PLANNED", now, now, VERSION).run();
    await logEvent(env, id, "TASK_PLANNED", `quality_score=${Number(contributor.score || 0)}; role=${contributor.role}`);
    tasks.push({ id, partnerId: contributor.partner_id, partnerName: contributor.name, role: contributor.role, title: bp.title, status: "PLANNED", sourceQualityScore: Number(contributor.score || 0) });
  }

  return {
    ok: true,
    planned: tasks.length > 0,
    version: VERSION,
    roomId: room.id,
    opportunityId: room.opportunity_id,
    tasks,
    guardrails: {
      autonomousDelegation: bool(env?.A2A_AUTONOMOUS_DELEGATION),
      dispatched: false,
      bindingAllowed: false,
      spendAllowed: false,
      contractAllowed: false
    }
  };
}

export async function planLatestSynthesizedCouncil(env) {
  if (!(await ensureSchema(env))) return { ok: false, error: "persistence_unavailable", version: VERSION };
  const room = await env.DB.prepare("SELECT r.* FROM lumen_council_rooms r WHERE r.status='SYNTHESIZED' AND NOT EXISTS (SELECT 1 FROM lumen_delegation_tasks d WHERE d.room_id=r.id) ORDER BY r.updated_at DESC LIMIT 1").first();
  if (!room) return { ok: true, planned: false, reason: "no_unplanned_synthesized_room", version: VERSION };
  return planDelegationFromCouncil(env, room.id);
}

async function stats(env) {
  await ensureSchema(env);
  const row = await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN status='PLANNED' THEN 1 ELSE 0 END) planned,SUM(CASE WHEN status='DISPATCHED' THEN 1 ELSE 0 END) dispatched,SUM(CASE WHEN status='COMPLETED' THEN 1 ELSE 0 END) completed,SUM(CASE WHEN status='FAILED' THEN 1 ELSE 0 END) failed FROM lumen_delegation_tasks").first();
  return json({
    version: VERSION,
    total: Number(row?.total || 0),
    planned: Number(row?.planned || 0),
    dispatched: Number(row?.dispatched || 0),
    completed: Number(row?.completed || 0),
    failed: Number(row?.failed || 0),
    autonomousDelegation: bool(env?.A2A_AUTONOMOUS_DELEGATION),
    autonomousOutgoingSpend: false,
    bindingActionsHumanGated: true
  });
}

async function tasks(env, roomId = "") {
  await ensureSchema(env);
  const result = roomId
    ? await env.DB.prepare("SELECT * FROM lumen_delegation_tasks WHERE room_id=? ORDER BY created_at ASC").bind(roomId).all()
    : await env.DB.prepare("SELECT * FROM lumen_delegation_tasks ORDER BY created_at DESC LIMIT 50").all();
  return json({ version: VERSION, tasks: result.results || [] });
}

export async function handleDelegationEngine(request, env) {
  const url = new URL(request.url);

  if (request.method === "GET" && url.pathname === "/delegation/stats") return stats(env);

  if (request.method === "GET" && url.pathname === "/delegation/tasks") {
    if (!authorized(request, env)) return json({ ok: false, error: "admin_token_required" }, 403);
    return tasks(env, clean(url.searchParams.get("roomId"), 120));
  }

  if (request.method === "POST" && url.pathname === "/delegation/plan") {
    if (!authorized(request, env)) return json({ ok: false, error: "admin_token_required" }, 403);
    let body = {};
    try { body = await request.json(); } catch {}
    return json(await planDelegationFromCouncil(env, clean(body?.roomId, 120)), 202);
  }

  return null;
}
