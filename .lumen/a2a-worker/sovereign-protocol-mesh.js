import { clean, host, object } from "./sovereign-store.js";

export const PROTOCOL_MESH_POLICY = Object.freeze({
  sendsRequests: false, signsPayments: false, createsCredentials: false,
  a2a: "draft_JSON_RPC_message_send_0.3", mcp: "draft_tools_call_requires_existing_initialized_session",
  x402: "existing_seller_checkout_reference_only", ap2: "BLOCKED_NO_MANDATE_VERIFIER_OR_PAYMENT_AUTHORITY",
  specifications: {
    a2a: "https://a2a-protocol.org/v0.3.0/specification/",
    mcp: "https://modelcontextprotocol.io/specification/2025-11-25/server/tools",
    ap2: "https://ap2-protocol.org/ap2/specification/"
  }
});
export function prepareProtocolEnvelope(protocol, task) {
  const id = clean(task?.id, 160), text = clean(task?.text, 1800);
  if (!id || !text) throw new Error("mesh_task_id_and_text_required");
  const base = { protocol, taskId: id, executable: false, authority: "PREPARATION_ONLY" };
  switch (protocol) {
    case "a2a":
      if (!host(task.endpoint)) throw new Error("mesh_https_endpoint_required");
      return { ...base, endpoint: task.endpoint, version: "0.3.0", body: {
        jsonrpc: "2.0", id, method: "message/send", params: {
          message: { kind: "message", role: "user", messageId: id, parts: [{ kind: "text", text }] }
        }
      } };
    case "mcp":
      if (!/^[a-zA-Z0-9_.-]{1,80}$/.test(task.tool || "")) throw new Error("mesh_tool_name_invalid");
      return { ...base, requiresInitializedSession: true, body: {
        jsonrpc: "2.0", id, method: "tools/call", params: { name: task.tool, arguments: object(task.arguments) }
      } };
    case "x402":
      if (!host(task.checkoutUrl)) throw new Error("mesh_https_checkout_required");
      return { ...base, checkoutUrl: task.checkoutUrl, network: "Base", asset: "USDC",
        consumesPaymentSignature: false, paymentProofSource: "provider_verified_receipt_in_DB" };
    case "ap2": return { ...base, blocked: true, reason: "signed_mandate_verification_and_human_payment_authority_not_configured" };
    default: throw new Error("mesh_protocol_unsupported");
  }
}
