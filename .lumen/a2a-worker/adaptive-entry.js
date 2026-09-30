import adaptiveCore from "./adaptive-core-entry.js";
import { handleViatorAffiliate } from "./viator-affiliate.js";

export default {
  async fetch(request, env, ctx) {
    const viatorResponse = await handleViatorAffiliate(request, env);
    if (viatorResponse) return viatorResponse;
    return adaptiveCore.fetch(request, env, ctx);
  },

  async scheduled(controller, env, ctx) {
    return adaptiveCore.scheduled(controller, env, ctx);
  }
};
