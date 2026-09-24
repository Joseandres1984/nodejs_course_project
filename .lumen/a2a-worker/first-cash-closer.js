import { buildTrackedCheckoutUrl } from "./commercial-checkout-link.js";
import { classifyCommercialResponse } from "./response-qualification.js";

const VERSION = "1.1-shared-response-first-cash-closer";
const SEND_TIMEOUT_MS = 15000;

function json(data, status = 200) {
  return Response.json(data, { status, headers: { "cache-control": "no-store", "x-content-type-options": "nosniff", "access-control-allow-origin": "*" } });
}
function clean(value, limit = 6000) { return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit); }
function boolVar(value, fallback = false) {
  const v = clean(value, 20).toLowerCase();
  if (!v) return fallback;
  return ["1", "true", "yes", "on"].includes(v);
}
function authorized(request, env) {
  const configured = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const provided = clean(request.headers.get("x-lumen-admin"), 500);
  return Boolean(configured && provided && configured === provided);
}
function isHttps(value) { try { return new URL(value).protocol === "https:"; } catch { return false; } }
function withTimeout(ms) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort("timeout"), ms);
  return { signal: controller.signal, clear: () => clearTimeout(timer) };
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_first_cash_closer (proposal_id TEXT PRIMARY KEY,opportunity_id TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,status TEXT NOT NULL,response_class TEXT NOT NULL,checkout_url TEXT,task_id TEXT,context_id TEXT,response_text TEXT,error TEXT,engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_first_cash_closer_status ON lumen_first_cash_closer(status,updated_at)")
  ]);
  return true;
}

async function candidateRows(env) {
  const primary = `SELECT p.proposal_id,p.opportunity_id,p.offer_id,p.offer_name,p.amount_usd,p.message,p.quality_gate_status,
    o.name AS target,x.agent_url,x.protocol_binding,x.protocol_version,x.context_id,
    COALESCE((SELECT f.response_text FROM lumen_followups f WHERE f.proposal_id=p.proposal_id AND f.response_text IS NOT NULL AND TRIM(f.response_text)<>'' ORDER BY COALESCE(f.sent_at,f.updated_at) DESC LIMIT 1),x.response_text) AS response_text
    FROM lumen_proposal_drafts p
    JOIN lumen_opportunities o ON o.id=p.opportunity_id
    JOIN lumen_outreach_attempts x ON x.proposal_id=p.proposal_id
    LEFT JOIN lumen_first_cash_closer c ON c.proposal_id=p.proposal_id
    WHERE p.quality_gate_status='PASS' AND c.proposal_id IS NULL AND x.agent_url IS NOT NULL
      AND (x.response_text IS NOT NULL OR EXISTS(SELECT 1 FROM lumen_followups f2 WHERE f2.proposal_id=p.proposal_id AND f2.response_text IS NOT NULL AND TRIM(f2.response_text)<>''))
    ORDER BY x.updated_at DESC LIMIT 100`;
  try { const r = await env.DB.prepare(primary).all(); return r.results || []; } catch {}

  const fallback = `SELECT p.proposal_id,p.opportunity_id,p.offer_id,p.offer_name,p.amount_usd,p.message,p.quality_gate_status,
    o.name AS target,x.agent_url,x.protocol_binding,x.protocol_version,x.context_id,x.response_text
    FROM lumen_proposal_drafts p
    JOIN lumen_opportunities o ON o.id=p.opportunity_id
    JOIN lumen_outreach_attempts x ON x.proposal_id=p.proposal_id
    LEFT JOIN lumen_first_cash_closer c ON c.proposal_id=p.proposal_id
    WHERE p.quality_gate_status='PASS' AND c.proposal_id IS NULL AND x.agent_url IS NOT NULL AND x.response_text IS NOT NULL
    ORDER BY x.updated_at DESC LIMIT 100`;
  try { const r = await env.DB.prepare(fallback).all(); return r.results || []; } catch { return []; }
}

