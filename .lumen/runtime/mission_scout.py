from __future__ import annotations

import os
from typing import Any, Dict, List, Tuple

from scout_connector import (
    API_KEY,
    PROVIDER,
    DAILY_QUERY_BUDGET,
    MARKET,
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


def _unique_queue(items: List[Tuple[str, str, str]]) -> List[Tuple[str, str, str]]:
    seen = set()
    out = []
    for item in items:
        if item[0] in seen:
            continue
        seen.add(item[0])
        out.append(item)
    return out


def _focus_categories(state: Dict[str, Any]) -> List[str]:
    strategic = state.get("strategic_directive", {}) or {}
    drive = state.get("entrepreneurial_drive", {}) or {}
    primary = drive.get("primary", {}) or {}
    learning = state.get("profit_learning", {}) or {}
    deprioritized = {str(x).strip().lower() for x in strategic.get("deprioritized_categories", []) or []}
    values: List[str] = []

    for category in strategic.get("focus_categories", []) or []:
        cat = str(category or "").strip()
        if cat and cat.lower() not in deprioritized and cat not in values:
            values.append(cat)
    if primary.get("focus_category"):
        cat = str(primary["focus_category"]).strip()
        if cat and cat.lower() not in deprioritized and cat not in values:
            values.append(cat)
    for item in learning.get("focus_categories", []) or []:
        cat = str(item.get("category") or "").strip()
        if cat and cat.lower() not in deprioritized and cat not in values:
            values.append(cat)
    return values[:3]


def _focused_queries(state: Dict[str, Any], side: str) -> List[Tuple[str, str, str]]:
    categories = _focus_categories(state)
    buyer: List[Tuple[str, str, str]] = []
    supplier: List[Tuple[str, str, str]] = []
    for category in categories:
        buyer.append((f'empresa industria planta mantenimiento "{category}" {MARKET} -proveedor -distribuidor', "buyer", category))
        supplier.append((f'"{category}" fabricante distribuidor proveedor {MARKET}', "supplier", category))
    if side == "supplier":
        return supplier + buyer
    if side == "buyer":
        return buyer + supplier
    return _interleave(buyer, supplier)


def _exploration_cycle(state: Dict[str, Any], exploit_pct: int) -> bool:
    brain = state.get("corporate_brain", {}) or {}
    learning = state.get("profit_learning", {}) or {}
    cycle = int(brain.get("cycle") or learning.get("cycles") or state.get("ticks") or 0)
    exploit_slots = max(1, min(9, round(exploit_pct / 10)))
    return cycle % 10 >= exploit_slots


def mission_scout_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    strategic = state.get("strategic_directive", {}) or {}
    drive = state.get("entrepreneurial_drive", {}) or {}
    primary = drive.get("primary", {}) or {}
    learning = state.get("profit_learning", {}) or {}
    governance = state.get("master_governance", {}) or {}
    switches = governance.get("kill_switches", {}) or {}
    resource_plan = governance.get("resource_plan", {}) or state.get("master_resource_plan", {}) or {}
    resource_cap = max(0, int(resource_plan.get("mission_queries_cap", MAX_MISSION_QUERIES) or 0))

    side = str(strategic.get("research_side") or primary.get("research_side") or "balanced")
    action = str(primary.get("action") or "expand_market")
    objective = str(primary.get("objective") or strategic.get("thesis") or "Expandir mercado")
    exploit_pct = int(strategic.get("exploit_pct") or learning.get("exploit_pct") or 70)
    exploit_pct = max(50, min(88, exploit_pct))
    explore = _exploration_cycle(state, exploit_pct)

    stats = {
        "configured": bool(PROVIDER and API_KEY),
        "mission_action": action,
        "research_side": side,
        "objective": objective,
        "corporate_strategy_mode": strategic.get("mode"),
        "corporate_strategy_epoch": strategic.get("strategy_epoch"),
        "master_company_mode": governance.get("company_mode"),
        "constitutional_query_cap": resource_cap,
        "mode": "explore" if explore else "exploit",
        "focus_categories": _focus_categories(state),
        "exploit_pct": exploit_pct,
        "explore_pct": 100 - exploit_pct,
        "queries": 0,
        "new_leads": 0,
        "errors": 0,
        "budget_exhausted": False,
        "constitutional_block": None,
    }
    if switches.get("global_pause") or switches.get("research_pause") or resource_cap <= 0:
        stats["constitutional_block"] = "master_orchestrator_research_pause"
        return stats
    if not stats["configured"]:
        return stats

    budget = _budget(state)
    if int(budget.get("queries_remaining") or 0) <= 0:
        stats["budget_exhausted"] = True
        return stats

    supplier_q = _supplier_queries(state)
    buyer_q = _buyer_queries(state)
    if side == "supplier":
        generic_queue = supplier_q + buyer_q
    elif side == "buyer":
        generic_queue = buyer_q + supplier_q
    else:
        generic_queue = _interleave(buyer_q, supplier_q)

    focused = _focused_queries(state, side)
    if explore or not focused:
        queue = _unique_queue(generic_queue + focused)
    else:
        queue = _unique_queue(focused + generic_queue)

    allowed = min(MAX_MISSION_QUERIES, resource_cap, int(budget.get("queries_remaining") or 0))
    for query, lead_type, category in queue[:allowed]:
        try:
            budget["queries_used"] = int(budget.get("queries_used") or 0) + 1
            stats["queries"] += 1
            results = search(query)
            created = _store_results(state, query, lead_type, category, results)
            stats["new_leads"] += created
            _log(
                state,
                f"Mission Scout [{stats['mode']}/{strategic.get('mode') or 'operativo'}/{governance.get('company_mode') or 'sin-orquestar'}] ejecutó {action}: {lead_type}/{category}; {created} leads nuevos con evidencia pública.",
            )
        except Exception as exc:
            stats["errors"] += 1
            _log(state, f"Mission Scout falló en {action}: {str(exc)[:140]}")

    budget["queries_remaining"] = max(0, DAILY_QUERY_BUDGET - int(budget.get("queries_used") or 0))
    budget["updated_at"] = utcnow()
    budget["last_mission_action"] = action
    budget["last_mission_mode"] = stats["mode"]
    budget["last_focus_categories"] = stats["focus_categories"]
    budget["last_corporate_strategy"] = strategic.get("mode")
    budget["last_master_company_mode"] = governance.get("company_mode")
    stats["budget_exhausted"] = int(budget.get("queries_remaining") or 0) <= 0
    return stats
