from __future__ import annotations

"""Net-new external exploration portfolio for LUMEN.

Reserves Scout's general lane for discovering new companies rather than re-running
buyer demand checks that already have dedicated demand/procurement modules. Each
Scout cycle starts with a balanced portfolio: one potential buyer, one supplier,
and one store/distributor query. Queries rotate category, commercial angle and
Argentine geography. Result storage prefers unique company domains over multiple
pages from the same company.

This runtime does not increase the shared provider budget and does not expand any
commercial authority. It only changes how already-authorized public search capacity
is spent.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple
import urllib.parse

import scout_connector


VERSION = "1.0-net-new-external-exploration"

_ORIGINAL_STORE_RESULTS = scout_connector._store_results

SEED_CATEGORIES = [
    "instrumentación industrial",
    "materiales eléctricos",
    "automatización industrial",
    "ferretería industrial",
    "bombas y válvulas",
    "motores industriales",
    "medición y control",
    "mantenimiento industrial",
]

GEOGRAPHIES = [
    "Argentina",
    "Buenos Aires Argentina",
    "Córdoba Argentina",
    "Santa Fe Argentina",
    "Mendoza Argentina",
    "Rosario Argentina",
]

BUYER_ANGLES = [
    "compras abastecimiento mantenimiento",
    "planta producción ingeniería",
    "industria mantenimiento compras",
    "proyectos ingeniería abastecimiento",
]

SUPPLIER_ANGLES = [
    "fabricante distribuidor proveedor",
    "importador representante distribuidor",
    "proveedor industrial stock catálogo",
    "fabricante mayorista distribuidor",
]

STORE_ANGLES = [
    'mayorista distribuidor "tienda online"',
    'distribuidor catálogo stock tienda',
    'ecommerce industrial mayorista distribuidor',
    'tienda técnica catálogo productos',
]

NEGATIVE = " -linkedin -facebook -instagram -youtube -wikipedia -indeed -glassdoor -pinterest -mercadolibre"


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _domain(url: str) -> str:
    try:
        return (urllib.parse.urlparse(str(url or "")).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _unique(values: List[Any]) -> List[str]:
    out: List[str] = []
    seen = set()
    for value in values:
        text = " ".join(str(value or "").strip().split())
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            out.append(text)
    return out


def _categories(state: Dict[str, Any]) -> List[str]:
    verified = [
        row.get("category")
        for row in state.get("candidate_accounts", []) or []
        if row.get("verified_company") and row.get("category")
    ]
    opportunities = [
        row.get("category")
        for row in state.get("market_opportunities", []) or []
        if row.get("category")
    ]
    leads = [
        row.get("category")
        for row in (state.get("research_leads", []) or [])[-120:]
        if row.get("category")
    ]
    return _unique(verified + opportunities + leads + SEED_CATEGORIES)[:24]


def _rotation_index(state: Dict[str, Any]) -> int:
    budget = state.get("scout_budget", {}) or {}
    used = int(budget.get("queries_used") or 0)
    per_tick = max(1, int(getattr(scout_connector, "MAX_QUERIES_PER_TICK", 3) or 3))
    return used // per_tick


def _query_triplet(state: Dict[str, Any]) -> List[Tuple[str, str, str]]:
    categories = _categories(state) or list(SEED_CATEGORIES)
    idx = _rotation_index(state)
    # Use three different category offsets so the same cycle spreads across the market.
    buyer_cat = categories[idx % len(categories)]
    supplier_cat = categories[(idx + 5) % len(categories)]
    store_cat = categories[(idx + 11) % len(categories)]
    geo = GEOGRAPHIES[idx % len(GEOGRAPHIES)]
    buyer_angle = BUYER_ANGLES[idx % len(BUYER_ANGLES)]
    supplier_angle = SUPPLIER_ANGLES[idx % len(SUPPLIER_ANGLES)]
    store_angle = STORE_ANGLES[idx % len(STORE_ANGLES)]

    buyer = (
        f'"{buyer_cat}" (empresa OR industria OR planta OR fábrica OR fabrica) '
        f'({buyer_angle.replace(" ", " OR ")}) {geo} -proveedor -distribuidor{NEGATIVE}',
        "buyer",
        buyer_cat,
    )
    supplier = (
        f'"{supplier_cat}" ({supplier_angle.replace(" ", " OR ")}) {geo}{NEGATIVE}',
        "supplier",
        supplier_cat,
    )
    store = (
        f'"{store_cat}" ({store_angle.replace(" ", " OR ")}) {geo}{NEGATIVE}',
        "supplier",
        store_cat,
    )
    return [buyer, supplier, store]


def _generic_search_plan(state: Dict[str, Any]):
    queue = _query_triplet(state)
    state["external_exploration_portfolio"] = {
        "version": VERSION,
        "status": "active",
        "mode": "balanced_net_new_domains",
        "queries_planned": len(queue),
        "portfolio": ["potential_buyers", "suppliers", "stores_and_distributors"],
        "rotation_index": _rotation_index(state),
        "total_provider_cap_unchanged": True,
        "demand_checks_moved_to_dedicated_lane": True,
        "updated_at": _utcnow(),
    }
    return "net_new_external_portfolio", queue


def _known_domains(state: Dict[str, Any]) -> set[str]:
    domains: set[str] = set()
    for row in state.get("research_leads", []) or []:
        d = str(row.get("domain") or "").lower().removeprefix("www.") or _domain(row.get("url", ""))
        if d:
            domains.add(d)
    for row in state.get("candidate_accounts", []) or []:
        d = str(row.get("domain") or "").lower().removeprefix("www.") or _domain(row.get("source_url", ""))
        if d:
            domains.add(d)
    return domains


def _store_results_net_new(
    state: Dict[str, Any], query: str, lead_type: str, category: str, results: List[Dict[str, str]]
) -> int:
    known_domains = _known_domains(state)
    filtered: List[Dict[str, str]] = []
    seen_this_query: set[str] = set()
    for item in results or []:
        d = _domain(item.get("url", ""))
        if not d or d in known_domains or d in seen_this_query:
            continue
        seen_this_query.add(d)
        filtered.append(item)

    before_ids = {str(x.get("id") or "") for x in state.get("research_leads", []) or []}
    created = _ORIGINAL_STORE_RESULTS(state, query, lead_type, category, filtered)
    storeish = any(token in query.lower() for token in ("tienda", "mayorista", "ecommerce", "catálogo", "catalogo"))
    for lead in state.get("research_leads", []) or []:
        if str(lead.get("id") or "") in before_ids:
            continue
        lead["growth_kind"] = "store_or_distributor" if storeish else ("potential_buyer" if lead_type == "buyer" else "supplier_discovery")
        lead["exploration_portfolio"] = True
        lead["net_new_domain"] = True
        lead["exploration_version"] = VERSION
        d = _domain(lead.get("url", ""))
        if d and not lead.get("domain"):
            lead["domain"] = d

    report = state.setdefault("external_exploration_portfolio", {})
    report["new_domains_last_query"] = int(created)
    report["last_query_type"] = "store_or_distributor" if storeish else lead_type
    report["last_category"] = category
    report["updated_at"] = _utcnow()
    return created


# Scout general capacity is discovery-only. Demand/procurement already has a separate Governor lane.
scout_connector._demand_candidates = lambda state: []
scout_connector._generic_search_plan = _generic_search_plan
scout_connector._store_results = _store_results_net_new

print({
    "external_exploration_runtime": {
        "version": VERSION,
        "status": "active",
        "general_lane": "net_new_discovery_only",
        "per_cycle_portfolio": ["buyer", "supplier", "store_or_distributor"],
        "dedupe": "unique_company_domain_first",
        "rotates_categories": True,
        "rotates_geographies": True,
        "total_provider_cap_unchanged": True,
    }
}, flush=True)
