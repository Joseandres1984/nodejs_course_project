from __future__ import annotations

"""Outcome learning for LUMEN net-new external exploration.

Learns which buyer/supplier/store search recipes actually create verified companies,
usable contacts, demand, market opportunities and useful stores. Zero-yield searches
are persisted too, so dead-end recipes lose priority. The policy is bounded
explore/exploit and never changes the shared provider hard cap or commercial authority.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

import external_exploration_runtime as ext
import scout_connector


VERSION = "1.0-external-exploration-yield-learning"
MAX_ATTEMPTS = 600
MIN_ATTEMPTS_FOR_WINNER = 2
ZERO_YIELD_COOLDOWN_HOURS = 18
EXPLORE_EVERY_N_CYCLES = 4

_ORIGINAL_STORE_RESULTS = scout_connector._store_results
_QUERY_META: Dict[str, Dict[str, str]] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_s() -> str:
    return _now().strftime("%Y-%m-%d %H:%M:%S UTC")


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _domain(url: Any) -> str:
    return ext._domain(str(url or ""))


def _provider() -> str:
    return str(getattr(scout_connector, "PROVIDER", "") or "unknown").lower()


def _kind_from_query(query: str, lead_type: str) -> str:
    q = query.lower()
    if any(x in q for x in ("tienda", "mayorista", "ecommerce", "catálogo", "catalogo")):
        return "store_or_distributor"
    return "potential_buyer" if lead_type == "buyer" else "supplier_discovery"


def _geo_from_query(query: str) -> str:
    q = query.lower()
    # Most specific first because several entries contain "Argentina".
    for geo in sorted(ext.GEOGRAPHIES, key=len, reverse=True):
        if geo.lower() in q:
            return geo
    return "Argentina"


def _recipe_key(kind: str, category: str, geography: str) -> str:
    return f"{_provider()}|{_norm(kind)}|{_norm(category)}|{_norm(geography)}"


def _parse_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for candidate in (text, text.replace(" UTC", "+00:00"), text.replace("Z", "+00:00")):
        try:
            dt = datetime.fromisoformat(candidate)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            continue
    return None


def _account_by_lead(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        str(row.get("source_lead_id")): row
        for row in state.get("candidate_accounts", []) or []
        if row.get("source_lead_id")
    }


def _opportunity_accounts(state: Dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for row in state.get("market_opportunities", []) or []:
        for key in ("buyer_account_id", "supplier_account_id"):
            if row.get(key):
                out.add(str(row.get(key)))
    return out


def _store_by_domain(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        str(row.get("domain") or "").lower().removeprefix("www."): row
        for row in state.get("partner_stores", []) or []
        if row.get("domain")
    }


def _evaluate_attempt(state: Dict[str, Any], attempt: Dict[str, Any]) -> Dict[str, int]:
    leads = {str(row.get("id")): row for row in state.get("research_leads", []) or [] if row.get("id")}
    accounts = _account_by_lead(state)
    opp_accounts = _opportunity_accounts(state)
    stores = _store_by_domain(state)
    verified = contacts = demand = opportunities = mapped_stores = active_partners = 0

    for lead_id in attempt.get("lead_ids", []) or []:
        lead = leads.get(str(lead_id)) or {}
        account = accounts.get(str(lead_id)) or {}
        if account.get("verified_company"):
            verified += 1
        if account.get("verified_contact") or account.get("commercial_channel_verified"):
            contacts += 1
        if account.get("demand_signal"):
            demand += 1
        if account.get("id") and str(account.get("id")) in opp_accounts:
            opportunities += 1
        domain = str(lead.get("domain") or account.get("domain") or _domain(lead.get("url"))).lower().removeprefix("www.")
        store = stores.get(domain) or {}
        if store:
            mapped_stores += 1
        if store.get("commercial_status") == "active_partner":
            active_partners += 1

    return {
        "verified_companies": verified,
        "usable_contacts": contacts,
        "demand_signals": demand,
        "opportunities": opportunities,
        "mapped_stores": mapped_stores,
        "active_partners": active_partners,
    }


def _report(state: Dict[str, Any]) -> Dict[str, Any]:
    attempts = list(state.get("external_exploration_attempts", []) or [])[-MAX_ATTEMPTS:]
    grouped: Dict[str, Dict[str, Any]] = {}
    for row in attempts:
        if not isinstance(row, dict):
            continue
        outcome = _evaluate_attempt(state, row)
        row["outcome"] = outcome
        key = str(row.get("recipe_key") or "")
        if not key:
            continue
        g = grouped.setdefault(key, {
            "recipe_key": key,
            "provider": row.get("provider"),
            "kind": row.get("kind"),
            "category": row.get("category"),
            "geography": row.get("geography"),
            "attempts": 0,
            "new_domains": 0,
            "verified_companies": 0,
            "usable_contacts": 0,
            "demand_signals": 0,
            "opportunities": 0,
            "mapped_stores": 0,
            "active_partners": 0,
            "zero_yield_attempts": 0,
            "last_attempt_at": None,
        })
        g["attempts"] += 1
        new_domains = int(row.get("new_domains") or 0)
        g["new_domains"] += new_domains
        if new_domains == 0:
            g["zero_yield_attempts"] += 1
        for field in ("verified_companies", "usable_contacts", "demand_signals", "opportunities", "mapped_stores", "active_partners"):
            g[field] += int(outcome.get(field) or 0)
        g["last_attempt_at"] = row.get("created_at")

    for g in grouped.values():
        attempts_n = max(1, int(g["attempts"]))
        # Downstream commercial proof dominates raw discovery volume.
        points = (
            g["new_domains"] * 1.0
            + g["verified_companies"] * 7.0
            + g["usable_contacts"] * 7.0
            + g["demand_signals"] * 10.0
            + g["opportunities"] * 18.0
            + g["mapped_stores"] * 3.0
            + g["active_partners"] * 30.0
        )
        g["avg_yield_score"] = round(points / attempts_n, 2)
        g["verification_rate"] = round(g["verified_companies"] / max(1, g["new_domains"]), 3)
        g["winner_eligible"] = bool(
            g["attempts"] >= MIN_ATTEMPTS_FOR_WINNER
            and (g["verified_companies"] >= 2 or g["usable_contacts"] >= 2 or g["opportunities"] >= 1 or g["active_partners"] >= 1)
        )

    by_kind: Dict[str, List[Dict[str, Any]]] = {}
    for g in grouped.values():
        by_kind.setdefault(str(g.get("kind") or "unknown"), []).append(g)
    winners = {}
    for kind, rows in by_kind.items():
        eligible = [x for x in rows if x.get("winner_eligible")]
        if eligible:
            winners[kind] = max(eligible, key=lambda x: (float(x.get("avg_yield_score") or 0), int(x.get("opportunities") or 0), int(x.get("verified_companies") or 0)))["recipe_key"]

    source_stats: Dict[str, Dict[str, int]] = {}
    for row in attempts:
        provider = str(row.get("provider") or "unknown")
        s = source_stats.setdefault(provider, {"attempts": 0, "new_domains": 0})
        s["attempts"] += 1
        s["new_domains"] += int(row.get("new_domains") or 0)

    report = {
        "version": VERSION,
        "status": "learning" if attempts else "cold_start",
        "attempts_total": len(attempts),
        "recipe_stats": grouped,
        "winner_by_kind": winners,
        "source_stats": source_stats,
        "policy": {
            "mode": "bounded_explore_exploit",
            "explore_every_n_cycles": EXPLORE_EVERY_N_CYCLES,
            "winner_min_attempts": MIN_ATTEMPTS_FOR_WINNER,
            "zero_yield_cooldown_hours": ZERO_YIELD_COOLDOWN_HOURS,
            "objective": "verified_company_contact_demand_opportunity_store_yield",
            "provider_cap_unchanged": True,
        },
        "updated_at": _now_s(),
    }
    state["external_exploration_learning"] = report
    state["external_exploration_attempts"] = attempts
    return report


def _recent_zero_yield(stat: Dict[str, Any]) -> bool:
    if not stat or int(stat.get("attempts") or 0) == 0:
        return False
    last = _parse_ts(stat.get("last_attempt_at"))
    if not last or _now() - last > timedelta(hours=ZERO_YIELD_COOLDOWN_HOURS):
        return False
    return int(stat.get("zero_yield_attempts") or 0) >= int(stat.get("attempts") or 0) and int(stat.get("new_domains") or 0) == 0


def _candidate_recipe(kind: str, category: str, geography: str) -> Dict[str, str]:
    return {
        "kind": kind,
        "category": category,
        "geography": geography,
        "recipe_key": _recipe_key(kind, category, geography),
    }


def _pick_recipe(state: Dict[str, Any], kind: str, categories: List[str], cycle_index: int) -> Dict[str, str]:
    report = _report(state)
    stats = report.get("recipe_stats", {}) or {}
    candidates = [
        _candidate_recipe(kind, category, geography)
        for category in categories[:12]
        for geography in ext.GEOGRAPHIES
    ]
    viable = [x for x in candidates if not _recent_zero_yield(stats.get(x["recipe_key"], {}) or {})] or candidates
    winner_key = (report.get("winner_by_kind", {}) or {}).get(kind)
    exploit = bool(winner_key) and cycle_index % EXPLORE_EVERY_N_CYCLES != 0
    if exploit:
        winner = next((x for x in viable if x["recipe_key"] == winner_key), None)
        if winner:
            winner["selection"] = "exploit_verified_yield_winner"
            return winner

    # Exploration chooses the least-tested recipe, then the one with the strongest observed yield.
    viable.sort(key=lambda x: (
        int((stats.get(x["recipe_key"], {}) or {}).get("attempts") or 0),
        -float((stats.get(x["recipe_key"], {}) or {}).get("avg_yield_score") or 0),
        x["recipe_key"],
    ))
    chosen = viable[cycle_index % max(1, min(len(viable), 12))] if viable else _candidate_recipe(kind, categories[0], ext.GEOGRAPHIES[0])
    chosen["selection"] = "explore_under_sampled_recipe"
    return chosen


def _adaptive_query_triplet(state: Dict[str, Any]) -> List[Tuple[str, str, str]]:
    categories = ext._categories(state) or list(ext.SEED_CATEGORIES)
    cycle_index = ext._rotation_index(state)
    buyer = _pick_recipe(state, "potential_buyer", categories, cycle_index)
    supplier = _pick_recipe(state, "supplier_discovery", categories, cycle_index + 1)
    store = _pick_recipe(state, "store_or_distributor", categories, cycle_index + 2)

    buyer_angle = ext.BUYER_ANGLES[cycle_index % len(ext.BUYER_ANGLES)]
    supplier_angle = ext.SUPPLIER_ANGLES[cycle_index % len(ext.SUPPLIER_ANGLES)]
    store_angle = ext.STORE_ANGLES[cycle_index % len(ext.STORE_ANGLES)]

    rows: List[Tuple[str, str, str]] = []
    definitions = [
        (buyer, "buyer", buyer_angle, "buyer"),
        (supplier, "supplier", supplier_angle, "supplier"),
        (store, "supplier", store_angle, "store"),
    ]
    for recipe, lead_type, angle, mode in definitions:
        category, geo = recipe["category"], recipe["geography"]
        angle_or = angle.replace(" ", " OR ")
        if mode == "buyer":
            query = f'"{category}" (empresa OR industria OR planta OR fábrica OR fabrica) ({angle_or}) {geo} -proveedor -distribuidor{ext.NEGATIVE}'
        else:
            query = f'"{category}" ({angle_or}) {geo}{ext.NEGATIVE}'
        _QUERY_META[query] = {**recipe, "provider": _provider(), "angle": angle}
        rows.append((query, lead_type, category))

    state["external_exploration_learning_selection"] = {
        "version": VERSION,
        "buyer": buyer,
        "supplier": supplier,
        "store": store,
        "cycle_index": cycle_index,
        "updated_at": _now_s(),
    }
    return rows


def _store_results_learning(state: Dict[str, Any], query: str, lead_type: str, category: str, results: List[Dict[str, str]]) -> int:
    before = {str(row.get("id")) for row in state.get("research_leads", []) or [] if row.get("id")}
    created = _ORIGINAL_STORE_RESULTS(state, query, lead_type, category, results)
    new_rows = [
        row for row in state.get("research_leads", []) or []
        if row.get("id") and str(row.get("id")) not in before
    ]
    meta = dict(_QUERY_META.get(query) or {})
    kind = str(meta.get("kind") or _kind_from_query(query, lead_type))
    geography = str(meta.get("geography") or _geo_from_query(query))
    recipe_key = str(meta.get("recipe_key") or _recipe_key(kind, category, geography))
    provider = str(meta.get("provider") or _provider())

    for lead in new_rows:
        lead["exploration_recipe_key"] = recipe_key
        lead["exploration_geography"] = geography
        lead["exploration_provider"] = provider
        lead["growth_hypothesis_key"] = recipe_key
        lead["growth_market"] = geography

    attempts = state.setdefault("external_exploration_attempts", [])
    attempts.append({
        "id": f"XEA-{len(attempts)+1:06d}",
        "created_at": _now_s(),
        "provider": provider,
        "kind": kind,
        "category": category,
        "geography": geography,
        "recipe_key": recipe_key,
        "selection": meta.get("selection"),
        "query": query,
        "result_count": len(results or []),
        "new_domains": int(created),
        "lead_ids": [str(row.get("id")) for row in new_rows],
    })
    state["external_exploration_attempts"] = attempts[-MAX_ATTEMPTS:]
    _report(state)
    return created


# Patch the dynamic recipe builder used by external_exploration_runtime's general search plan.
ext._query_triplet = _adaptive_query_triplet
# Wrap the already-installed net-new storage function so zero-yield attempts and downstream lineage persist.
scout_connector._store_results = _store_results_learning

print({
    "external_exploration_learning_runtime": {
        "version": VERSION,
        "status": "active",
        "learns_from": ["new_domains", "verified_companies", "usable_contacts", "demand", "opportunities", "mapped_stores", "active_partners"],
        "zero_yield_memory": True,
        "policy": "bounded_explore_exploit",
        "provider_cap_unchanged": True,
    }
}, flush=True)
