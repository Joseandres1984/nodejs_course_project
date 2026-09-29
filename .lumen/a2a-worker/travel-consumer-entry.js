import baseWorker from "./opportunity-entry.js";
import { handleTravelConsumerEngine, TRAVEL_CONSUMER_DESTINATIONS } from "./travel-consumer-engine.js";
import { handleTravelDemandBridge, syncTravelDemandToOpportunities } from "./travel-demand-bridge.js";
import { handleTravelProviderRegistry } from "./travel-provider-registry.js";
import { handleProviderBackedTravelDiscovery } from "./travel-provider-backed-discovery.js";

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

    const travelDemandResponse = await handleTravelDemandBridge(request, env);
    if (travelDemandResponse) return travelDemandResponse;

    const travelConsumerResponse = await handleTravelConsumerEngine(request, env);
    if (travelConsumerResponse) return travelConsumerResponse;

    return baseWorker.fetch(request, env, ctx);
  },

  async scheduled(controller, env, ctx) {
    ctx.waitUntil(
      syncTravelDemandToOpportunities(env).catch(() => ({ ok: false }))
    );
    return baseWorker.scheduled(controller, env, ctx);
  }
};