async function findEligibleCandidate(env) {
  const rows = await candidateRows(env);
  for (const row of rows) {
    const qualification = classifyCommercialResponse(row.response_text, row.message);
    const closeEligible = ["PURCHASE_INTENT", "COMMERCIAL_INTEREST"].includes(qualification.responseClass);
    if (!closeEligible) continue;
    const checkoutUrl = buildTrackedCheckoutUrl(env, {
      offerId: row.offer_id,
      proposalId: row.proposal_id,
      opportunityId: row.opportunity_id,
      source: "lumen_a2a",
      medium: "first_cash_closer",
      creative: qualification.responseClass.toLowerCase()
    });
    if (!checkoutUrl || !isHttps(row.agent_url)) continue;
    return { ...row, responseClass: qualification.responseClass, qualificationReason: qualification.reason, checkoutUrl };
  }
  return null;
}

function closerMessage(row) {
  const offer = clean(row.offer_name, 140) || "this LUMEN service";
  const amount = Number(row.amount_usd || 0);
  return clean([
    `Thanks for the interest in ${offer}.`,
    `The exact price is USD ${amount.toFixed(2)} per request.`,
    `Direct x402 checkout for this exact offer: ${row.checkoutUrl}`,
    "No subscription, contract or additional commitment is created by this message. A purchase only occurs if the buyer signs the x402 payment authorization and settlement succeeds.",
    "If you want the scope clarified before paying, reply with the requirement and LUMEN can confirm the deliverable."
  ].join("\n\n"), 2400);
}

function envelope(row, text) {
  const id = `lumen-close-${crypto.randomUUID()}`;
  const version = clean(row.protocol_version, 20) || "0.3.0";
  const isV1 = version.startsWith("1.");
  const message = { messageId: id, role: isV1 ? "ROLE_USER" : "user", parts: [{ text }] };
  const metadata = {
    lumen: {
      proposalId: row.proposal_id,
      opportunityId: row.opportunity_id,
      offerId: row.offer_id,
      amountUsd: Number(row.amount_usd || 0),
      stage: "first_cash_close",
      checkoutUrl: row.checkoutUrl
    }
  };
  if (clean(row.protocol_binding, 40).toUpperCase() === "HTTP+JSON") {
    return {
      url: `${clean(row.agent_url, 1000).replace(/\/$/, "")}/message:send`,
      headers: { "content-type": "application/a2a+json", "accept": "application/a2a+json, application/json", "a2a-version": version },
      payload: { message, metadata }
    };
  }
  return {
    url: row.agent_url,
    headers: { "content-type": "application/json", "accept": "application/json", "a2a-version": version },
    payload: { jsonrpc: "2.0", id, method: isV1 ? "SendMessage" : "message/send", params: { message, metadata } }
  };
}

function extractResponse(body, binding) {
  const value = clean(binding, 40).toUpperCase() === "JSONRPC" ? (body?.result || body || {}) : (body || {});
  const task = value?.task || (value?.id && value?.status ? value : null);
  const message = value?.message || null;
  const parts = message?.parts || task?.status?.message?.parts || task?.artifacts?.flatMap?.(a => a?.parts || []) || [];
  return {
    taskId: clean(task?.id, 300) || null,
    contextId: clean(task?.contextId, 300) || clean(message?.contextId, 300) || null,
    responseText: clean((Array.isArray(parts) ? parts : []).map(p => p?.text || "").filter(Boolean).join(" "), 5000) || null
  };
}

async function record(env, row, values) {
  const now = new Date().toISOString();
  await env.DB.prepare("INSERT INTO lumen_first_cash_closer(proposal_id,opportunity_id,created_at,updated_at,status,response_class,checkout_url,task_id,context_id,response_text,error,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(proposal_id) DO UPDATE SET updated_at=excluded.updated_at,status=excluded.status,response_class=excluded.response_class,checkout_url=excluded.checkout_url,task_id=excluded.task_id,context_id=excluded.context_id,response_text=excluded.response_text,error=excluded.error,engine_version=excluded.engine_version")
    .bind(row.proposal_id,row.opportunity_id,now,now,values.status,row.responseClass,row.checkoutUrl,values.taskId||null,values.contextId||null,values.responseText||null,values.error||null,VERSION).run();
}

