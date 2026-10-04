import coreWorker from "./opportunity-entry.js";
import { handleSourceIntelligence, runSourceIntelligence } from "./source-intelligence.js";
import { handleProductCommerceRadar, runProductCommerceRadar } from "./product-commerce-radar.js";
import { handleCommerceMachine, runCommerceMachine } from "./commerce-machine.js";
import { handleCommerceOperations, runCommerceOperations } from "./commerce-operations.js";
import { handleTiendanubeBridge } from "./tiendanube-bridge.js";
import { handleTiendanubeSupplierIntake, runTiendanubeSupplierIntake } from "./tiendanube-supplier-intake.js";

const VERSION = "1.0-intermediary-runtime";

async function handleIntermediaryRoutes(request, env) {
  const handlers = [
    handleTiendanubeBridge,
    handleTiendanubeSupplierIntake,
    handleProductCommerceRadar,
    handleCommerceMachine,
    handleCommerceOperations,
    handleSourceIntelligence,
  ];
  for (const handler of handlers) {
    const response = await handler(request, env);
    if (response) return response;
  }
  return null;
}

export async function runIntermediaryCycle(env) {
  const startedAt = new Date().toISOString();
  const results = {};

  // Demand intelligence and supply intake are independent. A failure in one lane
  // must not stop the rest of the existing commerce chain.
  const steps = [
    ["sourceIntelligence", runSourceIntelligence],
    ["supplierIntake", runTiendanubeSupplierIntake],
    ["productRadar", runProductCommerceRadar],
    ["commerceMachine", runCommerceMachine],
    ["commerceOperations", runCommerceOperations],
  ];

  for (const [name, step] of steps) {
    try {
      results[name] = await step(env);
    } catch (error) {
      results[name] = { ok: false, error: String(error?.message || error).slice(0, 500) };
    }
  }

  return {
    ok: Object.values(results).some(result => result?.ok !== false),
    version: VERSION,
    startedAt,
    finishedAt: new Date().toISOString(),
    mode: "existing_modules_integrated",
    authority: {
      autonomousSpendUsd: 0,
      autonomousPurchase: false,
      autonomousContracts: false,
      publicListingRequiresExistingCommerceApproval: true,
    },
    results,
  };
}

export default {
  async fetch(request, env, ctx) {
    const integrated = await handleIntermediaryRoutes(request, env);
    if (integrated) return integrated;

    const url = new URL(request.url);
    if (url.pathname === "/intermediary-runtime/policy" && request.method === "GET") {
      return Response.json({
        ok: true,
        version: VERSION,
        lifecycle: [
          "discover_demand",
          "ingest_authorized_supplier_inventory",
          "score_unit_economics",
          "prepare_channel_offer",
          "govern_publication",
          "ingest_verified_order",
          "prepare_fulfillment",
          "attribute_verified_revenue",
        ],
        existingModulesOnly: true,
        autonomousSpendUsd: 0,
        autonomousPurchase: false,
        autonomousContracts: false,
        publicListingRequiresExistingCommerceApproval: true,
      });
    }

    if (url.pathname === "/intermediary-runtime/run" && request.method === "POST") {
      const expected = String(env?.OPPORTUNITY_ADMIN_TOKEN || "").trim();
      const supplied = String(request.headers.get("x-lumen-admin") || "").trim();
      if (!expected || supplied !== expected) return Response.json({ ok: false, error: "unauthorized" }, { status: 401 });
      return Response.json(await runIntermediaryCycle(env));
    }

    return coreWorker.fetch(request, env, ctx);
  },

  async scheduled(controller, env, ctx) {
    const scheduledAt = new Date(controller?.scheduledTime || Date.now());
    // The dedicated :12 hourly trigger is reserved for the existing intermediary
    // chain so the heavier external reads do not run on every 15-minute cycle.
    if (scheduledAt.getUTCMinutes() === 12) {
      ctx.waitUntil(runIntermediaryCycle(env));
    }
    return coreWorker.scheduled(controller, env, ctx);
  },
};
