import { classifyCommercialResponse } from "./response-qualification.js";

const VERSION = "1.1-qualified-commercial-followup";
const SEND_TIMEOUT_MS = 15000;

function json(data, status = 200) {
  return Response.json(data, { status, headers: { "cache-control": "no-store", "x-content-type-options": "nosniff", "access-control-allow-origin": "*" } });
}

function clean(value, limit = 6000) {
  return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit);
}

function boolVar(value, fallback = false) {
  const v = clean(value, 20).toLowerCase();
  if (!v) return fallback;
  return ["1", "true", "yes", "on"].includes(v);
}

function intVar(value, fallback, min, max) {
  const n = Number.parseInt(String(value ?? ""), 10);
  return Number.isFinite(n) ? Math.max(min, Math.min(max, n)) : fallback;
}

function cooldownDays(env) { return intVar(env?.A2A_FOLLOWUP_COOLDOWN_DAYS, 4, 1, 30); }
function maxFollowups(env) { return intVar(env?.A2A_FOLLOWUP_MAX, 2, 0, 5); }
function autoEnabled(env) {
  return boolVar(env?.A2A_AUTONOMOUS_OUTREACH, false) && boolVar(env?.A2A_AUTONOMOUS_FOLLOWUP, false);
}

function addDays(iso, days) {
  const d = new Date(iso || Date.now());
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString();
}

function isHttps(value) {
  try { return new URL(value).protocol === "https:"; } catch { return false; }
}

function withTimeout(ms) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort("timeout"), ms);
  return { signal: controller.signal, clear: () => clearTimeout(timer) };
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_followups (id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL, opportunity_id TEXT NOT NULL, sequence INTEGER NOT NULL, created_at TEXT NOT NULL, due_at TEXT NOT NULL, sent_at TEXT, updated_at TEXT NOT NULL, status TEXT NOT NULL, message TEXT NOT NULL, task_id TEXT, context_id TEXT, response_text TEXT, request_json TEXT, response_json TEXT, error TEXT, engine_version TEXT NOT NULL, UNIQUE(proposal_id,sequence))"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_followups_due ON lumen_followups(status,due_at)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_sales_pipeline (proposal_id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL, target TEXT, offer_name TEXT, amount_usd REAL NOT NULL DEFAULT 0, stage TEXT NOT NULL, response_class TEXT, last_contact_at TEXT, next_action TEXT, next_action_at TEXT, followup_count INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL, notes TEXT)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_sales_pipeline_stage ON lumen_sales_pipeline(stage,next_action_at)")
  ]);
  return true;
}

async function latestContact(env, proposalId, outreachUpdatedAt) {
  const row = await env.DB.prepare("SELECT sent_at FROM lumen_followups WHERE proposal_id=? AND sent_at IS NOT NULL ORDER BY sequence DESC LIMIT 1").bind(proposalId).first();
  return row?.sent_at || outreachUpdatedAt || null;
}

async function followupCount(env, proposalId) {
  const row = await env.DB.prepare("SELECT COUNT(*) AS n FROM lumen_followups WHERE proposal_id=? AND status IN ('SENT','SENT_TASK','WORKING','RESPONDED')").bind(proposalId).first();
  return Number(row?.n || 0);
}

