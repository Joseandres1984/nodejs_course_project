from __future__ import annotations

# Expand the retail radar before Meta-LUMEN imports the production worker. This patch adds
# Tiendanube, major Argentine retailers, brand stores and independent e-commerce corroboration
# while preserving the existing public-search, budget and commission-only guardrails.
import retail_market_expansion  # noqa: F401,E402

# Run the complete Meta-LUMEN + production worker first.
import worker_meta  # noqa: F401,E402

from app import STATE, load_state
from cycle_journal import record_cycle


# Persist one compact, queryable audit row only after the business cycle completed.
# The journal uses its own Postgres table so the global LUMEN state does not grow without bound.
load_state()
journal = record_cycle(STATE, source="worker_complete")
print({"cycle_journal": {k: v for k, v in journal.items() if k != "entry"}}, flush=True)
