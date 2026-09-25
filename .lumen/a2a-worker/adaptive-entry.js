import currentWorker from "./opportunity-entry.js";
import { handleAdaptiveMarketHunter, runAdaptiveMarketHunter } from "./adaptive-market-hunter.js";
import { handleMarketHunterPruner, pruneMarketHunterStrategies } from "./market-hunter-pruner.js";
import { handleSourceIntelligence, runSourceIntelligence } from "./source-intelligence.js";
import { handleSourceIntelligencePolicy } from "./source-intelligence-policy.js";
import { handleProductCommerceRadar, runProductCommerceRadar } from "./product-commerce-radar.js";
import { handleCommerceMachine, runCommerceMachine } from "./commerce-machine.js";
import { handleCommerceOperations, runCommerceOperations } from "./commerce-operations.js";
import { handleTiendanubeBridge } from "./tiendanube-bridge.js";

export default {
  async fetch(request, env, ctx) {
    const sourcePolicyResponse = handleSourceIntelligencePolicy(request);
    if (sourcePolicyResponse) return sourcePolicyResponse;
    const tiendanubeResponse = await handleTiendanubeBridge(request, env);
    if (tiendanubeResponse) return tiendanubeResponse;
    const commerceOpsResponse = await handleCommerceOperations(request, env);
    if (commerceOpsResponse) return commerceOpsResponse;
    const commerceMachineResponse = await handleCommerceMachine(request, env);
    if (commerceMachineResponse) return commerceMachineResponse;
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
    // Discovery remains isolated from the established commercial execution slot.
    // Product Commerce observes allowed feeds. Commerce Machine researches and
    // prepares catalog/channel plans. Commerce Operations prepares publication,
    // inventory/price sync and fulfillment queues. Tiendanube Bridge receives
    // verified events and can execute only an explicitly admin-approved hidden
    // product creation; no autonomous publish, supplier purchase or monetary spend.
    ctx.waitUntil((async () => {
      const [sourceIntelligence, productCommerce, hunter] = await Promise.all([
        runSourceIntelligence(env),
        runProductCommerceRadar(env),
        runAdaptiveMarketHunter(env)
      ]);
      const commerceMachine = await runCommerceMachine(env);
      const commerceOperations = await runCommerceOperations(env);
      const pruning = await pruneMarketHunterStrategies(env);
      return { sourceIntelligence, productCommerce, commerceMachine, commerceOperations, hunter, pruning };
    })().catch(() => ({ ok: false, isolatedFailure: true })));
    return currentWorker.scheduled(controller, env, ctx);
  }
};