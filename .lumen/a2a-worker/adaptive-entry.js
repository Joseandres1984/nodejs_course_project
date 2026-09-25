import currentWorker from "./opportunity-entry.js";
import { handleAdaptiveMarketHunter, runAdaptiveMarketHunter } from "./adaptive-market-hunter.js";
import { handleMarketHunterPruner, pruneMarketHunterStrategies } from "./market-hunter-pruner.js";
import { handleSourceIntelligence, runSourceIntelligence } from "./source-intelligence.js";
import { handleSourceIntelligencePolicy } from "./source-intelligence-policy.js";
import { handleProductCommerceRadar, runProductCommerceRadar } from "./product-commerce-radar.js";

export default {
  async fetch(request, env, ctx) {
    const sourcePolicyResponse = handleSourceIntelligencePolicy(request);
    if (sourcePolicyResponse) return sourcePolicyResponse;
    const productCommerceResponse = await handleProductCommerceRadar(request, env);
    if (productCommerceResponse) return productCommerceResponse;
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
    // Source Intelligence, Product Commerce Radar and Adaptive Market Hunter only
    // observe allowed/public sources and write internal state. Product Commerce may
    // score and prepare DRAFT_READY candidates but never publishes, purchases,
    // accepts contracts or spends money autonomously. The established commercial
    // scheduler and Governor remain authoritative for every external action.
    ctx.waitUntil((async () => {
      const [sourceIntelligence, productCommerce, hunter] = await Promise.all([
        runSourceIntelligence(env),
        runProductCommerceRadar(env),
        runAdaptiveMarketHunter(env)
      ]);
      const pruning = await pruneMarketHunterStrategies(env);
      return { sourceIntelligence, productCommerce, hunter, pruning };
    })().catch(() => ({ ok: false, isolatedFailure: true })));
    return currentWorker.scheduled(controller, env, ctx);
  }
};