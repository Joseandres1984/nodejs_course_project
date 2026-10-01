import assert from "node:assert/strict";
import { deterministicReply } from "./lumen-conversation.js";

const snapshot = {
  economic: {
    phase: "FOLLOWUP",
    nextEconomicAction: "FOLLOW_UP",
    metrics: { verifiedRevenueUsd: 0 },
    revenueFocus: { backlog: { followupsReady: 2 } },
  },
  superautonomy: {
    phase: "FOLLOWUP",
    bottleneck: "due_followup",
    nextAction: "EXECUTE_DUE_FOLLOWUP",
    targetMetric: "followupsReady",
    stallCycles: 1,
    recovery: { mode: "REBALANCE_ATTENTION" },
    humanGateRequired: false,
  },
  channels: {
    gmail: { status: "stale", fresh: false, provider: "gmail_smtp", details: {} },
  },
};

{
  const reply = deterministicReply(snapshot, "¿Qué estás haciendo y cómo pensás mejorar?");
  assert.match(reply, /FOLLOWUP/);
  assert.match(reply, /due_followup/);
  assert.match(reply, /USD 0\.00/);
  assert.match(reply, /2 seguimiento\(s\)/);
  assert.match(reply, /REBALANCE_ATTENTION/);
  assert.match(reply, /No necesito aprobación humana/);
  assert.doesNotMatch(reply, /ganamos|cobramos|facturamos/i);
}

{
  const reply = deterministicReply(snapshot, "¿Qué pasa con Gmail?");
  assert.match(reply, /Gmail está stale/);
  assert.match(reply, /verificación no está fresca/);
  assert.match(reply, /no voy a mostrarlo como sano/);
}

{
  const gated = structuredClone(snapshot);
  gated.superautonomy.humanGateRequired = true;
  const reply = deterministicReply(gated, "¿Necesitás algo de mí?");
  assert.match(reply, /necesito aprobación humana/);
}

console.log("LUMEN_CONVERSATION_TESTS_OK");
