import adaptiveCore from "./adaptive-core-entry.js";
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
import { syncX402SettlementsToRevenue } from "./x402-revenue-bridge.js";
import { syncReferralSettlements } from "./referral-network.js";
import { syncReferralCommissionSettlements } from "./referral-commission-engine.js";
import { recomputeRevenueAttribution } from "./revenue-attribution-engine.js";
import { recomputeProfitFeedback } from "./profit-feedback-engine.js";

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

async function refreshCommercialTruth(env) {
  const x402 = await isolated(() => syncX402SettlementsToRevenue(env));
  const referralCommissions = await isolated(() => syncReferralCommissionSettlements(env));
  const referrals = await isolated(() => syncReferralSettlements(env));
  const revenueAttribution = await isolated(() => recomputeRevenueAttribution(env));
  const profitFeedback = await isolated(() => recomputeProfitFeedback(env));

  return {
    ok: [x402, referralCommissions, referrals, revenueAttribution, profitFeedback].every(result => result?.ok !== false),
    x402,
    referralCommissions,
    referrals,
    revenueAttribution,
    profitFeedback,
    truthOrder: [
      "verified_settlements",
      "referral_settlements",
      "revenue_attribution",
      "profit_feedback",
      "growth_decision"
    ],
    guardrails: {
      verifiedSettlementRequiredForRevenue: true,
      autonomousSpendUsd: 0,
      bindingActionsHumanGated: true
    }
  };
}

export default {
  async fetch(request, env, ctx) {
    const growthResponse = await handleAutonomousGrowthLoop(request, env);
    if (growthResponse) return growthResponse;

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

    ctx.waitUntil((async () => {
      await isolated(() => syncViatorBookingConversions(env));
      await isolated(() => runTravelAcquisitionEngine(env));

      if (!growthSlot) return { ok:true, growthSkipped:true };

      const commercialTruth = await refreshCommercialTruth(env);
      const growth = await runAutonomousGrowthLoop(env, {
        trigger:"cloudflare_hourly_growth_after_commercial_truth",
        scheduledTime:controller?.scheduledTime || null,
      });

      return { ok:Boolean(growth?.ok), commercialTruth, growth };
    })().catch(() => ({ ok:false, isolatedFailure:true })));

    return adaptiveCore.scheduled(controller, env, ctx);
  }
};