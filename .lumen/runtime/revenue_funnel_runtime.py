from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from canonical_revenue_truth_runtime import canonical_revenue_truth_tick

VERSION = "1.1-causal-revenue-funnel-canonical"
MAX_HISTORY = 96


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _real_offers(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [x for x in state.get("offers", []) or [] if str(x.get("source") or "").lower() not in {"demo", "demo/simulación", "simulation", "simulated"}]


def _realized(state: Dict[str, Any]) -> int:
    statuses = {"realized", "realized_partial", "received", "paid", "settled", "completed", "collected"}
    return sum(1 for x in state.get("revenue_ledger", []) or [] if str(x.get("status") or "").lower() in statuses)


def _counts(state: Dict[str, Any], truth: Dict[str, Any]) -> Dict[str, int]:
    accounts = list(state.get("candidate_accounts", []) or [])
    buyers = [x for x in accounts if x.get("type") == "buyer" and x.get("verified_company")]
    verified_contacts = [x for x in accounts if x.get("verified_company") and (x.get("commercial_channel_verified") or x.get("verified_contact"))]
    tc = truth.get("counts", {}) or {}
    canonical_opp_ids = set(str(x) for x in truth.get("canonical_opportunity_ids", []) or [])
    canonical_deal_ids = set(str(x) for x in truth.get("canonical_deal_ids", []) or [])
    rfq_ready = [x for x in state.get("interlocution_cases", []) or [] if x.get("supplier_rfq_ready") and str(x.get("opportunity_id") or "") in canonical_opp_ids]
    quotes = list(state.get("supplier_quotes", []) or []) + list(state.get("quotes", []) or [])
    offers = _real_offers(state)
    proposals = list(state.get("proposals", []) or [])
    return {
        "research_leads": len(state.get("research_leads", []) or []),
        "verified_companies": sum(1 for x in accounts if x.get("verified_company")),
        "verified_contacts": len(verified_contacts),
        "verified_buyers": len(buyers),
        "buyers_with_demand": int(tc.get("buyers_with_verified_demand") or 0),
        "market_opportunities": int(tc.get("canonical_opportunities") or 0),
        "raw_market_opportunities": int(tc.get("raw_market_opportunities") or 0),
        "rfq_ready": len(rfq_ready),
        "quotes": len(quotes),
        "real_offers": len(offers),
        "proposals": len(proposals),
        "active_deals": int(tc.get("canonical_active_deals") or 0),
        "raw_deals": int(tc.get("raw_deals") or 0),
        "closing_eligible_deals": int(tc.get("closing_eligible_deals") or 0),
        "close_ready": int(tc.get("canonical_close_ready") or 0),
        "quarantined_deals": int(tc.get("quarantined_deals") or 0),
        "realized_events": _realized(state),
    }


def _rate(num: int, den: int) -> float | None:
    return None if den <= 0 else round(num / den * 100.0, 1)


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


def revenue_funnel_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    cycle = int(state.get("ticks") or 0)
    truth = canonical_revenue_truth_tick(state)
    counts = _counts(state, truth)
    previous = state.get("revenue_funnel", {}) or {}
    previous_counts = previous.get("counts", {}) or {}
    deltas = {k: counts[k] - int(previous_counts.get(k) or 0) for k in counts}
    lane = str(truth.get("recommended_lane") or "demand_discovery")
    lane_map = {"opportunity_building": "opportunity", "quote_creation": "quote", "verification_contact": "contact", "demand_discovery": "demand", "closing": "close"}
    bottleneck = {
        "lane": lane_map.get(lane, lane),
        "target_metric": truth.get("target_metric"),
        "reason": truth.get("reason"),
    }
    snapshot = {
        "version": VERSION,
        "status": "active",
        "updated_at": utcnow(),
        "cycle": cycle,
        "counts": counts,
        "deltas": deltas,
        "conversion_rates": _rates(counts),
        "bottleneck": bottleneck,
        "canonical_truth_version": truth.get("version"),
        "truth_rule": "activity_is_not_progress; only canonical evidence-backed stage transitions count as funnel movement",
    }
    history = list(state.get("revenue_funnel_history", []) or [])
    history.append({"cycle": cycle, "updated_at": snapshot["updated_at"], "counts": counts, "deltas": deltas, "bottleneck": bottleneck})
    state["revenue_funnel_history"] = history[-MAX_HISTORY:]
    state["revenue_funnel"] = snapshot
    return snapshot
