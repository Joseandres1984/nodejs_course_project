from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List
from urllib.parse import urlencode

VERSION = "1.1-conversion-loop-live"
CONVERSION_BASE_URL = "https://lumen-zero-conversion.joseandresceol1-jac.workers.dev"

PRODUCTS = [
    {"id": "MP-SUPPLIER-SNAPSHOT", "slug": "supplier-snapshot", "name": "Supplier Snapshot", "price_usd": 5, "service_id": "SRV-SUPPLIERCHECK"},
    {"id": "MP-QUOTE-SANITY", "slug": "quote-sanity", "name": "Quote Sanity Check", "price_usd": 7, "service_id": "SRV-QUOTECHECK"},
    {"id": "MP-TENDER-SCAN", "slug": "tender-scan", "name": "Tender Quick Scan", "price_usd": 9, "service_id": "SRV-TENDER-HUNTER"},
    {"id": "MP-SOURCING-5", "slug": "sourcing-5", "name": "Supplier Shortlist 5", "price_usd": 15, "service_id": "SRV-SOURCING-EXPRESS"},
    {"id": "MP-BUYER-SIGNALS", "slug": "buyer-signals", "name": "Buyer Signal Scan", "price_usd": 19, "service_id": "SRV-B2B-PROSPECTING"},
    {"id": "MP-EXPORT-PULSE", "slug": "export-pulse", "name": "Export Market Pulse", "price_usd": 25, "service_id": "SRV-EXPORT-SCOUT"},
]


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _base_url(state: Dict[str, Any]) -> str:
    cfg = state.get("runtime_config", {}) or {}
    return str(cfg.get("conversion_base_url") or CONVERSION_BASE_URL).rstrip("/")


def build_conversion_catalog(state: Dict[str, Any]) -> Dict[str, Any]:
    public = _base_url(state)
    rows: List[Dict[str, Any]] = []
    for p in PRODUCTS:
        track = {
            "src": "organic",
            "medium": "lumen",
            "campaign": f"machine-{p['slug']}",
            "product": p["id"],
        }
        rows.append({
            **p,
            "landing_url": f"{public}/offer/{p['slug']}?{urlencode(track)}",
            "intent_url": f"{public}/intent/{p['slug']}?{urlencode(track)}",
            "cta": "Ver oferta y comprar",
            "funnel": ["visit", "qualified_intent", "checkout_started", "settled", "repeat_purchase"],
        })
    return {
        "version": VERSION,
        "status": "active",
        "updated_at": utcnow(),
        "objective": "organic_visit_to_settled_revenue_learning_loop",
        "conversion_base_url": public,
        "products": rows,
        "metrics": {
            "primary": "settled_revenue_usd",
            "secondary": ["qualified_intent", "checkout_started", "settled_orders", "repeat_buyers"],
            "vanity_metrics_are_not_primary": True,
        },
        "autonomy": {
            "paid_media_spend": False,
            "autonomous_outgoing_payment": False,
            "binding_actions_human_gated": True,
            "organic_owned_channels_allowed": True,
        },
    }


def conversion_loop_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    catalog = build_conversion_catalog(state)
    state["conversion_loop"] = catalog
    return catalog


def install(state: Dict[str, Any]) -> Dict[str, Any]:
    return conversion_loop_tick(state)
