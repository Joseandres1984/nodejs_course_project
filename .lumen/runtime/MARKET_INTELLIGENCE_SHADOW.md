# LUMEN Market Intelligence Scout — Shadow v1

## Status

Implemented on the integration branch only. Disabled by default.

Enable flag:

```text
LUMEN_MARKET_INTELLIGENCE_SHADOW_ENABLED=true
```

## Purpose

Extend LUMEN's existing public, robots-respecting store/catalog intelligence with structured Product/Offer evidence and deterministic price-asymmetry candidates.

## Existing components reused

- `store_catalog_crawler.py`
- `partner_network_ext.py`
- existing Scout/search budgets
- existing persistence/state cycle

The integration does not add a second crawler and does not consume additional search queries by itself.

## State ownership

The Scout writes only:

- `market_intelligence_observations`
- `market_intelligence_opportunity_candidates`
- `market_intelligence_scout`
- a compact `market_intelligence` report nested in `partner_network`

It does not mutate prospects, suppression, outbox, deals, approvals, orders or payments.

## Authority

All generated opportunity candidates are forced to:

```text
status = shadow_only
execution_allowed = false
outreach_allowed = false
financial_commitment_allowed = false
action_authority = none
```

Promotion into an actionable opportunity requires later passage through LUMEN's governed decision/execution path.

## Evidence extracted

When public JSON-LD exists, the Scout can retain:

- product name
- source URL/domain
- brand
- model
- SKU
- MPN
- GTIN variants
- color / size
- price
- currency
- availability
- observation timestamp

Missing facts are not invented.

## Opportunity rule in v1

A candidate is created only when:

- product identity can be matched deterministically;
- at least two distinct seller domains are observed;
- prices use the same currency;
- the observed price spread meets the configured threshold.

Cross-currency comparisons are not performed.

## Safety

The existing crawler policy remains unchanged: public GET only, same-domain crawl, robots.txt respected, no login, cart, checkout or form submission.

This v1 is research-only and is intentionally incapable of initiating outreach, purchasing, deal mutation or financial commitments.
