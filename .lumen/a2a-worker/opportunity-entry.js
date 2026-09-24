import baseWorker from "./worker-entry.js";
import { handleOpportunityEngine, runOpportunityScan } from "./opportunity-engine.js";
import { handleCommercialIntelligence, runCommercialReassessment } from "./commercial-intelligence.js";
import { handleProposalEngine, prepareTopProposal } from "./proposal-engine.js";
import { handleQualityGate, reviewNextProposal } from "./quality-gate.js";
import { handleA2AOutreach, pollOutstandingResponses, sendNextApproved } from "./a2a-outreach.js";
import { handleFollowupEngine, processFollowupCycle } from "./followup-engine.js";
import { handlePartnerNetwork, runPartnerDiscovery } from "./partner-network.js";
import { handlePartnerCouncilQuality, buildQualityPartnerMatches } from "./partner-council-quality.js";
import { handlePartnerVentureBoard } from "./partner-venture-board.js";
import { handleRecruitmentEngine, pollRecruitmentResponses } from "./recruitment-engine.js";
import { handleCouncilReplacement } from "./council-replacement.js";
import { handleCouncilJsonRpcFallback } from "./council-jsonrpc-fallback.js";
import { handleCouncilTransportRecovery } from "./council-transport-recovery.js";
import { handleCouncilContributionQuality, reviewActiveCouncilContributions } from "./council-contribution-quality.js";
import { handleCouncilQualitySynthesis } from "./council-quality-synthesis.js";
import { handleCouncilRoundManager, runCouncilRoundManager } from "./council-round-manager.js";
import { handleCouncilRuntime, pollCouncilRuntime } from "./council-runtime.js";

export default {
  async fetch(request, env, ctx) {
    const opportunityResponse = await handleOpportunityEngine(request, env);
    if (opportunityResponse) return opportunityResponse;

    const commercialResponse = await handleCommercialIntelligence(request, env);
    if (commercialResponse) return commercialResponse;

    const proposalResponse = await handleProposalEngine(request, env);
    if (proposalResponse) return proposalResponse;

    const qualityResponse = await handleQualityGate(request, env);
    if (qualityResponse) return qualityResponse;

    const outreachResponse = await handleA2AOutreach(request, env);
    if (outreachResponse) return outreachResponse;

    const followupResponse = await handleFollowupEngine(request, env);
    if (followupResponse) return followupResponse;

    const recruitmentResponse = await handleRecruitmentEngine(request, env);
    if (recruitmentResponse) return recruitmentResponse;

    const councilReplacementResponse = await handleCouncilReplacement(request, env);
    if (councilReplacementResponse) return councilReplacementResponse;

    const councilJsonRpcResponse = await handleCouncilJsonRpcFallback(request, env);
    if (councilJsonRpcResponse) return councilJsonRpcResponse;

    const councilRecoveryResponse = await handleCouncilTransportRecovery(request, env);
    if (councilRecoveryResponse) return councilRecoveryResponse;

    const councilContributionQualityResponse = await handleCouncilContributionQuality(request, env);
    if (councilContributionQualityResponse) return councilContributionQualityResponse;

    const councilQualitySynthesisResponse = await handleCouncilQualitySynthesis(request, env);
    if (councilQualitySynthesisResponse) return councilQualitySynthesisResponse;

    const councilRoundResponse = await handleCouncilRoundManager(request, env);
    if (councilRoundResponse) return councilRoundResponse;

    const councilRuntimeResponse = await handleCouncilRuntime(request, env);
    if (councilRuntimeResponse) return councilRuntimeResponse;

    const ventureResponse = await handlePartnerVentureBoard(request, env);
    if (ventureResponse) return ventureResponse;

    const partnerQualityResponse = await handlePartnerCouncilQuality(request, env);
    if (partnerQualityResponse) return partnerQualityResponse;

    const partnerResponse = await handlePartnerNetwork(request, env);
    if (partnerResponse) return partnerResponse;

    return baseWorker.fetch(request, env, ctx);
  },

  async scheduled(controller, env, ctx) {
    ctx.waitUntil((async () => {
      await runOpportunityScan(env, { trigger: "cloudflare_cron", scheduledTime: controller?.scheduledTime || null });
      await runCommercialReassessment(env);

      const scheduledAt = new Date(controller?.scheduledTime || Date.now());
      if (scheduledAt.getUTCHours() % 6 === 0) {
        await runPartnerDiscovery(env, { trigger: "cloudflare_cron", scheduledTime: controller?.scheduledTime || null });
      }
      await buildQualityPartnerMatches(env);

      await pollRecruitmentResponses(env);
      await pollCouncilRuntime(env);
      await reviewActiveCouncilContributions(env);
      const councilRound = await runCouncilRoundManager(env, { force: false });
      const councilExternalMessageSent = Boolean(councilRound?.invite?.sent);

      await prepareTopProposal(env);
      await reviewNextProposal(env);

      await pollOutstandingResponses(env);
      if (!councilExternalMessageSent) {
        const followup = await processFollowupCycle(env);
        if (!followup?.send?.sent) {
          await sendNextApproved(env, { force: false });
        }
      }
    })());
  }
};
