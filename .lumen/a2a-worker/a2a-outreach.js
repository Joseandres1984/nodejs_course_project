import { getFirstSettlementMissionStatus } from "./first-settlement-mission-v1.js";
const VERSION = "2.0-closer-swarm";
const CARD_TIMEOUT_MS = 8000;
const SEND_TIMEOUT_MS = 15000;
const MAX_CLOSERS_PER_CYCLE = 30;
const CLOSER_CONCURRENT_WAVE = 5;
const MAX_NEW_OUTREACH_24H = 120;
const DOMAIN_COOLDOWN_HOURS = 24;

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

function clean(value, limit = 6000) {
  return String(value ?? "").trim().replace(/\s+/g, " ").slice(0, limit);
}

function safeParse(value, fallback = {}) {
  try { return JSON.parse(value || ""); } catch { return fallback; }
}

function isHttps(value) {
  try { return new URL(value).protocol === "https:"; } catch { return false; }
}

function normalizeBaseUrl(value) {
  const url = new URL(value);
  url.hash = "";
  url.search = "";
  return url.toString().replace(/\/$/, "");
}

function outreachOrigin(value) {
  try { return new URL(value).origin.toLowerCase(); } catch { return ""; }
}

function withTimeout(ms) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort("timeout"), ms);
  return { signal: controller.signal, clear: () => clearTimeout(timer) };
}

async function ensureSchema(env) {
  if (!env?.DB) return false;
  await env.DB.batch([
    env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_outreach_attempts (proposal_id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, status TEXT NOT NULL, card_url TEXT, agent_url TEXT, protocol_binding TEXT, protocol_version TEXT, task_id TEXT, context_id TEXT, response_text TEXT, request_json TEXT, response_json TEXT, error TEXT, engine_version TEXT NOT NULL)"),
    env.DB.prepare("CREATE INDEX IF NOT EXISTS idx_lumen_outreach_attempts_status ON lumen_outreach_attempts(status,updated_at)")
  ]);
  return true;
}

async function preferredOpportunityId(env) {
  try {
    const status=await getFirstSettlementMissionStatus(env);
    return clean(status?.mission?.focus?.opportunity_id,120)||null;
  } catch { return null; }
}

async function getNextApproved(env) {
  const preferred=await preferredOpportunityId(env);
  return env.DB.prepare("SELECT p.proposal_id,p.opportunity_id,p.offer_id,p.offer_name,p.amount_usd,p.subject,p.message,p.metadata_json,o.name,o.endpoint FROM lumen_proposal_drafts p JOIN lumen_opportunities o ON o.id=p.opportunity_id LEFT JOIN lumen_outreach_attempts x ON x.proposal_id=p.proposal_id WHERE p.status='APPROVED' AND p.quality_gate_status='PASS' AND (x.proposal_id IS NULL OR (x.status IN ('CARD_FETCH_FAILED','SEND_FAILED') AND datetime(x.updated_at)<=datetime('now','-6 hours'))) ORDER BY CASE WHEN p.opportunity_id=? THEN 0 ELSE 1 END,p.updated_at ASC LIMIT 1").bind(preferred||"").first();
}

function hasRequiredAuth(card) {
  const requirements = card?.securityRequirements;
  if (Array.isArray(requirements) && requirements.length > 0) return true;
  const legacy = card?.security;
  return Array.isArray(legacy) && legacy.length > 0;
}

function selectInterfaces(card) {
  const selected = [];
  const seen = new Set();
  const add = (entry) => {
    if (!entry?.url || !entry?.binding) return;
    const key = `${entry.binding}|${entry.url}|${entry.version}`;
    if (seen.has(key)) return;
    seen.add(key);
    selected.push(entry);
  };
  const interfaces = Array.isArray(card?.supportedInterfaces) ? card.supportedInterfaces : [];
  for (const entry of interfaces) {
    const binding = clean(entry?.protocolBinding, 80).toUpperCase();
    if (!isHttps(entry?.url)) continue;
    if (binding === "JSONRPC" || binding === "HTTP+JSON") {
      add({
        url: normalizeBaseUrl(entry.url),
        binding,
        version: clean(entry?.protocolVersion || "1.0", 20),
        tenant: clean(entry?.tenant, 200) || null
      });
    }
  }
  if (isHttps(card?.url)) {
    const transport = clean(card?.preferredTransport || card?.transport || "JSONRPC", 80).toUpperCase();
    if (["JSONRPC", "JSON-RPC", "HTTP+JSON"].includes(transport)) {
      add({
        url: normalizeBaseUrl(card.url),
        binding: transport === "HTTP+JSON" ? "HTTP+JSON" : "JSONRPC",
        version: clean(card?.protocolVersion || "0.3", 20),
        tenant: null
      });
    }
  }
  return selected;
}

