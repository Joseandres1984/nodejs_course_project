# LUMEN v4 — Sovereign Revenue Engine

This release connects ten **bounded internal capabilities** to the existing
durable hourly Paid Boost Workflow. It is a working foundation, not a claim of
complete autonomous selling, general self-modifying code or a measured 60%
improvement. The fast commercial cycle and its existing authority remain in
place. No new connector, external message, purchase or financial action is
executed by v4.

## What runs

`paid-boost-entry.js` exposes the protected control plane. The production deploy
workflow already selects that entrypoint. `LumenDeepWorkflow` adds
`sovereign-revenue-v4` after commercial truth, existing learning/growth modules
and before proposal observers. Each v4 run atomically claims its ID, persists
artifacts, and records COMPLETED, DEGRADED or FAILED. Completed and degraded
runs return their stored result on replay. Ambiguous or failed runs never
blindly replay mutations.

| Capability | Implemented behavior | Boundary / remaining work |
|---|---|---|
| Revenue Brain v3 | Conservative settlement/send cohort estimates; value, effort, time and evidence ranking; ten-minute attention plan | Estimates are not profit or realized revenue. Actual billing cost is unavailable. |
| Deal Operator | Existing-evidence research drafts, exact scope reviews, negotiation preparation, receipt → fulfillment → delivery observation | No outbound negotiation, paid research dispatch, release or post-sale message. Existing Python fulfillment and delivery gates retain authority. |
| Protocol Mesh | A2A 0.3 `message/send`, MCP `tools/call` envelopes, existing x402 checkout references | Preparation only. MCP requires an existing initialized session. AP2 is blocked; signed mandate verification is not implemented. |
| Product Factory | Demand-backed input/output specs and packaging drafts over six existing capabilities | No new executable capability, catalog publication, price change or promised SLA; certification and price parity required. |
| Shadow Worlds | Four deterministic options with a separate constraint/utility judge | These are scenario estimates, not predictive simulations or additional AI agents. |
| Economic Memory Graph | Exact host/opportunity/offer/proposal/response/receipt relations; offer cohort lookup | No fuzzy identity merging. Hosts are demand proxies, not independent buyers. Missing people/supplier identities are not invented. |
| Autocoder Lab | Evidence-backed playbook patch, pinned base hash, path allowlist, adversarial tests, isolated draft PR workflow | Launch via workflow dispatch. Only reductions of internal workload / stricter evidence settings. No arbitrary code generation, merge or deploy. |
| Self-Healing | Idempotent local schema repair; persisted Workflow failure/ambiguity incidents | No restart/deploy, external retry or blind replay. Operational incidents require review. |
| Market Radar | Strong/medium actionable signals grouped by offer and distinct HTTPS hosts; exact verified receipts | Uses existing discovery sources. Shared registry hosts and test records excluded; no new crawling channel. |
| CEO Mode | Persisted revenue goal, bottleneck diagnosis, attention plan, internal artifact execution | Revenue goals do not grant spending or sending authority. Default USD 1,000 monthly is a target, not a forecast. |

Fresh allocation scores can add **0–8 priority points** to the existing Portfolio
Governor for two hours. They cannot override its collection precedence or its
maximum one external message per cycle. This is how economic attention affects
the existing execution path without creating a second sender.

## Approval meaning

Packets are **internal proposal reviews**, not payment mandates, contract
approval or send authorization. A decision neither modifies the legacy
proposal status nor instructs the legacy sender. Rejection is recorded in the
v4 deal view; it does not cancel independently authorized legacy activity.

Each packet binds proposal/opportunity IDs, endpoint, offer, amount, exact copy,
quality state and source status to SHA-256. Changed scopes supersede previous
pending/approved packets. Approval requires a passing quality gate, matching
current scope, a pending packet and an unexpired 24-hour TTL. Concurrent
decisions use an atomic conditional update. Expired packets require a new scope
review; they are not silently reauthorized. Tokens never appear in public policy
or generated links. No new approval email or UI is included.

## Economic truth

Deal progression requires a persisted, provider-verified receipt linked by the
existing bridge to the exact proposal, matching product and amount, successful
settlement, a 32-byte transaction hash, Base mainnet, USD receipt currency, and
the existing seller recipient. Both `settled_verified` and `redeemed_queued`
are recognized: redeeming a receipt must not erase payment evidence or count a
new sale. Delivery observation also matches exact receipt and order IDs and
requires a provider message ID before reporting post-sale status.

