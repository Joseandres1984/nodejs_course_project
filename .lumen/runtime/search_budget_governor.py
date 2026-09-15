from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from zoneinfo import ZoneInfo

import scout_connector


VERSION = "1.4-shared-hard-cap-search-budget-governor"
TZ_NAME = str(os.getenv("LUMEN_SCOUT_TIMEZONE", "America/Argentina/Buenos_Aires")).strip() or "America/Argentina/Buenos_Aires"
try:
    LOCAL_TZ = ZoneInfo(TZ_NAME)
except Exception:
    LOCAL_TZ = timezone(timedelta(hours=-3))

# The total provider envelope is the hard cap. Adaptive runtimes may only redistribute this total.
TOTAL_DAILY_CAP = max(6, int(os.getenv("LUMEN_SCOUT_DAILY_BUDGET", "24")))
DEMAND_RESERVED = max(1, min(TOTAL_DAILY_CAP - 2, int(os.getenv("LUMEN_DEMAND_RESERVED_SEARCHES", "6"))))
GENERAL_POOL_CAP = max(2, TOTAL_DAILY_CAP - DEMAND_RESERVED)


def local_day() -> str:
    return datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _used_today(row: Any, key: str = "queries_used") -> int:
    if not isinstance(row, dict) or str(row.get("date") or "") != local_day():
        return 0
    return max(0, _int(row.get(key), 0))


def _demand_used_today(state: Dict[str, Any]) -> int:
    return _used_today(state.get("demand_search_budget"), "queries_used")


def _general_used_today(state: Dict[str, Any]) -> int:
    return _used_today(state.get("scout_budget"), "queries_used")


def _actual_total_used(state: Dict[str, Any]) -> int:
    return _general_used_today(state) + _demand_used_today(state)


def _real_total_remaining(state: Dict[str, Any], demand_used: int | None = None) -> int:
    general_used = _general_used_today(state)
    demand_actual = _demand_used_today(state) if demand_used is None else max(0, _int(demand_used, 0))
    return max(0, TOTAL_DAILY_CAP - general_used - demand_actual)


def _canonical_usage(raw_general: int, raw_demand: int) -> tuple[int, int]:
    """Compress legacy over-cap counters without creating fresh provider capacity.

    Historical runtimes could count the same provider envelope through more than one lane. If that
    persisted state is already above today's provider hard cap, normalize it to exactly the hard cap
    while preserving a reconciliation snapshot. This is accounting repair only: remaining capacity
    stays zero for the day, so the migration can never authorize extra searches or extra spend.
    """
    raw_general = max(0, _int(raw_general, 0))
    raw_demand = max(0, _int(raw_demand, 0))
    target = min(TOTAL_DAILY_CAP, raw_general + raw_demand)

    general = min(raw_general, GENERAL_POOL_CAP)
    demand = min(raw_demand, DEMAND_RESERVED)
    remaining = max(0, target - general - demand)

    # If one lane historically consumed capacity beyond today's adaptive split, attribute only as much
    # overflow as is needed to preserve the provider-level total. Never invent usage above raw counters.
    if remaining:
        general_headroom = max(0, raw_general - general)
        add_general = min(remaining, general_headroom)
        general += add_general
        remaining -= add_general
    if remaining:
        demand_headroom = max(0, raw_demand - demand)
        add_demand = min(remaining, demand_headroom)
        demand += add_demand
        remaining -= add_demand

    return general, demand


