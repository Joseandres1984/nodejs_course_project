import app from "./decision_center_worker.js";

const STATE_KEY = "global";

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}

async function sha256Hex(bytes) {
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(hash)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function loadState(env) {
  const manifest = await env.DB.prepare(
    "SELECT encoding,chunk_count,payload_sha256,updated_at FROM lumen_state_manifest WHERE state_key=? LIMIT 1"
  ).bind(STATE_KEY).first();
  if (!manifest) throw new Error("state_not_initialized");
  const result = await env.DB.prepare(
    "SELECT chunk_no,payload FROM lumen_state_chunks WHERE state_key=? ORDER BY chunk_no ASC"
  ).bind(STATE_KEY).all();
  const chunks = result.results || [];
  if (chunks.length !== Number(manifest.chunk_count || 0)) throw new Error("incomplete_state_chunks");
  const encoded = chunks.map((row) => String(row.payload || "")).join("");
  const binary = atob(encoded);
  const compressed = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) compressed[i] = binary.charCodeAt(i);
  const stream = new Blob([compressed]).stream().pipeThrough(new DecompressionStream("deflate"));
  const raw = new Uint8Array(await new Response(stream).arrayBuffer());
  if (manifest.payload_sha256 && (await sha256Hex(raw)) !== manifest.payload_sha256) {
    throw new Error("state_checksum_mismatch");
  }
  return { state: JSON.parse(new TextDecoder().decode(raw)), manifest };
}

async function ensureSchema(env) {
  await env.DB.prepare(
    "CREATE TABLE IF NOT EXISTS lumen_owner_decision_commands (command_id TEXT PRIMARY KEY, decision_key TEXT NOT NULL UNIQUE, action TEXT NOT NULL, decision_type TEXT NOT NULL, object_id TEXT, actor TEXT NOT NULL, scope TEXT NOT NULL, payload_json TEXT, created_at TEXT NOT NULL, processed INTEGER NOT NULL DEFAULT 0, processed_at TEXT, result TEXT)"
  ).run();
  await env.DB.prepare(
    "CREATE INDEX IF NOT EXISTS idx_lumen_owner_decision_pending ON lumen_owner_decision_commands(processed, created_at)"
  ).run();
}

function commercialCandidates(state) {
  const approvals = Array.isArray(state?.approvals) ? state.approvals : [];
  const deals = Array.isArray(state?.deals) ? state.deals : [];
  const proposals = Array.isArray(state?.proposals) ? state.proposals : [];
  const out = [];

  for (const approval of approvals) {
    if (!approval || String(approval.status || "").toLowerCase() !== "pending") continue;
    const approvalId = String(approval.id || "").trim();
    if (!approvalId) continue;
    const dealId = String(approval.deal_id || "").trim();
    const deal = deals.find((row) => String(row?.id || "") === dealId) || {};
    const proposal = proposals.find((row) => String(row?.deal_id || "") === dealId) || {};
    const economics = deal.economics && typeof deal.economics === "object" ? deal.economics : {};
    const salePrice = Number(economics.sale_price ?? deal.sale_price ?? proposal.sale_price ?? 0);
    const companyProfit = Number(approval.company_profit ?? economics.company_profit ?? deal.company_profit ?? 0);
    const companyShare = Number(approval.company_share_pct ?? economics.company_share_pct ?? deal.company_share_pct ?? 0);
    const buyer = String(deal.buyer || proposal.buyer || "comprador");
    const kind = String(approval.kind || "commercial_decision");

    out.push({
      decision_key: `commercial:${approvalId}`,
      decision_type: "commercial_close",
      object_id: approvalId,
      code: `COMERCIAL · ${kind.toUpperCase()}`,
      title: `Resolver ${dealId || approvalId} · ${buyer}`,
      reason: String(approval.reason || "Esta operación requiere una decisión humana antes de continuar."),
      evidence: {
        approval_id: approvalId,
        deal_id: dealId || null,
        buyer,
        stage: deal.stage || null,
        sale_price_usd: salePrice,
        company_profit_usd: companyProfit,
        company_share_pct: companyShare,
        source: deal.source || null,
      },
      confidence: 1,
      samples: 1,
      risk: "high",
      scope: "COMMERCIAL_CLOSE_SIMULATED",
      recommendation: "Aprobar registra el cierre seguro/simulado existente. No ejecuta pagos, transferencias, compras ni contratos reales. Desestimar rechaza este cierre y lo retira de la cola.",
      created_at: approval.created_at || null,
      updated_at: approval.updated_at || approval.created_at || null,
    });
  }
  return out.sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || "")));
}

