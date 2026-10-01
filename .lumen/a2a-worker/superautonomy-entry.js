import adaptiveEntry from "./adaptive-entry.js";
import { handleSuperautonomy, runSuperautonomyCycle } from "./superautonomy-live.js";
import { runAutonomousGrowthLoop } from "./autonomous-growth-loop-v11.js";

async function isolated(step) {
  try { return await step(); }
  catch (error) {
    return { ok:false, isolatedFailure:true, error:String(error?.message || error || "superautonomy_failed").slice(0,240) };
  }
}

function isGrowthSlot(scheduledTime) {
  const when = new Date(Number(scheduledTime || Date.now()));
  return when.getUTCMinutes() === 7;
}

export default {
  async fetch(request, env, ctx) {
    const response = await handleSuperautonomy(request, env);
    if (response) return response;
    return adaptiveEntry.fetch(request, env, ctx);
  },

  async scheduled(controller, env, ctx) {
    const scheduledTime = controller?.scheduledTime || Date.now();

    ctx.waitUntil((async () => {
      const superautonomy = await isolated(() => runSuperautonomyCycle(env, {
        trigger: "cloudflare_scheduled_superautonomy"
      }));

      if (
        superautonomy?.ok === true &&
        superautonomy?.recovery?.accelerateGrowthLoop === true &&
        !isGrowthSlot(scheduledTime)
      ) {
        await isolated(() => runAutonomousGrowthLoop(env, {
          trigger: "superautonomy_anti_stall_recovery",
          scheduledTime
        }));
      }

      return superautonomy;
    })());

    return adaptiveEntry.scheduled(controller, env, ctx);
  }
};
