"""Atomic PostgreSQL-backed search-budget claims for LUMEN.

Loaded before worker/web runtimes. It preserves the existing shared daily cap and
lane allocations, but makes the actual provider-cap reservation transactional so
concurrent processes cannot spend the same remaining slot.

If PostgreSQL is unavailable, claims fail closed: no external search is started.
"""
from __future__ import annotations

import os
import threading
from typing import Any, Dict

import psycopg

import scout_connector
import search_budget_governor as governor

VERSION = "1.0-atomic-search-budget-claims"
DATABASE_URL = os.getenv("DATABASE_URL", "")
_DB_READY = False
_DB_LOCK = threading.Lock()


def _ensure_table() -> bool:
    global _DB_READY
    if not DATABASE_URL:
        return False
    if _DB_READY:
        return True
    with _DB_LOCK:
        if _DB_READY:
            return True
        try:
            with psycopg.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """CREATE TABLE IF NOT EXISTS lumen_search_budget_claims (
                            budget_day DATE PRIMARY KEY,
                            general_used INTEGER NOT NULL DEFAULT 0 CHECK (general_used >= 0),
                            demand_used INTEGER NOT NULL DEFAULT 0 CHECK (demand_used >= 0),
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )"""
                    )
            _DB_READY = True
            return True
        except Exception:
            return False


