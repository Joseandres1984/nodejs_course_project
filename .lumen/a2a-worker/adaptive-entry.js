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
import { handleSupplierMarketLaunch } from "./supplier-market-launch.js";

const ECONOMIC_CONTROL_VERSION = "1.0-economic-focus-cadence";

function skipped(reason, family) {
  return { ok: true, skipped: true, reason, economicFocus: family || null, version: ECONOMIC_CONTROL_VERSION };
}

async function readEconomicFocus(env) {
  if (!env?.DB) return { initialized: false, family: null, cycle: 0, attention: {} };
  try {
    const row = await env.DB.prepare("SELECT cycle,metrics_json FROM lumen_portfolio_governor_state WHERE id='GLOBAL' LIMIT 1").first();
    if (!row) return { initialized: false, family: null, cycle: 0, attention: {} };
    let metrics = {};
    try { metrics = JSON.parse(row.metrics_json || "{}"); } catch {}
    return {
      initialized: true,
      family: String(metrics?.recommendedBusinessFamily || "").trim() || null,
      cycle: Number(row.cycle || 0),
      attention: metrics?.businessFamilyAttention && typeof metrics.businessFamilyAttention === "object" ? metrics.businessFamilyAttention : {}
    };
  } catch {
    return { initialized: false, family: null, cycle: 0, attention: {} };
  }
}

function cadencePlan(focus, scheduledTime) {
  // Sensing never goes to zero. A non-priority family still gets periodic exploration,
  // while the current economic winner gets full-frequency discovery.
  if (!focus?.initialized || !focus?.family) {
    return { b2bDiscovery: true, commerceDiscovery: true, mode: "COLD_START_FULL_SENSING" };
  }
  const ms = Number(scheduledTime || Date.now());
  const hourSlot = Math.floor((Number.isFinite(ms) ? ms : Date.now()) / 3600000);
  const family = focus.family;
  const b2bDiscovery = family === "B2B_A2A" || family === "REFERRAL" || hourSlot % 3 === 0;
  const commerceDiscovery = family === "COMMERCE" || hourSlot % 4 === 0;
  return { b2bDiscovery, commerceDiscovery, mode: "ECONOMIC_FOCUS_WITH_BOUNDED_EXPLORATION" };
}

export default {
  async fetch(request, env, ctx) {
    const sourcePolicyResponse = handleSourceIntelligencePolicy(request);
    if (sourcePolicyResponse) return sourcePolicyResponse;
    const tiendanubeInstallResponse = await handleTiendanubeInstall(request, env);
    if (tiendanubeInstallResponse) return tiendanubeInstallResponse;
    const tiendanubePrivacyResponse = await handleTiendanubePrivacy(request, env);
    if (tiendanubePrivacyResponse) return tiendanubePrivacyResponse;
    const supplierLaunchResponse = await handleSupplierMarketLaunch(request, env);
    if (supplierLaunchResponse) return supplierLaunchResponse;
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
    // Economic focus governs scarce discovery cadence, not truth collection or safety.
    // The winning business family receives full-frequency discovery; other families
    // retain bounded exploration so LUMEN can detect regime changes and better ideas.
    // Supplier intake and Commerce Operations remain live every cycle for stock/order
    // truth and operational safety. No purchase, contract or spend authority is added.
    ctx.waitUntil((async () => {
      const focus = await readEconomicFocus(env);
      const plan = cadencePlan(focus, controller?.scheduledTime || null);

      const [sourceIntelligence, productCommerce, supplierIntake, hunter] = await Promise.all([
        plan.b2bDiscovery ? runSourceIntelligence(env) : Promise.resolve(skipped("economic_focus_exploration_cadence", focus.family)),
        plan.commerceDiscovery ? runProductCommerceRadar(env) : Promise.resolve(skipped("economic_focus_exploration_cadence", focus.family)),
        runTiendanubeSupplierIntake(env),
        plan.b2bDiscovery ? runAdaptiveMarketHunter(env) : Promise.resolve(skipped("economic_focus_exploration_cadence", focus.family))
      ]);

      const commerceMachine = plan.commerceDiscovery
        ? await runCommerceMachine(env)
        : skipped("economic_focus_exploration_cadence", focus.family);
      const commerceOperations = await runCommerceOperations(env);
      const pruning = plan.b2bDiscovery
        ? await pruneMarketHunterStrategies(env)
        : skipped("no_market_hunter_cycle_to_prune", focus.family);

      return {
        economicControl: {
          version: ECONOMIC_CONTROL_VERSION,
          focus,
          plan,
          guardrails: {
            sensingNeverZero: true,
            commerceOperationsAlwaysOn: true,
            supplierTruthAlwaysOn: true,
            autonomousSpendUsd: 0,
            autonomousPurchase: false,
            autonomousContract: false
          }
        },
        sourceIntelligence,
        productCommerce,
        supplierIntake,
        commerceMachine,
        commerceOperations,
        hunter,
        pruning
      };
    })().catch(() => ({ ok: false, isolatedFailure: true })));
    return currentWorker.scheduled(controller, env, ctx);
  }
};