Daily x402 revenue is a separate aggregate over receipt truth, not the bounded
ranking window or the sum of projected opportunity values. It is gross receipt
revenue, not verified net profit, refund-adjusted income or independently
confirmed buyer adoption. AI reservation estimates are labeled as estimates,
not actual provider compute. Missing capabilities are exposed; unexpected SQL
and transport failures propagate.

The five improvement targets are preserved, but the measurement endpoint
reports `INSUFFICIENT_COMPARABLE_DATA`. Yesterday may have no v4 baseline;
partial-day samples are not comparable to full-day samples. Useful experiment
and opportunity throughput comparisons still need matched observation windows.
No percentage is inferred from module count, source count or successful tests.

## Bounds

* Read windows: 60 opportunities, 60 proposals, 60 candidates, 200 receipts.
* Graph refresh: 30 opportunities, 20 proposals, 50 receipts; historical graph
  remains available. These bounds keep this Workflow step below the paid Worker
  D1 query ceiling rather than issuing a query for every historical entity.
* Up to three internal deals and two product drafts per cycle, four scenarios
  per allocation; current playbooks may reduce work further.
* Zero additional AI calls, network fetches, messages or spend from v4.
* Existing AI router, Worker CPU cap and Workflow checkpoints remain in force.
* Body size is capped at 16 KiB while streaming, including chunked bodies.

## Control plane

Except for the policy, all routes require `x-lumen-admin` matching the configured
`OPPORTUNITY_ADMIN_TOKEN` and return `cache-control: no-store`.

| Method / path | Result |
|---|---|
| GET `/sovereign/policy` | Public capability boundaries and targets |
| GET `/sovereign/status` | Latest persisted run and 30 recent review packets |
| GET `/sovereign/memory?offerId=MP-SUPPLIER-SNAPSHOT` | Up to 20 exact proposal peers for an offer |
| GET `/sovereign/autocoder/candidate` | Latest evidenced isolated patch candidate |
| POST `/sovereign/run` | Start the existing deduplicated hourly deep Workflow; not a second executor |
| POST `/sovereign/verify` | Deduplicated v4-only Workflow for deployment verification; never runs legacy senders or growth actions |
| POST `/sovereign/goal` | `{"targetMonthlyRevenueUsd":1000,"objective":"..."}`; rejects authority fields |
| POST `/sovereign/protocol/prepare` | `{ "protocol":"a2a", "task":{ "id":"...", "text":"...", "endpoint":"https://..." } }` |
| POST `/sovereign/approvals/{id}/decision` | `{"decision":"APPROVE","scopeHash":"..."}` or `REJECT`; review only |

## Rollout and verification

Run `node test-sovereign-revenue.mjs` and all existing `test-*.mjs` from
`.lumen/a2a-worker`; some legacy tests require that working directory. Also
bundle the production entry with:

```sh
npx --yes wrangler@latest deploy paid-boost-entry.js --dry-run --config wrangler.toml
```

The v4 suite uses a real SQLite-backed D1 facade and disables provider networking.
The deployment workflow records the pre-deploy public revenue baseline, verifies
the v4 public policy and protected status, and observes an isolated v4 cycle.
It logs aggregate artifact counts and elapsed wall time without proposal copy,
buyer identities or admin credentials. Wall time is not CPU usage.
It covers complete cycles, persisted replay, exact payment evidence, redeemed
receipts, scope changes, concurrent decisions, forged authority, host dedup,
governor integration, missing capabilities, honest benchmarks and hostile lab
patches. It does not prove live Cloudflare D1/Workflow behavior or a real sale.

Merge/deploy is a separate production action. The existing push deployment
workflow runs v4 tests before deployment. After deployment, verify public
policy, protected status and a completed/degraded deep instance with the v4
step. Inspect missing capabilities and actual artifacts; do not use a successful
bundle or launch acknowledgment as proof of successful selling.

Rollback: restore the previous Paid Boost entry/Workflow and governor code via a
reviewed revert. New `lumen_v4_*` tables are additive and do not change legacy
schemas. They can remain as historical data during rollback.

Protocol references: https://a2a-protocol.org/v0.3.0/specification/ ;
https://modelcontextprotocol.io/specification/2025-11-25/server/tools ;
https://ap2-protocol.org/ap2/specification/ . No protocol conformance is claimed
beyond the documented draft envelopes.