def _seed_row(state: Dict[str, Any]) -> bool:
    if not _ensure_table():
        return False
    governor.reconcile_legacy_counters(state)
    general_seed = max(0, governor._general_used_today(state))
    demand_seed = max(0, governor._demand_used_today(state))
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO lumen_search_budget_claims
                           (budget_day, general_used, demand_used, updated_at)
                       VALUES (%s, %s, %s, NOW())
                       ON CONFLICT (budget_day) DO NOTHING""",
                    (governor.local_day(), general_seed, demand_seed),
                )
        return True
    except Exception:
        return False


def _mirror(state: Dict[str, Any], general_used: int, demand_used: int) -> None:
    today = governor.local_day()
    general = state.setdefault("scout_budget", {})
    if str(general.get("date") or "") != today:
        general.clear()
    general["date"] = today
    general["timezone"] = governor.TZ_NAME
    general["queries_used"] = max(0, int(general_used))

    demand = state.get("demand_search_budget")
    if not isinstance(demand, dict):
        demand = {}
        state["demand_search_budget"] = demand
    if str(demand.get("date") or "") != today:
        demand.clear()
    demand["date"] = today
    demand["timezone"] = governor.TZ_NAME
    demand["queries_used"] = max(0, int(demand_used))

    governor.general_budget(state)
    governor.demand_budget(state)


def sync_state(state: Dict[str, Any]) -> bool:
    if not _seed_row(state):
        return False
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT general_used, demand_used FROM lumen_search_budget_claims WHERE budget_day=%s",
                    (governor.local_day(),),
                )
                row = cur.fetchone()
        if not row:
            return False
        _mirror(state, int(row[0]), int(row[1]))
        return True
    except Exception:
        return False


def _claim_one(state: Dict[str, Any], lane: str) -> bool:
    if lane not in {"general", "demand"}:
        return False
    if not _seed_row(state):
        return False

    if lane == "general":
        sql = """UPDATE lumen_search_budget_claims
                    SET general_used = general_used + 1, updated_at = NOW()
                  WHERE budget_day = %s
                    AND general_used < %s
                    AND general_used + demand_used < %s
              RETURNING general_used, demand_used"""
        params = (governor.local_day(), governor.GENERAL_POOL_CAP, governor.TOTAL_DAILY_CAP)
    else:
        sql = """UPDATE lumen_search_budget_claims
                    SET demand_used = demand_used + 1, updated_at = NOW()
                  WHERE budget_day = %s
                    AND demand_used < %s
                    AND general_used + demand_used < %s
              RETURNING general_used, demand_used"""
        params = (governor.local_day(), governor.DEMAND_RESERVED, governor.TOTAL_DAILY_CAP)

    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
        if not row:
            sync_state(state)
            return False
        _mirror(state, int(row[0]), int(row[1]))
        return True
    except Exception:
        return False


def reserve_demand_search_atomic(state: Dict[str, Any], wanted: int = 1) -> int:
    try:
        wanted_int = max(0, int(wanted))
    except (TypeError, ValueError):
        wanted_int = 0
    granted = 0
    for _ in range(wanted_int):
        if not _claim_one(state, "demand"):
            break
        granted += 1
    return granted


def scout_tick_atomic(state: Dict[str, Any]) -> Dict[str, Any]:
    state.setdefault("research_leads", [])
    sync_state(state)
    budget = governor.general_budget(state)
    strategy, generic_queue = scout_connector._generic_search_plan(state)
    stats = {
        "configured": bool(scout_connector.PROVIDER and scout_connector.API_KEY),
        "queries": 0,
        "new_leads": 0,
        "errors": 0,
        "demand_queries": 0,
        "demand_signals_verified": 0,
        "buyer_discovery_queries": 0,
        "supplier_discovery_queries": 0,
        "strategy": strategy,
        "budget_used_today": budget["queries_used"],
        "budget_remaining": budget["queries_remaining"],
        "budget_exhausted": False,
        "atomic_budget_claims": True,
    }
    if not stats["configured"]:
        return stats
    if budget["queries_remaining"] <= 0:
        stats["budget_exhausted"] = True
        scout_connector._log(
            state,
            "Scout pausó búsquedas: presupuesto diario agotado; prioriza calificación y seguimiento de evidencia existente.",
        )
        return stats

    allowed = min(scout_connector.MAX_QUERIES_PER_TICK, budget["queries_remaining"])
    used_this_tick = 0

    for account in scout_connector._demand_candidates(state):
        if used_this_tick >= allowed:
            break
        if not _claim_one(state, "general"):
            stats["budget_exhausted"] = True
            break
        used_this_tick += 1
        stats["queries"] += 1
        stats["demand_queries"] += 1
        query = scout_connector._demand_query(account)
        try:
            results = scout_connector.search(query)
            if scout_connector._store_demand_signal(state, account, query, results):
                stats["demand_signals_verified"] += 1
                scout_connector._log(
                    state,
                    f"Demand Signal verificó evidencia pública de intención para {account.get('id')} ({account.get('category')}).",
                )
            else:
                scout_connector._log(
                    state,
                    f"Demand Signal no encontró señal pública fuerte para {account.get('id')}; no se habilita contacto.",
                )
        except Exception as exc:
            stats["errors"] += 1
            scout_connector._log(state, f"Demand Signal falló para {account.get('id')}: {str(exc)[:140]}")

    for query, lead_type, category in generic_queue:
        if used_this_tick >= allowed:
            break
        if not _claim_one(state, "general"):
            stats["budget_exhausted"] = True
            break
        used_this_tick += 1
        stats["queries"] += 1
        if lead_type == "buyer":
            stats["buyer_discovery_queries"] += 1
        else:
            stats["supplier_discovery_queries"] += 1
        try:
            results = scout_connector.search(query)
            created = scout_connector._store_results(state, query, lead_type, category, results)
            stats["new_leads"] += created
            scout_connector._log(
                state,
                f"Scout [{strategy}] investigó {lead_type} para {category}: {created} leads nuevos con evidencia web.",
            )
        except Exception as exc:
            stats["errors"] += 1
            scout_connector._log(state, f"Scout falló al investigar {category}: {str(exc)[:140]}")

    sync_state(state)
    budget = governor.general_budget(state)
    stats["budget_used_today"] = budget["queries_used"]
    stats["budget_remaining"] = budget["queries_remaining"]
    stats["budget_exhausted"] = budget["queries_remaining"] <= 0
    return stats


_original_summary = governor.summary


def summary_atomic(state: Dict[str, Any]) -> Dict[str, Any]:
    sync_state(state)
    out = dict(_original_summary(state) or {})
    out["atomic_claims"] = True
    out["atomic_claims_version"] = VERSION
    return out


# Install before other runtimes import these functions.
governor.reserve_demand_search = reserve_demand_search_atomic
governor.summary = summary_atomic
scout_connector.scout_tick = scout_tick_atomic
