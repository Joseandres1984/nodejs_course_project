import assert from "node:assert/strict";
import { boundedBatchLimit } from "./a2a-outreach.js";

assert.equal(boundedBatchLimit("10"), 10);
assert.equal(boundedBatchLimit("1"), 1);
assert.equal(boundedBatchLimit("999"), 30);
assert.equal(boundedBatchLimit("0"), 1);
assert.equal(boundedBatchLimit("not-a-number"), 30);
console.log("CONTROLLED_BATCH_LIMIT_OK");
