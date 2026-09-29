import { handleChatGptMcp } from "./chatgpt-mcp.js";

const VERSION = "1.0-lumen-chatgpt-readonly-mcp";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/mcp") {
      return handleChatGptMcp(request, env);
    }

    if (request.method === "GET" && (url.pathname === "/" || url.pathname === "/health")) {
      return Response.json({
        ok: true,
        service: "LUMEN Read-Only MCP",
        version: VERSION,
        readOnly: true,
        paidOpenAiApiRequired: false,
        authority: {
          sendsMessages: false,
          writesState: false,
          triggersScans: false,
          triggersDeployments: false,
          autonomousSpendUsd: 0,
          approvesPayments: false
        }
      }, {
        status: 200,
        headers: {
          "cache-control": "no-store",
          "x-content-type-options": "nosniff",
          "access-control-allow-origin": "*"
        }
      });
    }

    return Response.json({ ok: false, error: "not_found", readOnly: true }, { status: 404 });
  }
};
