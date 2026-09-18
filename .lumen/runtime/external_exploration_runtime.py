from __future__ import annotations

"""Net-new discovery portfolio for LUMEN with a zero-capital Global Trade lane.

The general Scout lane still uses the same provider budget. Each cycle keeps one
local buyer query and one local store/distributor query, while the supplier query
rotates across international industrial sourcing markets. This is research only:
LUMEN acts as a commercial intermediary/sourcing coordinator, never as importer of
record, customs broker, freight forwarder, purchaser or payer.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple
import urllib.parse

import scout_connector


VERSION = "1.2-global-trade-discovery-compat"

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

LOCAL_GEOGRAPHIES = [
    "Argentina",
    "Buenos Aires Argentina",
    "Córdoba Argentina",
    "Santa Fe Argentina",
    "Mendoza Argentina",
    "Rosario Argentina",
]

GLOBAL_SUPPLIER_MARKETS = [
    "Brazil",
    "China",
    "United States",
    "Germany",
    "Italy",
    "India",
    "Turkey",
    "Mexico",
]

BUYER_ANGLES = [
    "compras abastecimiento mantenimiento",
    "planta producción ingeniería",
    "industria mantenimiento compras",
    "proyectos ingeniería abastecimiento",
]

SUPPLIER_ANGLES = [
    "manufacturer supplier exporter distributor",
    "industrial manufacturer exporter catalog",
    "supplier factory RFQ industrial",
    "manufacturer distributor export catalog",
]

STORE_ANGLES = [
    'mayorista distribuidor "tienda online"',
    'distribuidor catálogo stock tienda',
    'ecommerce industrial mayorista distribuidor',
    'tienda técnica catálogo productos',
]

# Backward-compatible public recipe surface used by the persistent exploration-learning layer.
# Keeping both local and international markets avoids the old missing-attribute crash while letting
# the learner keep exploring a broader market universe under the same search cap.
GEOGRAPHIES = LOCAL_GEOGRAPHIES + GLOBAL_SUPPLIER_MARKETS

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
    buyer_cat = categories[idx % len(categories)]
    supplier_cat = categories[(idx + 5) % len(categories)]
    store_cat = categories[(idx + 11) % len(categories)]
    local_geo = LOCAL_GEOGRAPHIES[idx % len(LOCAL_GEOGRAPHIES)]
    supplier_market = GLOBAL_SUPPLIER_MARKETS[idx % len(GLOBAL_SUPPLIER_MARKETS)]
    buyer_angle = BUYER_ANGLES[idx % len(BUYER_ANGLES)]
    store_angle = STORE_ANGLES[idx % len(STORE_ANGLES)]

    buyer = (
        f'"{buyer_cat}" (empresa OR industria OR planta OR fábrica OR fabrica) '
        f'({buyer_angle.replace(" ", " OR ")}) {local_geo} -proveedor -distribuidor{NEGATIVE}',
        "buyer",
        buyer_cat,
    )
    supplier = (
        f'"{supplier_cat}" (manufacturer OR supplier OR exporter OR distributor) '
        f'{supplier_market} industrial catalog RFQ{NEGATIVE}',
        "supplier",
        supplier_cat,
    )
    store = (
        f'"{store_cat}" ({store_angle.replace(" ", " OR ")}) {local_geo}{NEGATIVE}',
        "supplier",
        store_cat,
    )
    return [buyer, supplier, store]


def _query_market(query: str) -> str | None:
    low = query.lower()
    for market in GLOBAL_SUPPLIER_MARKETS:
        if market.lower() in low:
            return market
    return None


def _generic_search_plan(state: Dict[str, Any]):
    queue = _query_triplet(state)
    idx = _rotation_index(state)
    supplier_market = GLOBAL_SUPPLIER_MARKETS[idx % len(GLOBAL_SUPPLIER_MARKETS)]
    state["external_exploration_portfolio"] = {
        "version": VERSION,
        "status": "active",
        "mode": "local_demand_plus_global_supply",
        "queries_planned": len(queue),
        "portfolio": ["local_potential_buyers", "global_suppliers", "local_stores_and_distributors"],
        "rotation_index": idx,
        "global_supplier_market_this_cycle": supplier_market,
        "global_supplier_markets": list(GLOBAL_SUPPLIER_MARKETS),
        "total_provider_cap_unchanged": True,
        "demand_checks_moved_to_dedicated_lane": True,
        "global_trade": {
            "status": "active_research",
            "business_model": "zero_capital_b2b_intermediation",
            "role": "commercial_intermediary_and_sourcing_coordinator",
            "container_strategy": "LCL_or_FCL_only_after_verified_demand_and_real_logistics_costs",
            "own_capital_required": False,
            "takes_title_to_goods": False,
            "importer_of_record": False,
            "exporter_of_record": False,
            "customs_broker": False,
            "freight_forwarder": False,
            "autonomous_purchase": False,
            "autonomous_payment": False,
            "autonomous_binding_contract": False,
            "commission_or_fee_requires_human_approval": True,
            "customs_and_logistics_execution": "authorized_third_parties_only",
        },
        "updated_at": _utcnow(),
    }
    return "net_new_external_portfolio_global_trade", queue


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
    target_market = _query_market(query)
    global_supplier_search = bool(lead_type == "supplier" and target_market)

    for lead in state.get("research_leads", []) or []:
        if str(lead.get("id") or "") in before_ids:
            continue
        lead["growth_kind"] = "store_or_distributor" if storeish else ("potential_buyer" if lead_type == "buyer" else "supplier_discovery")
        lead["exploration_portfolio"] = True
        lead["net_new_domain"] = True
        lead["exploration_version"] = VERSION
        if global_supplier_search:
            lead["global_trade_candidate"] = True
            lead["target_market"] = target_market
            lead["commercial_role"] = "prospective_international_supplier"
            lead["requires_company_verification"] = True
            lead["requires_verified_commercial_channel_before_outreach"] = True
        d = _domain(lead.get("url", ""))
        if d and not lead.get("domain"):
            lead["domain"] = d

    report = state.setdefault("external_exploration_portfolio", {})
    report["new_domains_last_query"] = int(created)
    report["last_query_type"] = "global_supplier" if global_supplier_search else ("store_or_distributor" if storeish else lead_type)
    report["last_category"] = category
    if global_supplier_search:
        report["last_global_supplier_market"] = target_market
        report["last_global_supplier_candidates_created"] = int(created)
    report["updated_at"] = _utcnow()
    return created


# Scout capacity is unchanged: one existing supplier-search slot becomes international.
scout_connector._demand_candidates = lambda state: []
scout_connector._generic_search_plan = _generic_search_plan
scout_connector._store_results = _store_results_net_new

print({
    "external_exploration_runtime": {
        "version": VERSION,
        "status": "active",
        "general_lane": "local_demand_plus_global_supply",
        "per_cycle_portfolio": ["local_buyer", "global_supplier", "local_store_or_distributor"],
        "global_supplier_markets": GLOBAL_SUPPLIER_MARKETS,
        "legacy_learning_surface": {"GEOGRAPHIES": len(GEOGRAPHIES), "SUPPLIER_ANGLES": len(SUPPLIER_ANGLES)},
        "dedupe": "unique_company_domain_first",
        "rotates_categories": True,
        "rotates_geographies": True,
        "zero_capital_intermediation": True,
        "total_provider_cap_unchanged": True,
    }
}, flush=True)
