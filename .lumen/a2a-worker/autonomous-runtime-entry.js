import opportunityWorker from "./opportunity-entry.js";
import { handleAutonomousGrowthLoop, runAutonomousGrowthLoop } from "./autonomous-growth-loop-v11.js";

const GROWTH_CRON = "12 * * * *";

function growthEnabled(env) {
  return String(env?.LUMEN_AUTONOMOUS_GROWTH ?? "true").trim().toLowerCase() === "true";
}

export default {
  async fetch(request, env, ctx) {
    const growthResponse = await handleAutonomousGrowthLoop(request, env);
    if (growthResponse) return growthResponse;
    return opportunityWorker.fetch(request, env, ctx);
  },

  scheduled(controller, env, ctx) {
    const cron = String(controller?.cron || "").trim();

    if (cron === GROWTH_CRON) {
      if (!growthEnabled(env)) return;
      ctx.waitUntil(runAutonomousGrowthLoop(env, {
        trigger: "cloudflare_cron_hourly",
        scheduledTime: controller?.scheduledTime || null,
      }));
      return;
    }

    return opportunityWorker.scheduled(controller, env, ctx);
  },
};
