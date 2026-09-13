from __future__ import annotations

import os
from typing import Any, Dict

import app
import buyer_identity_resolver
import demand_hunter
import demand_hunter_runtime
import demand_intelligence
import scout_connector
import search_budget_governor


VERSION = "1.1-supreme-demand-autonomy"

# Demand discovery + confirmation share one protected lane. The generic/retail pool was reduced by
# exactly the same amount in search_budget_governor, preserving the original total daily envelope.
demand_hunter.DAILY_QUERY_BUDGET = search_budget_governor.DEMAND_RESERVED
demand_hunter._budget = search_budget_governor.demand_budget
demand_intelligence.DAILY_QUERY_BUDGET = search_budget_governor.DEMAND_RESERVED
demand_intelligence._budget = search_budget_governor.demand_budget
demand_hunter_runtime.DAILY_CAP = search_budget_governor.DEMAND_RESERVED

_BASE_SCOUT_TICK = demand_hunter_runtime._ORIGINAL_SCOUT_TICK
_ORIGINAL_GENERIC_PLAN = scout_connector._generic_search_plan
_BASE_LOAD_STATE = app.load_state
_BASE_SEED_DEMO = app.seed_demo


def _env_true(name: str, default: str = "false") -> bool:
    return str(os.getenv(name, default)).strip().lower() in {"1", "true", "yes", "on"}


def _purge_demo_commerce(state: Dict[str, Any]) -> Dict[str, int]:
    """Remove only explicitly demo-tagged commerce and objects linked to demo deals.

    Publicly discovered candidate_accounts are intentionally untouched. The cleanup is idempotent so
    every production boot can enforce the same truth boundary without risking real commercial data.
    """
    demo_opportunity_ids = {
        str(x.get("id")) for x in state.get("opportunities", []) or []
        if x.get("id") and str(x.get("source") or "").lower() == "demo"
    }
    demo_deal_ids = {
        str(x.get("id")) for x in state.get("deals", []) or []
        if x.get("id") and (
            str(x.get("source") or "").lower() == "demo"
            or str(x.get("opportunity_id") or "") in demo_opportunity_ids
        )
    }

    removed: Dict[str, int] = {}

    def filter_rows(key: str, predicate) -> None:
        rows = list(state.get(key, []) or [])
        kept = [row for row in rows if not predicate(row)]
        removed[key] = len(rows) - len(kept)
        state[key] = kept

    filter_rows("buyers", lambda x: str(x.get("source") or "").lower() == "demo")
    filter_rows("suppliers", lambda x: str(x.get("source") or "").lower() == "demo")
    filter_rows("opportunities", lambda x: str(x.get("source") or "").lower() == "demo")
    filter_rows(
        "deals",
        lambda x: str(x.get("source") or "").lower() == "demo"
        or str(x.get("id") or "") in demo_deal_ids,
    )
    filter_rows(
        "offers",
        lambda x: str(x.get("source") or "").lower() in {"demo", "demo/simulación"}
        or str(x.get("deal_id") or "") in demo_deal_ids,
    )
    for key in (
        "proposals",
        "negotiations",
        "approvals",
        "transactions",
        "revenue_ledger",
        "outbox",
        "conversations",
        "closing_packs",
    ):
        filter_rows(key, lambda x, ids=demo_deal_ids: str(x.get("deal_id") or "") in ids)

    queue = list(state.get("operating_action_queue", []) or [])
    kept_queue = [
        row for row in queue
        if str(row.get("object_id") or "") not in demo_deal_ids
        and str((row.get("payload") or {}).get("deal_id") or "") not in demo_deal_ids
    ]
    removed["operating_action_queue"] = len(queue) - len(kept_queue)
    state["operating_action_queue"] = kept_queue

    for index_key in ("closing_pack_index", "payment_route_index", "data_truth_index"):
        index = dict(state.get(index_key, {}) or {})
        for deal_id in demo_deal_ids:
            index.pop(deal_id, None)
        state[index_key] = index

    total = sum(removed.values())
    state["production_truth_boundary"] = {
        "demo_seed_enabled": False,
        "demo_records_removed_this_boot": total,
        "removed_by_collection": removed,
        "policy": "production_uses_only_real_or_publicly_discovered_commercial_entities",
    }
    return removed


def production_load_state() -> bool:
    loaded = bool(_BASE_LOAD_STATE())
    if loaded and not _env_true("LUMEN_DEMO_SEED_ENABLED", "false"):
        _purge_demo_commerce(app.STATE)
    return loaded


def production_seed_demo() -> None:
    if _env_true("LUMEN_DEMO_SEED_ENABLED", "false"):
        return _BASE_SEED_DEMO()
    app.STATE["production_truth_boundary"] = {
        **dict(app.STATE.get("production_truth_boundary", {}) or {}),
        "demo_seed_enabled": False,
        "policy": "production_uses_only_real_or_publicly_discovered_commercial_entities",
    }
    return None


# worker.py imports these symbols from app only after worker_entry imports this runtime, so production
# gets a clean real-data boundary without changing the legacy app implementation or its demo capability.
app.load_state = production_load_state
app.seed_demo = production_seed_demo


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
        "truth_policy": "demo_commerce_is_quarantined_from_production",
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
