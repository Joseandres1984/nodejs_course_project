import { WorkflowEntrypoint } from "cloudflare:workers";
import { refreshCommercialTruth } from "./adaptive-entry.js";
import { runLiveCognitiveCycle } from "./cognitive-core-live.js";
import { runMetaControllerCycle } from "./meta-controller.js";
import { runSuperautonomyCycle } from "./superautonomy-live.js";
import { runSelfLearningCycle } from "./self-learning-engine.js";
import { runSelfCriticCycle } from "./teacher-self-critic.js";
import { runSuperautonomyV3Cycle } from "./superautonomy-v3.js";
import { runGrowthMultiplierV2Cycle } from "./growth-multiplier-v2.js";
import { runGrowthEngineFoundryV2Cycle } from "./growth-engine-foundry-v2.js";
import { runAutonomousGrowthLoop } from "./autonomous-growth-loop-v11.js";
import { syncViatorBookingConversions } from "./viator-conversion-sync.js";
import { runTravelAcquisitionEngine } from "./travel-acquisition-engine.js";
import { withBudgetedAi } from "./ai-router.js";
import { ensureBoostSchema, checkpoint, recordRun, startOpportunityObservers, observeOpportunity } from "./paid-boost-runtime.js";
import { runSovereignCycle } from "./sovereign-runtime.js";

const MUTATING_STEP = { retries: { limit: 0, delay: "1 second" }, timeout: "3 minutes" };
const READ_STEP = { retries: { limit: 2, delay: "10 seconds", backoff: "exponential" }, timeout: "1 minute" };

export class LumenDeepWorkflow extends WorkflowEntrypoint {
  async run(event, step) {
    const env = withBudgetedAi(this.env), id = event.instanceId;
    await step.do("initialize", READ_STEP, async () => {
      await ensureBoostSchema(env);
      await recordRun(env, id, "DEEP", "RUNNING");
      return { ok: true };
    });
    const tasks = [
      ["verified-commercial-truth", () => refreshCommercialTruth(env)],
      ["cognitive-reasoning", () => runLiveCognitiveCycle(env, { trigger: "paid_boost_hourly_workflow" })],
      ["meta-prepare", () => runMetaControllerCycle(env, { trigger: "paid_boost_pre_superautonomy", applyNudge: true })],
      ["superautonomy", () => runSuperautonomyCycle(env, { trigger: "paid_boost_hourly_workflow" })],
      ["self-learning", () => runSelfLearningCycle(env, { trigger: "paid_boost_after_superautonomy" })],
      ["meta-learn", () => runMetaControllerCycle(env, { trigger: "paid_boost_after_self_learning", applyNudge: false })],
      ["self-critic", () => runSelfCriticCycle(env, { trigger: "paid_boost_after_meta_learning" })],
      ["superautonomy-v3", () => runSuperautonomyV3Cycle(env, { trigger: "paid_boost_after_self_critic" })],
      ["viator-conversions", () => syncViatorBookingConversions(env)],
      ["travel-acquisition", () => runTravelAcquisitionEngine(env)],
      ["growth-multiplier", () => runGrowthMultiplierV2Cycle(env, { trigger: "paid_boost_hourly_workflow" })],
      ["foundry-experiments", () => runGrowthEngineFoundryV2Cycle(env, { trigger: "paid_boost_hourly_workflow" })],
      ["growth-decision", () => runAutonomousGrowthLoop(env, { trigger: "paid_boost_hourly_workflow", scheduledTime: event.payload.scheduledTime })],
      ["sovereign-revenue-v4", () => runSovereignCycle(env, { runId: `v4-${id}` })],
      ["opportunity-observers", () => startOpportunityObservers(env)],
    ];
    const results = {};
    for (const [name, action] of tasks) {
      // One isolated failure does not discard earlier persisted steps.
      results[name] = await step.do(name, MUTATING_STEP, () => checkpoint(env, id, name, action));
    }
    const failed = Object.entries(results).filter(([, value]) => value?.ok === false).map(([name]) => name);
    return step.do("finish", READ_STEP, async () => {
      const result = { ok: failed.length === 0, failed, steps: tasks.length, autonomousSpendUsd: 0 };
      await recordRun(env, id, "DEEP", failed.length ? "DEGRADED" : "COMPLETED", result);
      // Bound history to roughly a month; never remove running claims.
      await env.DB.prepare("DELETE FROM lumen_paid_boost_steps WHERE updated_at<datetime('now','-35 days') AND status<>'RUNNING'").run();
      await env.DB.prepare("DELETE FROM lumen_paid_boost_runs WHERE updated_at<datetime('now','-35 days') AND status<>'RUNNING'").run();
      return result;
    });
  }
}

export class LumenOpportunityWorkflow extends WorkflowEntrypoint {
  async run(event, step) {
    const env = this.env, proposalId = event.payload.proposalId, id = event.instanceId;
    if (typeof proposalId !== "string" || proposalId.length > 160) throw new Error("invalid_proposal_id");
    await step.do("initialize", READ_STEP, async () => {
      await ensureBoostSchema(env);
      await recordRun(env, id, "OPPORTUNITY", "RUNNING");
      return { proposalId };
    });
    // Observe existing approvals and governor-controlled sends. Sleeping does
    // not occupy CPU. Never replay an external message or accept binding terms.
    for (let check = 0; check < 84; check++) {
      const observation = await step.do(`observe-${check}`, READ_STEP, () => observeOpportunity(env, proposalId, id));
      if (observation.paymentVerified || observation.stage === "PROPOSAL_MISSING") {
        await step.do("finish", READ_STEP, () => recordRun(env, id, "OPPORTUNITY", observation.stage, observation));
        return observation;
      }
      if (check < 83) await step.sleep(`wait-${check}`, "2 hours");
    }
    return step.do("expire", READ_STEP, async () => {
      await env.DB.prepare("UPDATE lumen_paid_boost_opportunities SET stage='OBSERVATION_EXPIRED',updated_at=? WHERE proposal_id=?").bind(new Date().toISOString(), proposalId).run();
      await recordRun(env, id, "OPPORTUNITY", "OBSERVATION_EXPIRED");
      return { proposalId, stage: "OBSERVATION_EXPIRED", paymentVerified: false };
    });
  }
}