async function syncPipeline(env) {
  if (!(await ensureSchema(env))) return { ok: false, error: "persistence_unavailable" };
  const rows = await env.DB.prepare("SELECT p.proposal_id,p.opportunity_id,p.status AS proposal_status,p.quality_gate_status,p.offer_name,p.amount_usd,p.message AS original_message,p.updated_at AS proposal_updated_at,o.name,x.status AS outreach_status,x.updated_at AS outreach_updated_at,x.response_text AS outreach_response,x.error AS outreach_error FROM lumen_proposal_drafts p JOIN lumen_opportunities o ON o.id=p.opportunity_id LEFT JOIN lumen_outreach_attempts x ON x.proposal_id=p.proposal_id WHERE p.quality_gate_status='PASS' ORDER BY p.updated_at DESC LIMIT 250").all();
  const now = new Date().toISOString();
  let tracked = 0;

  for (const row of rows.results || []) {
    const fuResponse = await env.DB.prepare("SELECT response_text FROM lumen_followups WHERE proposal_id=? AND response_text IS NOT NULL AND response_text<>'' ORDER BY sequence DESC LIMIT 1").bind(row.proposal_id).first();
    const responseText = fuResponse?.response_text || row.outreach_response || null;
    const classification = classifyCommercialResponse(responseText, row.original_message || "");
    const responseClass = classification.responseClass === "EMPTY" ? null : classification.responseClass;
    const count = await followupCount(env, row.proposal_id);
    const contactAt = await latestContact(env, row.proposal_id, row.outreach_updated_at || row.proposal_updated_at);
    const max = maxFollowups(env);
    let stage = classification.stage || "APPROVED";
    let nextAction = classification.nextAction || "await_initial_send";
    let nextActionAt = null;
    let notes = row.outreach_error || null;

    if (["TECHNICAL_ACK","ECHO","GENERIC_RESPONSE"].includes(responseClass)) {
      if (count >= max) {
        stage = "NO_RESPONSE";
        nextAction = "move_on";
        notes = `unqualified_response:${responseClass};followup_limit_reached`;
      } else {
        stage = "WAITING";
        nextAction = responseClass === "GENERIC_RESPONSE" ? `qualify_once_${count + 1}` : `follow_up_${count + 1}`;
        nextActionAt = addDays(contactAt || now, cooldownDays(env));
        notes = `unqualified_response:${responseClass};${classification.reason}`;
      }
    } else if (!responseClass) {
      const os = clean(row.outreach_status, 80).toUpperCase();
      const ps = clean(row.proposal_status, 80).toUpperCase();
      if (["SENT_TASK", "WORKING"].includes(os)) {
        stage = "WAITING_TASK";
        nextAction = "poll_task";
      } else if (os === "RESPONDED" || ps === "RESPONDED") {
        stage = "RESPONDED";
        nextAction = "qualify_response";
      } else if (["SEND_FAILED", "CARD_FETCH_FAILED", "INCOMPATIBLE", "AUTH_REQUIRED"].includes(os)) {
        stage = "BLOCKED";
        nextAction = "review_delivery_path";
      } else if (["SENT", "TASK_TERMINAL"].includes(os) || ps === "SENT") {
        if (count >= max) {
          stage = "NO_RESPONSE";
          nextAction = "move_on";
          notes = "followup_limit_reached";
        } else {
          stage = "WAITING";
          nextAction = `follow_up_${count + 1}`;
          nextActionAt = addDays(contactAt || now, cooldownDays(env));
        }
      } else if (ps === "APPROVED") {
        stage = "APPROVED";
        nextAction = "send_initial";
      } else {
        stage = "PROPOSAL";
        nextAction = "quality_or_send";
      }
    } else if (stage === "NEGOTIATING") {
      nextAction = classification.nextAction;
      notes = `qualified_response:${responseClass};${classification.reason}`;
    } else if (stage === "LOST") {
      nextAction = "close_and_move_on";
      notes = `terminal_response:${responseClass};${classification.reason}`;
    }

    await env.DB.prepare("INSERT INTO lumen_sales_pipeline(proposal_id,opportunity_id,target,offer_name,amount_usd,stage,response_class,last_contact_at,next_action,next_action_at,followup_count,updated_at,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(proposal_id) DO UPDATE SET target=excluded.target,offer_name=excluded.offer_name,amount_usd=excluded.amount_usd,stage=excluded.stage,response_class=excluded.response_class,last_contact_at=excluded.last_contact_at,next_action=excluded.next_action,next_action_at=excluded.next_action_at,followup_count=excluded.followup_count,updated_at=excluded.updated_at,notes=excluded.notes")
      .bind(row.proposal_id,row.opportunity_id,row.name || null,row.offer_name || null,Number(row.amount_usd || 0),stage,responseClass,contactAt,nextAction,nextActionAt,count,now,notes).run();
    tracked += 1;
  }
  return { ok: true, tracked, version: VERSION };
}

