# LUMEN Unified Economic Brain v1

This release makes one persisted economic mission the decision authority for each hourly cycle.

## Cognitive loop
OBSERVE -> INTERPRET -> GENERATE_HYPOTHESES -> REASON -> CHOOSE -> ACT_REVERSIBLY -> MEASURE -> LEARN.

## Design invariants
- Business-model hypotheses are open-ended; execution lanes only select an existing specialist tool family.
- One global mission is selected per cycle using an atomic D1 lease.
- Exploitation is score-first; bounded exploration deliberately tests novel zero-capital hypotheses.
- Verified x402 settlement is the strongest learning reward. Commercial response and published-offer evidence are weaker rewards.
- Specialists are subordinate to the selected mission. They no longer all receive execution budget by default.
- Autonomous outgoing spend, purchases, debt, contracts, price mutation and binding actions remain disabled/human-gated.
- Stored rationale is a concise evidence summary, not hidden chain-of-thought.

## Production verification
The lumen-zero push deploy workflow runs unit/regression tests, deploys the Worker, validates the public brain policy, verifies protected status, executes one bounded manual cognitive cycle, and requires a persisted live mission before the release is considered healthy.
