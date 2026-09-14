from __future__ import annotations

from typing import Any, Dict

import agent_fleet
import search_budget_governor as governor

VERSION = "1.0-shared-search-cap-runtime"
_ORIGINAL_AGENT_BUDGET = agent_fleet._budget


def _safe_agent_budget(state: Dict[str, Any]) -> Dict[str, Any]:
    # Preserve Agent Fleet's retail-reserve accounting, then clamp every general/deep-work caller
    # against the governor's one shared provider cap (general + demand actual usage).
    base = dict(_ORIGINAL_AGENT_BUDGET(state) or {})
    shared = dict(governor.general_budget(state) or {})
    shared_remaining = max(0, int(shared.get("queries_remaining") or 0))
    existing_general = max(0, int(base.get("general_queries_remaining") or 0))
    safe_general = min(existing_general, shared_remaining)

    base["general_queries_remaining"] = safe_general
    base["queries_remaining"] = safe_general
    base["queries_remaining_total"] = min(
        max(0, int(base.get("queries_remaining_total") or 0)),
        max(0, int(shared.get("real_total_remaining") or 0)),
    )
    base["shared_total_daily_cap"] = int(shared.get("total_daily_cap") or governor.TOTAL_DAILY_CAP)
    base["shared_actual_total_used"] = int(shared.get("actual_total_used") or 0)
    base["shared_over_cap_by"] = int(shared.get("over_cap_by") or 0)
    base["shared_hard_cap_enforced"] = True
    return base


agent_fleet._budget = _safe_agent_budget
print({"shared_search_cap_runtime": {"version": VERSION, "status": "active", "covers": ["agent_fleet", "professional_casework"], "shared_hard_cap": True}}, flush=True)
