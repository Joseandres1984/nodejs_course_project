import worker from "../../.lumen/a2a-worker/chatgpt-mcp-entry.js";

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function rpc(body) {
  const request = new Request("https://lumen-chatgpt-mcp.example/mcp", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body)
  });
  const response = await worker.fetch(request, {});
  assert(response.status === 200, `unexpected_status:${response.status}`);
  return response.json();
}

const health = await worker.fetch(new Request("https://lumen-chatgpt-mcp.example/health"), {});
assert(health.status === 200, "health_failed");
const healthBody = await health.json();
assert(healthBody.readOnly === true, "health_not_readonly");
assert(healthBody.paidOpenAiApiRequired === false, "unexpected_paid_api_requirement");

const init = await rpc({
  jsonrpc: "2.0",
  id: 1,
  method: "initialize",
  params: {
    protocolVersion: "2025-06-18",
    capabilities: {},
    clientInfo: { name: "smoke", version: "1" }
  }
});
assert(init.result?.serverInfo?.name === "lumen-readonly", "initialize_server_info_missing");
assert(init.result?.capabilities?.tools, "initialize_tools_capability_missing");

const list = await rpc({ jsonrpc: "2.0", id: 2, method: "tools/list", params: {} });
const names = (list.result?.tools || []).map(tool => tool.name);
const expected = [
  "lumen_status",
  "lumen_opportunities",
  "lumen_top_opportunities",
  "lumen_revenue_status",
  "lumen_pending_approvals"
];
assert(expected.every(name => names.includes(name)), `missing_tools:${expected.filter(name => !names.includes(name)).join(",")}`);
assert((list.result?.tools || []).every(tool => tool.annotations?.readOnlyHint === true), "tool_without_readonly_annotation");

console.log("LUMEN_CHATGPT_MCP_SMOKE_OK", names.join(","));
