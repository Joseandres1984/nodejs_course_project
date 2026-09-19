"""LUMEN search-budget policy override.

Loaded before search_budget_atomic_runtime so the shared governor sees the
current commercial search envelope for this deployment.
"""
from __future__ import annotations

import os

os.environ["LUMEN_SCOUT_DAILY_BUDGET"] = "192"
os.environ["LUMEN_DEMAND_RESERVED_SEARCHES"] = "134"

TOTAL_DAILY_CAP = 192
DEMAND_RESERVED = 134
GENERAL_POOL = 58
POLICY_VERSION = "2026-09-19-aggressive-first-cash"
