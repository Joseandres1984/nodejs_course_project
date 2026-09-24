import baseWorker from "./worker-entry.js";
import { handleOpportunityEngine, runOpportunityScan } from "./opportunity-engine.js";
import { handleCommercialIntelligence, runCommercialReassessment } from "./commercial-intelligence.js";
import { handleProposalEngine, prepareTopProposal } from "./proposal-engine.js";

export default {
  async fetch(request, env, ctx) {
    const opportunityResponse = await handleOpportunityEngine(request, env);
    if (opportunityResponse) return opportunityResponse;

    const commercialResponse = await handleCommercialIntelligence(request, env);
    if (commercialResponse) return commercialResponse;

    const proposalResponse = await handleProposalEngine(request, env);
    if (proposalResponse) return proposalResponse;

    return baseWorker.fetch(request, env, ctx);
  },

  async scheduled(controller, env, ctx) {
    ctx.waitUntil((async () => {
      await runOpportunityScan(env, { trigger: "cloudflare_cron", scheduledTime: controller?.scheduledTime || null });
      await runCommercialReassessment(env);
      await prepareTopProposal(env);
    })());
  }
};