async function fetchAgentCard(cardUrl) {
  if (!isHttps(cardUrl)) return { ok: false, status: "INCOMPATIBLE", error: "card_url_not_https" };
  const timeout = withTimeout(CARD_TIMEOUT_MS);
  try {
    const response = await fetch(cardUrl, {
      method: "GET",
      headers: { "accept": "application/json, application/a2a+json" },
      signal: timeout.signal
    });
    const text = await response.text();
    if (!response.ok) return { ok: false, status: "CARD_FETCH_FAILED", error: `card_http_${response.status}`, raw: clean(text, 2000) };
    let card;
    try { card = JSON.parse(text); } catch { return { ok: false, status: "CARD_FETCH_FAILED", error: "card_invalid_json" }; }
    if (hasRequiredAuth(card)) return { ok: false, status: "AUTH_REQUIRED", error: "agent_requires_authentication", card };
    const interfaces = selectInterfaces(card);
    if (!interfaces.length) return { ok: false, status: "INCOMPATIBLE", error: "no_supported_public_a2a_interface", card };
    return { ok: true, status: "READY", card, selected: interfaces[0], interfaces };
  } catch (error) {
    return { ok: false, status: "CARD_FETCH_FAILED", error: clean(error?.message || error, 300) };
  } finally {
    timeout.clear();
  }
}

function messageEnvelope(row, iface, env) {
  const messageId = `lumen-${crypto.randomUUID()}`;
  const checkoutUrl = clean(env?.X402_CHECKOUT_URL, 500) || null;
  const baseMessage = clean(row.message, 1800);
  const checkoutLine = checkoutUrl
    ? `If the requirement is confirmed, LUMEN can return the exact scope and x402 checkout at ${checkoutUrl}.`
    : "If the requirement is confirmed, LUMEN can return the exact scope and checkout details.";
  const text = clean(`${baseMessage}\n\n${checkoutLine}\n\nIf this is not relevant, no action is needed.`, 2400);
  const isV1 = String(iface.version || "").startsWith("1.");
  const role = isV1 ? "ROLE_USER" : "user";
  const message = { messageId, role, parts: [{ text }] };
  const metadata = {
    lumen: {
      proposalId: row.proposal_id,
      opportunityId: row.opportunity_id,
      offerId: row.offer_id,
      amountUsd: Number(row.amount_usd || 0),
      checkoutUrl
    }
  };

  if (iface.binding === "HTTP+JSON") {
    const payload = { message, metadata };
    if (iface.tenant) payload.tenant = iface.tenant;
    return {
      messageId,
      url: `${iface.url}/message:send`,
      headers: {
        "content-type": "application/a2a+json",
        "accept": "application/a2a+json, application/json",
        "a2a-version": iface.version || "1.0"
      },
      payload
    };
  }

  const params = { message, metadata };
  if (iface.tenant) params.tenant = iface.tenant;
  return {
    messageId,
    url: iface.url,
    headers: {
      "content-type": "application/json",
      "accept": "application/json",
      "a2a-version": iface.version || (isV1 ? "1.0" : "0.3")
    },
    payload: {
      jsonrpc: "2.0",
      id: messageId,
      method: isV1 ? "SendMessage" : "message/send",
      params
    }
  };
}

function unwrapResponse(body, binding) {
  if (binding === "JSONRPC") return body?.result || body;
  return body;
}

function extractTaskInfo(body, binding) {
  const value = unwrapResponse(body, binding) || {};
  const task = value.task || (value.id && value.status ? value : null);
  const message = value.message || null;
  const taskId = clean(task?.id, 300) || null;
  const contextId = clean(task?.contextId, 300) || clean(message?.contextId, 300) || null;
  const state = clean(task?.status?.state, 100) || null;
  const parts = message?.parts || task?.status?.message?.parts || task?.artifacts?.flatMap?.(a => a?.parts || []) || [];
  const responseText = clean((Array.isArray(parts) ? parts : []).map(part => part?.text || "").filter(Boolean).join(" "), 5000) || null;
  return { taskId, contextId, state, responseText, hasMessage: Boolean(message || responseText) };
}

