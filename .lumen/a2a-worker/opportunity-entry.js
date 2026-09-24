import baseWorker from "./worker-entry.js";
import { handleOpportunityEngine, runOpportunityScan } from "./opportunity-engine.js";
import { handleCommercialIntelligence, runCommercialReassessment } from "./commercial-intelligence.js";
import { handleProposalEngine, prepareTopProposal } from "./proposal-engine.js";
import { handleQualityGate, reviewNextProposal } from "./quality-gate.js";
import { handleA2AOutreach, pollOutstandingResponses, sendNextApproved } from "./a2a-outreach.js";
import { handleFollowupEngine, processFollowupCycle } from "./followup-engine.js";
import { handleCommercialReplyEngine, runCommercialReplyEngine, pollCommercialReplyTasks } from "./commercial-reply-engine.js";
import { handleFirstCashCloser, runFirstCashCloser } from "./first-cash-closer.js";
import { handleX402RevenueBridge, syncX402SettlementsToRevenue } from "./x402-revenue-bridge.js";
import { handleRevenueDirector, recomputeRevenueDirector } from "./revenue-director.js";
import { handlePartnerNetwork, runPartnerDiscovery } from "./partner-network.js";
import { handlePartnerCouncilQuality, buildQualityPartnerMatches } from "./partner-council-quality.js";
import { handlePartnerVentureBoard } from "./partner-venture-board.js";
import { handleVentureSuggestionIntake, ingestCouncilVentureSuggestions } from "./venture-suggestion-intake.js";
import { handleVentureCouncil, runVentureCouncil } from "./venture-council-engine.js";
import { handleVenturePeerReview, planVenturePeerReviews } from "./venture-peer-review.js";
import { handleCapabilityGapEngine, recomputeCapabilityGaps } from "./capability-gap-engine.js";
import { handlePartnerMarketplace, syncPartnerMarketplace, reviewMarketplaceInterests } from "./partner-marketplace.js";
import { handlePartnerMarketplacePublicCatalog } from "./partner-marketplace-public-catalog.js";
import { handleReferralNetwork, reviewInboundReferrals, planOutboundReferrals, syncReferralSettlements } from "./referral-network.js";
import { handleRevenueAttribution, recomputeRevenueAttribution } from "./revenue-attribution-engine.js";
import { handleProfitFeedback, recomputeProfitFeedback } from "./profit-feedback-engine.js";
import { handlePartnerEconomicPerformance, recomputePartnerEconomicPerformance } from "./partner-economic-performance.js";
import { handlePartnerNegotiator, recomputeNegotiator } from "./partner-negotiator.js";
import { handleNegotiatorTermsPlanner, planNegotiationTermRequests } from "./negotiator-terms-planner.js";
import { handleNegotiatorTermsRuntime, pollNegotiationTermResponses, sendNegotiationTermRequests } from "./negotiator-terms-runtime.js";
import { handleAgentEconomy, recomputeAgentEconomy } from "./agent-economy.js";
import { handleAgentGraph, recomputeAgentGraph } from "./agent-graph.js";
import { handleDynamicTeamEngine, buildDynamicTeams } from "./dynamic-team-engine.js";
import { handleRedundancyEngine, recomputeRedundancy } from "./redundancy-engine.js";
import { handleTrustLayer, recomputeTrust } from "./trust-layer.js";
import { handleUntrustedInputFirewall, sanitizeCouncilInputs, sanitizeDelegationResults } from "./untrusted-input-firewall.js";
import { handleRecruitmentEngine, pollRecruitmentResponses } from "./recruitment-engine.js";
import { handleCouncilReplacement } from "./council-replacement.js";
import { handleCouncilJsonRpcFallback } from "./council-jsonrpc-fallback.js";
import { handleCouncilTransportRecovery } from "./council-transport-recovery.js";
import { handleCouncilContributionQuality, reviewActiveCouncilContributions } from "./council-contribution-quality.js";
import { handleCouncilQualitySynthesis } from "./council-quality-synthesis.js";
import { handleCouncilRoundManager, runCouncilRoundManager } from "./council-round-manager.js";
import { handleDelegationEngine, planLatestSynthesizedCouncil } from "./delegation-engine.js";
import { handleDelegationQualityGate, reviewPendingDelegationTasks } from "./delegation-quality-gate.js";
import { handleDelegationResultQuality, reviewDelegationResults } from "./delegation-result-quality.js";
import { handleTrustedDelegationDispatch } from "./trusted-delegation-dispatch.js";
import { handleDelegationRuntime, pollDelegationTasks } from "./delegation-runtime.js";
import { handleObservedPartnerReputation, recomputeObservedReputation } from "./partner-observed-reputation.js";
import { handleCouncilRuntime, pollCouncilRuntime } from "./council-runtime.js";

