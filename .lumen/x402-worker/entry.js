import app, { PRODUCTS } from "./worker-v2.js";
import { handleCommissionCheckout } from "./commission-checkout.js";
import { handleApprovalManagement, preflightX402Settlement, finalizeX402Settlement } from "./settlement-approval.js";
import { briefFromUrl } from "./buyer-brief.js";

export default {
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