async function recordProbe(env, row, probe) {
  const now = new Date().toISOString();
  const selected = probe?.selected || null;
  await env.DB.prepare("INSERT INTO lumen_outreach_attempts(proposal_id,opportunity_id,created_at,updated_at,status,card_url,agent_url,protocol_binding,protocol_version,task_id,context_id,response_text,request_json,response_json,error,engine_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(proposal_id) DO UPDATE SET updated_at=excluded.updated_at,status=excluded.status,card_url=excluded.card_url,agent_url=excluded.agent_url,protocol_binding=excluded.protocol_binding,protocol_version=excluded.protocol_version,error=excluded.error,engine_version=excluded.engine_version")
    .bind(row.proposal_id, row.opportunity_id, now, now, probe.ok ? "READY" : probe.status, row.endpoint || null, selected?.url || null, selected?.binding || null, selected?.version || null, null, null, null, null, null, probe.ok ? null : probe.error, VERSION).run();
}

export async function probeNextApproved(env) {
  if (!(await ensureSchema(env))) return { ok: false, error: "persistence_unavailable" };
  const row = await getNextApproved(env);
  if (!row) return { ok: true, probed: false, reason: "no_approved_unsent_proposal", version: VERSION };
  const probe = await fetchAgentCard(row.endpoint);
  await recordProbe(env, row, probe);
  return {
    ok: true,
    probed: true,
    version: VERSION,
    proposalId: row.proposal_id,
    target: row.name,
    status: probe.ok ? "READY" : probe.status,
    protocol: probe.selected ? { binding: probe.selected.binding, version: probe.selected.version } : null,
    error: probe.ok ? null : probe.error,
    autonomousOutreachEnabled: String(env?.A2A_AUTONOMOUS_OUTREACH || "false").toLowerCase() === "true",
    nextAction: probe.ok ? "send_if_enabled_or_human_triggered" : "do_not_send"
  };
}

async function getReadyAttempt(env) {
  const preferred=await preferredOpportunityId(env);
  if(preferred){
    const priorityReady=await env.DB.prepare("SELECT x.proposal_id,x.opportunity_id,x.card_url,x.agent_url,x.protocol_binding,x.protocol_version,p.offer_id,p.offer_name,p.amount_usd,p.subject,p.message,p.metadata_json,o.name FROM lumen_outreach_attempts x JOIN lumen_proposal_drafts p ON p.proposal_id=x.proposal_id JOIN lumen_opportunities o ON o.id=p.opportunity_id WHERE x.status='READY' AND p.status='APPROVED' AND p.quality_gate_status='PASS' AND p.opportunity_id=? ORDER BY x.updated_at ASC LIMIT 1").bind(preferred).first();
    if(priorityReady) return priorityReady;
    const priorityPending=await env.DB.prepare("SELECT p.proposal_id FROM lumen_proposal_drafts p LEFT JOIN lumen_outreach_attempts x ON x.proposal_id=p.proposal_id WHERE p.status='APPROVED' AND p.quality_gate_status='PASS' AND p.opportunity_id=? AND (x.proposal_id IS NULL OR (x.status IN ('CARD_FETCH_FAILED','SEND_FAILED') AND datetime(x.updated_at)<=datetime('now','-6 hours'))) LIMIT 1").bind(preferred).first();
    if(priorityPending) return null;
  }
  return env.DB.prepare("SELECT x.proposal_id,x.opportunity_id,x.card_url,x.agent_url,x.protocol_binding,x.protocol_version,p.offer_id,p.offer_name,p.amount_usd,p.subject,p.message,p.metadata_json,o.name FROM lumen_outreach_attempts x JOIN lumen_proposal_drafts p ON p.proposal_id=x.proposal_id JOIN lumen_opportunities o ON o.id=p.opportunity_id WHERE x.status='READY' AND p.status='APPROVED' AND p.quality_gate_status='PASS' ORDER BY x.updated_at ASC LIMIT 1").first();
}

