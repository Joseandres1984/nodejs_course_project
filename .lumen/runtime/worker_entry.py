from __future__ import annotations

import runpy

import growth_prospector  # noqa: F401 - prospecting patches are applied on import
import demand_hunter_runtime  # noqa: F401 - demand-first discovery and prioritization patches

runpy.run_module("worker_journal", run_name="__main__")
