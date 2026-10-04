import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const runtime = await readFile(new URL("./runtime-entry.js", import.meta.url), "utf8");
const wrangler = await readFile(new URL("./wrangler.toml", import.meta.url), "utf8");

assert.match(wrangler, /main\s*=\s*"runtime-entry\.js"/);

for (const file of [
  "source-intelligence.js",
  "product-commerce-radar.js",
  "commerce-machine.js",
  "commerce-operations.js",
  "tiendanube-bridge.js",
  "tiendanube-supplier-intake.js",
]) {
  assert.ok(runtime.includes(`./${file}`), `runtime must wire ${file}`);
}

for (const step of [
  "runSourceIntelligence",
  "runTiendanubeSupplierIntake",
  "runProductCommerceRadar",
  "runCommerceMachine",
  "runCommerceOperations",
]) {
  assert.ok(runtime.includes(step), `hourly intermediary cycle must call ${step}`);
}

for (const handler of [
  "handleSourceIntelligence",
  "handleProductCommerceRadar",
  "handleCommerceMachine",
  "handleCommerceOperations",
  "handleTiendanubeBridge",
  "handleTiendanubeSupplierIntake",
]) {
  assert.ok(runtime.includes(handler), `production fetch must expose ${handler}`);
}

assert.match(runtime, /getUTCMinutes\(\)\s*===\s*12/);
assert.match(runtime, /autonomousSpendUsd:\s*0/);
assert.match(runtime, /autonomousPurchase:\s*false/);
assert.match(runtime, /autonomousContracts:\s*false/);
assert.match(runtime, /publicListingRequiresExistingCommerceApproval:\s*true/);

const supplierIntake = await readFile(new URL("./tiendanube-supplier-intake.js", import.meta.url), "utf8");
assert.match(supplierIntake, /supplierAssetsAuthorizedByIntegration:\s*true/);
assert.match(supplierIntake, /approvalRequiredBeforeLive:\s*true/);

const commerce = await readFile(new URL("./commerce-machine.js", import.meta.url), "utf8");
assert.match(commerce, /projectedProfit/);
assert.match(commerce, /projectedMarginPct/);
assert.match(commerce, /human_approval_required/);

console.log("INTERMEDIARY_RUNTIME_WIRING ok");
