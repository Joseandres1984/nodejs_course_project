# LUMEN recovery baseline — 2026-10-20

Status: AUDIT ONLY. Not a deployment or a claim of revenue.

## Source of truth and controls
- Repository: Joseandres1984/nodejs_course_project; production-oriented base: lumen-zero. Default repository branch is main; do not confuse them.
- Record evidence per service: source commit, Cloudflare deployment ID, health check, last successful commercial event, provider receipt.
- No Railway. No paid Connects, deposits, subscriptions or paid verification.
- No outbound messages or proposals without authorization. Anti-spam and human approval are mandatory.
- Every x402 settlement needs individual owner approval and provider-final verification; HTTP 402 is not revenue.
- No production merge/deploy until tests, rollback and live evidence are available.

## Confirmed GitHub observations
- PR #326 (fix/lumen-401-503-x402-gates-20261019) is OPEN/DRAFT. Its own description says it contains acceptance criteria only, not functional fixes. DO NOT MERGE as a repair.
- PR #325 (lumen-agent-identity-secure-v1-20261016) is OPEN/DRAFT, explicitly not deployed. Needs D1 database, secrets, rate limiter, staging and security review.
- PR #324 (Instagram reel delivery fix) is merged, but live publication status remains UNVERIFIED.
- Travel branches exist: lumen-travel-acquisition-full-trip, lumen-travel-monetization-activation-20261006, lumen-travelpayouts-project-config, etc. Their presence does not establish live conversion.
- No production settlement or affiliate commission verified by this audit.

## Inventory / verification backlog
| Stream | Existing evidence | Live status | Next safe verification |
|---|---|---|---|
| B2B | Sales pipeline and sourcing branches | UNKNOWN | Check buyer-intent records, deduplication, contact approval and revenue |
| A2A | Identity sidecar PR #325 | NOT DEPLOYED per PR | CI, D1 isolation, key/security review, staging |
| x402 | HTTP repair PR #326 | FIX NOT IMPLEMENTED per PR | Locate deployed commit; reproduce 401/503; implement and test receipt verification |
| Travel | Multiple affiliate, acquisition and tracking branches | UNKNOWN | Verify account approvals, tagged links, clicks, bookings and actual commission |
| Instagram | Merged PR #324 | UNKNOWN | Provider publication ID and visible post confirmation |

## Exit criteria
1. Inventory all active Workers, deployments, domains, secrets names (never secret values), and revenue endpoints.
2. Each business stream has one owner, operational status, measurable funnel, and evidence URLs.
3. Staging CI and security gates pass; deployment matches inspected SHA and rollback is available.
4. Count only real, independently confirmed financial receipts as revenue.
5. Log decisions and incidents so another AI can resume without relying on chat memory.

## Second-pass source inspection (2026-10-20)
- Found existing handoff `.lumen/LUMEN_HANDOFF.md`, last updated 2026-09-12. It documents Railway deployment and Postgres as *historical state*. User's later explicit instruction is **NO RAILWAY**; never treat that old handoff as current deployment authority.
- Existing code directories in `lumen-zero`: `.lumen/x402-worker` with `settlement-approval.js` and associated tests; `.lumen/public-worker/travel-storefront.js`; `.lumen/sales/public-demand-pipeline-2026-10-08.json`. These establish implementation artifacts, not verified live integrations or payments.
- PR #326 patch contains only `.lumen/production-repair-acceptance-20261019.md` (29 lines). No executable 401/503 fix.
- PR #325 includes 10 files for an isolated identity Worker and tests, but `agent-identity/wrangler.toml` still has `REPLACE_WITH_REAL_` D1 ID and its own PR states no production deployment.
- Next investigation: read x402 worker's actual receipt verifier and test scripts; trace travel storefront tracking to approved affiliate account and provider reports; compare deployed SHA before modifying production.
