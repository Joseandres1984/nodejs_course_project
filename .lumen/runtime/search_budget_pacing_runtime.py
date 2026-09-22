from __future__ import annotations

"""Intraday pacing for LUMEN's zero-cost public-search envelope.

The provider envelope is configured by the zero-cost runtime. This module limits how much of
that already-free envelope can be consumed at each part of the Argentina day so Autopilot does
not burn the whole allowance early. Pacing scales proportionally with the configured daily cap;
it never creates paid spend, adds provider quota, or relaxes verification gates.
"""

from datetime import datetime
from typing import Any, Dict, Tuple

import scout_connector
import search_budget_governor as governor

VERSION = "1.1-zero-cost-scaled-intraday-pacing"

_ORIGINAL_GENERAL_BUDGET = governor.general_budget
_ORIGINAL_DEMAND_BUDGET = governor.demand_budget
_ORIGINAL_SUMMARY = governor.summary


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _milestones(total: int | None = None) -> Tuple[int, int, int, int]:
    """Return cumulative unlocks preserving the original 4/10/17/24 pacing ratios."""
    cap = max(1, int(total if total is not None else governor.TOTAL_DAILY_CAP))
    first = max(1, min(cap, int(round(cap * (4 / 24)))))
    second = max(first, min(cap, int(round(cap * (10 / 24)))))
    third = max(second, min(cap, int(round(cap * (17 / 24)))))
    return first, second, third, cap


def pace_cap_now() -> int:
    """Maximum cumulative provider queries unlocked by current Argentina local hour."""
    hour = datetime.now(governor.LOCAL_TZ).hour
    first, second, third, full = _milestones()
    if hour < 6:
        return first
    if hour < 12:
        return second
    if hour < 18:
        return third
    return full


def next_unlock_local() -> str:
    hour = datetime.now(governor.LOCAL_TZ).hour
    if hour < 6:
        return "06:00"
    if hour < 12:
        return "12:00"
    if hour < 18:
        return "18:00"
    return "00:00"


def _schedule_labels() -> list[str]:
    first, second, third, full = _milestones()
    return [
        f"00:00→{first}",
        f"06:00→{second}",
        f"12:00→{third}",
        f"18:00→{full}",
    ]


def _actual_used(state: Dict[str, Any]) -> int:
    general = state.get("scout_budget") if isinstance(state.get("scout_budget"), dict) else {}
    demand = state.get("demand_search_budget") if isinstance(state.get("demand_search_budget"), dict) else {}
    today = governor.local_day()
    general_used = _i(general.get("queries_used")) if str(general.get("date") or "") == today else 0
    demand_used = _i(demand.get("queries_used")) if str(demand.get("date") or "") == today else 0
    return max(0, general_used) + max(0, demand_used)


def _apply_pace(row: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    unlocked = pace_cap_now()
    used = _actual_used(state)
    pace_remaining = max(0, unlocked - used)
    row["queries_remaining"] = min(max(0, _i(row.get("queries_remaining"))), pace_remaining)
    row["pacing_version"] = VERSION
    row["pacing_enabled"] = True
    row["pacing_unlocked_cap"] = unlocked
    row["pacing_remaining_now"] = pace_remaining
    row["pacing_next_unlock_local"] = next_unlock_local()
    row["pacing_daily_hard_cap"] = int(governor.TOTAL_DAILY_CAP)
    return row


def paced_general_budget(state: Dict[str, Any]) -> Dict[str, Any]:
    return _apply_pace(_ORIGINAL_GENERAL_BUDGET(state), state)


def paced_demand_budget(state: Dict[str, Any]) -> Dict[str, Any]:
    return _apply_pace(_ORIGINAL_DEMAND_BUDGET(state), state)


def paced_summary(state: Dict[str, Any]) -> Dict[str, Any]:
    base = dict(_ORIGINAL_SUMMARY(state) or {})
    unlocked = pace_cap_now()
    used = _actual_used(state)
    base["pacing"] = {
        "version": VERSION,
        "enabled": True,
        "timezone": governor.TZ_NAME,
        "daily_hard_cap": int(governor.TOTAL_DAILY_CAP),
        "unlocked_cap_now": unlocked,
        "used_now": min(int(governor.TOTAL_DAILY_CAP), used),
        "available_now": max(0, min(int(governor.TOTAL_DAILY_CAP) - used, unlocked - used)),
        "next_unlock_local": next_unlock_local(),
        "schedule": _schedule_labels(),
        "cost_usd": 0,
        "rule": "pace_free_queries_proportionally_without_increasing_configured_daily_cap",
    }
    return base


governor.general_budget = paced_general_budget
governor.demand_budget = paced_demand_budget
governor.summary = paced_summary
# Scout Connector is the shared general-search entry point and must see the paced function.
scout_connector._budget = paced_general_budget

print({
    "search_budget_pacing_runtime": {
        "version": VERSION,
        "status": "active",
        "daily_hard_cap_unchanged": int(governor.TOTAL_DAILY_CAP),
        "unlocked_cap_now": pace_cap_now(),
        "unlock_schedule": _schedule_labels(),
        "next_unlock_local": next_unlock_local(),
        "timezone": governor.TZ_NAME,
        "paid_spend": False,
    }
}, flush=True)
