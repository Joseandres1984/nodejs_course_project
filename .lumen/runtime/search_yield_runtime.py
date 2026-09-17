from __future__ import annotations

"""Increase value extracted from each already-authorized provider search.

This runtime does not create searches and does not widen the shared daily provider cap. It lets the
existing agent-fleet merge keep up to four useful URLs from one result page (instead of the older
small default) while preserving all normal company/contact/demand verification gates. It also keeps
bounded persistent yield memory so later allocation can distinguish productive searches from
repeated zero-yield patterns.
"""

import hashlib
import os
from typing import Any, Dict

import agent_fleet


VERSION = "1.0-search-yield-memory"
PROMOTION_LIMIT = max(2, min(5, int(os.getenv("LUMEN_SEARCH_PROMOTIONS_PER_QUERY", "4"))))
MAX_MEMORY_ENTRIES = max(40, min(400, int(os.getenv("LUMEN_SEARCH_YIELD_MAX_ENTRIES", "200"))))

_ORIGINAL_MERGE = agent_fleet._merge_search_results


def _clean(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _key(result: Dict[str, Any]) -> str:
    raw = "|".join([
        _clean(result.get("role")),
        _clean(result.get("category")),
        _clean(result.get("query")),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _memory(state: Dict[str, Any]) -> Dict[str, Any]:
    memory = state.get("search_yield_memory")
    if not isinstance(memory, dict):
        memory = {}
        state["search_yield_memory"] = memory
    memory["version"] = VERSION
    entries = memory.get("entries")
    if not isinstance(entries, dict):
        entries = {}
        memory["entries"] = entries
    return memory


def _prune(memory: Dict[str, Any]) -> None:
    entries = memory.get("entries") or {}
    if len(entries) <= MAX_MEMORY_ENTRIES:
        return
    ordered = sorted(
        entries.items(),
        key=lambda item: int((item[1] or {}).get("last_cycle") or 0),
    )
    for key, _ in ordered[: max(0, len(entries) - MAX_MEMORY_ENTRIES)]:
        entries.pop(key, None)


def _merge_with_yield_memory(state: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, int]:
    # Merge remains sequential in the fleet cycle. Temporarily increasing the per-result promotion
    # ceiling therefore does not affect concurrent provider calls and never changes verification.
    previous_limit = int(agent_fleet.MAX_LEADS_PER_SEARCH)
    try:
        agent_fleet.MAX_LEADS_PER_SEARCH = max(previous_limit, PROMOTION_LIMIT)
        merged = dict(_ORIGINAL_MERGE(state, result) or {})
    finally:
        agent_fleet.MAX_LEADS_PER_SEARCH = previous_limit

    memory = _memory(state)
    entries = memory["entries"]
    key = _key(result)
    row = entries.get(key)
    if not isinstance(row, dict):
        row = {
            "role": _clean(result.get("role")),
            "category": str(result.get("category") or "")[:240],
            "query": str(result.get("query") or "")[:1200],
            "provider_calls": 0,
            "cache_replays": 0,
            "runs": 0,
            "productive_runs": 0,
            "zero_yield_runs": 0,
            "leads_promoted": 0,
            "signals_promoted": 0,
            "provider_results_seen": 0,
        }
        entries[key] = row

    leads = int(merged.get("leads") or 0)
    signals = int(merged.get("signals") or 0)
    promoted = leads + signals
    seen = len(list(result.get("results") or []))
    row["runs"] = int(row.get("runs") or 0) + 1
    row["provider_results_seen"] = int(row.get("provider_results_seen") or 0) + seen
    row["leads_promoted"] = int(row.get("leads_promoted") or 0) + leads
    row["signals_promoted"] = int(row.get("signals_promoted") or 0) + signals
    if result.get("cached"):
        row["cache_replays"] = int(row.get("cache_replays") or 0) + 1
    else:
        row["provider_calls"] = int(row.get("provider_calls") or 0) + 1
    if promoted > 0:
        row["productive_runs"] = int(row.get("productive_runs") or 0) + 1
    else:
        row["zero_yield_runs"] = int(row.get("zero_yield_runs") or 0) + 1
    row["last_cycle"] = int(state.get("ticks") or 0)
    row["last_promoted"] = promoted

    provider_calls = max(1, int(row.get("provider_calls") or 0))
    row["promotions_per_provider_call"] = round(
        (int(row.get("leads_promoted") or 0) + int(row.get("signals_promoted") or 0)) / provider_calls,
        3,
    )

    _prune(memory)
    all_rows = list((memory.get("entries") or {}).values())
    memory["entries_total"] = len(all_rows)
    memory["promotion_limit_per_query"] = PROMOTION_LIMIT
    memory["provider_calls_observed"] = sum(int(x.get("provider_calls") or 0) for x in all_rows)
    memory["cache_replays_observed"] = sum(int(x.get("cache_replays") or 0) for x in all_rows)
    memory["leads_promoted"] = sum(int(x.get("leads_promoted") or 0) for x in all_rows)
    memory["signals_promoted"] = sum(int(x.get("signals_promoted") or 0) for x in all_rows)
    memory["productive_patterns"] = sum(1 for x in all_rows if int(x.get("productive_runs") or 0) > 0)
    memory["zero_yield_patterns"] = sum(
        1 for x in all_rows
        if int(x.get("provider_calls") or 0) > 0 and int(x.get("productive_runs") or 0) == 0
    )
    memory["daily_provider_cap_unchanged"] = True
    memory["verification_gates_unchanged"] = True
    return merged


agent_fleet._merge_search_results = _merge_with_yield_memory

print({
    "search_yield_runtime": {
        "version": VERSION,
        "status": "active",
        "promotion_limit_per_query": PROMOTION_LIMIT,
        "persistent_yield_memory": True,
        "daily_provider_cap_unchanged": True,
        "verification_gates_unchanged": True,
        "paid_spend_authority_changed": False,
    }
}, flush=True)
