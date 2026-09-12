from __future__ import annotations

import os
from typing import Any, Dict, List, Tuple

from scout_connector import (
    API_KEY,
    PROVIDER,
    DAILY_QUERY_BUDGET,
    _budget,
    _buyer_queries,
    _supplier_queries,
    _store_results,
    search,
    utcnow,
)

MAX_MISSION_QUERIES = max(1, min(3, int(os.getenv("LUMEN_MISSION_SCOUT_MAX_QUERIES", "1"))))


def _log(state: Dict[str, Any], msg: str) -> None:
    state.setdefault("activity", []).insert(0, {"ts": utcnow(), "msg": msg})
    state["activity"] = state["activity"][:100]


def _interleave(a: List[Tuple[str, str, str]], b: List[Tuple[str, str, str]]) -> List[Tuple[str, str, str]]:
    out: List[Tuple[str, str, str]] = []
    for i in range(max(len(a), len(b))):
        if i < len(a):
            out.append(a[i])
        if i < len(b):
            out.append(b[i])
    return out


def mission_scout_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    drive = state.get("entrepreneurial_drive", {}) or {}
    primary = drive.get("primary", {}) or {}
    side = str(primary.get("research_side") or "balanced")
    action = str(primary.get("action") or "expand_market")
    objective = str(primary.get("objective") or "Expandir mercado")

    stats = {
        "configured": bool(PROVIDER and API_KEY),
        "mission_action": action,
        "research_side": side,
        "objective": objective,
        "queries": 0,
        "new_leads": 0,
        "errors": 0,
        "budget_exhausted": False,
    }
    if not stats["configured"]:
        return stats

    budget = _budget(state)
    if int(budget.get("queries_remaining") or 0) <= 0:
        stats["budget_exhausted"] = True
        return stats

    supplier_q = _supplier_queries(state)
    buyer_q = _buyer_queries(state)
    if side == "supplier":
        queue = supplier_q + buyer_q
    elif side == "buyer":
        queue = buyer_q + supplier_q
    else:
        queue = _interleave(buyer_q, supplier_q)

    allowed = min(MAX_MISSION_QUERIES, int(budget.get("queries_remaining") or 0))
    for query, lead_type, category in queue[:allowed]:
        try:
            budget["queries_used"] = int(budget.get("queries_used") or 0) + 1
            stats["queries"] += 1
            results = search(query)
            created = _store_results(state, query, lead_type, category, results)
            stats["new_leads"] += created
            _log(
                state,
                f"Mission Scout ejecutó la misión {action}: {lead_type}/{category}; {created} leads nuevos con evidencia pública.",
            )
        except Exception as exc:
            stats["errors"] += 1
            _log(state, f"Mission Scout falló en {action}: {str(exc)[:140]}")

    budget["queries_remaining"] = max(0, DAILY_QUERY_BUDGET - int(budget.get("queries_used") or 0))
    budget["updated_at"] = utcnow()
    budget["last_mission_action"] = action
    stats["budget_exhausted"] = int(budget.get("queries_remaining") or 0) <= 0
    return stats