function followupMessage(row, sequence) {
  const offer = clean(row.offer_name, 120) || "the LUMEN offer";
  const amount = Number(row.amount_usd || 0);
  if (sequence === 1) {
    return clean(`Following up once on LUMEN's ${offer} note${amount ? ` (USD ${amount})` : ""}. If this is useful, reply with the requirement or scope you want checked and LUMEN can confirm the exact deliverable before checkout. This remains non-binding and creates no order, payment or commitment. If it is not relevant, no action is needed.`, 1800);
  }
  return clean(`Last follow-up from LUMEN regarding ${offer}${amount ? ` (USD ${amount})` : ""}. If useful, reply with the requirement or scope and LUMEN can confirm the exact deliverable before checkout. Otherwise this thread will be closed and LUMEN will not follow up again. This message is non-binding and creates no order, payment or commitment.`, 1800);
}

function envelope(row, message, sequence, env) {
  const id = `lumen-followup-${crypto.randomUUID()}`;
  const version = clean(row.protocol_version, 20) || "0.3.0";
  const isV1 = version.startsWith("1.");
  const msg = { messageId: id, role: isV1 ? "ROLE_USER" : "user", parts: [{ text: message }] };
  const metadata = { lumen: { proposalId: row.proposal_id, opportunityId: row.opportunity_id, followupSequence: sequence, checkoutUrl: clean(env?.X402_CHECKOUT_URL, 500) || null } };
  if (clean(row.protocol_binding, 40).toUpperCase() === "HTTP+JSON") {
    return { url: `${clean(row.agent_url, 1000).replace(/\/$/, "")}/message:send`, headers: { "content-type": "application/a2a+json", "accept": "application/a2a+json, application/json", "a2a-version": version }, payload: { message: msg, metadata } };
  }
  return { url: row.agent_url, headers: { "content-type": "application/json", "accept": "application/json", "a2a-version": version }, payload: { jsonrpc: "2.0", id, method: isV1 ? "SendMessage" : "message/send", params: { message: msg, metadata } } };
}

function extractResponse(body, binding) {
  const value = clean(binding, 40).toUpperCase() === "JSONRPC" ? (body?.result || body || {}) : (body || {});
  const task = value?.task || (value?.id && value?.status ? value : null);
  const message = value?.message || null;
  const parts = message?.parts || task?.status?.message?.parts || task?.artifacts?.flatMap?.(a => a?.parts || []) || [];
  return {
    taskId: clean(task?.id, 300) || null,
    contextId: clean(task?.contextId, 300) || clean(message?.contextId, 300) || null,
    responseText: clean((Array.isArray(parts) ? parts : []).map(p => p?.text || "").filter(Boolean).join(" "), 5000) || null,
    state: clean(task?.status?.state, 100) || null
  };
}

