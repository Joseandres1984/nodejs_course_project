from __future__ import annotations

import os
from typing import Any, Dict, List

import market_intelligence_scout as intelligence
import partner_network_ext as partner_ext
import store_catalog_crawler as catalog

VERSION = "1.0-shadow-market-intelligence"
ENABLED = str(os.getenv("LUMEN_MARKET_INTELLIGENCE_SHADOW_ENABLED", "false")).strip().lower() in {"1", "true", "yes", "on"}

_ORIGINAL_JSONLD_PRODUCTS = catalog._jsonld_products
_ORIGINAL_CRAWL = catalog.crawl_store_catalog
_ORIGINAL_PARTNER_TICK = partner_ext.partner_network_tick
_CAPTURED_CRAWLS: List[tuple[str, Dict[str, Any]]] = []


def _enriched_jsonld_products(blocks: List[str], source_url: str):
    enriched = intelligence.extract_jsonld_products(blocks, source_url)
    if enriched:
        return enriched
    return _ORIGINAL_JSONLD_PRODUCTS(blocks, source_url)


def _tracked_crawl(domain: str, seed_urls=None):
    result = _ORIGINAL_CRAWL(domain, seed_urls)
    _CAPTURED_CRAWLS.append((str(domain or "").lower().removeprefix("www."), dict(result or {})))
    return result


def _capture_from_crawls(state: Dict[str, Any]) -> Dict[str, int]:
    stores = {str(x.get("domain") or "").lower().removeprefix("www."): x for x in state.get("partner_stores", []) or []}
    new_observations = 0
    products_seen = 0
    crawls = list(_CAPTURED_CRAWLS)
    _CAPTURED_CRAWLS.clear()
    for domain, result in crawls:
        store = stores.get(domain) or {"domain": domain}
        for row in result.get("products", []) or []:
            products_seen += 1
            if intelligence.capture_catalog_observation(state, store=store, product=row):
                new_observations += 1
    return {"crawls": len(crawls), "products_seen": products_seen, "new_observations": new_observations}


def _partner_tick_with_market_intelligence(state: Dict[str, Any]) -> Dict[str, Any]:
    if not ENABLED:
        return dict(_ORIGINAL_PARTNER_TICK(state) or {})
    _CAPTURED_CRAWLS.clear()
    report = dict(_ORIGINAL_PARTNER_TICK(state) or {})
    capture = _capture_from_crawls(state)
    market = intelligence.market_intelligence_tick(state)
    report["market_intelligence"] = {
        "version": VERSION,
        "status": market.get("status"),
        "observations_total": market.get("observations_total"),
        "priced_observations": market.get("priced_observations"),
        "opportunity_candidates": market.get("opportunity_candidates"),
        "capture": capture,
        "authority": market.get("authority"),
    }
    state["partner_network"] = report
    return report


if ENABLED:
    # Additive monkey patches only: public crawler keeps its GET/robots policy, while JSON-LD output gains
    # structured offer facts and the existing partner cycle records them into shadow-only intelligence state.
    catalog._jsonld_products = _enriched_jsonld_products
    partner_ext.crawl_store_catalog = _tracked_crawl
    partner_ext.partner_network_tick = _partner_tick_with_market_intelligence
    print({"market_intelligence_runtime": {"version": VERSION, "status": "shadow_enabled", "authority": "research_only"}}, flush=True)
else:
    print({"market_intelligence_runtime": {"version": VERSION, "status": "disabled", "enable_with": "LUMEN_MARKET_INTELLIGENCE_SHADOW_ENABLED=true"}}, flush=True)
