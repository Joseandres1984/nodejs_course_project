# LUMEN production repair acceptance gates

This branch is isolated from production. Do not merge or deploy until the following are evidenced.

## HTTP 401 / Market Hunter
- Identify which request returns 401 (registry, internal Worker, or administrative route).
- Never print or commit tokens. Do not broaden permissions.
- Classify 401 as non-retryable until credentials are corrected through approved secret management.
- Verify read-only demand search and quality filters with live authorized credentials.

## HTTP 503 / Street Mode
- On 503, honor Retry-After when present; apply bounded exponential backoff and jitter.
- Do not blindly retry non-idempotent sends. Require stable idempotency keys and provider confirmation before retry.
- Keep 24h origin cooldown, daily cap, approved proposal, quality gate, and untrusted-input firewall.
- Record provider errors separately from safe idle and successful delivery.

## x402 settlement truth
- Count only provider-confirmed final settlement events, never HTTP 402, requests, clicks, responses, or redeemed_queued.
- Require provider name, provider transaction ID, final status, amount, currency, recipient, attribution, and independent provider evidence.
- Deduplicate by (provider, network, transaction ID); reconcile USD credited only after finality and ownership validation.
- Fail closed on missing, conflicting, reversed, pending, or synthetic records.
- Any payment or binding action requires Jose's explicit approval.

## Release
1. Locate production Worker deployment commit and current workflows.
2. Implement fixes with unit and integration regression tests.
3. Run security and quality gates; inspect failed cases.
4. Deploy only approved existing Cloudflare infrastructure (never Railway), verify live health and settlement evidence.
5. Report unique verified settlements and actually credited USD; never claim CI green equals revenue.
