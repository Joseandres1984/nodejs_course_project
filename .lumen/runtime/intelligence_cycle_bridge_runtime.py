from __future__ import annotations

from typing import Any, Dict

import continuous_revenue_drive_runtime
import service_revenue_runtime


VERSION = "1.0-intelligence-cycle-bridge"
_ORIGINAL_CRD_TICK = continuous_revenue_drive_runtime.continuous_revenue_drive_tick


def _continuous_revenue_with_intelligence(state: Dict[str, Any]) -> Dict[str, Any]:
    report = dict(_ORIGINAL_CRD_TICK(state) or {})
    service_summary = dict(service_revenue_runtime.service_revenue_tick(state) or {})
    intelligence = dict(state.get("intelligence_revenue_runtime", {}) or {})
    report["service_revenue"] = {
        "status": service_summary.get("status"),
        "active_services": service_summary.get("active_services"),
        "realized_revenue_usd": service_summary.get("realized_revenue_usd", 0.0),
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
        "paid_spend": False,
        "binding_authority_changed": False,
    }
}, flush=True)