async function augmentDecisionData(response, env) {
  if (!response.ok || !String(response.headers.get("content-type") || "").includes("application/json")) return response;
  const data = await response.json();
  const { state } = await loadState(env);
  const resolved = new Set((data.resolved || []).map((row) => String(row.decision_key || "")));
  const commercial = commercialCandidates(state).filter((row) => !resolved.has(row.decision_key));
  data.pending = [...commercial, ...(Array.isArray(data.pending) ? data.pending : [])];
  data.counts = data.counts || {};
  data.counts.pending = data.pending.length;
  data.counts.commercial_pending = commercial.length;
  data.counts.self_improvement_pending = data.pending.filter((row) => row.decision_type === "self_improvement").length;
  data.guardrails = {
    ...(data.guardrails || {}),
    commercial_approval_scope: "simulated_close_only",
    financial_commitment_executed: false,
    actual_payment_executed: false,
    contract_execution: false,
  };
  const headers = new Headers(response.headers);
  headers.delete("content-length");
  headers.set("cache-control", "no-store");
  headers.set("x-lumen-unified-decisions", "v1");
  return new Response(JSON.stringify(data), { status: response.status, headers });
}

async function recordCommercialDecision(request, env, body) {
  const decisionKey = String(body?.decision_key || "").trim();
  const action = String(body?.action || "").trim().toLowerCase();
  if (!decisionKey.startsWith("commercial:") || !["approve", "reject"].includes(action)) {
    return json({ ok: false, error: "invalid_commercial_decision" }, 400);
  }
  await ensureSchema(env);
  const existing = await env.DB.prepare(
    "SELECT decision_key,action,scope,created_at,processed,processed_at,result FROM lumen_owner_decision_commands WHERE decision_key=? LIMIT 1"
  ).bind(decisionKey).first();
  if (existing) return json({ ok: true, status: "ALREADY_DECIDED", decision: existing });

  const { state } = await loadState(env);
  const candidate = commercialCandidates(state).find((row) => row.decision_key === decisionKey);
  if (!candidate) return json({ ok: false, error: "commercial_decision_not_active_or_stale" }, 409);

  const commandId = `OWNER-${crypto.randomUUID()}`;
  const now = new Date().toISOString();
  const payload = JSON.stringify({
    code: candidate.code,
    title: candidate.title,
    reason: candidate.reason,
    evidence: candidate.evidence,
    risk: candidate.risk,
    recommendation: candidate.recommendation,
  });
  try {
    await env.DB.prepare(
      "INSERT INTO lumen_owner_decision_commands(command_id,decision_key,action,decision_type,object_id,actor,scope,payload_json,created_at,processed) VALUES(?,?,?,?,?,?,?,?,?,0)"
    ).bind(
      commandId,
      decisionKey,
      action,
      "commercial_close",
      candidate.object_id,
      "authenticated_dashboard_owner",
      "COMMERCIAL_CLOSE_SIMULATED",
      payload,
      now
    ).run();
  } catch (error) {
    const race = await env.DB.prepare(
      "SELECT decision_key,action,scope,created_at,processed,result FROM lumen_owner_decision_commands WHERE decision_key=? LIMIT 1"
    ).bind(decisionKey).first();
    if (race) return json({ ok: true, status: "ALREADY_DECIDED", decision: race });
    throw error;
  }

  return json({
    ok: true,
    status: action === "approve" ? "COMMERCIAL_APPROVAL_RECORDED" : "COMMERCIAL_REJECTION_RECORDED",
    decision_key: decisionKey,
    action,
    scope: "COMMERCIAL_CLOSE_SIMULATED",
    guardrails: {
      financial_commitment_executed: false,
      actual_payment_executed: false,
      contract_execution: false,
      autonomous_spend_usd: 0,
    },
    message: action === "approve"
      ? "Aprobación comercial registrada. LUMEN procesará el cierre seguro/simulado; no se ejecutará ningún pago ni contrato real."
      : "Cierre desestimado. LUMEN lo retirará de la cola y registrará tu decisión.",
  }, 202);
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const upstream = await app.fetch(request.clone(), env, ctx);

    // The underlying Decision Center remains the authentication authority.
    if (upstream.status === 401 || upstream.status === 503) return upstream;

    if (url.pathname === "/api/owner-decisions" && request.method === "GET") {
      try {
        return await augmentDecisionData(upstream, env);
      } catch (error) {
        return json({ ok: false, error: "unified_decision_read_failed", detail: String(error?.message || error).slice(0, 240) }, 500);
      }
    }

    if (url.pathname === "/api/owner-decisions" && request.method === "POST") {
      let body = {};
      try { body = await request.json(); } catch { return upstream; }
      if (String(body?.decision_key || "").startsWith("commercial:")) {
        try {
          return await recordCommercialDecision(request, env, body);
        } catch (error) {
          return json({ ok: false, error: "commercial_decision_write_failed", detail: String(error?.message || error).slice(0, 240) }, 500);
        }
      }
    }

    return upstream;
  },
};
