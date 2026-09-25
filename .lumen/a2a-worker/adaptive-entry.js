import currentWorker from "./opportunity-entry.js";
import { handleAdaptiveMarketHunter, runAdaptiveMarketHunter } from "./adaptive-market-hunter.js";
import { handleMarketHunterPruner, pruneMarketHunterStrategies } from "./market-hunter-pruner.js";
import { handleSourceIntelligence, runSourceIntelligence } from "./source-intelligence.js";
import { handleSourceIntelligencePolicy } from "./source-intelligence-policy.js";

export default {
  async fetch(request, env, ctx) {
    const sourcePolicyResponse = handleSourceIntelligencePolicy(request);
    if (sourcePolicyResponse) return sourcePolicyResponse;
    const sourceResponse = await handleSourceIntelligence(request, env);
    if (sourceResponse) return sourceResponse;
    const hunterResponse = await handleAdaptiveMarketHunter(request, env);
    if (hunterResponse) return hunterResponse;
    const prunerResponse = await handleMarketHunterPruner(request, env);
    if (prunerResponse) return prunerResponse;
    return currentWorker.fetch(request, env, ctx);
  },

  async scheduled(controller, env, ctx) {
    // Discovery learning stays independent from the commercial execution slot.
    // The source radar and Adaptive Market Hunter only read public market data and
    // write internal source/strategy/opportunity state. They add no external messages,
    // purchases, contracts or autonomous spend. Weak generated Hunter lanes can be
    // retired after learning; seed strategies and economically validated lanes remain
    // protected. The established commercial scheduler remains the authority for all
    // external actions.
    ctx.waitUntil((async () => {
      const [sourceIntelligence, hunter] = await Promise.all([
        runSourceIntelligence(env),
        runAdaptiveMarketHunter(env)
      ]);
      const pruning = await pruneMarketHunterStrategies(env);
      return { sourceIntelligence, hunter, pruning };
    })().catch(() => ({ ok: false, isolatedFailure: true })));
    return currentWorker.scheduled(controller, env, ctx);
  }
};