async function sentLast24h(env) {
  const row = await env.DB.prepare("SELECT COUNT(*) AS n FROM lumen_outreach_attempts WHERE status IN ('SENT','SENT_TASK','WORKING','RESPONDED','TASK_TERMINAL') AND datetime(updated_at)>=datetime('now','-24 hours')").first();
  return Number(row?.n || 0);
}

async function getReadyAttempts(env, limit = MAX_CLOSERS_PER_CYCLE) {
  const recent = await env.DB.prepare("SELECT card_url,agent_url FROM lumen_outreach_attempts WHERE status IN ('SENT','SENT_TASK','WORKING','RESPONDED','TASK_TERMINAL') AND datetime(updated_at)>=datetime('now','-24 hours') ORDER BY updated_at DESC LIMIT 500").all();
  const blockedOrigins = new Set();
  for (const row of recent.results || []) {
    const origin = outreachOrigin(row.agent_url || row.card_url);
    if (origin) blockedOrigins.add(origin);
  }

  const candidates = await env.DB.prepare("SELECT x.proposal_id,x.opportunity_id,x.card_url,x.agent_url,x.protocol_binding,x.protocol_version,p.offer_id,p.offer_name,p.amount_usd,p.subject,p.message,p.metadata_json,o.name FROM lumen_outreach_attempts x JOIN lumen_proposal_drafts p ON p.proposal_id=x.proposal_id JOIN lumen_opportunities o ON o.id=p.opportunity_id WHERE x.status='READY' AND p.status='APPROVED' AND p.quality_gate_status='PASS' ORDER BY x.updated_at ASC LIMIT 240").all();
  const selected = [];
  const seenOrigins = new Set();
  const seenOpportunities = new Set();
  for (const row of candidates.results || []) {
    const origin = outreachOrigin(row.agent_url || row.card_url);
    if (!origin || blockedOrigins.has(origin) || seenOrigins.has(origin) || seenOpportunities.has(row.opportunity_id)) continue;
    seenOrigins.add(origin);
    seenOpportunities.add(row.opportunity_id);
    selected.push(row);
    if (selected.length >= limit) break;
  }
  return selected;
}

async function claimReadyAttempts(env, rows) {
  const claimed = [];
  for (const row of rows) {
    const result = await env.DB.prepare("UPDATE lumen_outreach_attempts SET status='CLAIMED',updated_at=? WHERE proposal_id=? AND status='READY'")
      .bind(new Date().toISOString(), row.proposal_id).run();
    if (Number(result?.meta?.changes || 0) > 0) claimed.push(row);
  }
  return claimed;
}

export async function sendApprovedBatch(env, { force = false, limit = MAX_CLOSERS_PER_CYCLE } = {}) {
  if (!(await ensureSchema(env))) return { ok: false, error: "persistence_unavailable", version: VERSION };
  const autoEnabled = String(env?.A2A_AUTONOMOUS_OUTREACH || "false").toLowerCase() === "true";
  if (!force && !autoEnabled) {
    return { ok: true, attempted: 0, sent: 0, reason: "autonomous_outreach_disabled", version: VERSION };
  }

  const dailyUsed = await sentLast24h(env);
  const dailyRemaining = Math.max(0, MAX_NEW_OUTREACH_24H - dailyUsed);
  const requested = Math.max(0, Math.min(Number(limit || 0), MAX_CLOSERS_PER_CYCLE, dailyRemaining));
  if (requested < 1) {
    return { ok: true, attempted: 0, sent: 0, reason: "daily_new_outreach_cap_reached", dailyUsed, dailyRemaining, version: VERSION };
  }

  const ready = await getReadyAttempts(env, requested);
  const claimed = await claimReadyAttempts(env, ready);
  const results = [];
  for (let offset = 0; offset < claimed.length; offset += CLOSER_CONCURRENT_WAVE) {
    const wave = claimed.slice(offset, offset + CLOSER_CONCURRENT_WAVE);
    const waveResults = await Promise.all(wave.map(row => sendReady(env, row)));
    results.push(...waveResults);
  }
  const sent = results.filter(row => row?.sent === true).length;
  const responded = results.filter(row => row?.status === "RESPONDED").length;
  const failed = results.filter(row => row?.ok === false).length;
  return {
    ok: failed < results.length || results.length === 0,
    version: VERSION,
    closerCapacity: MAX_CLOSERS_PER_CYCLE,
    concurrentCloserWave: CLOSER_CONCURRENT_WAVE,
    dailyNewOutreachCap: MAX_NEW_OUTREACH_24H,
    domainCooldownHours: DOMAIN_COOLDOWN_HOURS,
    dailyUsedBefore: dailyUsed,
    dailyRemainingBefore: dailyRemaining,
    attempted: results.length,
    sent,
    responded,
    failed,
    results
  };
}

