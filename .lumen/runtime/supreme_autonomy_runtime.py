from __future__ import annotations

from typing import Any, Dict

import buyer_identity_resolver
import demand_hunter
import demand_hunter_runtime
import demand_intelligence
import scout_connector
import search_budget_governor


VERSION = "1.0-supreme-demand-autonomy"

# Demand discovery + confirmation share one protected lane. The generic/retail pool was reduced by
# exactly the same amount in search_budget_governor, preserving the original total daily envelope.
demand_hunter.DAILY_QUERY_BUDGET = search_budget_governor.DEMAND_RESERVED
demand_hunter._budget = search_budget_governor.demand_budget
demand_intelligence.DAILY_QUERY_BUDGET = search_budget_governor.DEMAND_RESERVED
demand_intelligence._budget = search_budget_governor.demand_budget
demand_hunter_runtime.DAILY_CAP = search_budget_governor.DEMAND_RESERVED

_BASE_SCOUT_TICK = demand_hunter_runtime._ORIGINAL_SCOUT_TICK
_ORIGINAL_GENERIC_PLAN = scout_connector._generic_search_plan


def _verified_suppliers(state: Dict[str, Any]) -> list[Dict[str, Any]]:
    return [
        x for x in state.get("candidate_accounts", []) or []
        if x.get("type") == "supplier" and x.get("verified_company")
    ]


def _verified_demand_buyers(state: Dict[str, Any]) -> list[Dict[str, Any]]:
    return [
        x for x in state.get("candidate_accounts", []) or []
        if x.get("type") == "buyer" and x.get("verified_company") and x.get("demand_signal")
    ]


def adaptive_search_plan(state: Dict[str, Any]):
    """When supply exists but verified demand does not, spend generic discovery only on buyers.

    This prevents the system from accumulating more suppliers while the monetization bottleneck is
    clearly demand. Once verified demand exists, the original balanced/category-gap strategy returns.
    """
    if _verified_suppliers(state) and not _verified_demand_buyers(state):
        buyer_q = list(scout_connector._buyer_queries(state) or [])
        if buyer_q:
            return "demand_gap_buyer_priority", buyer_q
    return _ORIGINAL_GENERIC_PLAN(state)


scout_connector._generic_search_plan = adaptive_search_plan


def supreme_scout_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    # Normalize both lanes before any engine can spend a search.
    search_budget_governor.general_budget(state)
    demand_budget = search_budget_governor.demand_budget(state)

    if int(demand_budget.get("queries_remaining") or 0) > 0:
        hunter = dict(demand_hunter.demand_hunter_tick(state) or {})
    else:
        hunter = {
            "active": False,
            "mode": "demand_first",
            "queries": 0,
            "signals_found": 0,
            "buyer_leads_created": 0,
            "errors": 0,
            "reason": "demand_reserved_budget_exhausted",
            "budget_remaining": 0,
        }

    # Resolve procurement/portal signals into actual candidate buyer identities before Lead Intelligence
    # runs later in worker.py. This can create research leads but never bypasses company verification.
    resolver = dict(buyer_identity_resolver.resolver_tick(state) or {})

    # Generic Scout uses only the non-demand pool and becomes buyer-only while demand_gap is active.
    base = dict(_BASE_SCOUT_TICK(state) or {})
    budget_report = search_budget_governor.summary(state)

    runtime = {
        "version": VERSION,
        "mode": "demand_first_adaptive",
        "demand_gap": bool(_verified_suppliers(state) and not _verified_demand_buyers(state)),
        "search_strategy": base.get("strategy"),
        "demand_hunter": hunter,
        "buyer_identity_resolver": resolver,
        "budget": budget_report,
        "autonomy_policy": "reallocate_existing_search_budget_to_current_bottleneck_without_outreach_bypass",
        "performance_policy": "demand_first_then_identity_then_generic_buyer_discovery",
        "updated_at": scout_connector.utcnow(),
    }
    state["supreme_autonomy_runtime"] = runtime

    base["demand_hunter"] = hunter
    base["buyer_identity_resolver"] = resolver
    base["search_budget_governor"] = budget_report
    base["supreme_autonomy_version"] = VERSION
    return base


# worker.py imports `scout_tick` only after worker_entry loads this module, so the production cycle
# receives the optimized pipeline without changing its safety ordering.
scout_connector.scout_tick = supreme_scout_tick
