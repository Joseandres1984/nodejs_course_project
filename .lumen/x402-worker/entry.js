import app, { PRODUCTS } from "./worker-v2.js";
import { handleCommissionCheckout } from "./commission-checkout.js";
import { handleApprovalManagement, preflightX402Settlement, finalizeX402Settlement } from "./settlement-approval.js";
import { briefFromUrl } from "./buyer-brief.js";

export default {
  async scheduled(_event, env, ctx) {
    // Read-only discovery of candidates. Never initiate transfers or owner approvals.
    const job = async () => {
      if (!env.DB || !env.LUMEN_RECONCILE_TOKEN || env.LUMEN_RECONCILE_TOKEN.length < 32) {
        console.error("X402_RECONCILE_CRON_NOT_CONFIGURED");
        return;
      }
      const pending = await env.DB.prepare(
        "SELECT id,request_metadata FROM lumen_x402_receipts WHERE status='awaiting_independent_verification' AND json_valid(request_metadata) AND json_extract(request_metadata,'$.settlement.facilitatorReportedSuccess')=1 AND length(json_extract(request_metadata,'$.settlement.transaction'))=66 ORDER BY created_at ASC LIMIT 10"
      ).all();
      let verified = 0, deferred = 0, errors = 0;
      for (const row of pending.results || []) {
        let meta;
        try { meta = JSON.parse(row.request_metadata || "{}"); } catch { deferred++; continue; }
        if (meta?.settlement?.facilitatorReportedSuccess !== true ||
            !/^0x[0-9a-fA-F]{64}$/.test(String(meta?.settlement?.transaction || ""))) {
          deferred++;
          continue;
        }
        try {
          // Reuse the same authenticated, fail-closed reconciliation path as manual calls.
          const request = new Request("https://lumen.internal/internal/reconcile-usdc", {
            method:"POST",
            headers:{"content-type":"application/json","x-lumen-reconcile-token":env.LUMEN_RECONCILE_TOKEN},
            body:JSON.stringify({receiptId:row.id})
          });
          const response = await app.fetch(request, env);
          if (response.status === 200) verified++;
          else if (response.status === 409) deferred++;
          else errors++;
        } catch { errors++; }
      }
      // Scheduled observability runs in the deployed Worker, independently of GitHub's default branch.
      try {
        const summary = await env.DB.prepare(
          "SELECT status, COUNT(*) AS receipts FROM lumen_x402_receipts GROUP BY status"
        ).all();
        const counts = Object.fromEntries((summary.results || []).map(r => [String(r.status),Number(r.receipts)]));
        console.log(JSON.stringify({event:"X402_D1_STATUS_AUDIT",counts,nominalAmountsAreNotRevenue:true}));
      } catch {
        errors++;
        console.error("X402_D1_STATUS_AUDIT_FAILED");
      }
      console.log(JSON.stringify({event:"X402_RECONCILE_CRON",examined:(pending.results||[]).length,verified,deferred,errors}));
      if (errors) console.error("X402_RECONCILE_CRON_ERRORS",errors);
    };
    ctx.waitUntil(job());
  },
  async fetch(request, env, ctx) {
    let claimId = null;
    let response = null;
    try {
      // A malformed or malicious machine brief is blocked BEFORE any payment
      // signature can reach the facilitator, even if the owner approved.
      const requestUrl = new URL(request.url);
      if (request.method === "GET" && requestUrl.pathname.startsWith("/buy/")) {
        const brief = briefFromUrl(requestUrl);
        if (!brief.ok) return Response.json({
          ok:false, error:brief.error, paymentAttempted:false,
          noCharge:true, ownerApprovalStillRequired:true
        }, {status:400,headers:{"cache-control":"no-store"}});
      }
      // Owner decisions are explicit, separate and never automated.
      const management = await handleApprovalManagement(request, env);
      if (management) return management;

      // This MUST run before either paymentMiddleware implementation. Neither
      // the normal product checkout nor the referral commission path may settle
      // a signed payment without a one-time, scope-bound human approval.
      const preflight = await preflightX402Settlement(request, env, PRODUCTS);
      if (preflight.response) return preflight.response;
      claimId = preflight.claimedId;

      const commissionResponse = await handleCommissionCheckout(request, env);
      response = commissionResponse || await app.fetch(request, env, ctx);
      return response;
    } catch (error) {
      const url = new URL(request.url);
      const diagnostic = url.searchParams.get("technical_canary") === "1" && Boolean(request.headers.get("x-lumen-public-origin"));
      const payload = diagnostic
        ? { ok:false, error:"x402_internal_error", detail:String(error?.message || error || "unknown").slice(0,500), name:String(error?.name || "Error").slice(0,80) }
        : { ok:false, error:"x402_internal_error" };
      response = Response.json(payload, {
        status:500,
        headers:{
          "cache-control":"no-store",
          "x-content-type-options":"nosniff",
          "access-control-allow-origin":"*"
        }
      });
      return response;
    } finally {
      // An uncertain outcome stays locked for manual investigation; never
      // reopen an approval automatically after a settlement attempt.
      if (claimId) await finalizeX402Settlement(env, claimId, response);
    }
  }
};
