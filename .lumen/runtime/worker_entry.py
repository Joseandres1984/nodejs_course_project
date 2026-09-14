from __future__ import annotations

import runpy

# Install the shared search-budget split before other modules import Scout constants.
import search_budget_governor  # noqa: F401

# Existing prospecting and demand-intelligence upgrades.
import growth_prospector  # noqa: F401 - prospecting patches are applied on import
import demand_hunter_runtime  # noqa: F401 - demand-first scoring/prioritization patches

# Final production orchestration: protected demand budget + buyer identity resolution + adaptive search.
import supreme_autonomy_runtime  # noqa: F401

# Search public procurement first so published demand can be resolved to buyers in the same cycle,
# even when LUMEN does not yet have a verified supplier for that category.
import public_procurement_runtime  # noqa: F401

# Reorder public-procurement categories from the previous cycle's real economic/progression evidence.
# Exploration keeps a floor, so the system learns without starving categories that have little history.
import adaptive_procurement_runtime  # noqa: F401

# Operational health must reflect current business risk, not stale diagnostic canary failures.
import operational_health_runtime  # noqa: F401

# Install HTTPS email routing before worker.py imports `send_pending` from mail_connector.
# This makes the final worker outbound step use the production-ready Brevo/Resend route instead of
# falling back to hosting-blocked SMTP while preserving the existing Go-Live/quality/contact gates.
import https_mail_transport  # noqa: F401

# Archive each provider-confirmed Brevo send into Gmail Sent via IMAP without resending it.
# The runtime is idempotent and deduplicates by LUMEN outbox id before appending.
import gmail_sent_runtime  # noqa: F401

# Shadow market intelligence enriches only the existing robots-respecting public catalog pipeline.
# It is disabled by default and has no outreach, deal, purchase, approval or financial authority.
import market_intelligence_runtime  # noqa: F401

# Normalize legacy production state shapes before Continuous Learning reads metrics. This is a
# read-only compatibility shim and does not mutate persisted acquisition campaign rows.
import continuous_learning_compat_runtime  # noqa: F401

# Revenue Execution v2: dynamically allocate the existing workforce to the current revenue lane,
# adapt the existing search envelope without increasing its total cap, and turn demand evidence into
# evidence-gated opportunity work plus causal funnel telemetry before Autonomy OS builds its queue.
import adaptive_search_budget_runtime  # noqa: F401

# Hard-cap bridge: Agent Fleet and Professional Deep Work must obey the same real provider envelope
# as Demand Search even after an intraday adaptive reallocation. Already-spent capacity is never recreated.
import shared_search_cap_runtime  # noqa: F401

import revenue_allocator_runtime  # noqa: F401
import revenue_execution_bridge_runtime  # noqa: F401

# Quote acceleration does not raise outbound caps: it gives the existing bounded message capacity to
# requirement-ready / quote-starved cases before lower-value RevOps work.
import quote_accelerator_runtime  # noqa: F401

# Commercial Learning v2 extends Continuous Learning with historical source reputation, controlled
# reversible experiments, anti-drift, time-to-revenue memory, two-brain attention and an internal
# commercial/finance/quality review board. It cannot self-deploy code or widen financial authority.
import commercial_learning_v2_runtime  # noqa: F401
import commercial_learning_v2_log_runtime  # noqa: F401

runpy.run_module("worker_journal", run_name="__main__")
