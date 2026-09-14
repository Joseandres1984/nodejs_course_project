from __future__ import annotations

import runpy

# Install the shared search-budget split before other modules import Scout constants.
import search_budget_governor  # noqa: F401

# Existing prospecting and demand-intelligence upgrades.
import growth_prospector  # noqa: F401 - prospecting patches are applied on import
import demand_hunter_runtime  # noqa: F401 - demand-first scoring/prioritization patches
import supreme_autonomy_runtime  # noqa: F401
import public_procurement_runtime  # noqa: F401
import adaptive_procurement_runtime  # noqa: F401
import operational_health_runtime  # noqa: F401
import https_mail_transport  # noqa: F401
import gmail_sent_runtime  # noqa: F401
import market_intelligence_runtime  # noqa: F401
import continuous_learning_compat_runtime  # noqa: F401

# Revenue Execution v2: adaptive budget with one shared hard provider cap.
import adaptive_search_budget_runtime  # noqa: F401
import shared_search_cap_runtime  # noqa: F401

# Single commercial source of truth. This installs the Autonomy OS filter before allocator/bridge
# wrappers are imported, so raw legacy deals cannot create false closing priority.
import canonical_revenue_truth_runtime  # noqa: F401

import revenue_allocator_runtime  # noqa: F401
import revenue_execution_bridge_runtime  # noqa: F401
import quote_accelerator_runtime  # noqa: F401
import commercial_learning_v2_runtime  # noqa: F401
import commercial_learning_v2_log_runtime  # noqa: F401

runpy.run_module("worker_journal", run_name="__main__")
