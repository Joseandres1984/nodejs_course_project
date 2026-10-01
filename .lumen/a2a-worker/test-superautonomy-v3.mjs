import assert from "node:assert/strict";
import {
  SUPER_AUTONOMY_V3_VERSION,
  capabilityLevel,
  autonomyMode,
  deriveSelfModel,
  chooseStrategyExperiment,
  buildAutonomousPlan,
} from "./superautonomy-v3.js";

assert.equal(SUPER_AUTONOMY_V3_VERSION, "3.0-four-engine-superautonomy");
assert.equal(capabilityLevel(20, 0), 0);
assert.equal(autonomyMode(0), "OBSERVE_ONLY");
assert.equal(autonomyMode(3), "AUTONOMOUS_REVERSIBLE");
assert.equal(autonomyMode(4), "TRUSTED_AUTONOMOUS_REVERSIBLE");

function baseContext() {
  return {
    cycle: 42,
    phase: "FOLLOWUP",
    bottleneck: "due_followup",
    contextKey: "FOLLOWUP:due_followup",
    nextAction: "EXECUTE_DUE_FOLLOWUP",
    selectedTactic: "due_followup",
    targetMetric: "followupsReady",
    currentValue: 2,
    baselineValue: 2,
    stallCycles: 0,
    recoveryLevel: 0,
    autonomyRatio: 0.92,
    goals: [{ objective: "Convert existing commercial evidence first." }],
    actionMemory: [],
    contextMemory: [],
    meta: null,
    delegation: { total:0, planned:0, approved:0, active:0, results:0, failed:0, avgQuality:0 },
    teams: { total:0, active:0, bestScore:0 },
    learning: { total:0, positive:0, nonpositive:0 },
    postmortems: { total:0, progress:0 },
  };
}

{
  const context = baseContext();
  const model = deriveSelfModel(context);
  const followup = model.find(x => x.capability === "outbound_followup");
  assert.ok(followup);
  assert.ok(followup.level <= 1, "No evidence must not unlock autonomous reversible execution");
  const experiment = chooseStrategyExperiment(context);
  const plan = buildAutonomousPlan(context, model, experiment, null);
  const execute = plan.steps.find(x => x.kind === "EXECUTE_TACTIC");
  assert.equal(execute.authority, "PREPARE_ONLY");
  assert.equal(plan.authority.autonomousSpendUsd, 0);
  assert.equal(plan.authority.bindingActionsHumanGated, true);
  assert.equal(plan.authority.productionDeploy, false);
}

{
  const context = baseContext();
  context.actionMemory = [
    { action_key:"due_followup", attempts:14, wins:12, stalls:2, score:1.55, last_outcome:"VERIFIED_PROGRESS" },
    { action_key:"followup_reframe", attempts:7, wins:4, stalls:3, score:1.18, last_outcome:"VERIFIED_PROGRESS" },
  ];
  context.contextMemory = [
    { context_key:context.contextKey, action_key:"due_followup", attempts:9, wins:8, stalls:1, score:1.55 },
    { context_key:context.contextKey, action_key:"followup_reframe", attempts:6, wins:3, stalls:3, score:1.10 },
  ];
  context.meta = {
    preferred_action:"due_followup",
    challenger_action:"followup_reframe",
    recommendation:{ whatWouldChangeMyMind:"Rotate if two comparable follow-up cycles fail to improve the target metric." }
  };
  context.learning = { total:12, positive:9, nonpositive:3 };
  context.postmortems = { total:10, progress:8 };
  const model = deriveSelfModel(context);
  const followup = model.find(x => x.capability === "outbound_followup");
  assert.ok(followup.level >= 3, "Repeated verified success should earn reversible autonomy");
  const experiment = chooseStrategyExperiment(context);
  assert.equal(experiment.recommendedArm, "CHAMPION");
  const plan = buildAutonomousPlan(context, model, experiment, null);
  const execute = plan.steps.find(x => x.kind === "EXECUTE_TACTIC");
  assert.equal(execute.authority, "AUTO_REVERSIBLE");
}

{
  const context = baseContext();
  context.stallCycles = 4;
  context.recoveryLevel = 2;
  context.actionMemory = [
    { action_key:"due_followup", attempts:8, wins:5, stalls:3, score:1.30 },
    { action_key:"followup_reframe", attempts:3, wins:2, stalls:1, score:1.22 },
  ];
  context.contextMemory = [
    { context_key:context.contextKey, action_key:"due_followup", attempts:6, wins:3, stalls:3, score:1.15 },
    { context_key:context.contextKey, action_key:"followup_reframe", attempts:3, wins:2, stalls:1, score:1.20 },
  ];
  context.meta = {
    preferred_action:"due_followup",
    challenger_action:"followup_reframe",
    recommendation:{ whatWouldChangeMyMind:"The next comparable stall should rotate the tactic." }
  };
  const experiment = chooseStrategyExperiment(context);
  assert.equal(experiment.recommendedArm, "CHALLENGER");
  assert.equal(experiment.recommendedAction, "followup_reframe");
  assert.ok(experiment.explorationShare >= 0.35);
  const model = deriveSelfModel(context);
  const plan = buildAutonomousPlan(context, model, experiment, { context_key:context.contextKey });
  assert.equal(plan.selectedAction, "followup_reframe");
  assert.equal(plan.accelerateGrowthLoop, true);
  assert.ok(plan.steps.some(x => x.kind === "REPLAN"));
}

{
  const context = baseContext();
  context.bottleneck = "qualified_reply";
  context.contextKey = "CONVERTING:qualified_reply";
  context.stallCycles = 5;
  context.recoveryLevel = 2;
  context.actionMemory = [
    { action_key:"qualify_and_reply", attempts:12, wins:10, stalls:2, score:1.6 },
    { action_key:"objection_response", attempts:9, wins:7, stalls:2, score:1.5 },
  ];
  context.contextMemory = [
    { context_key:context.contextKey, action_key:"qualify_and_reply", attempts:7, wins:5, stalls:2, score:1.45 },
    { context_key:context.contextKey, action_key:"objection_response", attempts:5, wins:4, stalls:1, score:1.42 },
  ];
  context.teams = { total:10, active:8, bestScore:92 };
  context.delegation = { total:10, planned:1, approved:2, active:1, results:8, failed:1, avgQuality:90 };
  context.learning = { total:12, positive:10, nonpositive:2 };
  context.postmortems = { total:10, progress:8 };
  const model = deriveSelfModel(context);
  const plan = buildAutonomousPlan(context, model, chooseStrategyExperiment(context), null);
  assert.equal(plan.needsSwarm, true);
  assert.ok(plan.steps.some(x => x.kind === "SWARM"));
  assert.ok(plan.steps.some(x => x.kind === "ESCALATE_ONLY_IF_REQUIRED"));
  assert.equal(plan.authority.autonomousContract, false);
  assert.equal(plan.authority.autonomousDebt, false);
}

console.log("SUPER_AUTONOMY_V3_TESTS_OK");
