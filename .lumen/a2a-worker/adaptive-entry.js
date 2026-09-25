import currentWorker from "./opportunity-entry.js";
import { handleAdaptiveMarketHunter, runAdaptiveMarketHunter } from "./adaptive-market-hunter.js";

export default {
  async fetch(request, env, ctx) {
    const hunterResponse = await handleAdaptiveMarketHunter(request, env);
    if (hunterResponse) return hunterResponse;
    return currentWorker.fetch(request, env, ctx);
  },

  async scheduled(controller, env, ctx) {
    // Discovery learning is intentionally independent from the commercial execution slot.
    // It only reads public market data and writes internal strategy/opportunity state.
    // The established commercial scheduler remains the authority for all external actions.
    ctx.waitUntil(
      runAdaptiveMarketHunter(env).catch(() => ({ ok: false, isolatedFailure: true }))
    );
    return currentWorker.scheduled(controller, env, ctx);
  }
};