async function sendDueFollowup(env) {
  await syncPipeline(env);
  if (!autoEnabled(env)) return { ok: true, sent: false, reason: "autonomous_followup_disabled", version: VERSION };
  const now = new Date().toISOString();
  const row = await env.DB.prepare("SELECT s.proposal_id,s.opportunity_id,s.target,s.offer_name,s.amount_usd,s.followup_count,s.next_action_at,x.card_url,x.agent_url,x.protocol_binding,x.protocol_version,p.status AS proposal_status FROM lumen_sales_pipeline s JOIN lumen_outreach_attempts x ON x.proposal_id=s.proposal_id JOIN lumen_proposal_drafts p ON p.proposal_id=s.proposal_id WHERE s.stage='WAITING' AND s.next_action_at IS NOT NULL AND s.next_action_at<=? AND s.followup_count<? AND p.quality_gate_status='PASS' AND p.status IN ('SENT','RESPONDED') ORDER BY s.next_action_at ASC LIMIT 1").bind(now,maxFollowups(env)).first();
  if (!row) return { ok: true, sent: false, reason: "no_followup_due", version: VERSION };
  if (!isHttps(row.agent_url)) return { ok: false, sent: false, error: "agent_url_not_https", proposalId: row.proposal_id };

  const sequence = Number(row.followup_count || 0) + 1;
  const message = followupMessage(row, sequence);
  const id = `FUP-${row.proposal_id}-${sequence}`;
  const createdAt = now;
  await env.DB.prepare("INSERT INTO lumen_followups(id,proposal_id,opportunity_id,sequence,created_at,due_at,sent_at,updated_at,status,message,task_id,context_id,response_text,request_json,response_json,error,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(proposal_id,sequence) DO NOTHING")
    .bind(id,row.proposal_id,row.opportunity_id,sequence,createdAt,row.next_action_at,null,createdAt,"QUEUED",message,null,null,null,null,null,null,VERSION).run();

  const req = envelope(row, message, sequence, env);
  const timeout = withTimeout(SEND_TIMEOUT_MS);
  let raw = "";
  try {
    const response = await fetch(req.url, { method: "POST", headers: req.headers, body: JSON.stringify(req.payload), signal: timeout.signal });
    raw = await response.text();
    if (!response.ok) throw new Error(`followup_http_${response.status}`);
    let body = {}; try { body = JSON.parse(raw); } catch {}
    const info = extractResponse(body, row.protocol_binding);
    const status = info.responseText ? "RESPONDED" : info.taskId ? "SENT_TASK" : "SENT";
    await env.DB.prepare("UPDATE lumen_followups SET sent_at=?,updated_at=?,status=?,task_id=?,context_id=?,response_text=?,request_json=?,response_json=?,error=NULL WHERE id=?")
      .bind(now,now,status,info.taskId,info.contextId,info.responseText,JSON.stringify(req.payload),clean(raw,12000),id).run();
    if (info.responseText) await env.DB.prepare("UPDATE lumen_proposal_drafts SET status='RESPONDED',updated_at=? WHERE proposal_id=?").bind(now,row.proposal_id).run();
    await syncPipeline(env);
    return { ok: true, sent: true, version: VERSION, proposalId: row.proposal_id, sequence, status, responseText: info.responseText || null };
  } catch (error) {
    const err = clean(error?.message || error, 400);
    await env.DB.prepare("UPDATE lumen_followups SET updated_at=?,status='SEND_FAILED',response_json=?,error=? WHERE id=?").bind(now,clean(raw,12000),err,id).run();
    await syncPipeline(env);
    return { ok: false, sent: false, version: VERSION, proposalId: row.proposal_id, sequence, status: "SEND_FAILED", error: err };
  } finally { timeout.clear(); }
}

async function pollFollowupTasks(env) {
  if (!(await ensureSchema(env))) return { ok: false, error: "persistence_unavailable" };
  const rows = await env.DB.prepare("SELECT f.id,f.proposal_id,f.task_id,x.agent_url,x.protocol_binding,x.protocol_version FROM lumen_followups f JOIN lumen_outreach_attempts x ON x.proposal_id=f.proposal_id WHERE f.status IN ('SENT_TASK','WORKING') AND f.task_id IS NOT NULL ORDER BY f.updated_at ASC LIMIT 5").all();
  const results = [];
  for (const row of rows.results || []) {
    if (!isHttps(row.agent_url)) continue;
    const version = clean(row.protocol_version, 20) || "0.3.0";
    const isV1 = version.startsWith("1.");
    const timeout = withTimeout(SEND_TIMEOUT_MS);
    try {
      let response;
      if (clean(row.protocol_binding, 40).toUpperCase() === "HTTP+JSON") {
        response = await fetch(`${clean(row.agent_url,1000).replace(/\/$/,"")}/tasks/${encodeURIComponent(row.task_id)}`, { headers: { "accept": "application/a2a+json, application/json", "a2a-version": version }, signal: timeout.signal });
      } else {
        response = await fetch(row.agent_url, { method: "POST", headers: { "content-type": "application/json", "accept": "application/json", "a2a-version": version }, body: JSON.stringify({ jsonrpc:"2.0", id:`poll-${crypto.randomUUID()}`, method:isV1?"GetTask":"tasks/get", params:{ id:row.task_id, historyLength:5 } }), signal: timeout.signal });
      }
      const raw = await response.text();
      if (!response.ok) throw new Error(`poll_http_${response.status}`);
      let body = {}; try { body = JSON.parse(raw); } catch {}
      const info = extractResponse(body,row.protocol_binding);
      const terminal = ["TASK_STATE_COMPLETED","TASK_STATE_FAILED","TASK_STATE_CANCELED","TASK_STATE_REJECTED","completed","failed","canceled","rejected"].includes(info.state);
      const status = info.responseText ? "RESPONDED" : terminal ? "TASK_TERMINAL" : "WORKING";
      await env.DB.prepare("UPDATE lumen_followups SET updated_at=?,status=?,response_text=COALESCE(?,response_text),response_json=? WHERE id=?").bind(new Date().toISOString(),status,info.responseText,clean(raw,12000),row.id).run();
      if (info.responseText) await env.DB.prepare("UPDATE lumen_proposal_drafts SET status='RESPONDED',updated_at=? WHERE proposal_id=?").bind(new Date().toISOString(),row.proposal_id).run();
      results.push({ proposalId: row.proposal_id, status, responseText: info.responseText || null });
    } catch (error) {
      results.push({ proposalId: row.proposal_id, status: "POLL_FAILED", error: clean(error?.message || error, 300) });
    } finally { timeout.clear(); }
  }
  await syncPipeline(env);
  return { ok: true, polled: results.length, results, version: VERSION };
}

