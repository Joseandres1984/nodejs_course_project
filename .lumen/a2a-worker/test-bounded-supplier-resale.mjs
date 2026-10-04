import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const launch = await readFile(new URL("./supplier-market-launch.js", import.meta.url), "utf8");
const entry = await readFile(new URL("./paid-boost-entry.js", import.meta.url), "utf8");

assert.match(launch, /1\.1-supplier-market-launch-autonomous/);
assert.match(launch, /MAX_AUTONOMOUS_LAUNCHES_PER_CYCLE = 1/);
assert.match(launch, /TIENDANUBE_CONNECTED_SUPPLIER/);
assert.match(launch, /connected_tiendanube_catalog/);
assert.match(launch, /supplierAssetsAuthorizedByIntegration/);
assert.match(launch, /liveStockRevalidation: true/);
assert.match(launch, /positiveNetMarginRequired: true/);
assert.match(launch, /priceMutation: false/);
assert.match(launch, /autonomousPurchase: false/);
assert.match(launch, /autonomousSpendUsd: 0/);
assert.match(launch, /autonomousContract: false/);
assert.match(launch, /visibility: "visible", free_shipping: false/);
assert.match(launch, /connected_supplier_authorized_inventory_existing_price/);
assert.match(launch, /explicit_human_approval_required/);
assert.match(launch, /MARKET_VALIDATED_HUMAN_APPROVED_LAUNCH|explicitHumanApprovalStillAvailable/);

const autoStart = launch.indexOf("export async function runAutonomousSupplierLaunch");
const statusStart = launch.indexOf("async function status", autoStart);
assert.ok(autoStart >= 0 && statusStart > autoStart);
const autoBody = launch.slice(autoStart, statusStart);
assert.doesNotMatch(autoBody, /variants\/\$\{encodeURIComponent\(candidate\.variantId\)\}/);
assert.doesNotMatch(autoBody, /price:\s*String\(candidate\.launchPrice\)/);

assert.match(entry, /runAutonomousSupplierLaunch/);
assert.match(entry, /getUTCMinutes\(\)/);
assert.match(entry, /minute === 7/);
assert.match(entry, /ctx\.waitUntil\(runAutonomousSupplierLaunch\(env\)\)/);

console.log("BOUNDED_SUPPLIER_RESALE_GUARDRAILS_OK");
