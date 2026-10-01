import fs from 'node:fs';
import assert from 'node:assert/strict';

const conversation = fs.readFileSync(new URL('./lumen-conversation-v2.js', import.meta.url), 'utf8');
const learning = fs.readFileSync(new URL('./self-learning-engine.js', import.meta.url), 'utf8');
const adaptive = fs.readFileSync(new URL('./adaptive-entry.js', import.meta.url), 'utf8');

assert.match(conversation, /AI_TIMEOUT_MS = 6500/);
assert.match(conversation, /llama-3\.1-8b-instruct-fast/);
assert.match(conversation, /deterministic_grounded_fallback/);
assert.match(conversation, /no implica conciencia/);
assert.match(learning, /verifiedProgressRequiredForPromotion:true/);
assert.match(learning, /selfModifyingCode:false/);
assert.match(learning, /autonomousSpendUsd:0/);
assert.match(adaptive, /runSelfLearningCycle/);
assert.match(adaptive, /handleSelfLearning/);

console.log('LUMEN_MIND_V2_STATIC_OK');
