from __future__ import annotations

import os
from typing import Any, Dict

import partner_network as base
from store_catalog_crawler import crawl_store_catalog

CRAWL_STORES_PER_CYCLE = max(0, min(5, int(os.getenv("LUMEN_PARTNER_CRAWL_STORES_PER_CYCLE", "1"))))


def _crawl(state: Dict[str, Any]) -> Dict[str, int]:
    stores = list(state.get("partner_stores", []) or [])
    stores.sort(key=lambda x: (int(x.get("catalog_crawl_count") or 0), -len(x.get("source_urls", []) or []), str(x.get("domain") or "")))
    crawled = pages = products = denied = errors = 0
    for store in stores[:CRAWL_STORES_PER_CYCLE]:
        domain = str(store.get("domain") or "")
        if not domain:
            continue
        result = crawl_store_catalog(domain, list(store.get("source_urls", []) or []))
        store["catalog_crawl_count"] = int(store.get("catalog_crawl_count") or 0) + 1
        store["catalog_crawl_status"] = result.get("status")
        store["catalog_crawl_last_at"] = base.utcnow()
        pages += int(result.get("pages") or 0)
        denied += int(result.get("robots_denied") or 0)
        errors += int(result.get("errors") or 0)
        added = 0
        category = str((store.get("categories") or [""])[0] or "")
        for row in result.get("products", []) or []:
            if base._add_product(store, title=str(row.get("title") or ""), url=str(row.get("url") or ""), category=category, source=str(row.get("source") or "public_catalog_crawl")):
                added += 1
        products += added
        crawled += 1
    return {"stores": crawled, "pages": pages, "products": products, "robots_denied": denied, "errors": errors}


def partner_network_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    report = dict(base.partner_network_tick(state) or {})
    crawl = _crawl(state) if CRAWL_STORES_PER_CYCLE > 0 else {"stores": 0, "pages": 0, "products": 0, "robots_denied": 0, "errors": 0}
    base._apply_agreements(state)
    new_offers = base._sync_referral_offers(state)
    report.update({
        "catalog_crawl": crawl,
        "catalog_crawl_policy": "same_domain_public_get_only_robots_respected_no_login_no_cart_no_checkout_no_form_submission",
        "referral_offers_created_after_crawl": new_offers,
        "referral_offers_active": sum(1 for x in state.get("partner_referral_offers", []) or [] if x.get("status") == "active"),
    })
    state["partner_network"] = report
    state.setdefault("activity", []).insert(0, {
        "ts": base.utcnow(),
        "msg": f"Partner Catalog Deep Scan: {crawl['stores']} tienda(s), {crawl['pages']} páginas públicas revisadas, {crawl['products']} productos nuevos detectados."
    })
    state["activity"] = state["activity"][:100]
    return report
