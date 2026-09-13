from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from zoneinfo import ZoneInfo

import scout_connector


VERSION = "1.1-autonomous-search-budget-governor"
TZ_NAME = str(os.getenv("LUMEN_SCOUT_TIMEZONE", "America/Argentina/Buenos_Aires")).strip() or "America/Argentina/Buenos_Aires"
try:
    LOCAL_TZ = ZoneInfo(TZ_NAME)
except Exception:
    LOCAL_TZ = timezone(timedelta(hours=-3))

# Keep the same total search envelope; only reallocate it toward the current bottleneck.
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


def general_budget(state: Dict[str, Any]) -> Dict[str, Any]:
    """Budget used by generic discovery, agents, Mission Scout, retail, partner and deep-work search.

    Demand discovery/confirmation uses a separate reserved lane. The two lanes still sum to the
    original daily cap, so this changes allocation rather than increasing search spend.
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
        # Migration is deliberately non-destructive: if the legacy budget was already consumed
        # today, never reset it and accidentally create extra provider spend.
        budget["timezone"] = TZ_NAME
        budget["queries_used"] = max(0, _int(budget.get("queries_used"), 0))

    budget["daily_budget"] = GENERAL_POOL_CAP
    budget["queries_remaining"] = max(0, GENERAL_POOL_CAP - _int(budget.get("queries_used"), 0))
    budget["governor_version"] = VERSION
    budget["total_daily_cap"] = TOTAL_DAILY_CAP
    budget["demand_reserved_daily"] = DEMAND_RESERVED
    budget["general_pool_daily"] = GENERAL_POOL_CAP
    return budget


def _migration_debt_for_today(state: Dict[str, Any]) -> int:
    legacy = state.get("scout_budget", {}) or {}
    legacy_used = 0
    if str(legacy.get("date") or "") == local_day():
        legacy_used = max(0, _int(legacy.get("queries_used"), 0))
    return min(DEMAND_RESERVED, max(0, legacy_used - GENERAL_POOL_CAP))


def demand_budget(state: Dict[str, Any]) -> Dict[str, Any]:
    """Dedicated reserve for Demand Hunter, demand confirmation and buyer identity resolution."""
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
        # If today's reserve consists only of migration debt and the owner raises the total cap
        # mid-day, recompute that debt against the new general-pool size. This releases only the
        # newly-authorized capacity; it never rewinds real demand searches already executed.
        prior_migration_debt = max(0, _int(budget.get("migration_debt"), 0))
        current_used = max(0, _int(budget.get("queries_used"), 0))
        if current_used == prior_migration_debt:
            recomputed_debt = _migration_debt_for_today(state)
            if recomputed_debt < prior_migration_debt:
                budget["queries_used"] = recomputed_debt
                budget["migration_debt"] = recomputed_debt
                budget["migration_debt_adjusted_at"] = utcnow()
                budget["migration_debt_adjustment_reason"] = "daily_cap_increased_without_rewinding_real_demand_searches"

    budget["timezone"] = TZ_NAME
    budget["daily_budget"] = DEMAND_RESERVED
    budget["queries_used"] = max(0, _int(budget.get("queries_used"), 0))
    budget["queries_remaining"] = max(0, DEMAND_RESERVED - budget["queries_used"])
    budget["governor_version"] = VERSION
    budget["updated_at"] = utcnow()
    return budget


def reserve_demand_search(state: Dict[str, Any], wanted: int = 1) -> int:
    budget = demand_budget(state)
    count = max(0, min(_int(wanted, 0), _int(budget.get("queries_remaining"), 0)))
    budget["queries_used"] += count
    budget["queries_remaining"] = max(0, DEMAND_RESERVED - budget["queries_used"])
    budget["updated_at"] = utcnow()
    return count


def summary(state: Dict[str, Any]) -> Dict[str, Any]:
    general = general_budget(state)
    demand = demand_budget(state)
    general_effective = min(GENERAL_POOL_CAP, max(0, _int(general.get("queries_used"), 0)))
    demand_effective = min(DEMAND_RESERVED, max(0, _int(demand.get("queries_used"), 0)))
    return {
        "version": VERSION,
        "timezone": TZ_NAME,
        "total_daily_cap": TOTAL_DAILY_CAP,
        "general_retail_pool_daily": GENERAL_POOL_CAP,
        "general_retail_used": general_effective,
        "general_retail_remaining": max(0, GENERAL_POOL_CAP - general_effective),
        "demand_reserved_daily": DEMAND_RESERVED,
        "demand_used": demand_effective,
        "demand_remaining": max(0, DEMAND_RESERVED - demand_effective),
        "effective_total_used": min(TOTAL_DAILY_CAP, general_effective + demand_effective),
        "effective_total_remaining": max(0, TOTAL_DAILY_CAP - general_effective - demand_effective),
        "allocation_policy": "demand_reserved_plus_general_retail_same_total_cap",
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
    })
    return base


scout_connector.status = governed_status
