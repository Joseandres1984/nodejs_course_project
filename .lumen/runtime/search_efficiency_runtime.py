from __future__ import annotations

"""Persistent search-result reuse for LUMEN's elastic agent fleet.

This runtime keeps a bounded cache inside the already-persisted LUMEN state. Exact normalized
queries can reuse previously collected public search results without claiming another provider
slot. Fresh live searches still use the existing PostgreSQL-backed atomic budget claim, so the
shared daily hard cap remains authoritative.

The cache also keeps all provider results (up to eight) even though the normal lead promotion
limit remains unchanged. Replaying a cached result set lets later cycles process additional unseen
URLs without another provider query.
"""

import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Tuple

import agent_fleet
import search_budget_atomic_runtime as atomic_budget


VERSION = "1.0-persistent-search-reuse"
CACHE_KEY = "web_search_cache"
MAX_ENTRIES = max(40, min(400, int(os.getenv("LUMEN_SEARCH_CACHE_MAX_ENTRIES", "160"))))
DEFAULT_TTL_HOURS = max(24, min(24 * 30, int(os.getenv("LUMEN_SEARCH_CACHE_DEFAULT_TTL_HOURS", "240"))))
FRESH_TTL_HOURS = max(6, min(72, int(os.getenv("LUMEN_SEARCH_CACHE_FRESH_TTL_HOURS", "24"))))
RETAIL_TTL_HOURS = max(12, min(168, int(os.getenv("LUMEN_SEARCH_CACHE_RETAIL_TTL_HOURS", "72"))))

_FRESH_TERMS = (
    "licitacion", "licitación", "cotizacion", "cotización", "pliego", "tender", "procurement",
    "solicitud de oferta", "concurso de precios", "compras", "abastecimiento",
)
_RETAIL_FRESH_TERMS = ("precio", "stock", "comprar", "oferta", "tienda online")


def _normalize_query(query: Any) -> str:
    return " ".join(str(query or "").strip().lower().split())


def _cache_id(query: str) -> str:
    provider = str(agent_fleet.scout_connector.PROVIDER or "").strip().lower()
    country = str(agent_fleet.scout_connector.COUNTRY_CODE or "").strip().lower()
    language = str(agent_fleet.scout_connector.LANGUAGE or "").strip().lower()
    raw = f"{provider}|{country}|{language}|{_normalize_query(query)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _ttl_seconds(query: str) -> int:
    q = _normalize_query(query)
    if any(term in q for term in _FRESH_TERMS):
        return FRESH_TTL_HOURS * 3600
    if any(term in q for term in _RETAIL_FRESH_TERMS):
        return RETAIL_TTL_HOURS * 3600
    return DEFAULT_TTL_HOURS * 3600


def _cache_container(state: Dict[str, Any]) -> Dict[str, Any]:
    raw = state.get(CACHE_KEY)
    if not isinstance(raw, dict):
        raw = {}
        state[CACHE_KEY] = raw
    raw.setdefault("version", VERSION)
    raw.setdefault("entries", {})
    if not isinstance(raw.get("entries"), dict):
        raw["entries"] = {}
    return raw


def _prune(state: Dict[str, Any]) -> Dict[str, Any]:
    cache = _cache_container(state)
    entries = cache["entries"]
    now = time.time()
    max_age = max(DEFAULT_TTL_HOURS, FRESH_TTL_HOURS, RETAIL_TTL_HOURS) * 3600

    stale = []
    for key, row in list(entries.items()):
        if not isinstance(row, dict):
            stale.append(key)
            continue
        try:
            fetched_at = float(row.get("fetched_at_epoch") or 0)
        except (TypeError, ValueError):
            fetched_at = 0
        if fetched_at <= 0 or now - fetched_at > max_age:
            stale.append(key)
    for key in stale:
        entries.pop(key, None)

    if len(entries) > MAX_ENTRIES:
        ordered = sorted(
            entries.items(),
            key=lambda item: float((item[1] or {}).get("last_used_epoch") or (item[1] or {}).get("fetched_at_epoch") or 0),
        )
        for key, _ in ordered[: max(0, len(entries) - MAX_ENTRIES)]:
            entries.pop(key, None)

    cache["entries_total"] = len(entries)
    cache["max_entries"] = MAX_ENTRIES
    cache["default_ttl_hours"] = DEFAULT_TTL_HOURS
    cache["fresh_ttl_hours"] = FRESH_TTL_HOURS
    cache["retail_ttl_hours"] = RETAIL_TTL_HOURS
    cache["expired_pruned_last_run"] = len(stale)
    return cache


