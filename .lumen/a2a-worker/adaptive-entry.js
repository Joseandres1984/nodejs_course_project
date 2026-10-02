import adaptiveCore from "./adaptive-core-entry.js";
export { LumenDeepWorkflow, LumenOpportunityWorkflow } from "./paid-boost-workflows.js";
import { handleViatorAffiliate } from "./viator-affiliate.js";
import { handleViatorApi } from "./viator-api.js";
import { handleViatorRevenue } from "./viator-revenue.js";
import { handleViatorConversionSync, syncViatorBookingConversions } from "./viator-conversion-sync.js";
import { handleViatorOptimizedRecommend } from "./viator-optimized-recommend.js";
import { handleViatorSmartRecommend } from "./viator-smart-recommend.js";
import { handleTravelAffiliateOrchestrator, runTravelAffiliateOrchestrator } from "./travel-affiliate-orchestrator.js";
import { handleTravelConsumerEngine, TRAVEL_CONSUMER_DESTINATIONS } from "./travel-consumer-engine.js";
import { handleTravelDemandBridge, syncTravelDemandToOpportunities } from "./travel-demand-bridge.js";
import { handleTravelProviderRegistry } from "./travel-provider-registry.js";
import { handleProviderBackedTravelDiscovery } from "./travel-provider-backed-discovery.js";
import { handleTravelAffiliateRegistry } from "./travel-affiliate-registry.js";
import { handleTravelAcquisitionEngine, runTravelAcquisitionEngine } from "./travel-acquisition-engine.js";
import { handleAutonomousGrowthLoop, runAutonomousGrowthLoop } from "./autonomous-growth-loop-v11.js";
import { handleGrowthMultiplierV2, runGrowthMultiplierV2Cycle } from "./growth-multiplier-v2.js";
import { handleGrowthEngineFoundry } from "./growth-engine-foundry.js";
import { handleGrowthEngineFoundryV2 } from "./growth-engine-foundry-v2.js";
import { handleTravelpayoutsFinance, syncTravelpayoutsFinance } from "./travelpayouts-finance-sync.js";
import { syncX402SettlementsToRevenue } from "./x402-revenue-bridge.js";
import { syncReferralSettlements } from "./referral-network.js";
import { syncReferralCommissionSettlements } from "./referral-commission-engine.js";
import { recomputeRevenueAttribution } from "./revenue-attribution-engine.js";
import { recomputeProfitFeedback } from "./profit-feedback-engine.js";
import { handleSuperautonomy, runSuperautonomyCycle } from "./superautonomy-live.js";
import { handleSuperautonomyV3, runSuperautonomyV3Cycle } from "./superautonomy-v3.js";
import { handleLumenConversation } from "./lumen-conversation-v2.js";
import { handleSelfLearning, runSelfLearningCycle } from "./self-learning-engine.js";
import { handleMetaController, runMetaControllerCycle } from "./meta-controller.js";
import { handleTeacherSelfCritic, runSelfCriticCycle } from "./teacher-self-critic.js";

async function isolated(step) {
  try {
    return await step();
  } catch (error) {
    return {
      ok: false,
      isolatedFailure: true,
      error: String(error?.message || error || "commercial_truth_refresh_failed").slice(0, 240)
    };
  }
}

export async function refreshCommercialTruth(env) {
  const x402 = await isolated(() => syncX402SettlementsToRevenue(env));
  const travelpayoutsFinance = await isolated(() => syncTravelpayoutsFinance(env));
  const referralCommissions = await isolated(() => syncReferralCommissionSettlements(env));
  const referrals = await isolated(() => syncReferralSettlements(env));
  const revenueAttribution = await isolated(() => recomputeRevenueAttribution(env));
  const profitFeedback = await isolated(() => recomputeProfitFeedback(env));

  return {
    ok: [x402, travelpayoutsFinance, referralCommissions, referrals, revenueAttribution, profitFeedback].every(result => result?.ok !== false),
    x402,
    travelpayoutsFinance,
    referralCommissions,
    referrals,
    revenueAttribution,
    profitFeedback,
    truthOrder: [
      "verified_x402_settlements",
      "travelpayouts_verified_affiliate_rewards",
      "referral_settlements",
      "revenue_attribution",
      "profit_feedback",
      "growth_multiplier_allocation",
      "growth_decision"
    ],
    guardrails: {
      verifiedRevenueEvidenceRequired: true,
      affiliatePayoutsNotDoubleCountedAsRevenue: true,
      autonomousSpendUsd: 0,
      bindingActionsHumanGated: true
    }
  };
}