async function sendReady(env, row) {
  const cardProbe = await fetchAgentCard(row.card_url);
  if (!cardProbe.ok) {
    await env.DB.prepare("UPDATE lumen_outreach_attempts SET updated_at=?,status=?,error=? WHERE proposal_id=?")
      .bind(new Date().toISOString(), cardProbe.status, cardProbe.error, row.proposal_id).run();
    return { ok: false, sent: false, status: cardProbe.status, error: cardProbe.error };
  }

  const interfaces = Array.isArray(cardProbe.interfaces) && cardProbe.interfaces.length
    ? cardProbe.interfaces.slice(0, 3)
    : [cardProbe.selected];
  const transportErrors = [];
  for (let index = 0; index < interfaces.length; index++) {
    const iface = interfaces[index];
    const envelope = messageEnvelope(row, iface, env);
    const timeout = withTimeout(SEND_TIMEOUT_MS);
    let responseText = "";
    let responseStatus = 0;
    try {
      const response = await fetch(envelope.url, {
        method: "POST",
        headers: envelope.headers,
        body: JSON.stringify(envelope.payload),
        signal: timeout.signal
      });
      responseStatus = response.status;
      responseText = await response.text();

      if (!response.ok) {
        const retryableTransportMismatch = [404,405,415,426].includes(response.status);
        transportErrors.push(`${iface.binding}@${iface.url}:http_${response.status}`);
        if (retryableTransportMismatch && index < interfaces.length - 1) continue;
        throw new Error(`send_http_${response.status}`);
      }

      let body = {};
      try { body = JSON.parse(responseText); } catch {}
      const info = extractTaskInfo(body, iface.binding);
      const now = new Date().toISOString();
      const status = info.hasMessage ? "RESPONDED" : info.taskId ? "SENT_TASK" : "SENT";

      await env.DB.prepare("UPDATE lumen_outreach_attempts SET updated_at=?,status=?,agent_url=?,protocol_binding=?,protocol_version=?,task_id=?,context_id=?,response_text=?,request_json=?,response_json=?,error=NULL WHERE proposal_id=?")
        .bind(now, status, iface.url, iface.binding, iface.version, info.taskId, info.contextId, info.responseText, JSON.stringify(envelope.payload), clean(responseText, 12000), row.proposal_id).run();
      await env.DB.prepare("UPDATE lumen_proposal_drafts SET status=?,updated_at=? WHERE proposal_id=?")
        .bind(info.hasMessage ? "RESPONDED" : "SENT", now, row.proposal_id).run();

      return {
        ok: true,
        sent: true,
        proposalId: row.proposal_id,
        status,
        taskId: info.taskId,
        responseText: info.responseText,
        checkoutReady: Boolean(clean(env?.X402_CHECKOUT_URL, 500)),
        transport: { binding: iface.binding, version: iface.version, fallbackIndex: index }
      };
    } catch (error) {
      const err = clean(error?.message || error, 500);
      const retryableTransportMismatch = [404,405,415,426].includes(responseStatus);
      if (retryableTransportMismatch && index < interfaces.length - 1) {
        transportErrors.push(`${iface.binding}@${iface.url}:${err}`);
        continue;
      }
      const now = new Date().toISOString();
      const combined = clean([...transportErrors, err].filter(Boolean).join(";"), 1000);
      await env.DB.prepare("UPDATE lumen_outreach_attempts SET updated_at=?,status='SEND_FAILED',response_json=?,error=? WHERE proposal_id=?")
        .bind(now, clean(responseText, 12000), combined, row.proposal_id).run();
      return { ok: false, sent: false, status: "SEND_FAILED", error: combined };
    } finally {
      timeout.clear();
    }
  }
  const now = new Date().toISOString();
  const combined = clean(transportErrors.join(";"), 1000) || "no_working_public_a2a_transport";
  await env.DB.prepare("UPDATE lumen_outreach_attempts SET updated_at=?,status='SEND_FAILED',error=? WHERE proposal_id=?")
    .bind(now, combined, row.proposal_id).run();
  return { ok:false, sent:false, status:"SEND_FAILED", error:combined };
}