def _lookup(state: Dict[str, Any], query: str) -> Tuple[bool, List[Dict[str, str]]]:
    cache = _prune(state)
    row = cache["entries"].get(_cache_id(query))
    if not isinstance(row, dict):
        return False, []
    try:
        fetched_at = float(row.get("fetched_at_epoch") or 0)
    except (TypeError, ValueError):
        fetched_at = 0
    if fetched_at <= 0 or time.time() - fetched_at > _ttl_seconds(query):
        return False, []
    row["hits"] = int(row.get("hits") or 0) + 1
    row["last_used_epoch"] = time.time()
    results = row.get("results")
    if not isinstance(results, list):
        results = []
    return True, [dict(x) for x in results if isinstance(x, dict)][:8]


def _store(state: Dict[str, Any], query: str, results: List[Dict[str, Any]]) -> None:
    cache = _prune(state)
    now = time.time()
    compact: List[Dict[str, str]] = []
    for item in list(results or [])[:8]:
        if not isinstance(item, dict):
            continue
        compact.append({
            "title": str(item.get("title") or "")[:300],
            "url": str(item.get("url") or "")[:1200],
            "snippet": str(item.get("snippet") or "")[:500],
        })
    key = _cache_id(query)
    previous = cache["entries"].get(key) or {}
    cache["entries"][key] = {
        "query": str(query or "")[:1200],
        "normalized_query": _normalize_query(query)[:1200],
        "provider": str(agent_fleet.scout_connector.PROVIDER or ""),
        "fetched_at_epoch": now,
        "last_used_epoch": now,
        "hits": int(previous.get("hits") or 0),
        "result_count": len(compact),
        "results": compact,
    }
    cache["entries_total"] = len(cache["entries"])