export default {
  async fetch(request, env, ctx) {
    const opportunityResponse = await handleOpportunityEngine(request, env); if (opportunityResponse) return opportunityResponse;
    const commercialResponse = await handleCommercialIntelligence(request, env); if (commercialResponse) return commercialResponse;
    const proposalResponse = await handleProposalEngine(request, env); if (proposalResponse) return proposalResponse;
    const qualityResponse = await handleQualityGate(request, env); if (qualityResponse) return qualityResponse;
    const outreachResponse = await handleA2AOutreach(request, env); if (outreachResponse) return outreachResponse;
    const followupResponse = await handleFollowupEngine(request, env); if (followupResponse) return followupResponse;
    const commercialReplyResponse = await handleCommercialReplyEngine(request, env); if (commercialReplyResponse) return commercialReplyResponse;
    const firstCashResponse = await handleFirstCashCloser(request, env); if (firstCashResponse) return firstCashResponse;
    const x402RevenueBridgeResponse = await handleX402RevenueBridge(request, env); if (x402RevenueBridgeResponse) return x402RevenueBridgeResponse;
    const revenueDirectorResponse = await handleRevenueDirector(request, env); if (revenueDirectorResponse) return revenueDirectorResponse;
    const recruitmentResponse = await handleRecruitmentEngine(request, env); if (recruitmentResponse) return recruitmentResponse;
    const councilReplacementResponse = await handleCouncilReplacement(request, env); if (councilReplacementResponse) return councilReplacementResponse;
    const councilJsonRpcResponse = await handleCouncilJsonRpcFallback(request, env); if (councilJsonRpcResponse) return councilJsonRpcResponse;
    const councilRecoveryResponse = await handleCouncilTransportRecovery(request, env); if (councilRecoveryResponse) return councilRecoveryResponse;
    const councilContributionQualityResponse = await handleCouncilContributionQuality(request, env); if (councilContributionQualityResponse) return councilContributionQualityResponse;
    const councilQualitySynthesisResponse = await handleCouncilQualitySynthesis(request, env); if (councilQualitySynthesisResponse) return councilQualitySynthesisResponse;
    const councilRoundResponse = await handleCouncilRoundManager(request, env); if (councilRoundResponse) return councilRoundResponse;
    const delegationResponse = await handleDelegationEngine(request, env); if (delegationResponse) return delegationResponse;
    const delegationQualityResponse = await handleDelegationQualityGate(request, env); if (delegationQualityResponse) return delegationQualityResponse;
    const delegationResultQualityResponse = await handleDelegationResultQuality(request, env); if (delegationResultQualityResponse) return delegationResultQualityResponse;
    const trustedDelegationResponse = await handleTrustedDelegationDispatch(request, env); if (trustedDelegationResponse) return trustedDelegationResponse;
    const delegationRuntimeResponse = await handleDelegationRuntime(request, env); if (delegationRuntimeResponse) return delegationRuntimeResponse;
    const observedReputationResponse = await handleObservedPartnerReputation(request, env); if (observedReputationResponse) return observedReputationResponse;
    const trustResponse = await handleTrustLayer(request, env); if (trustResponse) return trustResponse;
    const firewallResponse = await handleUntrustedInputFirewall(request, env); if (firewallResponse) return firewallResponse;
    const councilRuntimeResponse = await handleCouncilRuntime(request, env); if (councilRuntimeResponse) return councilRuntimeResponse;
    const ventureResponse = await handlePartnerVentureBoard(request, env); if (ventureResponse) return ventureResponse;
    const ventureIntakeResponse = await handleVentureSuggestionIntake(request, env); if (ventureIntakeResponse) return ventureIntakeResponse;
    const ventureCouncilResponse = await handleVentureCouncil(request, env); if (ventureCouncilResponse) return ventureCouncilResponse;
    const venturePeerReviewResponse = await handleVenturePeerReview(request, env); if (venturePeerReviewResponse) return venturePeerReviewResponse;
    const capabilityGapResponse = await handleCapabilityGapEngine(request, env); if (capabilityGapResponse) return capabilityGapResponse;
    const marketplaceCatalogResponse = await handlePartnerMarketplacePublicCatalog(request, env); if (marketplaceCatalogResponse) return marketplaceCatalogResponse;
    const marketplaceResponse = await handlePartnerMarketplace(request, env); if (marketplaceResponse) return marketplaceResponse;
    const referralResponse = await handleReferralNetwork(request, env); if (referralResponse) return referralResponse;
    const revenueAttributionResponse = await handleRevenueAttribution(request, env); if (revenueAttributionResponse) return revenueAttributionResponse;
    const profitFeedbackResponse = await handleProfitFeedback(request, env); if (profitFeedbackResponse) return profitFeedbackResponse;
    const partnerEconomicResponse = await handlePartnerEconomicPerformance(request, env); if (partnerEconomicResponse) return partnerEconomicResponse;
    const negotiatorResponse = await handlePartnerNegotiator(request, env); if (negotiatorResponse) return negotiatorResponse;
    const negotiatorTermsResponse = await handleNegotiatorTermsPlanner(request, env); if (negotiatorTermsResponse) return negotiatorTermsResponse;
    const negotiatorTermsRuntimeResponse = await handleNegotiatorTermsRuntime(request, env); if (negotiatorTermsRuntimeResponse) return negotiatorTermsRuntimeResponse;
    const economyResponse = await handleAgentEconomy(request, env); if (economyResponse) return economyResponse;
    const agentGraphResponse = await handleAgentGraph(request, env); if (agentGraphResponse) return agentGraphResponse;
    const dynamicTeamResponse = await handleDynamicTeamEngine(request, env); if (dynamicTeamResponse) return dynamicTeamResponse;
    const redundancyResponse = await handleRedundancyEngine(request, env); if (redundancyResponse) return redundancyResponse;
    const partnerQualityResponse = await handlePartnerCouncilQuality(request, env); if (partnerQualityResponse) return partnerQualityResponse;
    const partnerResponse = await handlePartnerNetwork(request, env); if (partnerResponse) return partnerResponse;
    return baseWorker.fetch(request, env, ctx);
  },

  async scheduled(controller, env, ctx) {
    ctx.waitUntil((async () => {
      await runOpportunityScan(env, { trigger: "cloudflare_cron", scheduledTime: controller?.scheduledTime || null });
      await runCommercialReassessment(env);

      // Revenue conversations come first. Poll old messages, then async commercial replies, then close hot intent.
      await pollOutstandingResponses(env);
      await pollCommercialReplyTasks(env);
      const firstCash = await runFirstCashCloser(env, { force: false });
      const firstCashExternalMessageSent = Boolean(firstCash?.sent);
      const commercialReply = firstCashExternalMessageSent
        ? { sent: false, reason: "first_cash_conversion_has_external_priority" }
        : await runCommercialReplyEngine(env, { force: false });
      const commercialReplyExternalMessageSent = Boolean(commercialReply?.sent);
      const conversionExternalMessageSent = firstCashExternalMessageSent || commercialReplyExternalMessageSent;

      const scheduledAt = new Date(controller?.scheduledTime || Date.now());
      if (scheduledAt.getUTCHours() % 6 === 0) await runPartnerDiscovery(env, { trigger: "cloudflare_cron", scheduledTime: controller?.scheduledTime || null });
      await recomputeTrust(env, { limit: 6 });
      await buildQualityPartnerMatches(env);
      await pollRecruitmentResponses(env);
      await pollCouncilRuntime(env);
      await reviewActiveCouncilContributions(env);
      await sanitizeCouncilInputs(env);
      const councilRound = conversionExternalMessageSent
        ? { acted: false, reason: "commercial_conversion_has_external_priority" }
        : await runCouncilRoundManager(env, { force: false });
      const councilExternalMessageSent = Boolean(councilRound?.invite?.sent);
      await planLatestSynthesizedCouncil(env);
      await reviewPendingDelegationTasks(env);
      await pollDelegationTasks(env);
      await reviewDelegationResults(env);
      await sanitizeDelegationResults(env);
      await ingestCouncilVentureSuggestions(env);
      await runVentureCouncil(env);
      await planVenturePeerReviews(env, { limit: 6 });
      await recomputeCapabilityGaps(env);
      await syncPartnerMarketplace(env);
      await reviewMarketplaceInterests(env);
      await reviewInboundReferrals(env);
      await planOutboundReferrals(env);
      await syncReferralSettlements(env);

      // Canonical cash truth: settled x402 receipt -> verified revenue event -> attribution -> learning.
      await syncX402SettlementsToRevenue(env);
      await recomputeRevenueAttribution(env);
      await recomputePartnerEconomicPerformance(env);
      await recomputeObservedReputation(env);
      await recomputeProfitFeedback(env);
      await recomputeRevenueDirector(env);
      await pollNegotiationTermResponses(env);
      await recomputeNegotiator(env);
      await planNegotiationTermRequests(env);
      let termsExternalMessageSent = false;
      if (!conversionExternalMessageSent && !councilExternalMessageSent) {
        const termInquiry = await sendNegotiationTermRequests(env, { force: false, limit: 1 });
        termsExternalMessageSent = Number(termInquiry?.sent || 0) > 0;
      }
      // Agent Economy only accounts/plans; outgoing execution is hard-blocked at USD 0.
      await recomputeAgentEconomy(env);
      await recomputeAgentGraph(env);
      await buildDynamicTeams(env);
      await recomputeRedundancy(env);
      await prepareTopProposal(env);
      await reviewNextProposal(env);

      if (!conversionExternalMessageSent && !councilExternalMessageSent && !termsExternalMessageSent) {
        const followup = await processFollowupCycle(env);
        if (!followup?.send?.sent) await sendNextApproved(env, { force: false });
      }
    })());
  }
};