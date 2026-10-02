# LUMEN Paid Boost v1

Production deploy selects `paid-boost-entry.js`. The legacy `opportunity-entry.js`
remains in the base config for existing config-rewrite checks. Deploy through
`lumen-cloudflare-deploy.yml`; a plain deploy of the base entry is not the full
production application. Travel's compatibility entry wraps Paid Boost and exports
the same Workflow classes so its existing follow-on deploy preserves the upgrade.

Fast cron: `7,22,37,52 * * * *`. Deep cron: `12 * * * *`, launching a deduplicated
`lumen-deep-cycle` Workflow. Deep cognition, learning, self-criticism, multiplier,
Foundry v2 experiments and growth guidance are removed from the fast schedule.
Existing commercial sends remain governed by the existing hourly slot and policy.
This version does not raise external-message quotas or market-search limits.

The deep Workflow persists each task and records COMPLETED or DEGRADED results in
D1. Mutating engines have no automatic retries: an ambiguous RUNNING claim after
a crash requires review rather than incrementing learning counters twice. Other
tasks continue after an isolated error. Idempotent observation steps retry twice.
This is at-most-once invocation protection, not an exactly-once guarantee over
all writes inside an engine.

At most two existing proposals per hourly cycle get a durable observer. It tracks
quality review, existing governor-controlled send, response and exact verified
x402 settlement every two hours for up to seven days. It creates no messages,
charges, booking, approvals or paid delivery. Quality approval is not human
approval. Binding actions continue to use the existing human gate. Verified
payment produces PAYMENT_VERIFIED_DELIVERY_PENDING; delivery completion is not
invented. Automatic approval email/buttons are outside this change.

AI router: fast Llama for existing conversation; Gemma for deep cognition. Both
share an atomic A2A D1 counter, capped at 80 calls and 2,500 conservatively reserved
Neurons per UTC day. Existing 30-conversation/50-cognition daily guards stay in
place. Unknown models, tools, streaming, oversized input and unbounded output are
blocked. Failed/time-out calls keep reservations. Existing deterministic fallback
continues when the budget or provider fails. No extra AI spend is enabled.

Reservations use UTF-8 byte estimates, twice documented model rates and a chat
framing allowance. They are NOT provider billing measurements or an account-wide
hard cap: other account Workers share Cloudflare's 10,000 free daily Neurons.
Workers requests/CPU/D1/Workflow overages are separately billed. `cpu_ms=30000`
is a per-invocation limit, not a monthly billing cap. Review account usage; this
upgrade cannot promise a total bill of exactly USD 5.

Public: GET `/paid-boost/policy`. Admin token: GET `/paid-boost/status`, POST
`/paid-boost/deep/run` (deduplicated by UTC hour). Operational state is private.
Rollback: revert this PR and redeploy; terminate old Workflow instances in
Cloudflare if immediate cessation is needed. Removing bindings alone does not
terminate already running instances.

Validation: `node .lumen/a2a-worker/test-paid-boost.mjs`; existing discovery,
learning, superautonomy and Foundry tests; Wrangler dry-run of paid-boost entry.

API and pricing sources verified 2026-10-02:
- https://developers.cloudflare.com/workflows/build/workers-api/
- https://developers.cloudflare.com/workers/platform/limits/
- https://developers.cloudflare.com/workers-ai/platform/pricing/
- https://developers.cloudflare.com/workers-ai/models/gemma-4-26b-a4b-it/
- https://developers.cloudflare.com/workers-ai/models/llama-3.1-8b-instruct-fp8/
