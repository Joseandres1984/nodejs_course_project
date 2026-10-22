# LUMEN — verified demand to commercial proposal handoff

This workflow connects new buyer demand discovered in research to LUMEN's **existing, authenticated, review-only proposal queue**. It is not an outreach tool and cannot submit bids, claim agent bounties, sign contracts, pay fees, approve settlements, or send direct messages.

## Operator input

Edit `.lumen/sales/verified-demand-queue.json` in a dedicated review branch, adding no more than 10 **new** high-affinity leads. Each lead must have all fields below, sourced from publicly checkable original evidence:

```json
{
  "lane": "B2B",
  "sourceUrl": "https://example.org/real-request-url",
  "buyer": "Verified buyer company or agent",
  "sourceQuote": "An exact excerpt of the buyer's current commercial purchasing request (at least 35 characters).",
  "buyerNeed": "An exact excerpt of the buyer's current commercial purchasing request (at least 35 characters). Added scope description.",
  "publishedAt": "2026-10-21T14:00:00Z",
  "verifiedAt": "2026-10-21T16:00:00Z",
  "openVerified": true,
  "budgetUsd": 100,
  "budgetCurrency": "USD",
  "proposedUsd": 7,
  "paymentCapacityVerified": true,
  "paymentEvidenceUrl": "https://example.org/real-request-url",
  "paymentEvidenceNote": "Evidence that the identified buyer has published funding or escrow, not a payment promise.",
  "channel": "Buyer-authorized public application route",
  "channelRulesUrl": "https://example.org/official-applicant-rules",
  "feeCheckNote": "Verified no paid connects, deposits, required memberships or paid identity validation.",
  "freeApplicationVerified": true,
  "channelAllowsProposal": true,
  "requiredSpendUsd": 0,
  "requiresConnects": false,
  "requiresPaidVerification": false,
  "productId": "MP-QUOTE-SANITY",
  "deliverable": "Evidence-linked quote structure comparison",
  "automatedApplicationRequested": false
}
```

**The JSON above is only a schema illustration, NOT an opportunity or a valid real buyer.** Do not copy its dummy URLs, names, budget, dates, or approval booleans into production. An actual price must fit both buyer budget and LUMEN's capabilities.

The importer checks source, date, budget, channel, fee, evidence and historic Upwork duplicates from the October 8 pipeline; it refuses the entire batch if any lead fails. It does not independently crawl or authenticate the external buyer; researchers must verify original textual evidence before recording `true`. A listing is **not** automatically interest in LUMEN.

For `lane: "X402"`, additionally require `x402CheckoutVerified: true` and `ownerSettlementApprovalRequired: true` only after separately verifying the exact published checkout. A paid buyer-side bounty is not a LUMEN x402 settlement. The proposer must not count prospective payments, 402 HTTP responses, or developer conversations as revenue.

## Execution

Pull request CI runs all qualification tests without any live third-party application. When vetted entries are merged into `lumen-zero`, GitHub Actions triggers the importer with the existing `OPPORTUNITY_ADMIN_TOKEN` repository secret. It POSTs each eligible lead **only** to `/commercial/proposals/prepare` on `lumen-zero-a2a.lumen-b2b.workers.dev`. D1 enforces idempotent source URLs and replies `AWAITING_OWNER_REVIEW`. If no leads are entered, zero requests are made. No credentials should be committed to Git.

To inspect the private drafts, use `GET /commercial/proposals/queue` with the admin header. Each proposal awaits review; no external platform or A2A protocol send is performed. Genuine replies, external communications and any x402 settlement require independently verified channel authority and individual owner approval.

### Honest KPI tracking

Measure verified new buyers, proposals **prepared**, separately proposals **actually submitted**, authentic human or agent purchase-interest replies, contracts **signed**, x402 receipts **independently settled**, and USD paid. Do not substitute CI success for cash.