def reconcile_legacy_counters(state: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize only persisted same-day counters that predate the shared hard-cap accounting.

    The raw values are retained in `search_budget_reconciliation` for audit. Canonical counters are
    capped at the provider envelope and therefore cannot poison the dashboard or later lane math.
    Crucially, a reconciled over-cap day remains fully exhausted.
    """
    today = local_day()
    raw_general = _general_used_today(state)
    raw_demand = _demand_used_today(state)
    raw_total = raw_general + raw_demand

    if raw_total <= TOTAL_DAILY_CAP:
        return {
            "reconciled": False,
            "date": today,
            "raw_general": raw_general,
            "raw_demand": raw_demand,
            "raw_total": raw_total,
            "canonical_total": raw_total,
            "legacy_overage_absorbed": 0,
        }

    canonical_general, canonical_demand = _canonical_usage(raw_general, raw_demand)
    canonical_total = canonical_general + canonical_demand

    general = state.setdefault("scout_budget", {})
    general.update({
        "date": today,
        "timezone": TZ_NAME,
        "queries_used": canonical_general,
        "daily_budget": GENERAL_POOL_CAP,
        "queries_remaining": 0,
        "real_total_remaining": 0,
        "actual_total_used": canonical_total,
        "over_cap_by": 0,
        "hard_cap_enforced": True,
        "governor_version": VERSION,
        "total_daily_cap": TOTAL_DAILY_CAP,
        "demand_reserved_daily": DEMAND_RESERVED,
        "general_pool_daily": GENERAL_POOL_CAP,
        "reconciled_at": utcnow(),
    })

    demand = state.get("demand_search_budget")
    if not isinstance(demand, dict):
        demand = {}
        state["demand_search_budget"] = demand
    previous_migration_debt = max(0, _int(demand.get("migration_debt"), 0))
    demand.update({
        "date": today,
        "timezone": TZ_NAME,
        "queries_used": canonical_demand,
        "daily_budget": DEMAND_RESERVED,
        "queries_remaining": 0,
        "actual_total_used": canonical_total,
        "over_cap_by": 0,
        "hard_cap_enforced": True,
        "governor_version": VERSION,
        "updated_at": utcnow(),
        # Neutralize the old migration-debt heuristic so the repaired demand usage is not later
        # mistaken for synthetic debt and subtracted again, which would recreate budget mid-day.
        "migration_debt": 0,
        "legacy_migration_debt": previous_migration_debt,
        "reconciled_at": utcnow(),
    })

    record = {
        "version": VERSION,
        "date": today,
        "reconciled": True,
        "reason": "legacy_multi_lane_counter_overage_normalized_without_reopening_provider_budget",
        "raw_general": raw_general,
        "raw_demand": raw_demand,
        "raw_total": raw_total,
        "canonical_general": canonical_general,
        "canonical_demand": canonical_demand,
        "canonical_total": canonical_total,
        "provider_daily_cap": TOTAL_DAILY_CAP,
        "legacy_overage_absorbed": max(0, raw_total - TOTAL_DAILY_CAP),
        "remaining_after_reconciliation": 0,
        "reconciled_at": utcnow(),
    }
    state["search_budget_reconciliation"] = record
    return record


def general_budget(state: Dict[str, Any]) -> Dict[str, Any]:
    """Shared hard-cap budget for general discovery/agents/retail/deep-work.

    The general lane may be resized intraday, but already-consumed demand searches always remain
    charged to the same TOTAL_DAILY_CAP. Reallocation can therefore move only unused capacity.
    """
    today = local_day()
    budget = state.setdefault("scout_budget", {})
    prior_date = str(budget.get("date") or "")

    if prior_date != today:
        budget.clear()
        budget.update({
            "date": today,
            "timezone": TZ_NAME,
            "queries_used": 0,
            "daily_budget": GENERAL_POOL_CAP,
            "reset_reason": "search_budget_governor_local_day_reset",
            "reset_at": utcnow(),
        })
    else:
        budget["timezone"] = TZ_NAME
        budget["queries_used"] = max(0, _int(budget.get("queries_used"), 0))

    general_used = max(0, _int(budget.get("queries_used"), 0))
    demand_used = _demand_used_today(state)
    lane_remaining = max(0, GENERAL_POOL_CAP - general_used)
    real_total_remaining = max(0, TOTAL_DAILY_CAP - general_used - demand_used)

    budget["daily_budget"] = GENERAL_POOL_CAP
    budget["queries_remaining"] = min(lane_remaining, real_total_remaining)
    budget["real_total_remaining"] = real_total_remaining
    budget["actual_total_used"] = general_used + demand_used
    budget["over_cap_by"] = max(0, general_used + demand_used - TOTAL_DAILY_CAP)
    budget["hard_cap_enforced"] = True
    budget["governor_version"] = VERSION
    budget["total_daily_cap"] = TOTAL_DAILY_CAP
    budget["demand_reserved_daily"] = DEMAND_RESERVED
    budget["general_pool_daily"] = GENERAL_POOL_CAP
    return budget


def _migration_debt_for_today(state: Dict[str, Any]) -> int:
    legacy_used = _general_used_today(state)
    return min(DEMAND_RESERVED, max(0, legacy_used - GENERAL_POOL_CAP))


def demand_budget(state: Dict[str, Any]) -> Dict[str, Any]:
    """Dedicated demand lane, still bounded by the same hard provider cap."""
    today = local_day()
    budget = state.get("demand_search_budget")

    if not isinstance(budget, dict) or str(budget.get("date") or "") != today:
        migration_debt = _migration_debt_for_today(state)
        budget = {
            "date": today,
            "timezone": TZ_NAME,
            "queries_used": migration_debt,
            "daily_budget": DEMAND_RESERVED,
            "migration_debt": migration_debt,
            "reset_at": utcnow(),
        }
        state["demand_search_budget"] = budget
    else:
        prior_migration_debt = max(0, _int(budget.get("migration_debt"), 0))
        current_used = max(0, _int(budget.get("queries_used"), 0))
        if current_used == prior_migration_debt and not budget.get("reconciled_at"):
            recomputed_debt = _migration_debt_for_today(state)
            if recomputed_debt < prior_migration_debt:
                budget["queries_used"] = recomputed_debt
                budget["migration_debt"] = recomputed_debt
                budget["migration_debt_adjusted_at"] = utcnow()
                budget["migration_debt_adjustment_reason"] = "daily_cap_increased_without_rewinding_real_demand_searches"

    budget["timezone"] = TZ_NAME
    budget["daily_budget"] = DEMAND_RESERVED
    budget["queries_used"] = max(0, _int(budget.get("queries_used"), 0))
    lane_remaining = max(0, DEMAND_RESERVED - budget["queries_used"])
    budget["queries_remaining"] = min(lane_remaining, _real_total_remaining(state, budget["queries_used"]))
    budget["actual_total_used"] = _general_used_today(state) + budget["queries_used"]
    budget["over_cap_by"] = max(0, budget["actual_total_used"] - TOTAL_DAILY_CAP)
    budget["hard_cap_enforced"] = True
    budget["governor_version"] = VERSION
    budget["updated_at"] = utcnow()
    return budget


def reserve_demand_search(state: Dict[str, Any], wanted: int = 1) -> int:
    budget = demand_budget(state)
    count = max(0, min(_int(wanted, 0), _int(budget.get("queries_remaining"), 0)))
    budget["queries_used"] += count
    lane_remaining = max(0, DEMAND_RESERVED - budget["queries_used"])
    budget["queries_remaining"] = min(lane_remaining, _real_total_remaining(state, budget["queries_used"]))
    budget["updated_at"] = utcnow()
    return count


def summary(state: Dict[str, Any]) -> Dict[str, Any]:
    general = general_budget(state)
    demand = demand_budget(state)
    general_actual = max(0, _int(general.get("queries_used"), 0))
    demand_actual = max(0, _int(demand.get("queries_used"), 0))
    actual_total = general_actual + demand_actual
    reconciliation = state.get("search_budget_reconciliation", {}) or {}
    reconciliation_today = reconciliation if str(reconciliation.get("date") or "") == local_day() else {}
    return {
        "version": VERSION,
        "timezone": TZ_NAME,
        "total_daily_cap": TOTAL_DAILY_CAP,
        "general_retail_pool_daily": GENERAL_POOL_CAP,
        "general_retail_used": general_actual,
        "general_retail_remaining": int(general.get("queries_remaining") or 0),
        "demand_reserved_daily": DEMAND_RESERVED,
        "demand_used": demand_actual,
        "demand_remaining": int(demand.get("queries_remaining") or 0),
        "effective_total_used": min(TOTAL_DAILY_CAP, actual_total),
        "effective_total_remaining": max(0, TOTAL_DAILY_CAP - actual_total),
        "over_cap_by": max(0, actual_total - TOTAL_DAILY_CAP),
        "legacy_overage_absorbed_today": int(reconciliation_today.get("legacy_overage_absorbed") or 0),
        "raw_total_before_reconciliation": reconciliation_today.get("raw_total"),
        "accounting_reconciled": bool(reconciliation_today.get("reconciled")),
        "hard_cap_enforced_now": True,
        "allocation_policy": "adaptive_lanes_share_one_hard_daily_cap_no_intraday_budget_recreation",
        "updated_at": utcnow(),
    }


# Install before the rest of LUMEN imports constants/functions from Scout Connector.
scout_connector.DAILY_QUERY_BUDGET = GENERAL_POOL_CAP
scout_connector.utcdate = local_day
scout_connector._budget = general_budget

_original_status = scout_connector.status


def governed_status() -> Dict[str, Any]:
    base = dict(_original_status() or {})
    base.update({
        "daily_query_budget": TOTAL_DAILY_CAP,
        "general_retail_pool_daily": GENERAL_POOL_CAP,
        "demand_reserved_daily": DEMAND_RESERVED,
        "budget_timezone": TZ_NAME,
        "budget_governor_version": VERSION,
        "shared_hard_cap": True,
    })
    return base


scout_connector.status = governed_status
