import { handleOpportunityEngine } from "./opportunity-engine.js";
import { handlePortfolioGovernor } from "./portfolio-governor.js";
import { handleQualityGate } from "./quality-gate.js";
import { handleRevenueDirector } from "./revenue-director.js";

const VERSION = "1.0-lumen-chatgpt-readonly-mcp";
const MCP_PROTOCOL_VERSION = "2025-06-18";

const TOOL_DEFS = [
  {
    name: "lumen_status",
    title: "LUMEN status",
    description: "Read LUMEN's current operational, opportunity, portfolio, quality-gate, and revenue status. Use for questions like what LUMEN is doing now or whether the commercial system is healthy.",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
    annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false }
  },
  {
    name: "lumen_opportunities",
    title: "List LUMEN opportunities",
    description: "Read the opportunities already discovered by LUMEN. This never launches a scan, contacts anyone, or changes state.",
    inputSchema: {
      type: "object",
      properties: {
        limit: { type: "integer", minimum: 1, maximum: 50, default: 20 },
        min_score: { type: "integer", minimum: 0, maximum: 100, default: 35 },
        status: { type: "string", maxLength: 40, description: "Optional existing LUMEN opportunity status filter." }
      },
      additionalProperties: false
    },
    annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false }
  },
  {
    name: "lumen_top_opportunities",
    title: "Top LUMEN opportunities",
    description: "Read LUMEN's highest-scoring already-discovered opportunities for prioritization. This is read-only and does not contact targets.",
    inputSchema: {
      type: "object",
      properties: {
        limit: { type: "integer", minimum: 1, maximum: 20, default: 5 },
        min_score: { type: "integer", minimum: 0, maximum: 100, default: 65 }
      },
      additionalProperties: false
    },
    annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false }
  },
  {
    name: "lumen_revenue_status",
    title: "LUMEN revenue status",
    description: "Read the existing LUMEN First-Cash Revenue Director state, including observed funnel metrics, bottleneck, tactic, and verified revenue. It cannot recompute or alter revenue strategy.",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
    annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false }
  },
  {
    name: "lumen_pending_approvals",
    title: "LUMEN pending approvals",
    description: "Read the existing proposal quality-gate queue and approved-awaiting-outreach counts. It never approves, reviews, sends, or changes a proposal.",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
    annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false }
  }
];

function corsHeaders(extra = {}) {
  return {
    "access-control-allow-origin": "*",
    "access-control-allow-methods": "POST, GET, OPTIONS",
    "access-control-allow-headers": "content-type, mcp-session-id",
    "access-control-expose-headers": "Mcp-Session-Id",
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
    ...extra
  };
}

function jsonRpc(payload, status = 200) {
  return Response.json(payload, { status, headers: corsHeaders({ "content-type": "application/json" }) });
}

function rpcResult(id, result) {
  return jsonRpc({ jsonrpc: "2.0", id, result });
}

function rpcError(id, code, message, data) {
  const error = { code, message };
  if (data !== undefined) error.data = data;
  return jsonRpc({ jsonrpc: "2.0", id: id ?? null, error }, code === -32600 || code === -32700 ? 400 : 200);
}

function toolResult(data, summary) {
  return {
    content: [{ type: "text", text: summary }],
    structuredContent: data,
    isError: false
  };
}

function toolError(message) {
  return {
    content: [{ type: "text", text: message }],
    structuredContent: { ok: false, error: message },
    isError: true
  };
}

function clampInt(value, fallback, min, max) {
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(min, Math.min(max, Math.trunc(n)));
}

function safeStatus(value) {
  return String(value ?? "").trim().replace(/[^a-zA-Z0-9_-]/g, "").slice(0, 40);
}

async function invokeReadHandler(handler, path, request, env) {
  const url = new URL(request.url);
  url.pathname = path.split("?")[0];
  url.search = path.includes("?") ? `?${path.split("?").slice(1).join("?")}` : "";
  const internalRequest = new Request(url.toString(), { method: "GET", headers: { accept: "application/json" } });
  const response = await handler(internalRequest, env);
  if (!response) throw new Error(`read_route_not_found:${path}`);
  const text = await response.text();
  if (!response.ok) throw new Error(`read_route_http_${response.status}:${text.slice(0, 180)}`);
  try { return JSON.parse(text); } catch { throw new Error(`invalid_json_from_read_route:${path}`); }
}

