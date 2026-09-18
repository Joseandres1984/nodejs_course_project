from __future__ import annotations

from typing import Any, Dict

import commercial_offer_engine_runtime
import continuous_revenue_drive_runtime
import service_revenue_runtime


VERSION = "1.1-intelligence-offer-cycle-bridge"
_ORIGINAL_CRD_TICK = continuous_revenue_drive_runtime.continuous_revenue_drive_tick


def _continuous_revenue_with_intelligence(state: Dict[str, Any]) -> Dict[str, Any]:
    report = dict(_ORIGINAL_CRD_TICK(state) or {})
    service_summary = dict(service_revenue_runtime.service_revenue_tick(state) or {})
    offer_engine = dict(commercial_offer_engine_runtime.offer_engine_tick(state) or {})
    intelligence = dict(state.get("intelligence_revenue_runtime", {}) or {})
    report["service_revenue"] = {
        "status": service_summary.get("status"),
        "active_services": service_summary.get("active_services"),
        "realized_revenue_usd": service_summary.get("realized_revenue_usd", 0.0),
    }
    report["commercial_offer_engine"] = {
        "status": offer_engine.get("status"),
        "pricing_mode": offer_engine.get("pricing_mode"),
        "active_pricebook_services": offer_engine.get("active_pricebook_services", 0),
        "offers_recommended_for_inquiries": offer_engine.get("offers_recommended_for_inquiries", 0),
        "pricing_review_due_services": offer_engine.get("pricing_review_due_services", []),
        "autonomous_discount_allowed": offer_engine.get("autonomous_discount_allowed", False),
        "binding_authority_changed": offer_engine.get("binding_authority_changed", False),
    }
    report["intelligence_revenue"] = {
        "status": intelligence.get("status"),
        "active_products": intelligence.get("active_products", 0),
        "verified_product_fit_candidates": intelligence.get("verified_product_fit_candidates", 0),
        "outbound_attention_active": intelligence.get("outbound_attention_active", 0),
        "public_inquiries": intelligence.get("public_inquiries", 0),
        "real_contacted": intelligence.get("real_contacted", 0),
        "replies": intelligence.get("replies", 0),
        "realized_intelligence_revenue_usd": intelligence.get("realized_intelligence_revenue_usd", 0.0),
        "searches_used": intelligence.get("searches_used", 0),
        "paid_spend": intelligence.get("paid_spend", False),
    }
    state["continuous_revenue_drive"] = report
    print({
        "intelligence_cycle_bridge": {
            "version": VERSION,
            "status": "executed",
            "products": intelligence.get("active_products", 0),
            "verified_candidates": intelligence.get("verified_product_fit_candidates", 0),
            "outbound_attention": intelligence.get("outbound_attention_active", 0),
            "public_inquiries": intelligence.get("public_inquiries", 0),
            "real_contacted": intelligence.get("real_contacted", 0),
            "replies": intelligence.get("replies", 0),
            "realized_revenue_usd": intelligence.get("realized_intelligence_revenue_usd", 0.0),
            "searches_used": intelligence.get("searches_used", 0),
            "paid_spend": intelligence.get("paid_spend", False),
            "offer_engine": {
                "status": offer_engine.get("status"),
                "pricing_mode": offer_engine.get("pricing_mode"),
                "services": offer_engine.get("active_pricebook_services", 0),
                "offers_recommended": offer_engine.get("offers_recommended_for_inquiries", 0),
                "review_due_services": offer_engine.get("pricing_review_due_services", []),
                "autonomous_discount": offer_engine.get("autonomous_discount_allowed", False),
            },
        }
    }, flush=True)
    return report


if not getattr(continuous_revenue_drive_runtime, "_lumen_intelligence_cycle_bridge_installed", False):
    continuous_revenue_drive_runtime.continuous_revenue_drive_tick = _continuous_revenue_with_intelligence
    continuous_revenue_drive_runtime._lumen_intelligence_cycle_bridge_installed = True

print({
    "intelligence_cycle_bridge_install": {
        "version": VERSION,
        "status": "installed",
        "trigger": "continuous_revenue_drive_every_worker_cycle",
        "offer_engine": commercial_offer_engine_runtime.VERSION,
        "paid_spend": False,
        "binding_authority_changed": False,
    }
}, flush=True)