def _execute_assignment(assignment: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    if assignment.get("cached"):
        return {
            "agent_id": assignment["agent_id"],
            "role": assignment["role"],
            "kind": "web_search",
            "category": assignment.get("category"),
            "query": assignment.get("query"),
            "ok": True,
            "cached": True,
            "finding": f"Memoria de búsqueda reutilizada para {assignment.get('category') or 'foco comercial'}.",
            "results": list(assignment.get("cached_results") or [])[:8],
        }
    return dict(agent_fleet._execute(assignment, ctx) or {})


def run_agent_fleet_cycle_cached(state: Dict[str, Any]) -> Dict[str, Any]:
    started = agent_fleet.utcnow()
    roster = agent_fleet.build_roster()
    ctx = agent_fleet._context(state)
    scout_status = agent_fleet.scout_connector.status()

    # Synchronize persisted counters first. If DB is unavailable, live claims fail closed, while
    # cached evidence can still be processed locally without provider usage.
    atomic_budget.sync_state(state)
    budget_before = dict(agent_fleet._budget(state))

    desired_slots = max(0, min(int(agent_fleet.SEARCHES_PER_CYCLE), len(roster))) if scout_status.get("configured") else 0
    candidates = agent_fleet._select_search_agents(roster, ctx, desired_slots)

    selected: List[Dict[str, Any]] = []
    cache_hits = 0
    live_claims = 0
    cache_results_processed = 0

    for candidate in candidates:
        query = str(candidate.get("query") or "")
        hit, cached_results = _lookup(state, query)
        if hit:
            selected.append({**candidate, "cached": True, "cached_results": cached_results})
            cache_hits += 1
            cache_results_processed += len(cached_results)
            continue

        # Only a real provider miss claims one atomic general-search slot.
        if atomic_budget._claim_one(state, "general"):
            selected.append({**candidate, "cached": False})
            live_claims += 1

    selected_by_id = {x["id"]: x for x in selected}
    assignments: List[Dict[str, Any]] = []
    for agent in roster:
        selected_row = selected_by_id.get(agent["id"])
        if selected_row:
            assignment = {
                "agent_id": agent["id"],
                "role": agent["role"],
                "title": agent["title"],
                "kind": "web_search",
                "category": selected_row.get("category"),
                "query": selected_row.get("query"),
                "cached": bool(selected_row.get("cached")),
            }
            if selected_row.get("cached"):
                assignment["cached_results"] = list(selected_row.get("cached_results") or [])[:8]
            assignments.append(assignment)
        else:
            assignments.append({
                "agent_id": agent["id"],
                "role": agent["role"],
                "title": agent["title"],
                "kind": "analysis",
            })

    results: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(agent_fleet.MAX_PARALLEL, len(assignments))) as pool:
        futures = {pool.submit(_execute_assignment, assignment, ctx): assignment for assignment in assignments}
        for future in as_completed(futures):
            assignment = futures[future]
            try:
                results.append(dict(future.result() or {}))
            except Exception as exc:
                results.append({
                    "agent_id": assignment["agent_id"],
                    "role": assignment["role"],
                    "kind": assignment["kind"],
                    "ok": False,
                    "cached": bool(assignment.get("cached")),
                    "finding": f"Agente falló: {type(exc).__name__}: {str(exc)[:160]}",
                    "results": [],
                })

    # Save every live provider result, including zero-result searches. This prevents repeatedly
    # paying for known-zero queries during their TTL window.
    for result in results:
        if result.get("kind") == "web_search" and result.get("ok") and not result.get("cached"):
            _store(state, str(result.get("query") or ""), list(result.get("results") or [])[:8])

    new_leads = 0
    market_signals = 0
    for result in results:
        if result.get("kind") == "web_search" and result.get("ok"):
            merged = agent_fleet._merge_search_results(state, result)
            new_leads += int(merged.get("leads") or 0)
            market_signals += int(merged.get("signals") or 0)

    by_role: Dict[str, Dict[str, int]] = {}
    for agent in roster:
        row = by_role.setdefault(agent["role"], {"recruited": 0, "assignments": 0, "web_searches": 0, "cache_hits": 0, "errors": 0})
        row["recruited"] += 1
        row["assignments"] += 1
    for result in results:
        row = by_role.setdefault(result.get("role") or "unknown", {"recruited": 0, "assignments": 0, "web_searches": 0, "cache_hits": 0, "errors": 0})
        if result.get("kind") == "web_search":
            if result.get("cached"):
                row["cache_hits"] += 1
            else:
                row["web_searches"] += 1
        if not result.get("ok"):
            row["errors"] += 1

    findings: List[str] = []
    seen: set[str] = set()
    for result in sorted(results, key=lambda x: (x.get("kind") != "web_search", x.get("agent_id") or "")):
        finding = agent_fleet._clean(result.get("finding"))
        if finding and finding not in seen:
            seen.add(finding)
            findings.append(finding)
        if len(findings) >= 12:
            break

    budget_after = dict(agent_fleet._budget(state))
    errors = sum(1 for x in results if not x.get("ok"))
    cache = _prune(state)
    report = {
        "version": VERSION,
        "started_at": started,
        "completed_at": agent_fleet.utcnow(),
        "company_cycle": int(state.get("ticks") or 0),
        "status": "healthy" if errors == 0 else "degraded",
        "fleet_size": len(roster),
        "max_parallel": agent_fleet.MAX_PARALLEL,
        "assignments_created": len(assignments),
        "assignments_completed": len(results),
        # Preserve historical meaning: web_searches means real provider calls / charged slots.
        "web_searches": live_claims,
        "provider_searches": live_claims,
        "search_cache_hits": cache_hits,
        "searches_avoided": cache_hits,
        "cached_results_processed": cache_results_processed,
        "search_candidates": len(candidates),
        "cache_entries": int(cache.get("entries_total") or 0),
        "new_research_leads": new_leads,
        "new_market_signals": market_signals,
        "errors": errors,
        "bottleneck": ctx["bottleneck"],
        "search_provider_configured": bool(scout_status.get("configured")),
        "search_budget_before_general": int(budget_before.get("general_queries_remaining") or 0),
        "search_budget_after_general": int(budget_after.get("general_queries_remaining") or 0),
        "search_budget_total_remaining": int(budget_after.get("queries_remaining_total") or 0),
        "retail_reserved_remaining": int(budget_after.get("retail_reserved_remaining") or 0),
        "by_role": by_role,
        "top_findings": findings,
        "autonomy_boundary": "nonbinding research, analysis and commercial preparation only",
        "search_efficiency": {
            "version": VERSION,
            "persistent_cache": True,
            "cache_entries": int(cache.get("entries_total") or 0),
            "cache_hits_this_cycle": cache_hits,
            "provider_searches_this_cycle": live_claims,
            "searches_avoided_this_cycle": cache_hits,
            "result_retention_per_query": 8,
            "lead_promotion_limits_unchanged": True,
            "daily_provider_cap_unchanged": True,
            "paid_spend_authority_changed": False,
        },
    }

    workforce = state.setdefault("agent_workforce", {})
    workforce["version"] = VERSION
    workforce["roster"] = roster
    workforce["roster_count"] = len(roster)
    workforce["last_cycle"] = report
    workforce["last_results"] = [
        {k: row.get(k) for k in ("agent_id", "role", "kind", "ok", "cached", "category", "finding") if row.get(k) is not None}
        for row in sorted(results, key=lambda x: x.get("agent_id") or "")
    ][:len(roster)]
    history = list(workforce.get("recent_cycles", []) or [])
    history.append({k: report.get(k) for k in (
        "completed_at", "company_cycle", "status", "fleet_size", "assignments_completed", "web_searches",
        "provider_searches", "search_cache_hits", "searches_avoided", "cache_entries",
        "new_research_leads", "new_market_signals", "errors", "bottleneck",
    )})
    workforce["recent_cycles"] = history[-24:]

    state.setdefault("activity", []).insert(0, {
        "ts": agent_fleet.utcnow(),
        "msg": (
            f"Workforce digital: {len(roster)} agentes completaron {len(results)} asignaciones; "
            f"{live_claims} búsquedas proveedor y {cache_hits} reutilizadas desde memoria "
            f"({new_leads} leads, {market_signals} señales)."
        ),
    })
    state["activity"] = state["activity"][:100]
    return report


# Install as a runtime patch. Elastic Agent Fleet delegates to this function, so one patch covers the
# whole elastic workforce while preserving its sizing and role-allocation logic.
agent_fleet.run_agent_fleet_cycle = run_agent_fleet_cycle_cached

print({
    "search_efficiency_runtime": {
        "version": VERSION,
        "status": "active",
        "scope": "elastic_agent_fleet",
        "persistent_cache": True,
        "cache_max_entries": MAX_ENTRIES,
        "default_ttl_hours": DEFAULT_TTL_HOURS,
        "fresh_ttl_hours": FRESH_TTL_HOURS,
        "retail_ttl_hours": RETAIL_TTL_HOURS,
        "daily_provider_cap_unchanged": True,
        "production_authority_changed": False,
    }
}, flush=True)