export default {
  async fetch(request, env, ctx) {
    const conversationResponse = await handleLumenConversation(request, env);
    if (conversationResponse) return conversationResponse;

    const learningResponse = await handleSelfLearning(request, env);
    if (learningResponse) return learningResponse;

    const metaControllerResponse = await handleMetaController(request, env);
    if (metaControllerResponse) return metaControllerResponse;

    const teacherCriticResponse = await handleTeacherSelfCritic(request, env);
    if (teacherCriticResponse) return teacherCriticResponse;

    const superautonomyV3Response = await handleSuperautonomyV3(request, env);
    if (superautonomyV3Response) return superautonomyV3Response;

    const superautonomyResponse = await handleSuperautonomy(request, env);
    if (superautonomyResponse) return superautonomyResponse;

    const growthFoundryV2Response = await handleGrowthEngineFoundryV2(request, env);
    if (growthFoundryV2Response) return growthFoundryV2Response;

    const growthFoundryResponse = await handleGrowthEngineFoundry(request, env);
    if (growthFoundryResponse) return growthFoundryResponse;

    const growthMultiplierResponse = await handleGrowthMultiplierV2(request, env);
    if (growthMultiplierResponse) return growthMultiplierResponse;

    const growthResponse = await handleAutonomousGrowthLoop(request, env);
    if (growthResponse) return growthResponse;

    const travelpayoutsFinanceResponse = await handleTravelpayoutsFinance(request, env);
    if (travelpayoutsFinanceResponse) return travelpayoutsFinanceResponse;

    const providerBackedDiscoveryResponse = await handleProviderBackedTravelDiscovery(
      request,
      env,
      TRAVEL_CONSUMER_DESTINATIONS
    );
    if (providerBackedDiscoveryResponse) return providerBackedDiscoveryResponse;

    const travelProviderResponse = await handleTravelProviderRegistry(request, env, TRAVEL_CONSUMER_DESTINATIONS);
    if (travelProviderResponse) return travelProviderResponse;

    const affiliateRegistryResponse = await handleTravelAffiliateRegistry(request, env);
    if (affiliateRegistryResponse) return affiliateRegistryResponse;

    const travelDemandResponse = await handleTravelDemandBridge(request, env);
    if (travelDemandResponse) return travelDemandResponse;

    const travelConsumerResponse = await handleTravelConsumerEngine(request, env);
    if (travelConsumerResponse) return travelConsumerResponse;

    const travelAcquisitionResponse = await handleTravelAcquisitionEngine(request, env);
    if (travelAcquisitionResponse) return travelAcquisitionResponse;

    const viatorApiResponse = await handleViatorApi(request, env);
    if (viatorApiResponse) return viatorApiResponse;

    const viatorConversionResponse = await handleViatorConversionSync(request, env);
    if (viatorConversionResponse) return viatorConversionResponse;

    const viatorRevenueResponse = await handleViatorRevenue(request, env);
    if (viatorRevenueResponse) return viatorRevenueResponse;

    const viatorResponse = await handleViatorAffiliate(request, env);
    if (viatorResponse) return viatorResponse;

    const optimizedRecommendResponse = await handleViatorOptimizedRecommend(request, env);
    if (optimizedRecommendResponse) return optimizedRecommendResponse;

    const viatorSmartResponse = await handleViatorSmartRecommend(request, env);
    if (viatorSmartResponse) return viatorSmartResponse;

    const travelAffiliateResponse = await handleTravelAffiliateOrchestrator(request, env);
    if (travelAffiliateResponse) return travelAffiliateResponse;

    return adaptiveCore.fetch(request, env, ctx);
  },

  async scheduled(controller, env, ctx) {
    ctx.waitUntil(syncTravelDemandToOpportunities(env).catch(() => ({ ok:false, isolatedFailure:true })));
    ctx.waitUntil(runTravelAffiliateOrchestrator(env).catch(() => ({ ok:false, isolatedFailure:true })));

    const scheduledAt = new Date(controller?.scheduledTime || Date.now());
    const growthSlot = scheduledAt.getUTCMinutes() === 7;

    if (!env.LUMEN_DEEP_WORKFLOW_MANAGED) ctx.waitUntil((async () => {
      const metaPrepare = await isolated(() => runMetaControllerCycle(env, {
        trigger: "scheduled_pre_superautonomy",
        applyNudge: true
      }));

      const superautonomy = await isolated(() => runSuperautonomyCycle(env, {
        trigger: "cloudflare_scheduled_superautonomy"
      }));

      const selfLearning = await isolated(() => runSelfLearningCycle(env, {
        trigger: "scheduled_after_superautonomy"
      }));

      const metaLearn = await isolated(() => runMetaControllerCycle(env, {
        trigger: "scheduled_after_self_learning",
        applyNudge: false
      }));

      const selfCritic = await isolated(() => runSelfCriticCycle(env, {
        trigger: "scheduled_after_meta_learning"
      }));

      const superautonomyV3 = await isolated(() => runSuperautonomyV3Cycle(env, {
        trigger: "scheduled_after_self_critic"
      }));

      await isolated(() => syncViatorBookingConversions(env));
      await isolated(() => runTravelAcquisitionEngine(env));

      const recoveryGrowth =
        (superautonomy?.ok === true && superautonomy?.recovery?.accelerateGrowthLoop === true) ||
        (superautonomyV3?.ok === true && superautonomyV3?.accelerateGrowthLoop === true);

      if (!growthSlot && !recoveryGrowth) {
        return { ok:true, growthSkipped:true, metaPrepare, superautonomy, selfLearning, metaLearn, selfCritic, superautonomyV3 };
      }

      const commercialTruth = await refreshCommercialTruth(env);
      const growthMultiplier = await isolated(() => runGrowthMultiplierV2Cycle(env, {
        trigger: recoveryGrowth && !growthSlot ? "superautonomy_anti_stall_growth_multiplier" : "cloudflare_hourly_growth_multiplier"
      }));
      const growth = await runAutonomousGrowthLoop(env, {
        trigger: recoveryGrowth && !growthSlot ? "superautonomy_anti_stall_recovery" : "cloudflare_hourly_growth_after_commercial_truth",
        scheduledTime:controller?.scheduledTime || null,
      });

      return { ok:Boolean(growth?.ok), commercialTruth, growthMultiplier, growth, metaPrepare, superautonomy, selfLearning, metaLearn, selfCritic, superautonomyV3 };
    })().catch(() => ({ ok:false, isolatedFailure:true })));

    return adaptiveCore.scheduled(controller, env, ctx);
  }
};