export async function runFirstCashCloser(env, { force = false } = {}) {
  if (!(await ensureSchema(env))) return { ok: false, sent: false, error: "persistence_unavailable", version: VERSION };
  const candidate = await findEligibleCandidate(env);
  if (!candidate) return { ok: true, sent: false, reason: "no_verified_commercial_intent", version: VERSION };

  const enabled = boolVar(env?.A2A_AUTONOMOUS_OUTREACH, false) && boolVar(env?.A2A_AUTONOMOUS_CONVERSION_CLOSE, false);
  if (!force && !enabled) {
    return { ok: true, sent: false, ready: true, proposalId: candidate.proposal_id, responseClass: candidate.responseClass, reason: "autonomous_conversion_close_disabled", version: VERSION };
  }

  const text = closerMessage(candidate);
  const req = envelope(candidate, text);
  const timeout = withTimeout(SEND_TIMEOUT_MS);
  let raw = "";
  try {
    const response = await fetch(req.url, { method: "POST", headers: req.headers, body: JSON.stringify(req.payload), signal: timeout.signal });
    raw = await response.text();
    if (!response.ok) throw new Error(`first_cash_close_http_${response.status}`);
    let body = {}; try { body = JSON.parse(raw); } catch {}
    const info = extractResponse(body, candidate.protocol_binding);
    const status = info.responseText ? "RESPONDED" : info.taskId ? "SENT_TASK" : "SENT";
    await record(env, candidate, { status, ...info });
    return {
      ok: true,
      sent: true,
      version: VERSION,
      proposalId: candidate.proposal_id,
      opportunityId: candidate.opportunity_id,
      offerId: candidate.offer_id,
      amountUsd: Number(candidate.amount_usd || 0),
      responseClass: candidate.responseClass,
      qualificationReason: candidate.qualificationReason,
      status,
      taskId: info.taskId,
      checkoutUrl: candidate.checkoutUrl,
      guardrails: { positiveIntentRequired: true, sharedResponseQualification: true, exactOfferCheckout: true, autonomousDiscounting: false, autonomousSpend: false, bindingActionsHumanGated: true }
    };
  } catch (error) {
    const err = clean(error?.message || error, 500);
    await record(env, candidate, { status: "SEND_FAILED", error: err });
    return { ok: false, sent: false, version: VERSION, proposalId: candidate.proposal_id, status: "SEND_FAILED", error: err };
  } finally { timeout.clear(); }
}

async function statsData(env) {
  await ensureSchema(env);
  let row = null;
  try { row = await env.DB.prepare("SELECT COUNT(*) total,SUM(CASE WHEN status IN ('SENT','SENT_TASK','RESPONDED') THEN 1 ELSE 0 END) sent,SUM(CASE WHEN status='RESPONDED' THEN 1 ELSE 0 END) responded,SUM(CASE WHEN status='SEND_FAILED' THEN 1 ELSE 0 END) failed FROM lumen_first_cash_closer").first(); } catch {}
  const candidate = await findEligibleCandidate(env);
  return {
    total: Number(row?.total || 0),
    sent: Number(row?.sent || 0),
    responded: Number(row?.responded || 0),
    failed: Number(row?.failed || 0),
    readyToClose: Boolean(candidate),
    readyProposalId: candidate?.proposal_id || null,
    readyResponseClass: candidate?.responseClass || null,
    autonomousEnabled: boolVar(env?.A2A_AUTONOMOUS_OUTREACH, false) && boolVar(env?.A2A_AUTONOMOUS_CONVERSION_CLOSE, false)
  };
}

export async function handleFirstCashCloser(request, env) {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/first-cash/policy") {
    return json({ version: VERSION, name: "LUMEN First Cash Closer", positiveIntentRequired: true, sharedResponseQualification: true, checkoutEligibleClasses:["PURCHASE_INTENT","COMMERCIAL_INTEREST"], technicalAckIsNotIntent: true, echoIsNotIntent:true, genericResponseIsNotIntent:true, exactOfferCheckout: true, trackedAttribution: true, maxExternalMessagesPerRun: 1, autonomousDiscounting: false, autonomousSpend: false, autonomousContract: false, bindingActionsHumanGated: true });
  }
  if (request.method === "GET" && url.pathname === "/first-cash/stats") return json({ version: VERSION, ...await statsData(env) });
  if (request.method === "POST" && url.pathname === "/first-cash/run") {
    if (!authorized(request, env)) return json({ ok: false, error: "admin_token_required" }, 403);
    return json(await runFirstCashCloser(env, { force: false }), 202);
  }
  return null;
}