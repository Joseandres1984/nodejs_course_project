from __future__ import annotations

"""Zero-cost search-budget claims for LUMEN Zero.

The legacy production runtime used a PostgreSQL table to make search-budget reservations atomic.
LUMEN Zero no longer has PostgreSQL, and GitHub Actions already serializes production cycles with
one concurrency group. This adapter therefore keeps the same daily/provider caps while making each
claim atomic inside the running process and persisting the counters with the normal D1 state save.

It does not increase any search budget, add a paid provider, or bypass verification/outreach gates.
"""

import threading
from typing import Any, Dict

import search_budget_atomic_runtime as atomic
import search_budget_governor as governor


VERSION = "1.1-zero-d1-state-claims"
_LOCK = threading.Lock()


def sync_state_zero(state: Dict[str, Any]) -> bool:
    """Normalize persisted D1 counters without requiring a separate PostgreSQL claim table."""
    with _LOCK:
        governor.reconcile_legacy_counters(state)
        governor.general_budget(state)
        governor.demand_budget(state)
    return True


def claim_one_zero(state: Dict[str, Any], lane: str) -> bool:
    if lane not in {"general", "demand"}:
        return False

    with _LOCK:
        governor.reconcile_legacy_counters(state)
        general = governor.general_budget(state)
        demand = governor.demand_budget(state)

        general_used = max(0, int(general.get("queries_used") or 0))
        demand_used = max(0, int(demand.get("queries_used") or 0))
        total_used = general_used + demand_used
        if total_used >= governor.TOTAL_DAILY_CAP:
            return False

        if lane == "general":
            if general_used >= governor.GENERAL_POOL_CAP or int(general.get("queries_remaining") or 0) <= 0:
                return False
            general["queries_used"] = general_used + 1
        else:
            if demand_used >= governor.DEMAND_RESERVED or int(demand.get("queries_remaining") or 0) <= 0:
                return False
            demand["queries_used"] = demand_used + 1

        # Recompute both views immediately so every later engine sees the same hard-cap truth.
        governor.general_budget(state)
        governor.demand_budget(state)
        return True


# Patch the functions used dynamically by scout_tick_atomic, reserve_demand_search_atomic and
# summary_atomic. Subsequent runtimes can keep using the same public interfaces unchanged.
atomic.VERSION = VERSION
atomic.sync_state = sync_state_zero
atomic._claim_one = claim_one_zero

print(
    {
        "zero_search_budget_runtime": {
            "status": "active",
            "version": VERSION,
            "backend": "d1_persisted_state",
            "cross_run_serialization": "github_actions_concurrency",
            "in_process_lock": True,
            "total_daily_cap_unchanged": True,
            "paid_search": False,
        }
    },
    flush=True,
)
