import currentWorker from "./opportunity-entry.js";
import { handleAdaptiveMarketHunter, runAdaptiveMarketHunter } from "./adaptive-market-hunter.js";
import { handleMarketHunterPruner, pruneMarketHunterStrategies } from "./market-hunter-pruner.js";
import { handleSourceIntelligence, runSourceIntelligence } from "./source-intelligence.js";
import { handleSourceIntelligencePolicy } from "./source-intelligence-policy.js";
import { handleProductCommerceRadar, runProductCommerceRadar } from "./product-commerce-radar.js";
import { handleCommerceMachine, runCommerceMachine } from "./commerce-machine.js";
import { handleCommerceOperations, runCommerceOperations } from "./commerce-operations.js";
import { handleTiendanubeInstall } from "./tiendanube-install.js";
import { handleTiendanubeBridge } from "./tiendanube-bridge.js";
import { handleTiendanubePrivacy } from "./tiendanube-privacy.js";
import { handleTiendanubeSupplierIntake, runTiendanubeSupplierIntake } from "./tiendanube-supplier-intake.js";

export default {
  async fetch(request, env, ctx) {
    const sourcePolicyResponse = handleSourceIntelligencePolicy(request);
    if (sourcePolicyResponse) return sourcePolicyResponse;
    const tiendanubeInstallResponse = await handleTiendanubeInstall(request, env);
    if (tiendanubeInstallResponse) return tiendanubeInstallResponse;
    const tiendanubePrivacyResponse = await handleTiendanubePrivacy(request, env);
    if (tiendanubePrivacyResponse) return tiendanubePrivacyResponse;
    const supplierIntakeResponse = await handleTiendanubeSupplierIntake(request, env);
    if (supplierIntakeResponse) return supplierIntakeResponse;
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
    // Supplier Intake stages connected Tiendanube products, reads variant cost/stock,
    // hides fresh imports until approval, and feeds landed-cost candidates into the
    // existing Commerce Machine. No supplier purchase, publication or spend authority.
    ctx.waitUntil((async () => {
      const [sourceIntelligence, productCommerce, supplierIntake, hunter] = await Promise.all([
        runSourceIntelligence(env),
        runProductCommerceRadar(env),
        runTiendanubeSupplierIntake(env),
        runAdaptiveMarketHunter(env)
      ]);
      const commerceMachine = await runCommerceMachine(env);
      const commerceOperations = await runCommerceOperations(env);
      const pruning = await pruneMarketHunterStrategies(env);
      return { sourceIntelligence, productCommerce, supplierIntake, commerceMachine, commerceOperations, hunter, pruning };
    })().catch(() => ({ ok: false, isolatedFailure: true })));
    return currentWorker.scheduled(controller, env, ctx);
  }
};