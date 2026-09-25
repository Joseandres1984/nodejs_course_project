import assert from "node:assert/strict";
import { handleTiendanubeSupplierIntake, runTiendanubeSupplierIntake } from "./tiendanube-supplier-intake.js";

const policyResponse = await handleTiendanubeSupplierIntake(new Request("https://example.com/supplier-intake/policy"), {});
assert.equal(policyResponse.status, 200);
const policy = await policyResponse.json();
assert.equal(policy.version, "1.0-tiendanube-supplier-intake");
assert.equal(policy.readsVariantCost, true);
assert.equal(policy.readsStock, true);
assert.equal(policy.importedProductsAutoHiddenInStaging, true);
assert.equal(policy.autonomousPublishing, false);
assert.equal(policy.autonomousPurchasing, false);
assert.equal(policy.supplierOrdering, false);
assert.equal(policy.autonomousSpendUsd, 0);
assert.equal(policy.approvalRequiredBeforeLive, true);
assert.equal(policy.maxComboQty, 3);

const skipped = await runTiendanubeSupplierIntake({});
assert.equal(skipped.ok, false);
assert.equal(skipped.reason, "missing_db");

const unauthorized = await handleTiendanubeSupplierIntake(new Request("https://example.com/supplier-intake/status"), { OPPORTUNITY_ADMIN_TOKEN: "secret" });
assert.equal(unauthorized.status, 401);

console.log("TIENDANUBE_SUPPLIER_INTAKE_TESTS_OK");