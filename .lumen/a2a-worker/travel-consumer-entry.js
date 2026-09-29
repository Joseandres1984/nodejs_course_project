import baseWorker from "./opportunity-entry.js";
import { handleTravelConsumerEngine } from "./travel-consumer-engine.js";

export default {
  async fetch(request, env, ctx) {
    const travelConsumerResponse = await handleTravelConsumerEngine(request, env);
    if (travelConsumerResponse) return travelConsumerResponse;
    return baseWorker.fetch(request, env, ctx);
  },

  async scheduled(controller, env, ctx) {
    return baseWorker.scheduled(controller, env, ctx);
  }
};
