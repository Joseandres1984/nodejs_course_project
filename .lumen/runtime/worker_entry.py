from __future__ import annotations

import runpy

import growth_prospector  # noqa: F401 - production patches are applied on import

runpy.run_module("worker_journal", run_name="__main__")
