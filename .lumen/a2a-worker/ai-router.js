export const AI_ROUTER_POLICY = Object.freeze({
  version: "1.0-paid-boost-ai-router", dailyReservedNeurons: 2500,
  dailyCalls: 80, maxOutputTokens: 600, maxInputBytes: 24000,
  autonomousSpendUsd: 0, paidOverageEnabled: false,
  accounting: "conservative_estimate_not_provider_billing",
  scope: "a2a_worker_only_other_account_workers_share_provider_quota",
});

// Rates from Cloudflare model docs, 2026-10-02. Reserve twice the byte-based
// input estimate plus bounded output. Failed/timed-out calls keep reservations.
const RATES = {
  "@cf/meta/llama-3.1-8b-instruct-fast": [0.152, 0.384],
  "@cf/google/gemma-4-26b-a4b-it": [0.10, 0.30],
};
export function estimateAiReservation(model, payload) {
  const rates = RATES[model];
  if (!rates) throw new Error("ai_model_not_allowlisted");
  if (payload.stream || payload.tools || payload.images || payload.audio || payload.n > 1)
    throw new Error("ai_unbudgeted_payload");
  const bytes = new TextEncoder().encode(JSON.stringify(payload)).length;
  const output = Number(payload.max_completion_tokens ?? payload.max_tokens);
  if (bytes > AI_ROUTER_POLICY.maxInputBytes || !Number.isInteger(output) || output < 1 || output > AI_ROUTER_POLICY.maxOutputTokens)
    throw new Error("ai_payload_budget_exceeded");
  // $0.011 per 1000 Neurons; 512 extra input tokens cover chat framing.
  return Math.ceil(2 * ((bytes + 512) * rates[0] + output * rates[1]) / 11);
}

export async function reserveAiBudget(env, neurons) {
  if (!Number.isInteger(neurons) || neurons < 1 || neurons > AI_ROUTER_POLICY.dailyReservedNeurons)
    throw new Error("ai_invalid_reservation");
  if (!env.DB) throw new Error("ai_budget_persistence_required");
  await env.DB.prepare("CREATE TABLE IF NOT EXISTS lumen_paid_boost_ai_usage (day TEXT PRIMARY KEY,calls INTEGER NOT NULL DEFAULT 0,reserved_neurons INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL)").run();
  const day = new Date().toISOString().slice(0, 10), now = new Date().toISOString();
  await env.DB.prepare("INSERT OR IGNORE INTO lumen_paid_boost_ai_usage(day,updated_at) VALUES(?,?)").bind(day, now).run();
  const result = await env.DB.prepare("UPDATE lumen_paid_boost_ai_usage SET calls=calls+1,reserved_neurons=reserved_neurons+?,updated_at=? WHERE day=? AND calls<? AND reserved_neurons+?<=?")
    .bind(neurons, now, day, AI_ROUTER_POLICY.dailyCalls, neurons, AI_ROUTER_POLICY.dailyReservedNeurons).run();
  if (Number(result?.meta?.changes) !== 1) throw new Error("ai_shared_budget_exhausted");
}

export function withBudgetedAi(env) {
  if (!env.AI) return env;
  return { ...env, AI: { async run(model, payload) {
    const neurons = estimateAiReservation(model, payload);
    await reserveAiBudget(env, neurons);
    return env.AI.run(model, payload);
  } } };
}
