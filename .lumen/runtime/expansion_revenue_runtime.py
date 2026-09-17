from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List

import opportunity_factory_runtime
import search_budget_governor
import canonical_revenue_truth_runtime

VERSION = "1.0-expansion-revenue-network"
MAX_COMPANIES = 400
MAX_CATALOGS = 220
MAX_DEMAND_RECORDS = 160
MAX_SALES_PROFILES = 220

REALIZED_REVENUE_STATUSES = {
    "realized", "realized_partial", "received", "paid", "settled", "completed", "collected"
}
NEGOTIATION_STAGES = {
    "negotiation", "negociacion", "negociación", "counteroffer", "contraoferta", "preclose", "pre_close"
}
PROPOSAL_STAGES = {
    "proposal", "propuesta", "offer", "oferta", "quote_sent", "cotizacion", "cotización"
}
CLOSED_STAGES = {
    "closed", "cerrado", "won", "ganado", "completed", "settled", "paid", "collected"
}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _clean(value: Any, limit: int = 300) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _norm(value: Any) -> str:
    return _clean(value, 260).lower()


def _num(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _stable(prefix: str, *parts: Any) -> str:
    raw = "|".join(_clean(x, 400) for x in parts)
    return prefix + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _account_index(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        str(row.get("id")): row
        for row in (state.get("candidate_accounts", []) or [])
        if isinstance(row, dict) and row.get("id")
    }


def _company_rows(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    for account in state.get("candidate_accounts", []) or []:
        if not isinstance(account, dict):
            continue
        key = str(account.get("id") or _stable("CMP-", account.get("domain"), account.get("name_hint")))
        rows[key] = {
            "id": key,
            "name": _clean(account.get("legal_name") or account.get("name_hint") or account.get("domain"), 180),
            "type": _clean(account.get("type"), 40),
            "domain": _clean(account.get("domain"), 220).lower(),
            "category": _clean(account.get("category"), 160),
            "verified_company": bool(account.get("verified_company")),
            "verified_contact": bool(account.get("commercial_channel_verified") or account.get("verified_contact")),
            "demand_signal": bool(account.get("demand_signal")),
            "source": _clean(account.get("source") or account.get("market_source"), 100),
            "updated_at": utcnow(),
        }

    for store in state.get("partner_stores", []) or []:
        if not isinstance(store, dict):
            continue
        domain = _clean(store.get("domain"), 220).lower()
        key = str(store.get("id") or _stable("CMP-", domain, store.get("name")))
        current = rows.get(key, {})
        rows[key] = {
            "id": key,
            "name": _clean(store.get("name") or current.get("name") or domain, 180),
            "type": current.get("type") or "supplier_or_store",
            "domain": domain or current.get("domain", ""),
            "category": _clean((store.get("categories") or [current.get("category") or ""])[0], 160),
            "verified_company": bool(current.get("verified_company")),
            "verified_contact": bool(current.get("verified_contact")),
            "demand_signal": bool(current.get("demand_signal")),
            "source": "partner_network",
            "catalog_products": len(store.get("catalog_products", []) or []),
            "catalog_crawl_status": store.get("catalog_crawl_status"),
            "commercial_status": store.get("commercial_status"),
            "updated_at": utcnow(),
        }

    out = list(rows.values())
    out.sort(
        key=lambda x: (
            bool(x.get("verified_company")),
            bool(x.get("demand_signal")),
            int(x.get("catalog_products") or 0),
            bool(x.get("verified_contact")),
        ),
        reverse=True,
    )
    return out[:MAX_COMPANIES]


def _catalog_rows(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for store in state.get("partner_stores", []) or []:
        if not isinstance(store, dict):
            continue
        products = [x for x in (store.get("catalog_products", []) or []) if isinstance(x, dict)]
        rows.append({
            "partner_id": store.get("id"),
            "domain": _clean(store.get("domain"), 220).lower(),
            "name": _clean(store.get("name"), 180),
            "categories": [_clean(x, 120) for x in (store.get("categories", []) or [])[:12] if _clean(x, 120)],
            "products_known": len(products),
            "crawl_count": int(store.get("catalog_crawl_count") or 0),
            "crawl_status": store.get("catalog_crawl_status"),
            "crawl_last_at": store.get("catalog_crawl_last_at"),
            "searches": int(store.get("catalog_searches") or 0),
            "agreement_required": bool(store.get("agreement_required")),
            "commission_authorized": bool(store.get("commission_authorized")),
        })
    rows.sort(key=lambda x: (x["products_known"], x["crawl_count"]), reverse=True)
    return rows[:MAX_CATALOGS]


def _market_map_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    companies = _company_rows(state)
    catalogs = _catalog_rows(state)
    categories = sorted({
        _clean(x.get("category"), 160)
        for x in companies
        if _clean(x.get("category"), 160)
    } | {
        _clean(cat, 160)
        for row in catalogs
        for cat in (row.get("categories") or [])
        if _clean(cat, 160)
    })
    product_keys = set()
    for store in state.get("partner_stores", []) or []:
        domain = _clean(store.get("domain"), 220).lower()
        for product in store.get("catalog_products", []) or []:
            if not isinstance(product, dict):
                continue
            identity = _clean(product.get("url"), 900) or _clean(product.get("key"), 200) or _clean(product.get("title"), 260)
            if identity:
                product_keys.add(f"{domain}|{identity}")

    opp_edges = []
    for opp in state.get("market_opportunities", []) or []:
        if not isinstance(opp, dict):
            continue
        buyer = str(opp.get("buyer_account_id") or "")
        supplier = str(opp.get("supplier_account_id") or "")
        if buyer or supplier:
            opp_edges.append({
                "opportunity_id": opp.get("id"),
                "buyer_account_id": buyer or None,
                "supplier_account_id": supplier or None,
                "category": _clean(opp.get("category") or opp.get("need"), 160),
                "score": _num(opp.get("score") or opp.get("portfolio_priority_score")),
            })

    snapshot = {
        "version": VERSION,
        "status": "active",
        "updated_at": utcnow(),
        "companies_known": len(companies),
        "verified_companies": sum(1 for x in companies if x.get("verified_company")),
        "catalogs_indexed": len(catalogs),
        "products_known": len(product_keys),
        "categories_known": len(categories),
        "opportunity_edges": len(opp_edges),
        "catalog_first": True,
        "search_last": True,
        "companies": companies,
        "catalogs": catalogs,
        "categories": categories[:120],
        "opportunity_links": opp_edges[:200],
        "truth_rule": "reuse_persisted_company_catalog_and_relationship_evidence_before_new_search",
    }
    state["expansion_market_map"] = snapshot
    return snapshot


def _signal_rows(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    seen = set()
    rows: List[Dict[str, Any]] = []
    for key in ("unlinked_demand_signals", "public_procurement_signals"):
        for signal in state.get(key, []) or []:
            if not isinstance(signal, dict):
                continue
            ident = str(signal.get("id") or signal.get("url") or signal.get("source_url") or _stable("SIG-", signal.get("title"), signal.get("category")))
            if ident in seen:
                continue
            seen.add(ident)
            row = dict(signal)
            row["_source_collection"] = key
            rows.append(row)

    for account in state.get("candidate_accounts", []) or []:
        if not isinstance(account, dict) or account.get("type") != "buyer" or not account.get("demand_signal"):
            continue
        ident = f"buyer:{account.get('id')}"
        if ident in seen:
            continue
        seen.add(ident)
        rows.append({
            "id": ident,
            "title": account.get("need") or account.get("category") or f"Demanda verificada: {account.get('name_hint') or account.get('domain')}",
            "category": account.get("category"),
            "buyer_account_id": account.get("id"),
            "source": account.get("market_source") or account.get("source") or "verified_buyer_account",
            "summary": account.get("demand_summary") or account.get("need") or account.get("category"),
            "score": account.get("demand_score") or account.get("score") or 70,
            "_source_collection": "verified_buyer_accounts",
        })
    return rows


def _demand_radar_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    accounts = _account_index(state)
    suppliers = [
        x for x in accounts.values()
        if x.get("type") == "supplier" and x.get("verified_company")
    ]
    market_opps = [x for x in (state.get("market_opportunities", []) or []) if isinstance(x, dict)]
    records = []

    for signal in _signal_rows(state):
        category = _clean(signal.get("category") or signal.get("need"), 160)
        buyer_id = str(signal.get("buyer_account_id") or "")
        buyer = accounts.get(buyer_id, {})
        supplier_matches = [
            x for x in suppliers
            if category and _norm(x.get("category")) == _norm(category)
        ][:5]
        linked_opps = [
            str(x.get("id"))
            for x in market_opps
            if str(x.get("buyer_account_id") or "") == buyer_id and buyer_id
        ]
        records.append({
            "id": str(signal.get("id") or _stable("DR-", signal.get("url"), signal.get("title"), category)),
            "need": _clean(signal.get("title") or signal.get("summary") or category or "Demanda detectada", 220),
            "category": category,
            "buyer_account_id": buyer_id or None,
            "buyer": _clean(buyer.get("legal_name") or buyer.get("name_hint") or buyer.get("domain"), 180) or None,
            "buyer_verified": bool(buyer.get("verified_company")),
            "demand_verified": bool(buyer.get("demand_signal")),
            "source": _clean(signal.get("source") or signal.get("_source_collection"), 100),
            "source_url": signal.get("url") or signal.get("source_url"),
            "supplier_candidates": [x.get("id") for x in supplier_matches],
            "supplier_candidates_count": len(supplier_matches),
            "linked_opportunity_ids": linked_opps[:8],
            "margin_potential_usd": None,
            "margin_truth": "unknown_until_real_buyer_and_supplier_economics_are_evidenced",
            "updated_at": utcnow(),
        })

    records.sort(
        key=lambda x: (
            bool(x.get("buyer_verified")),
            bool(x.get("demand_verified")),
            int(x.get("supplier_candidates_count") or 0),
            len(x.get("linked_opportunity_ids") or []),
        ),
        reverse=True,
    )
    records = records[:MAX_DEMAND_RECORDS]
    report = {
        "version": "2.0-demand-radar",
        "status": "active",
        "updated_at": utcnow(),
        "signals_total": len(records),
        "verified_buyer_demand": sum(1 for x in records if x.get("buyer_verified") and x.get("demand_verified")),
        "with_supplier_candidates": sum(1 for x in records if int(x.get("supplier_candidates_count") or 0) > 0),
        "linked_to_opportunity": sum(1 for x in records if x.get("linked_opportunity_ids")),
        "records": records,
        "truth_rule": "need_buyer_product_supplier_margin_is_progressively_evidenced; unknown_margin_stays_null",
    }
    state["demand_radar_v2"] = report
    state["demand_radar_records"] = records
    return report


def _sales_brain_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    accounts = _account_index(state)
    profiles = []
    for relation in state.get("commercial_relationships", []) or []:
        if not isinstance(relation, dict):
            continue
        account_id = str(relation.get("account_id") or "")
        account = accounts.get(account_id, {})
        outbound = int(relation.get("outbound_count") or 0)
        replies = int(relation.get("response_count") or 0)
        profiles.append({
            "relationship_key": relation.get("key"),
            "account_id": account_id or None,
            "account_type": account.get("type"),
            "counterparty": _clean(relation.get("counterparty") or account.get("name_hint") or account.get("domain"), 180),
            "domain": _clean(relation.get("domain") or account.get("domain"), 220),
            "categories": [_clean(x, 120) for x in (relation.get("categories", []) or [])[:10]],
            "relationship_state": relation.get("relationship_state"),
            "outbound_count": outbound,
            "response_count": replies,
            "response_rate_pct": round(replies / outbound * 100.0, 1) if outbound else None,
            "follow_up_count": int(relation.get("follow_up_count") or 0),
            "last_interaction_at": relation.get("last_interaction_at"),
            "next_follow_up_at": relation.get("next_follow_up_at"),
            "opted_out": bool(relation.get("opted_out")),
            "verified_company": bool(account.get("verified_company")),
            "verified_contact": bool(account.get("commercial_channel_verified") or account.get("verified_contact")),
        })
    profiles.sort(key=lambda x: (x["response_count"], x["outbound_count"], bool(x["verified_company"])), reverse=True)
    profiles = profiles[:MAX_SALES_PROFILES]
    report = {
        "version": "1.0-sales-brain",
        "status": "active",
        "updated_at": utcnow(),
        "accounts_total": len(profiles),
        "engaged": sum(1 for x in profiles if x.get("relationship_state") == "engaged"),
        "awaiting_reply": sum(1 for x in profiles if x.get("relationship_state") == "awaiting_reply"),
        "follow_up_due": sum(1 for x in profiles if x.get("relationship_state") == "follow_up_due"),
        "cooldown": sum(1 for x in profiles if x.get("relationship_state") == "cooldown"),
        "opted_out": sum(1 for x in profiles if x.get("opted_out")),
        "profiles": profiles,
        "truth_rule": "commercial_memory_is_rebuilt_from_persisted_interaction_evidence",
    }
    state["sales_brain"] = report
    return report


def _realized_revenue_usd(state: Dict[str, Any]) -> float:
    total = 0.0
    for row in state.get("revenue_ledger", []) or []:
        if not isinstance(row, dict) or _norm(row.get("status")) not in REALIZED_REVENUE_STATUSES:
            continue
        amount = None
        for key in ("realized_revenue_usd", "revenue_usd", "amount_usd", "realized_amount_usd", "company_revenue_usd"):
            amount = _num(row.get(key))
            if amount is not None:
                break
        if amount is not None and amount > 0:
            total += amount
    service = state.get("service_revenue", {}) or {}
    service_amount = _num(service.get("realized_service_revenue_usd"))
    if service_amount and service_amount > 0:
        total += service_amount
    return round(total, 2)


def _margin_potential_usd(state: Dict[str, Any], canonical_deal_ids: set[str]) -> float:
    total = 0.0
    for deal in state.get("deals", []) or []:
        if not isinstance(deal, dict) or str(deal.get("id") or "") not in canonical_deal_ids:
            continue
        if _norm(deal.get("stage")) in CLOSED_STAGES:
            continue
        value = None
        for key in ("risk_adjusted_expected_profit_usd", "expected_company_profit_usd", "expected_profit_usd", "company_profit"):
            value = _num(deal.get(key))
            if value is not None:
                break
        if value is not None and value > 0:
            total += value
    return round(total, 2)


def _contacted_counts(state: Dict[str, Any], accounts: Dict[str, Dict[str, Any]]) -> tuple[int, int, int]:
    buyers = suppliers = replies = 0
    for relation in state.get("commercial_relationships", []) or []:
        if not isinstance(relation, dict):
            continue
        outbound = int(relation.get("outbound_count") or 0)
        response = int(relation.get("response_count") or 0)
        if outbound <= 0:
            continue
        account = accounts.get(str(relation.get("account_id") or ""), {})
        if account.get("type") == "buyer":
            buyers += 1
        elif account.get("type") == "supplier":
            suppliers += 1
        replies += response
    return buyers, suppliers, replies


def _revenue_loop_tick(
    state: Dict[str, Any],
    market_map: Dict[str, Any],
    demand: Dict[str, Any],
    opportunity: Dict[str, Any],
    sales: Dict[str, Any],
) -> Dict[str, Any]:
    truth = dict(canonical_revenue_truth_runtime.canonical_revenue_truth_tick(state) or {})
    counts = truth.get("counts", {}) or {}
    canonical_deal_ids = set(str(x) for x in (truth.get("canonical_deal_ids", []) or []))
    accounts = _account_index(state)
    buyers_contacted, suppliers_contacted, replies = _contacted_counts(state, accounts)

    deals = [x for x in (state.get("deals", []) or []) if isinstance(x, dict)]
    canonical_deals = [x for x in deals if str(x.get("id") or "") in canonical_deal_ids]
    negotiations = sum(1 for x in canonical_deals if _norm(x.get("stage")) in NEGOTIATION_STAGES)
    proposals = int(counts.get("canonical_proposals") or 0)
    if proposals <= 0:
        proposals = sum(1 for x in canonical_deals if _norm(x.get("stage")) in PROPOSAL_STAGES)
    realized_events = sum(
        1 for x in (state.get("revenue_ledger", []) or [])
        if isinstance(x, dict) and _norm(x.get("status")) in REALIZED_REVENUE_STATUSES
    )
    close_ready = int(counts.get("canonical_close_ready") or 0)
    active_opps = int(counts.get("canonical_opportunities") or 0)

    roles = [
        {"role": "Demand Hunter", "status": "active", "workload": int(demand.get("signals_total") or 0)},
        {"role": "Catalog Scout", "status": "active", "workload": int(market_map.get("catalogs_indexed") or 0)},
        {"role": "Buyer Hunter", "status": "active", "workload": sum(1 for x in accounts.values() if x.get("type") == "buyer" and x.get("verified_company"))},
        {"role": "Supplier Hunter", "status": "active", "workload": sum(1 for x in accounts.values() if x.get("type") == "supplier" and x.get("verified_company"))},
        {"role": "Opportunity Analyst", "status": "active", "workload": int(opportunity.get("cases_total") or 0)},
        {"role": "Negotiator", "status": "active", "workload": negotiations},
        {"role": "Closer", "status": "active", "workload": close_ready},
        {"role": "Sentinel", "status": "active", "workload": 0},
    ]

    metrics = {
        "companies_known": int(market_map.get("companies_known") or 0),
        "catalogs_indexed": int(market_map.get("catalogs_indexed") or 0),
        "products_known": int(market_map.get("products_known") or 0),
        "needs_detected": int(demand.get("signals_total") or 0),
        "opportunities_active": active_opps,
        "buyers_contacted": buyers_contacted,
        "suppliers_contacted": suppliers_contacted,
        "replies": replies,
        "negotiations": negotiations,
        "proposals": proposals,
        "margin_potential_usd": _margin_potential_usd(state, canonical_deal_ids),
        "sales_closed": realized_events,
        "revenue_generated_usd": _realized_revenue_usd(state),
    }

    next_stage = str(truth.get("recommended_lane") or "demand_discovery")
    report = {
        "version": VERSION,
        "status": "active",
        "updated_at": utcnow(),
        "objective": "detect_need_source_supplier_build_opportunity_contact_negotiate_propose_close_learn",
        "stage": next_stage,
        "metrics": metrics,
        "specialist_roles": roles,
        "canonical_truth": {
            "version": truth.get("version"),
            "recommended_lane": truth.get("recommended_lane"),
            "counts": counts,
        },
        "authority": {
            "research_and_nonbinding_commercial_preparation": True,
            "binding_contracts_human_required": True,
            "payments_orders_human_required": True,
            "paid_spend_authority_changed": False,
            "binding_authority_changed": False,
            "autonomous_purchase": False,
            "autonomous_cart_checkout": False,
            "new_login_authority": False,
        },
        "search_governance": {
            "daily_provider_cap": int(search_budget_governor.TOTAL_DAILY_CAP),
            "daily_cap_unchanged_by_expansion": True,
            "catalog_first_search_last": True,
        },
        "truth_rule": "pipeline_value_is_not_revenue; only_realized_ledger_events_count_as_generated_revenue",
    }
    state["expansion_revenue"] = report
    state["expansion_revenue_metrics"] = metrics
    state["expansion_specialist_roles"] = roles
    return report


def expansion_revenue_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    market_map = _market_map_tick(state)
    demand = _demand_radar_tick(state)
    opportunity = dict(opportunity_factory_runtime.opportunity_factory_tick(state) or {})
    sales = _sales_brain_tick(state)
    loop = _revenue_loop_tick(state, market_map, demand, opportunity, sales)

    report = {
        "version": VERSION,
        "status": "healthy",
        "updated_at": utcnow(),
        "market_map": {
            "companies_known": market_map.get("companies_known"),
            "catalogs_indexed": market_map.get("catalogs_indexed"),
            "products_known": market_map.get("products_known"),
            "categories_known": market_map.get("categories_known"),
        },
        "demand_radar": {
            "signals_total": demand.get("signals_total"),
            "verified_buyer_demand": demand.get("verified_buyer_demand"),
            "with_supplier_candidates": demand.get("with_supplier_candidates"),
        },
        "opportunity_factory": {
            "cases_total": opportunity.get("cases_total"),
            "ready_for_pipeline": opportunity.get("ready_for_pipeline"),
            "enrichment_required": opportunity.get("enrichment_required"),
            "opportunities_materialized": opportunity.get("opportunities_materialized"),
        },
        "sales_brain": {
            "accounts_total": sales.get("accounts_total"),
            "engaged": sales.get("engaged"),
            "follow_up_due": sales.get("follow_up_due"),
        },
        "revenue_loop": loop,
        "guardrails": loop.get("authority"),
        "search_governance": loop.get("search_governance"),
    }
    state["expansion_phase"] = report
    state.setdefault("activity", []).insert(0, {
        "ts": utcnow(),
        "msg": (
            "Expansion / Revenue: "
            f"{loop['metrics']['companies_known']} empresas, "
            f"{loop['metrics']['catalogs_indexed']} catálogos, "
            f"{loop['metrics']['needs_detected']} necesidades y "
            f"{loop['metrics']['opportunities_active']} oportunidades canónicas activas."
        ),
    })
    state["activity"] = state["activity"][:100]
    return report
