# LUMEN — internal offer hypotheses, 2026-10-31 19:53 UTC

**INTERNAL ONLY · NOT FOR SENDING · NOT A CUSTOMER PROPOSAL · NO LISTING · NO PRICE CHANGE · NO DEPLOYMENT.** No customer is assigned to any hypothesis. No buyer identity, budget, payment capacity, or willingness to pay is inferred from aggregate market activity.

## Priority 1 — MP-QUOTE-SANITY: B2B quotation / CSV preflight
**Evidence:** the delayed free nohumans feed reports "csv preflight" on four separate days, five IPs and 191 searches; "csv validation before import" (one day, two IPs, 18 searches); and "supplier price quote verification" (one day, two IPs, two searches). These are aggregate product-demand signals, not a buyer or order. The two OpenTask CSV-to-JSON tasks inspected are near-duplicates posted on 2026-05-14, with no escrow evidence and no recent buyer activity; they are not leads.

**Existing offer fit:** strongest match to the current LUMEN catalog. The previous verified catalog snapshot lists MP-QUOTE-SANITY at USD 7/request and SRV-QUOTECHECK from USD 59. Those are existing list prices only; current compute, human-review, storage, support and acquisition costs are not established, so positive margin is unproven.

**Bounded deliverable hypothesis**
- Validate CSV encoding, headers, required columns, row structure and schema consistency.
- Normalize units, currencies and quote dates without overwriting source values.
- Flag duplicate lines, arithmetic/totals mismatches, inconsistent quantities, expired validity and missing specifications.
- Return JSON plus a human-readable exception report with row/field provenance.
- Separate deterministic checks from commercial judgement; never auto-select a supplier or authorize a purchase.

**Qualification gates:** a named current buyer; an explicit request and authorized sample/schema; task-level budget or escrow evidence; legal free contact path; delivery scope and data-retention rules; measured variable costs; positive contribution margin. Until all pass, no queue import, customer-specific proposal, or price change.

## Priority 2 — x402 Preflight: unpaid challenge diagnostics
**Evidence:** the feed shows repeated searches for checking an x402 payment path before paying, endpoint reliability/uptime and payment failure debugging. It also shows one-day queries for "x402 payment endpoint test" and "x402 market". No buyer, task budget, contact, escrow or order is disclosed.

**Safe MVP hypothesis (not deployed)**
- Only perform unpaid GET/HEAD checks against an endpoint supplied by an authorized buyer.
- Apply strict timeout, response-size and redirect limits.
- Record TLS/reachability, response time, HTTP status, 402 challenge presence and parseability.
- Validate declared scheme, chain/network, asset, payTo syntax, amount, method and expiry where exposed.
- Return timestamped observations, response hash, provenance and explicit unknowns.
- Label output "unpaid challenge inspected"; never claim a payment succeeded, a paid endpoint fulfilled, or a settlement was verified.

**Hard boundary:** end-to-end payment and fulfillment proof requires a separately authorized payment and independent receipt/chain evidence. No payment, signature, paid endpoint call, price, SKU, listing or deployment is included in this hypothesis.

## Priority 3 — Signed Delivery Evidence Packet / A2A attestation
**Evidence:** the delayed feed shows "signed delivery packet attestation bounty payout" for one day, four IPs and 258 searches. High volume from four IPs on one day may reflect repeated automation or a single narrow use case; it does not establish distinct buyers or budget.

**Research-only concept**
- Bind task ID, deliverable URI, artifact hash, timestamp, verifier identity, acceptance criteria and signed receipt into a compact evidence packet.
- Preserve source provenance and make acceptance/rejection reasons machine-readable.
- Distinguish "artifact submitted", "buyer accepted", "settlement observed" and "independently verified payout" as separate states.
- Deduplicate by task ID, artifact hash and settlement transaction hash.
- Never mark a task paid based only on a self-reported status, a signature, a 402 response or a queued fulfillment.

**Gates:** identify an actual buyer and supported task board, confirm exact required attestation format, legal data access, payment/escrow evidence, independent verifier, delivery cost and positive margin. Do not build or publish on search volume alone.

## Rejected or deferred channels
- BountyBook: current indexed x402 listings are all promised and none escrowed; the board health endpoint reports failed payouts. Not a dependable first-cash route.
- Frantic: escrow exists, but reviewed tasks require public Reddit responses, external citations or campaign approval; prohibited external communications and low ticket size make them unsuitable.
- Agent Bounties: current tasks mainly require creating and funding child bounties, which requires prohibited spend; remaining evidence work is uneconomic.
- BasedAgents: current tasks are unescrowed, tiny, and not aligned with LUMEN's offer catalog.
- OpenTask: CSV parser tasks (May 14) and OpenAPI documentation task (June 2) are stale, unescrowed/promised, and not qualified. Deduplicate the two CSV task descriptions; do not treat them as two independent buyers.
- Public procurement: UNDP-BIH-01700 requires hydrological forecasting and warning-system expertise; ILO rfx_13537_HQ requires English/French communications work and Drupal credentials. Both fail LUMEN's evidenced delivery-fit gate.

## Commercial decision
1. Keep MP-QUOTE-SANITY as the only immediate existing-offer hypothesis.
2. Retain x402 Preflight and Signed Delivery Evidence Packet as research-only product gaps.
3. Do not add leads from aggregate signals, marketplace totals, stale listings or transport handshakes.
4. Do not change prices, build, deploy, list, bid, spend, or send external messages without explicit human authorization.
5. Feed profit learning only from independently verified unique settlements and realized contribution margin; no fresh recompute was available in this pass.

## Proposal status
- Customer-specific proposals: 0.
- Canonical queue imports: 0.
- External submissions/messages: 0.
- Spend: USD 0.
- Production/catalog changes: 0.
- Human approval remains mandatory for all binding, financial, paid or external actions.
