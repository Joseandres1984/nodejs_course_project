import adaptiveCore from "./adaptive-core-entry.js";
import { handleViatorAffiliate } from "./viator-affiliate.js";
import { handleViatorApi } from "./viator-api.js";
import { handleViatorSmartRecommend } from "./viator-smart-recommend.js";
import { handleTravelAffiliateOrchestrator, runTravelAffiliateOrchestrator } from "./travel-affiliate-orchestrator.js";
import { handleTravelConsumerEngine, TRAVEL_CONSUMER_DESTINATIONS } from "./travel-consumer-engine.js";
import { handleTravelDemandBridge, syncTravelDemandToOpportunities } from "./travel-demand-bridge.js";
import { handleTravelProviderRegistry } from "./travel-provider-registry.js";
import { handleProviderBackedTravelDiscovery } from "./travel-provider-backed-discovery.js";
import { handleTravelAffiliateRegistry } from "./travel-affiliate-registry.js";

export default {
  async fetch(request, env, ctx) {
    const providerBackedDiscoveryResponse = await handleProviderBackedTravelDiscovery(
      request,
      env,
      TRAVEL_CONSUMER_DESTINATIONS
    );
    if (providerBackedDiscoveryResponse) return providerBackedDiscoveryResponse;

    const travelProviderResponse = await handleTravelProviderRegistry(request, env, TRAVEL_CONSUMER_DESTINATIONS);
    if (travelProviderResponse) return travelProviderResponse;

    const affiliateRegistryResponse = await handleTravelAffiliateRegistry(request, env);
    if (affiliateRegistryResponse) return affiliateRegistryResponse;

    const travelDemandResponse = await handleTravelDemandBridge(request, env);
    if (travelDemandResponse) return travelDemandResponse;

    const travelConsumerResponse = await handleTravelConsumerEngine(request, env);
    if (travelConsumerResponse) return travelConsumerResponse;

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
    ctx.waitUntil(syncTravelDemandToOpportunities(env).catch(() => ({ ok:false, isolatedFailure:true })));
    ctx.waitUntil(runTravelAffiliateOrchestrator(env).catch(() => ({ ok:false, isolatedFailure:true })));
    return adaptiveCore.scheduled(controller, env, ctx);
  }
};
