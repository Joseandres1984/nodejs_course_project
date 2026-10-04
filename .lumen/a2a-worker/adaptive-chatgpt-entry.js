import adaptiveWorker from "./adaptive-entry.js";
import { handleChatGptMcp } from "./chatgpt-mcp.js";

export default {
  async fetch(request, env, ctx) {
    const mcpResponse = await handleChatGptMcp(request, env);
    if (mcpResponse) return mcpResponse;
    return adaptiveWorker.fetch(request, env, ctx);
  },

  async scheduled(controller, env, ctx) {
    return adaptiveWorker.scheduled(controller, env, ctx);
  }
};
