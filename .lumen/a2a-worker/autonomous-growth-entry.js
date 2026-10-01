import opportunityWorker from "./opportunity-entry.js";
import { handleAutonomousGrowthLoop, runAutonomousGrowthLoop } from "./autonomous-growth-loop.js";

export default {
  async fetch(request, env, ctx) {
    const growthResponse = await handleAutonomousGrowthLoop(request, env);
    if (growthResponse) return growthResponse;
    return opportunityWorker.fetch(request, env, ctx);
  },

  async scheduled(controller, env, ctx) {
    opportunityWorker.scheduled(controller, env, ctx);
    const scheduledAt = new Date(controller?.scheduledTime || Date.now());
    if (scheduledAt.getUTCMinutes() === 7) {
      ctx.waitUntil(runAutonomousGrowthLoop(env, {
        trigger: "cloudflare_hourly_growth",
        scheduledTime: controller?.scheduledTime || null,
      }));
    }
  },
};
