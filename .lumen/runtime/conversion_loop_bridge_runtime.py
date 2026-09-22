from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Dict, List
from urllib.parse import urlencode

import acquisition_campaigns as acq
import conversion_loop_learning_runtime as learning
import conversion_loop_runtime as loop

VERSION = "1.0-conversion-loop-campaign-bridge"
BASE = (os.getenv("LUMEN_CONVERSION_BASE_URL") or loop.CONVERSION_BASE_URL).rstrip("/")

_PRODUCT_BY_AUDIENCE = {
    "buyer": "sourcing-5",
    "supplier": "buyer-signals",
}
_ORIGINAL_PAYLOADS = acq._channel_payloads
_ORIGINAL_TICK = acq.acquisition_campaign_tick


def _tracking_url(campaign: Dict[str, Any], variant: Dict[str, Any], channel: str) -> str:
    audience = str(campaign.get("audience") or "").lower()
    slug = _PRODUCT_BY_AUDIENCE.get(audience)
    path = f"/offer/{slug}" if slug else "/catalog"
    query = urlencode({
        "src": "organic",
        "medium": channel or "campaign",
        "campaign": str(campaign.get("id") or ""),
        "creative": str(variant.get("id") or ""),
        "offer": audience or "catalog",
    })
    return f"{BASE}{path}?{query}"


def _conversion_payloads(campaign: Dict[str, Any], variant: Dict[str, Any]) -> List[Dict[str, Any]]:
    payloads = _ORIGINAL_PAYLOADS(campaign, variant)
    for payload in payloads:
        old = str(payload.get("tracking_url") or "")
        new = _tracking_url(campaign, variant, str(payload.get("channel") or "campaign"))
        copy = str(payload.get("copy") or "")
        if old:
            copy = copy.replace(old, new)
        payload["copy"] = copy
        payload["tracking_url"] = new
        payload["conversion_loop"] = True
        payload["conversion_metric"] = "settled_revenue"
        payload["paid_media_spend_authorized"] = False
    return payloads


def _live_stats() -> Dict[str, Any]:
    try:
        req = urllib.request.Request(f"{BASE}/stats", headers={"Accept": "application/json", "User-Agent": "LUMEN-ConversionLoop/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read(120000).decode("utf-8", errors="replace") or "{}")
    except Exception as exc:
        return {"ok": False, "status": "unavailable", "error": f"{type(exc).__name__}: {str(exc)[:180]}"}


def _tick(state: Dict[str, Any]) -> Dict[str, Any]:
    loop_state = loop.conversion_loop_tick(state)
    result = _ORIGINAL_TICK(state)
    live = _live_stats()
    state["conversion_loop_live"] = live
    learned = learning.tick(state)
    learned["live_stats_available"] = bool(live.get("ok"))
    if live.get("ok"):
        funnel = live.get("funnel", {}) or {}
        settlement = live.get("settlement", {}) or {}
        learned["live_funnel"] = {
            "visits": int(funnel.get("visit") or 0),
            "qualified_intent": int(funnel.get("qualified_intent") or 0),
            "checkout_started": int(funnel.get("checkout_started") or 0),
            "settled_orders": int(settlement.get("orders") or 0),
            "realized_revenue_usd": float(settlement.get("realizedRevenueUsd") or 0.0),
        }
        if int(settlement.get("orders") or 0) > 0:
            learned["optimization_priority"] = "settled_revenue"
        elif int(funnel.get("qualified_intent") or 0) > 0:
            learned["optimization_priority"] = "intent_to_checkout"
        elif int(funnel.get("visit") or 0) > 0:
            learned["optimization_priority"] = "visit_to_intent"
    state["conversion_loop_learning"] = learned
    result["conversion_loop"] = {
        "version": VERSION,
        "status": "active",
        "conversion_base_url": BASE,
        "products": len(loop_state.get("products", [])),
        "live_stats": bool(live.get("ok")),
        "paid_media_spend": False,
        "autonomous_outgoing_payment": False,
    }
    return result


acq._channel_payloads = _conversion_payloads
acq.acquisition_campaign_tick = _tick

print({"conversion_loop_bridge_runtime": {
    "version": VERSION,
    "status": "active",
    "conversion_base_url": BASE,
    "buyer_offer": "sourcing-5",
    "supplier_offer": "buyer-signals",
    "partner_destination": "catalog",
    "primary_metric": "settled_revenue",
    "paid_media_spend": False,
}}, flush=True)