export async function sendNextApproved(env, { force = false } = {}) {
  if (!(await ensureSchema(env))) return { ok: false, error: "persistence_unavailable" };
  let row = await getReadyAttempt(env);
  if (!row) {
    const probe = await probeNextApproved(env);
    if (!probe?.probed || probe?.status !== "READY") return { ...probe, sent: false };
    row = await getReadyAttempt(env);
  }
  if (!row) return { ok: true, sent: false, reason: "no_ready_proposal", version: VERSION };

  const autoEnabled = String(env?.A2A_AUTONOMOUS_OUTREACH || "false").toLowerCase() === "true";
  if (!force && !autoEnabled) {
    return {
      ok: true,
      sent: false,
      ready: true,
      proposalId: row.proposal_id,
      reason: "autonomous_outreach_disabled",
      nextAction: "human_trigger_or_enable_guarded_autonomy"
    };
  }
  return sendReady(env, row);
}

function responseState(body, binding) {
  const info = extractTaskInfo(body, binding);
  const terminal = ["TASK_STATE_COMPLETED","TASK_STATE_FAILED","TASK_STATE_CANCELED","TASK_STATE_REJECTED","completed","failed","canceled","rejected"].includes(info.state);
  return { ...info, terminal };
}

async function pollOne(env, row) {
  if (!row.task_id || !row.agent_url) return { polled: false };
  const isV1 = String(row.protocol_version || "").startsWith("1.");
  const timeout = withTimeout(SEND_TIMEOUT_MS);
  try {
    let response;
    if (row.protocol_binding === "HTTP+JSON") {
      response = await fetch(`${normalizeBaseUrl(row.agent_url)}/tasks/${encodeURIComponent(row.task_id)}`, {
        method: "GET",
        headers: { "accept": "application/a2a+json, application/json", "a2a-version": row.protocol_version || "1.0" },
        signal: timeout.signal
      });
    } else {
      response = await fetch(row.agent_url, {
        method: "POST",
        headers: { "content-type": "application/json", "accept": "application/json", "a2a-version": row.protocol_version || (isV1 ? "1.0" : "0.3") },
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: `poll-${crypto.randomUUID()}`,
          method: isV1 ? "GetTask" : "tasks/get",
          params: isV1 ? { id: row.task_id, historyLength: 5 } : { id: row.task_id, historyLength: 5 }
        }),
        signal: timeout.signal
      });
    }
    const text = await response.text();
    if (!response.ok) throw new Error(`poll_http_${response.status}`);
    let body = {};
    try { body = JSON.parse(text); } catch {}
    const state = responseState(body, row.protocol_binding);
    const now = new Date().toISOString();
    const status = state.responseText ? "RESPONDED" : state.terminal ? "TASK_TERMINAL" : "WORKING";
    await env.DB.prepare("UPDATE lumen_outreach_attempts SET updated_at=?,status=?,response_text=COALESCE(?,response_text),response_json=? WHERE proposal_id=?")
      .bind(now, status, state.responseText, clean(text, 12000), row.proposal_id).run();
    if (state.responseText) {
      await env.DB.prepare("UPDATE lumen_proposal_drafts SET status='RESPONDED',updated_at=? WHERE proposal_id=?")
        .bind(now, row.proposal_id).run();
    }
    return { polled: true, proposalId: row.proposal_id, status, responseText: state.responseText };
  } catch (error) {
    return { polled: true, proposalId: row.proposal_id, status: "POLL_FAILED", error: clean(error?.message || error, 300) };
  } finally {
    timeout.clear();
  }
}

export async function pollOutstandingResponses(env) {
  if (!(await ensureSchema(env))) return { ok: false, error: "persistence_unavailable" };
  const rows = await env.DB.prepare("SELECT proposal_id,task_id,agent_url,protocol_binding,protocol_version FROM lumen_outreach_attempts WHERE status IN ('SENT_TASK','WORKING') AND task_id IS NOT NULL ORDER BY updated_at ASC LIMIT 5").all();
  const results = [];
  for (const row of rows.results || []) results.push(await pollOne(env, row));
  return { ok: true, version: VERSION, polled: results.length, results };
}

