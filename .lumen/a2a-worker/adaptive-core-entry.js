import currentWorker from "./opportunity-entry.js";
import { handleAdaptiveMarketHunter, runAdaptiveMarketHunter } from "./adaptive-market-hunter.js";
import { handleMarketHunterPruner, pruneMarketHunterStrategies } from "./market-hunter-pruner.js";
import { handleSourceIntelligence, runSourceIntelligence } from "./source-intelligence.js";
import { handleSourceIntelligencePolicy } from "./source-intelligence-policy.js";
import { handleTenderSupplierMatch } from "./tender-supplier-match.js";
import { handleProductCommerceRadar, runProductCommerceRadar } from "./product-commerce-radar.js";
import { handleCommerceMachine, runCommerceMachine } from "./commerce-machine.js";
import { handleCommerceOperations, runCommerceOperations } from "./commerce-operations.js";
import { handleTiendanubeInstall } from "./tiendanube-install.js";
import { handleTiendanubeBridge } from "./tiendanube-bridge.js";
import { handleTiendanubePrivacy } from "./tiendanube-privacy.js";
import { handleTiendanubeSupplierIntake, runTiendanubeSupplierIntake } from "./tiendanube-supplier-intake.js";
import { handleSupplierMarketLaunch } from "./supplier-market-launch.js";
import { handleRevenueFocusController, computeRevenueFocus } from "./revenue-focus-controller.js";
import { handleLiveCognitiveCore, runLiveCognitiveCycle } from "./cognitive-core-live.js";
import { handleCognitiveTaskMemory, runCognitiveTaskMemory } from "./cognitive-task-memory.js";

const ECONOMIC_CONTROL_VERSION = "1.4-live-cognitive-persistent-agenda";
const HOURLY_COMMERCIAL_MINUTE_UTC = 7;
const COGNITIVE_HINT_MAX_AGE_MS = 3 * 60 * 60 * 1000;

function skipped(reason, family) {
  return { ok: true, skipped: true, reason, economicFocus: family || null, version: ECONOMIC_CONTROL_VERSION };
}

async function readEconomicFocus(env) {
  if (!env?.DB) return { initialized: false, family: null, cycle: 0, attention: {}, verifiedRevenueUsd: 0 };
  try {
    const row = await env.DB.prepare("SELECT cycle,metrics_json FROM lumen_portfolio_governor_state WHERE id='GLOBAL' LIMIT 1").first();
    if (!row) return { initialized: false, family: null, cycle: 0, attention: {}, verifiedRevenueUsd: 0 };
    let metrics = {};
    try { metrics = JSON.parse(row.metrics_json || "{}"); } catch {}
    return {
      initialized: true,
      family: String(metrics?.recommendedBusinessFamily || "").trim() || null,
      cycle: Number(row.cycle || 0),
      attention: metrics?.businessFamilyAttention && typeof metrics.businessFamilyAttention === "object" ? metrics.businessFamilyAttention : {},
      verifiedRevenueUsd: Math.max(0, Number(metrics?.verifiedRevenueUsd ?? metrics?.metrics?.verifiedRevenueUsd ?? 0) || 0)
    };
  } catch {
    return { initialized: false, family: null, cycle: 0, attention: {}, verifiedRevenueUsd: 0 };
  }
}

async function readCognitiveHint(env) {
  if (!env?.DB) return null;
  try {
    const row = await env.DB.prepare("SELECT updated_at,cycle,provider,action_type,target_lane,confidence,expected_value FROM lumen_live_cognitive_state WHERE id='GLOBAL' LIMIT 1").first();
    if (!row) return null;
    const updatedMs = Date.parse(String(row.updated_at || ""));
    const ageMs = Number.isFinite(updatedMs) ? Math.max(0, Date.now() - updatedMs) : Number.POSITIVE_INFINITY;
    if (ageMs > COGNITIVE_HINT_MAX_AGE_MS) return null;
    return {
      updatedAt: row.updated_at || null,
      cycle: Number(row.cycle || 0),
      provider: row.provider || null,
      actionType: row.action_type || null,
      targetLane: row.target_lane || null,
      confidence: Math.max(0, Math.min(1, Number(row.confidence || 0))),
      expectedValue: Math.max(0, Math.min(1, Number(row.expected_value || 0))),
      ageMs,
      authority: "internal_discovery_guidance_only"
    };
  } catch {
    return null;
  }
}

