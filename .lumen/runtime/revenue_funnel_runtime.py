from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

VERSION = "1.0-causal-revenue-funnel"
MAX_HISTORY = 96


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _real_offers(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [x for x in state.get("offers", []) or [] if str(x.get("source") or "") not in {"demo", "demo/simulación"}]


def _realized(state: Dict[str, Any]) -> int:
    statuses = {"realized", "realized_partial", "received", "paid", "settled", "completed", "collected"}
    return sum(1 for x in state.get("revenue_ledger", []) or [] if str(x.get("status") or "").lower() in statuses)


def _counts(state: Dict[str, Any]) -> Dict[str, int]:
    accounts = list(state.get("candidate_accounts", []) or [])
    buyers = [x for x in accounts if x.get("type") == "buyer" and x.get("verified_company")]
    verified_contacts = [x for x in accounts if x.get("verified_company") and (x.get("commercial_channel_verified") or x.get("verified_contact"))]
    opportunities = list(state.get("market_opportunities", []) or [])
    rfq_ready = [x for x in state.get("interlocution_cases", []) or [] if x.get("supplier_rfq_ready")]
    quotes = list(state.get("supplier_quotes", []) or []) + list(state.get("quotes", []) or [])
    offers = _real_offers(state)
    proposals = list(state.get("proposals", []) or [])
    deals = list(state.get("deals", []) or [])
    close_ready = [x for x in deals if str(x.get("stage") or "").lower() in {"listo para cerrar", "close_ready", "autorizado para cierre"}]
    return {
        "research_leads": len(state.get("research_leads", []) or []),
        "verified_companies": sum(1 for x in accounts if x.get("verified_company")),
        "verified_contacts": len(verified_contacts),
        "verified_buyers": len(buyers),
        "buyers_with_demand": sum(1 for x in buyers if x.get("demand_signal")),
        "market_opportunities": len(opportunities),
        "rfq_ready": len(rfq_ready),
        "quotes": len(quotes),
        "real_offers": len(offers),
        "proposals": len(proposals),
        "active_deals": sum(1 for x in deals if str(x.get("stage") or "").lower() not in {"closed", "lost", "cancelled", "canceled", "cerrado"}),
        "close_ready": len(close_ready),
        "realized_events": _realized(state),
    }


def _rate(num: int, den: int) -> float | None:
    if den <= 0:
        return None
    return round(num / den * 100.0, 1)


def _rates(c: Dict[str, int]) -> Dict[str, float | None]:
    return {
        "lead_to_verified_company_pct": _rate(c["verified_companies"], c["research_leads"]),
        "company_to_verified_contact_pct": _rate(c["verified_contacts"], c["verified_companies"]),
        "verified_buyer_to_demand_pct": _rate(c["buyers_with_demand"], c["verified_buyers"]),
        "demand_to_opportunity_pct": _rate(c["market_opportunities"], c["buyers_with_demand"]),
        "opportunity_to_rfq_ready_pct": _rate(c["rfq_ready"], c["market_opportunities"]),
        "opportunity_to_quote_pct": _rate(c["quotes"], c["market_opportunities"]),
        "quote_to_offer_pct": _rate(c["real_offers"], c["quotes"]),
        "offer_to_proposal_pct": _rate(c["proposals"], c["real_offers"]),
        "active_deal_to_close_ready_pct": _rate(c["close_ready"], c["active_deals"]),
        "close_ready_to_realized_pct": _rate(c["realized_events"], c["close_ready"]),
    }


def _bottleneck(c: Dict[str, int]) -> Dict[str, Any]:
    checks = [
        ("verification", c["research_leads"] > 0 and c["verified_companies"] == 0, "verified_companies"),
        ("contact", c["verified_companies"] > 0 and c["verified_contacts"] == 0, "verified_contacts"),
        ("demand", c["verified_buyers"] > 0 and c["buyers_with_demand"] == 0, "buyers_with_demand"),
        ("opportunity", c["buyers_with_demand"] > 0 and c["market_opportunities"] == 0, "market_opportunities"),
        ("quote", c["market_opportunities"] > 0 and c["quotes"] == 0 and c["real_offers"] == 0, "quotes"),
        ("offer", c["quotes"] > 0 and c["real_offers"] == 0, "real_offers"),
        ("proposal", c["real_offers"] > 0 and c["proposals"] == 0, "proposals"),
        ("close", c["active_deals"] > 0 and c["close_ready"] == 0, "close_ready"),
        ("cash", c["close_ready"] > 0 and c["realized_events"] == 0, "realized_events"),
    ]
    for lane, blocked, target in checks:
        if blocked:
            return {"lane": lane, "target_metric": target, "reason": f"El embudo tiene evidencia aguas arriba pero {target}=0."}
    return {"lane": "flowing", "target_metric": "realized_events", "reason": "No hay un corte absoluto; optimizar la conversión más débil."}


def revenue_funnel_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    cycle = int(state.get("ticks") or 0)
    counts = _counts(state)
    previous = state.get("revenue_funnel", {}) or {}
    previous_counts = previous.get("counts", {}) or {}
    deltas = {k: counts[k] - int(previous_counts.get(k) or 0) for k in counts}
    bottleneck = _bottleneck(counts)
    snapshot = {
        "version": VERSION,
        "status": "active",
        "updated_at": utcnow(),
        "cycle": cycle,
        "counts": counts,
        "deltas": deltas,
        "conversion_rates": _rates(counts),
        "bottleneck": bottleneck,
        "truth_rule": "activity_is_not_progress; only verified stage transitions count as funnel movement",
    }
    history = list(state.get("revenue_funnel_history", []) or [])
    history.append({"cycle": cycle, "updated_at": snapshot["updated_at"], "counts": counts, "deltas": deltas, "bottleneck": bottleneck})
    state["revenue_funnel_history"] = history[-MAX_HISTORY:]
    state["revenue_funnel"] = snapshot
    return snapshot
