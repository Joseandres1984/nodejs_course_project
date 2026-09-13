from __future__ import annotations

import runpy

# Install the shared search-budget split before other modules import Scout constants.
import search_budget_governor  # noqa: F401

# Existing prospecting and demand-intelligence upgrades.
import growth_prospector  # noqa: F401 - prospecting patches are applied on import
import demand_hunter_runtime  # noqa: F401 - demand-first scoring/prioritization patches

# Final production orchestration: protected demand budget + buyer identity resolution + adaptive search.
import supreme_autonomy_runtime  # noqa: F401

runpy.run_module("worker_journal", run_name="__main__")