export async function processOutreachCycle(env) {
  const poll = await pollOutstandingResponses(env);
  const send = await sendNextApproved(env, { force: false });
  return { ok: true, version: VERSION, poll, send };
}

async function outreachStats(env) {
  await ensureSchema(env);
  const total = await env.DB.prepare("SELECT COUNT(*) AS n FROM lumen_outreach_attempts").first();
  const ready = await env.DB.prepare("SELECT COUNT(*) AS n FROM lumen_outreach_attempts WHERE status='READY'").first();
  const sent = await env.DB.prepare("SELECT COUNT(*) AS n FROM lumen_outreach_attempts WHERE status IN ('SENT','SENT_TASK','WORKING','RESPONDED','TASK_TERMINAL')").first();
  const responded = await env.DB.prepare("SELECT COUNT(*) AS n FROM lumen_outreach_attempts WHERE status='RESPONDED'").first();
  return json({
    version: VERSION,
    totalAttempts: Number(total?.n || 0),
    ready: Number(ready?.n || 0),
    sent: Number(sent?.n || 0),
    responded: Number(responded?.n || 0),
    closerCapacity: MAX_CLOSERS_PER_CYCLE,
    concurrentCloserWave: CLOSER_CONCURRENT_WAVE,
    dailyNewOutreachCap: MAX_NEW_OUTREACH_24H,
    domainCooldownHours: DOMAIN_COOLDOWN_HOURS,
    dedupePolicy: "one_opportunity_per_closer_and_one_origin_per_24h",
    autonomousOutreachEnabled: String(env?.A2A_AUTONOMOUS_OUTREACH || "false").toLowerCase() === "true",
    autonomousOutgoingSpend: false,
    autonomousContract: false
  });
}

async function outreachNext(env) {
  await ensureSchema(env);
  const row = await env.DB.prepare("SELECT x.proposal_id,x.opportunity_id,x.status,x.card_url,x.agent_url,x.protocol_binding,x.protocol_version,x.task_id,x.response_text,x.error,p.offer_name,p.amount_usd,o.name FROM lumen_outreach_attempts x JOIN lumen_proposal_drafts p ON p.proposal_id=x.proposal_id JOIN lumen_opportunities o ON o.id=p.opportunity_id ORDER BY x.updated_at DESC LIMIT 1").first();
  return json({
    version: VERSION,
    outreach: row ? {
      proposalId: row.proposal_id,
      opportunityId: row.opportunity_id,
      target: row.name,
      status: row.status,
      protocol: row.protocol_binding ? { binding: row.protocol_binding, version: row.protocol_version } : null,
      taskId: row.task_id || null,
      responseText: row.response_text || null,
      error: row.error || null,
      offerName: row.offer_name,
      amountUsd: Number(row.amount_usd || 0)
    } : null,
    nextAction: row?.status === "READY" ? "send_if_authorized" : row?.status === "RESPONDED" ? "qualify_response_then_checkout" : "continue_pipeline"
  });
}

function authorized(request, env) {
  const configured = clean(env?.OPPORTUNITY_ADMIN_TOKEN, 500);
  const provided = clean(request.headers.get("x-lumen-admin"), 500);
  return Boolean(configured && provided && configured === provided);
}

export async function handleA2AOutreach(request, env) {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/outreach/stats") return outreachStats(env);
  if (request.method === "GET" && url.pathname === "/outreach/next") return outreachNext(env);

  if (request.method === "POST" && ["/outreach/probe-next","/outreach/send-next","/outreach/send-batch","/outreach/poll"].includes(url.pathname)) {
    if (!authorized(request, env)) return json({ ok: false, error: "admin_token_required" }, 403);
    if (url.pathname === "/outreach/probe-next") return json(await probeNextApproved(env), 202);
    if (url.pathname === "/outreach/send-next") return json(await sendNextApproved(env, { force: true }), 202);
    if (url.pathname === "/outreach/send-batch") return json(await sendApprovedBatch(env, { force: true, limit: MAX_CLOSERS_PER_CYCLE }), 202);
    if (url.pathname === "/outreach/poll") return json(await pollOutstandingResponses(env), 202);
  }
  return null;
}
