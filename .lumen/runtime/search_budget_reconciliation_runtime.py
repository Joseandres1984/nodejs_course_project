from __future__ import annotations

from typing import Any, Dict

import app
import search_budget_governor as governor


VERSION = "1.0-search-budget-reconciliation-runtime"
_ORIGINAL_LOAD_STATE = app.load_state


def reconciled_load_state() -> bool:
    """Load persisted state, then repair legacy same-day search counters before any cycle uses them.

    This wrapper is installed after the adaptive lane split is selected, so reconciliation uses the
    active general/demand allocation. It never reopens provider capacity: an over-cap legacy day is
    normalized to the provider hard cap with zero remaining budget and an audit snapshot retained.
    """
    loaded = bool(_ORIGINAL_LOAD_STATE())
    if not loaded:
        return loaded

    result: Dict[str, Any] = dict(governor.reconcile_legacy_counters(app.STATE) or {})
    app.STATE["search_budget_reconciliation_runtime"] = {
        "version": VERSION,
        "status": "active",
        "reconciled": bool(result.get("reconciled")),
        "legacy_overage_absorbed": int(result.get("legacy_overage_absorbed") or 0),
        "provider_daily_cap": int(governor.TOTAL_DAILY_CAP),
        "remaining_after_reconciliation": int(result.get("remaining_after_reconciliation") or 0),
        "policy": "normalize_legacy_accounting_without_reopening_provider_budget",
        "updated_at": governor.utcnow(),
    }
    return loaded


app.load_state = reconciled_load_state
print({
    "search_budget_reconciliation_runtime": {
        "version": VERSION,
        "status": "active",
        "provider_daily_cap": governor.TOTAL_DAILY_CAP,
        "policy": "reconcile_after_every_persisted_state_load",
    }
}, flush=True)