function firstCashActive(env, focus) {
  return String(env?.LUMEN_FIRST_CASH_MODE || "").toLowerCase() === "true" && Number(focus?.verifiedRevenueUsd || 0) < 1;
}

function cadencePlan(focus, scheduledTime, forceB2BDiscovery = false, revenueFocus = null, cognitiveHint = null) {
  if (!focus?.initialized || !focus?.family) {
    return {
      b2bDiscovery: true,
      commerceDiscovery: true,
      mode: forceB2BDiscovery ? "FIRST_CASH_FULL_B2B_SENSING" : "COLD_START_FULL_SENSING",
      cognitiveGuidanceApplied: false
    };
  }
  const ms = Number(scheduledTime || Date.now());
  const hourSlot = Math.floor((Number.isFinite(ms) ? ms : Date.now()) / 3600000);
  const family = focus.family;
  let b2bDiscovery = forceB2BDiscovery || family === "B2B_A2A" || family === "REFERRAL" || hourSlot % 3 === 0;
  let commerceDiscovery = family === "COMMERCE" || hourSlot % 4 === 0;
  let cognitiveGuidanceApplied = false;

  if (revenueFocus?.mode === "NORMAL_DISCOVERY" && cognitiveHint && Number(cognitiveHint.confidence || 0) >= 0.55) {
    if (cognitiveHint.actionType === "DISCOVER_B2B" || cognitiveHint.targetLane === "B2B_A2A" || cognitiveHint.targetLane === "REFERRAL") {
      b2bDiscovery = true;
      cognitiveGuidanceApplied = true;
    }
    if (cognitiveHint.actionType === "DISCOVER_COMMERCE" || cognitiveHint.targetLane === "COMMERCE") {
      commerceDiscovery = true;
      cognitiveGuidanceApplied = true;
    }
  }

  if (revenueFocus?.mode === "CONVERSION_FIRST") {
    b2bDiscovery = b2bDiscovery && hourSlot % 3 === 0;
    commerceDiscovery = commerceDiscovery && hourSlot % 4 === 0;
    cognitiveGuidanceApplied = false;
  } else if (revenueFocus?.mode === "BALANCED_CONVERSION") {
    b2bDiscovery = b2bDiscovery && hourSlot % 2 === 0;
    cognitiveGuidanceApplied = false;
  }
  return {
    b2bDiscovery,
    commerceDiscovery,
    mode: revenueFocus?.mode || (forceB2BDiscovery ? "FIRST_CASH_QUARTER_HOUR_B2B" : "ECONOMIC_FOCUS_WITH_BOUNDED_EXPLORATION"),
    cognitiveGuidanceApplied
  };
}

function isHourlyCommercialSlot(scheduledTime) {
  const when = new Date(Number(scheduledTime || Date.now()));
  return when.getUTCMinutes() === HOURLY_COMMERCIAL_MINUTE_UTC;
}

