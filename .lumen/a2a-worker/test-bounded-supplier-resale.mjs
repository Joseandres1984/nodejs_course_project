import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { computeSupplierLaunchEconomics, rankSupplierLaunchCandidate } from "./supplier-market-launch.js";

const launch = await readFile(new URL("./supplier-market-launch.js", import.meta.url), "utf8");
const entry = await readFile(new URL("./paid-boost-entry.js", import.meta.url), "utf8");

assert.match(launch, /1\.1-supplier-market-launch-evolving/);
assert.match(launch, /commerce_machine_market_snapshot/);
assert.match(launch, /MAX_AUTOMATIC_BENCHMARK_AGE_HOURS = 48/);
assert.match(launch, /MIN_AUTOMATIC_MARKET_SAMPLES = 2/);
assert.match(launch, /automaticBenchmarkRequiredCurrency: "ARS"/);
assert.match(launch, /TIENDANUBE_CONNECTED_SUPPLIER/);
assert.match(launch, /connected_tiendanube_catalog/);
assert.match(launch, /supplierAssetsAuthorizedByIntegration/);
assert.match(launch, /liveStockRevalidation: true/);
assert.match(launch, /positiveNetMarginRequired: true/);
assert.match(launch, /autonomousPublishing: false/);
assert.match(launch, /autonomousPurchasing: false/);
assert.match(launch, /autonomousSpendUsd: 0/);
assert.match(launch, /autonomousContracts: false/);
assert.match(launch, /bindingActionsHumanGated: true/);
assert.match(launch, /HUMAN_APPROVAL_REQUIRED/);
assert.match(launch, /EXPLICIT_HUMAN_APPROVAL_TO_PUBLISH/);
assert.match(launch, /lumen_supplier_launch_queue/);
assert.match(launch, /projected_net_margin_with_market_confidence/);

const evolutionStart = launch.indexOf("export async function runSupplierMarketLaunchEvolution");
const executeStart = launch.indexOf("async function executeLaunch", evolutionStart);
assert.ok(evolutionStart >= 0 && executeStart > evolutionStart);
const evolutionBody = launch.slice(evolutionStart, executeStart);
assert.doesNotMatch(evolutionBody, /method:\s*"PUT"/);
assert.doesNotMatch(evolutionBody, /visibility:\s*"visible"/);
assert.doesNotMatch(evolutionBody, /externalWriteExecuted:\s*true/);

const executeBody = launch.slice(executeStart);
assert.match(executeBody, /explicit_human_approval_required/);
assert.match(executeBody, /method:\s*"PUT"/);

const economics = computeSupplierLaunchEconomics(50000, 100000, {
  paymentFeePct: 8,
  riskReservePct: 3,
  fixedShippingArs: 10000,
  minMarginPct: 18
});
assert.equal(economics.projectedProfit, 29000);
assert.equal(economics.projectedMarginPct, 29);
assert.ok(rankSupplierLaunchCandidate({ ok: true, launchable: true, economics, benchmark: { sampleCount: 5 } }) > 0);
assert.equal(rankSupplierLaunchCandidate({ ok: true, launchable: false, economics, benchmark: { sampleCount: 5 } }), 0);

assert.match(entry, /runSupplierMarketLaunchEvolution/);
assert.match(entry, /getUTCMinutes\(\)/);
assert.match(entry, /minute === 7/);
assert.match(entry, /ctx\.waitUntil\(runSupplierMarketLaunchEvolution\(env\)\)/);
assert.doesNotMatch(entry, /runAutonomousSupplierLaunch/);

console.log("SUPPLIER_INTERMEDIARY_EVOLUTION_GUARDRAILS_OK");