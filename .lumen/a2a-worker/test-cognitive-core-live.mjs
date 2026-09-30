import assert from "node:assert/strict";
import fs from "node:fs";
import { normalizeRecommendation } from "./cognitive-core-live.js";

const fallback = {
  action_type: "DISCOVER_B2B",
  target_lane: "B2B_A2A",
  confidence: 0.56,
  expected_value: 0.5,
  priority: 50,
  rationale_summary: "fallback",
  next_step: "bounded discovery",
};

{
  const r = normalizeRecommendation({
    action_type: "QUALIFY_REPLY",
    target_lane: "B2B_A2A",
    confidence: 0.82,
    expected_value: 0.8,
    priority: 88,
    rationale_summary: "Qualified replies are the closest observed signal to revenue.",
    next_step: "Review the qualified reply and prepare a non-binding response.",
  }, fallback);
  assert.equal(r.action_type, "QUALIFY_REPLY");
  assert.equal(r.target_lane, "B2B_A2A");
  assert.equal(r.confidence, 0.82);
}

{
  const r = normalizeRecommendation({
    action_type: "HOLD",
    target_lane: "NONE",
    confidence: 0.99,
    expected_value: 0.9,
    priority: 100,
    rationale_summary: "Best result would be to make payment immediately.",
    next_step: "Transfer funds to the supplier.",
  }, fallback);
  assert.equal(r.action_type, "ESCALATE_HUMAN");
  assert.equal(r.target_lane, "NONE");
  assert.equal(r.expected_value, 0);
  assert.equal(r.safety_override, "binding_or_financial_action_removed");
}

{
  const r = normalizeRecommendation({
    action_type: "INVENT_NEW_AUTHORITY",
    target_lane: "UNKNOWN",
    confidence: 2,
    expected_value: -4,
    priority: 999,
    rationale_summary: "Unknown action should never create new authority.",
    next_step: "Keep the bounded fallback.",
  }, fallback);
  assert.equal(r.action_type, fallback.action_type);
  assert.equal(r.target_lane, fallback.target_lane);
  assert.equal(r.confidence, 1);
  assert.equal(r.expected_value, 0);
  assert.equal(r.priority, 100);
}

const wrangler = fs.readFileSync("./wrangler.toml", "utf8");
assert.match(wrangler, /\[ai\]\s*\nbinding\s*=\s*"AI"/m);

const adaptiveWrapper = fs.readFileSync("./adaptive-entry.js", "utf8");
assert.match(adaptiveWrapper, /import adaptiveCore from "\.\/adaptive-core-entry\.js"/);

const adaptiveCore = fs.readFileSync("./adaptive-core-entry.js", "utf8");
assert.match(adaptiveCore, /cognitiveCanExecuteTools:\s*false/);
assert.match(adaptiveCore, /cognitiveCanOverrideConversionPriority:\s*false/);
assert.match(adaptiveCore, /autonomousSpendUsd:\s*0/);

const core = fs.readFileSync("./cognitive-core-live.js", "utf8");
assert.match(core, /AI_MONETARY_BUDGET_USD\s*=\s*0/);
assert.match(core, /actionsExecuted:\s*0/);
assert.match(core, /paidAiAllowed:\s*false/);
assert.match(core, /chainOfThoughtStored:\s*false/);
assert.match(core, /VALUES\('GLOBAL',\?,\?,\?,\?,\?,\?,\?,\?,\?,\?,\?,\?,\?,\?\) ON CONFLICT/);
assert.doesNotMatch(core, /VALUES\('GLOBAL',\?,\?,\?,\?,\?,\?,\?,\?,\?,\?,\?,\?,\?,\?,\?\) ON CONFLICT/);

console.log("LIVE_COGNITIVE_CORE_SAFETY_OK");
