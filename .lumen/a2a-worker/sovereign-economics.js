import { clamp, number, V4_POLICY } from "./sovereign-store.js";

const FIXED_CATALOG_VALUE_USD = Object.freeze({
  "MP-SUPPLIER-SNAPSHOT": 1,
  "MP-QUOTE-SANITY": 7,
  "MP-TENDER-SCAN": 9,
  "MP-SOURCING-5": 15,
  "MP-BUYER-SIGNALS": 19,
  "MP-EXPORT-PULSE": 25
});

export function candidateValueUsd(row = {}) {
  const explicit = clamp(row.estimated_value_usd, 0, 10000);
  if (explicit > 0) return { valueUsd: explicit, valueSource: "candidate_estimate" };
  const catalog = clamp(FIXED_CATALOG_VALUE_USD[row.offer_id], 0, 10000);
  if (catalog > 0) return { valueUsd: catalog, valueSource: "fixed_catalog_price" };
  return { valueUsd: 0, valueSource: "unknown_zero" };
}

// Explicit estimates, never revenue evidence. Probability comes from observed
// settlement/send cohorts with a conservative prior, discounted for weak fit.
export function evaluateEconomics(row, cohort = {}) {
  const evidence = clamp(row.evidence_score, 0, 100) / 100;
  const sent = Math.max(0, number(cohort.sent)), wins = clamp(cohort.verified_settlements, 0, sent);
  const empirical = (wins + 1) / (sent + 20);
  const probability = Math.min(0.8, empirical * (0.5 + evidence / 2));
  const { valueUsd: value, valueSource } = candidateValueUsd(row);
  const costMinutes = { COLLECTION: 1, CLOSE: 2, INBOUND: 2, FOLLOW_UP: 1, NEW_BUSINESS: 3, EXPERIMENT: 4 }[row.lane] || 3;
  const cashHours = { COLLECTION: 1, CLOSE: 6, INBOUND: 12, FOLLOW_UP: 24, NEW_BUSINESS: 72, EXPERIMENT: 168 }[row.lane] || 72;
  const risk = 1 - evidence;
  const expectedRevenueUsd = value * probability;
  const utility = expectedRevenueUsd * (0.5 + evidence / 2) / costMinutes / (1 + cashHours / 24) / (1 + risk);
  return { candidateId: row.id, sourceType: row.source_type, sourceId: row.source_id,
    lane: row.lane, offerId: row.offer_id || null, probability, probabilityModel: "beta_prior_1_19_times_evidence",
    estimatedValueUsd: value, valueSource, expectedRevenueUsd, projectedComputeMinutes: costMinutes, projectedCashHours: cashHours,
    risk, evidence, utility, estimatesOnly: true, verifiedRevenueUsd: 0 };
}

export function judgeWorld(world, economics) {
  const blockers = [];
  if (world.priceChange || world.spendUsd !== 0 || world.externalExecution) blockers.push("authority_exceeded");
  if (world.minutes < 1 || world.minutes > V4_POLICY.planningMinutes) blockers.push("compute_budget_exceeded");
  if (world.requiresEvidence && economics.evidence < 0.65) blockers.push("insufficient_evidence");
  // This deterministic judge deliberately does not trust the scenario's own score.
  const utility = blockers.length ? 0 : economics.expectedRevenueUsd * world.probabilityMultiplier /
    world.minutes / (1 + economics.projectedCashHours / 24) / (1 + economics.risk + world.uncertainty);
  return { ...world, admissible: !blockers.length, blockers, judgedUtility: utility,
    method: "deterministic_scenario_estimate_not_predictive_simulation" };
}
export function simulateWorlds(economics) {
  const worlds = [
    { id: "research", action: "REFRESH_RESEARCH_DRAFT", minutes: 3, probabilityMultiplier: 1, uncertainty: 0.2, requiresEvidence: false },
    { id: "proposal", action: "PREPARE_SCOPE_PACKET", minutes: 2, probabilityMultiplier: 1.05, uncertainty: 0.3, requiresEvidence: true },
    { id: "delivery", action: "OBSERVE_PAID_FULFILLMENT", minutes: 1, probabilityMultiplier: 1, uncertainty: 0.1, requiresEvidence: true },
    { id: "repackage", action: "PREPARE_PRODUCT_DRAFT", minutes: 4, probabilityMultiplier: 1.1, uncertainty: 0.7, requiresEvidence: true }
  ].map(w => judgeWorld({ ...w, priceChange: false, spendUsd: 0, externalExecution: false }, economics));
  // A delivery observer is meaningful only after a collection signal.
  const delivery = worlds.find(w => w.id === "delivery");
  if (economics.lane !== "COLLECTION") { delivery.admissible = false; delivery.blockers.push("no_collection_signal"); delivery.judgedUtility = 0; }
  const ranked = worlds.filter(w => w.admissible).sort((a,b) => b.judgedUtility - a.judgedUtility || a.id.localeCompare(b.id));
  return { worlds, winner: ranked[0] || null };
}

export function allocateAttention(candidates, minutes = V4_POLICY.planningMinutes) {
  let remaining = minutes; const allocations = [];
  const ranked = [...candidates].sort((a,b) => (b.lane === "COLLECTION") - (a.lane === "COLLECTION") || b.utility - a.utility || a.candidateId.localeCompare(b.candidateId));
  for (const economic of ranked) {
    const simulation = simulateWorlds(economic), winner = simulation.winner;
    if (!winner || winner.minutes > remaining) continue;
    allocations.push({ ...economic, minutes: winner.minutes, nextAction: winner.action, simulation });
    remaining -= winner.minutes;
    if (remaining === 0) break;
  }
  return { planningMinutes: minutes, usedMinutes: minutes - remaining, unusedMinutes: remaining, allocations,
    budgetIsPlanningEstimate: true, actualCpuBudgetEnforcedByWorker: true };
}

export function benchmark(baseline, current) {
  const ratios = {}, reasons = [];
  for (const key of ["opportunitiesEvaluated", "usefulExperiments", "humanDecisions", "proposalLatencyMs", "revenuePerReservedNeuron"]) {
    if (!Number.isFinite(baseline?.[key]) || baseline[key] <= 0 || !Number.isFinite(current?.[key])) {
      ratios[key] = null; reasons.push(`${key}:missing_positive_comparable_baseline`);
    } else ratios[key] = current[key] / baseline[key];
  }
  return { status: reasons.length ? "INSUFFICIENT_COMPARABLE_DATA" : "MEASURED",
    ratios, reasons, revenueImprovement60PercentVerified: ratios.revenuePerReservedNeuron === null ? null : ratios.revenuePerReservedNeuron >= 1.6,
    overall60PercentImprovementVerified: false };
}