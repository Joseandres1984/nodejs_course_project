/**
 * This is an internal trust signal, not a credit score or a proof of payment.
 * Older signed, authorized events lose influence with a 90-day half-life.
 */
export function computeReputation(events, now = Date.now()) {
  let positive = 0, negative = 0;
  const protocolTotals = Object.create(null);
  for (const event of events) {
    if (!Number.isFinite(event.weight) || event.weight <= 0 || event.weight > 1) continue;
    if (!Number.isSafeInteger(event.timestamp) || event.timestamp > now) continue;
    const weight = event.weight * Math.pow(0.5, (now - event.timestamp) / (90 * 86400000));
    const bucket = protocolTotals[event.protocol] ??= { positive: 0, negative: 0 };
    if (event.event_type === "positive") { positive += weight; bucket.positive += weight; }
    if (event.event_type === "negative") { negative += weight; bucket.negative += weight; }
  }
  const score = (p,n) => Math.round((50 + 50 * (p - n) / (p + n + 5)) * 100) / 100;
  return {
    globalScore: score(positive, negative),
    protocolScores: Object.fromEntries(Object.entries(protocolTotals).map(([k,v]) => [k, score(v.positive, v.negative)])),
    totalInteractions: events.length,
    successRate: positive + negative > 0 ? Math.round(positive / (positive + negative) * 10000) / 10000 : 0,
    decayFactor: 0.5,
    computedAt: now
  };
}