export default {
  async fetch(request, env, ctx) {
    const sourcePolicyResponse = handleSourceIntelligencePolicy(request);
    if (sourcePolicyResponse) return sourcePolicyResponse;
    const cognitiveResponse = await handleLiveCognitiveCore(request, env);
    if (cognitiveResponse) return cognitiveResponse;
    const cognitiveTaskResponse = await handleCognitiveTaskMemory(request, env);
    if (cognitiveTaskResponse) return cognitiveTaskResponse;
    const revenueFocusResponse = await handleRevenueFocusController(request, env);
    if (revenueFocusResponse) return revenueFocusResponse;
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
    const tenderMatchResponse = await handleTenderSupplierMatch(request, env);
    if (tenderMatchResponse) return tenderMatchResponse;
    const hunterResponse = await handleAdaptiveMarketHunter(request, env);
    if (hunterResponse) return hunterResponse;
    const prunerResponse = await handleMarketHunterPruner(request, env);
    if (prunerResponse) return prunerResponse;
    return currentWorker.fetch(request, env, ctx);
  },

  async scheduled(controller, env, ctx) {
    const scheduledTime = controller?.scheduledTime || Date.now();
    const hourlyCommercialSlot = isHourlyCommercialSlot(scheduledTime);

    ctx.waitUntil((async () => {
      const [focus, cognitiveHint] = await Promise.all([
        readEconomicFocus(env),
        readCognitiveHint(env)
      ]);
      const firstCash = firstCashActive(env, focus);
      const revenueFocus = await computeRevenueFocus(env);

      let cognitiveTaskMemory;
      try {
        cognitiveTaskMemory = await runCognitiveTaskMemory(env, { cognitiveHint });
      } catch (error) {
        cognitiveTaskMemory = {
          ok: false,
          isolatedFailure: true,
          error: String(error?.message || error || "cognitive_task_memory_failed").slice(0, 180),
          authority: {
            directToolExecution: false,
            externalMessagesCreated: false,
            autonomousSpendUsd: 0,
            bindingActionsHumanGated: true,
          }
        };
      }

      const plan = cadencePlan(focus, scheduledTime, firstCash, revenueFocus, cognitiveHint);

      const [sourceIntelligence, productCommerce, supplierIntake, hunter] = await Promise.all([
        plan.b2bDiscovery ? runSourceIntelligence(env) : Promise.resolve(skipped("conversion_inventory_has_priority", focus.family)),
        plan.commerceDiscovery ? runProductCommerceRadar(env) : Promise.resolve(skipped("conversion_inventory_has_priority", focus.family)),
        runTiendanubeSupplierIntake(env),
        plan.b2bDiscovery ? runAdaptiveMarketHunter(env) : Promise.resolve(skipped("conversion_inventory_has_priority", focus.family))
      ]);

      const commerceMachine = plan.commerceDiscovery
        ? await runCommerceMachine(env)
        : skipped("conversion_inventory_has_priority", focus.family);
      const commerceOperations = await runCommerceOperations(env);
      const pruning = plan.b2bDiscovery
        ? await pruneMarketHunterStrategies(env)
        : skipped("no_market_hunter_cycle_to_prune", focus.family);

      const cognitive = hourlyCommercialSlot && !env.LUMEN_DEEP_WORKFLOW_MANAGED
        ? await runLiveCognitiveCycle(env, { trigger: "hourly_cloudflare_cron" })
        : skipped("hourly_cognitive_slot_not_due", focus.family);

      return {
        economicControl: {
          version: ECONOMIC_CONTROL_VERSION,
          focus,
          firstCash,
          revenueFocus,
          cognitiveHint,
          cognitiveTaskMemory,
          hourlyCommercialSlot,
          plan,
          guardrails: {
            discoveryBaselineMinutes: 15,
            commercialExternalSlotEveryMinutes: 60,
            cognitiveReasoningEveryMinutes: 60,
            cognitiveTaskMemoryRefreshMinutes: 15,
            persistentCognitiveAgenda: true,
            cognitiveAuthority: "internal_discovery_guidance_only",
            cognitiveCanOverrideConversionPriority: false,
            cognitiveCanExecuteTools: false,
            cognitiveTaskMemoryCanExecuteTools: false,
            maxAutonomousNewOutreachPerBatch: 30,
            maxAutonomousNewOutreachPer24h: 120,
            oneOriginPer24hForNewOutreach: true,
            oneOpportunityPerCloser: true,
            conversionInventoryBeforeExpansion: true,
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
        pruning,
        cognitive
      };
    })().catch(() => ({ ok: false, isolatedFailure: true })));

    if (hourlyCommercialSlot) return currentWorker.scheduled(controller, env, ctx);
    return undefined;
  }
};
