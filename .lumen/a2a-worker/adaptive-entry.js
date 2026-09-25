import currentWorker from "./opportunity-entry.js";
import { handleAdaptiveMarketHunter, runAdaptiveMarketHunter } from "./adaptive-market-hunter.js";
import { handleMarketHunterPruner, pruneMarketHunterStrategies } from "./market-hunter-pruner.js";

export default {
  async fetch(request, env, ctx) {
    const hunterResponse = await handleAdaptiveMarketHunter(request, env);
    if (hunterResponse) return hunterResponse;
    const prunerResponse = await handleMarketHunterPruner(request, env);
    if (prunerResponse) return prunerResponse;
    return currentWorker.fetch(request, env, ctx);
  },

  async scheduled(controller, env, ctx) {
    // Discovery learning is intentionally independent from the commercial execution slot.
    // It only reads public market data and writes internal strategy/opportunity state.
    // After learning, weak generated lanes can be retired while seed lanes and economically
    // validated lanes are protected. The established commercial scheduler remains the
    // authority for all external actions.
    ctx.waitUntil((async () => {
      const hunter = await runAdaptiveMarketHunter(env);
      const pruning = await pruneMarketHunterStrategies(env);
      return { hunter, pruning };
    })().catch(() => ({ ok: false, isolatedFailure: true })));
    return currentWorker.scheduled(controller, env, ctx);
  }
};