export async function processFollowupCycle(env) {
  const poll = await pollFollowupTasks(env);
  const sync = await syncPipeline(env);
  const send = await sendDueFollowup(env);
  return { ok: true, version: VERSION, poll, sync, send };
}

async function stats(env) {
  await syncPipeline(env);
  const counts = await env.DB.prepare("SELECT stage,COUNT(*) AS n FROM lumen_sales_pipeline GROUP BY stage").all();
  const due = await env.DB.prepare("SELECT COUNT(*) AS n FROM lumen_sales_pipeline WHERE stage='WAITING' AND next_action_at IS NOT NULL AND next_action_at<=?").bind(new Date().toISOString()).first();
  const sent = await env.DB.prepare("SELECT COUNT(*) AS n FROM lumen_followups WHERE status IN ('SENT','SENT_TASK','WORKING','RESPONDED')").first();
  const byStage = {}; for (const row of counts.results || []) byStage[row.stage] = Number(row.n || 0);
  return json({ version: VERSION, tracked: Object.values(byStage).reduce((a,b)=>a+b,0), byStage, followupsSent: Number(sent?.n || 0), dueNow: Number(due?.n || 0), cooldownDays: cooldownDays(env), maxFollowups: maxFollowups(env), sharedResponseQualification:true, autonomousFollowupEnabled: autoEnabled(env), autonomousOutgoingSpend: false, autonomousContract: false });
}

async function pipeline(env) {
  await syncPipeline(env);
  const rows = await env.DB.prepare("SELECT proposal_id,opportunity_id,target,offer_name,amount_usd,stage,response_class,last_contact_at,next_action,next_action_at,followup_count,updated_at,notes FROM lumen_sales_pipeline ORDER BY CASE stage WHEN 'NEGOTIATING' THEN 1 WHEN 'WAITING' THEN 2 WHEN 'RESPONDED' THEN 3 WHEN 'APPROVED' THEN 4 ELSE 5 END, COALESCE(next_action_at,updated_at) ASC LIMIT 100").all();
  return json({ version: VERSION, pipeline: rows.results || [], policy: { cooldownDays: cooldownDays(env), maxFollowups: maxFollowups(env), sharedResponseQualification:true, rawAckDoesNotBlockFollowup:true, oneExternalMessagePerCycle: true } });
}

function authorized(request, env) {
  const configured = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const provided = clean(request.headers.get("x-lumen-admin"), 500);
  return Boolean(configured && provided && configured === provided);
}

export async function handleFollowupEngine(request, env) {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/followup/stats") return stats(env);
  if (request.method === "GET" && url.pathname === "/followup/pipeline") return pipeline(env);
  if (request.method === "POST" && url.pathname === "/followup/run") {
    if (!authorized(request, env)) return json({ ok:false, error:"admin_token_required" },403);
    return json(await processFollowupCycle(env),202);
  }
  return null;
}