import baseWorker from "./opportunity-entry.js";
import { handleTravelConsumerEngine } from "./travel-consumer-engine.js";
import { handleTravelDemandBridge, syncTravelDemandToOpportunities } from "./travel-demand-bridge.js";

export default {
  async fetch(request, env, ctx) {
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