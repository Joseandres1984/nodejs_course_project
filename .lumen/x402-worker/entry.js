import app from "./worker-v2.js";

export default {
  async fetch(request, env, ctx) {
    try {
      return await app.fetch(request, env, ctx);
    } catch (error) {
      const url = new URL(request.url);
      const diagnostic = url.searchParams.get("technical_canary") === "1" && Boolean(request.headers.get("x-lumen-public-origin"));
      const payload = diagnostic
        ? { ok:false, error:"x402_internal_error", detail:String(error?.message || error || "unknown").slice(0,500), name:String(error?.name || "Error").slice(0,80) }
        : { ok:false, error:"x402_internal_error" };
      return Response.json(payload, {
        status:500,
        headers:{
          "cache-control":"no-store",
          "x-content-type-options":"nosniff",
          "access-control-allow-origin":"*"
        }
      });
    }
  }
};
