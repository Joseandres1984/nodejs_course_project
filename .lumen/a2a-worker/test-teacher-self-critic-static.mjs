import fs from 'node:fs';
import assert from 'node:assert/strict';

const engine = fs.readFileSync(new URL('./teacher-self-critic.js', import.meta.url), 'utf8');
const entry = fs.readFileSync(new URL('./adaptive-entry.js', import.meta.url), 'utf8');

for (const token of [
  'human_feedback_is_a_hypothesis_not_ground_truth',
  'verifiedEvidenceOverridesAdvice:true',
  'selfModifyingCode:false',
  'autonomousSpendUsd:0',
  'bindingActionsHumanGated:true',
  'MAX_TEACHER_NUDGE = 0.04',
  'whatWouldChangeMyMind',
  'ROTATE_TO_CHALLENGER',
  'RUN_COMPARATIVE_TEST',
  '/teacher/feedback',
  '/self-critic/status',
]) assert.ok(engine.includes(token), `missing ${token}`);

for (const token of [
  'handleTeacherSelfCritic',
  'runSelfCriticCycle',
  'scheduled_after_meta_learning',
]) assert.ok(entry.includes(token), `adaptive entry missing ${token}`);

console.log('TEACHER_SELF_CRITIC_STATIC_OK');