async function callTool(name, args, request, env) {
  if (name === "lumen_opportunities" || name === "lumen_top_opportunities") {
    const top = name === "lumen_top_opportunities";
    const limit = clampInt(args?.limit, top ? 5 : 20, 1, top ? 20 : 50);
    const minScore = clampInt(args?.min_score, top ? 65 : 35, 0, 100);
    const status = top ? "" : safeStatus(args?.status);
    const query = new URLSearchParams({ limit: String(limit), min_score: String(minScore) });
    if (status) query.set("status", status);
    const data = await invokeReadHandler(handleOpportunityEngine, `/opportunities?${query.toString()}`, request, env);
    return toolResult(
      { ok: true, readOnly: true, ...data },
      top ? `Read LUMEN's top opportunities (minimum score ${minScore}). No scan or outreach was triggered.` : `Read LUMEN's existing opportunity inventory. No scan or outreach was triggered.`
    );
  }

  if (name === "lumen_revenue_status") {
    const data = await invokeReadHandler(handleRevenueDirector, "/revenue-director/state", request, env);
    return toolResult({ ok: true, readOnly: true, ...data }, "Read LUMEN's Revenue Director state. No recompute, spend, or commercial action was triggered.");
  }

  if (name === "lumen_pending_approvals") {
    const [stats, next] = await Promise.all([
      invokeReadHandler(handleQualityGate, "/quality/stats", request, env),
      invokeReadHandler(handleQualityGate, "/quality/next", request, env)
    ]);
    return toolResult(
      { ok: true, readOnly: true, quality: { stats, next } },
      "Read LUMEN's proposal quality queue and approved-awaiting-outreach state. No proposal was reviewed, approved, or sent."
    );
  }

  if (name === "lumen_status") {
    const [opportunities, portfolio, quality, revenue] = await Promise.all([
      invokeReadHandler(handleOpportunityEngine, "/opportunities/stats", request, env),
      invokeReadHandler(handlePortfolioGovernor, "/portfolio-governor/state", request, env),
      invokeReadHandler(handleQualityGate, "/quality/stats", request, env),
      invokeReadHandler(handleRevenueDirector, "/revenue-director/state", request, env)
    ]);
    return toolResult(
      {
        ok: true,
        readOnly: true,
        version: VERSION,
        opportunities,
        portfolio,
        quality,
        revenue,
        authority: {
          sendsMessages: false,
          writesState: false,
          triggersScans: false,
          triggersDeployments: false,
          autonomousSpendUsd: 0,
          approvesPayments: false
        }
      },
      "Read LUMEN's current status from existing read-only routes. No state-changing operation was triggered."
    );
  }

  return toolError(`Unknown tool: ${name}`);
}

async function handlePost(request, env) {
  let body;
  try { body = await request.json(); } catch { return rpcError(null, -32700, "Parse error"); }
  if (!body || body.jsonrpc !== "2.0" || typeof body.method !== "string") return rpcError(body?.id, -32600, "Invalid Request");

  const id = body.id;
  if (body.method === "initialize") {
    return rpcResult(id, {
      protocolVersion: MCP_PROTOCOL_VERSION,
      capabilities: { tools: { listChanged: false } },
      serverInfo: { name: "lumen-readonly", title: "LUMEN Read-Only", version: VERSION },
      instructions: "Read-only window into LUMEN. Use these tools to inspect current LUMEN status, opportunities, revenue and proposal queues. Never claim these tools sent messages, spent money, changed state, approved anything, triggered a scan, or deployed code."
    });
  }

  if (body.method === "notifications/initialized" || body.method === "notifications/cancelled") {
    return new Response(null, { status: 202, headers: corsHeaders() });
  }

  if (body.method === "ping") return rpcResult(id, {});
  if (body.method === "tools/list") return rpcResult(id, { tools: TOOL_DEFS });

  if (body.method === "tools/call") {
    const name = String(body.params?.name || "");
    const args = body.params?.arguments && typeof body.params.arguments === "object" ? body.params.arguments : {};
    try {
      return rpcResult(id, await callTool(name, args, request, env));
    } catch (error) {
      return rpcResult(id, toolError(String(error?.message || error || "tool_call_failed").slice(0, 500)));
    }
  }

  return rpcError(id, -32601, `Method not found: ${body.method}`);
}

export async function handleChatGptMcp(request, env) {
  const url = new URL(request.url);
  if (url.pathname !== "/mcp") return null;

  if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: corsHeaders() });
  if (request.method === "GET") {
    return Response.json({
      ok: true,
      name: "LUMEN Read-Only MCP",
      version: VERSION,
      transport: "streamable-http-json-response",
      readOnly: true,
      tools: TOOL_DEFS.map(tool => tool.name)
    }, { status: 200, headers: corsHeaders() });
  }
  if (request.method === "DELETE") return new Response(null, { status: 204, headers: corsHeaders() });
  if (request.method !== "POST") return new Response("Method Not Allowed", { status: 405, headers: corsHeaders({ allow: "POST, GET, DELETE, OPTIONS" }) });

  return handlePost(request, env);
}
