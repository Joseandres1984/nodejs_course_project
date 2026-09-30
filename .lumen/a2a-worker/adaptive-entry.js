import adaptiveCore from "./adaptive-core-entry.js";
import { handleViatorAffiliate } from "./viator-affiliate.js";
import { handleViatorApi } from "./viator-api.js";
import { handleViatorSmartRecommend } from "./viator-smart-recommend.js";
import { handleTravelAffiliateOrchestrator, runTravelAffiliateOrchestrator } from "./travel-affiliate-orchestrator.js";

export default {
  async fetch(request, env, ctx) {
    const viatorApiResponse = await handleViatorApi(request, env);
    if (viatorApiResponse) return viatorApiResponse;
    const viatorResponse = await handleViatorAffiliate(request, env);
    if (viatorResponse) return viatorResponse;
    const viatorSmartResponse = await handleViatorSmartRecommend(request, env);
    if (viatorSmartResponse) return viatorSmartResponse;
    const travelAffiliateResponse = await handleTravelAffiliateOrchestrator(request, env);
    if (travelAffiliateResponse) return travelAffiliateResponse;
    return adaptiveCore.fetch(request, env, ctx);
  },

  async scheduled(controller, env, ctx) {
    ctx.waitUntil(runTravelAffiliateOrchestrator(env).catch(() => ({ ok:false, isolatedFailure:true })));
    return adaptiveCore.scheduled(controller, env, ctx);
  }
};
