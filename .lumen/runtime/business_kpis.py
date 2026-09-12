from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from autonomous_management_runtime import executive_management_cycle
from business_controller import business_controller_tick
from capital_margin_intelligence import capital_margin_tick
from deal_room import deal_room_tick
from negotiation_intelligence import negotiation_intelligence_tick
from order_to_cash import order_to_cash_tick
from venture_attribution import propagate_venture_attribution
from venture_builder import venture_builder_tick


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator * 100.0, 1)


def kpi_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    leads = state.get("research_leads", [])
    accounts = state.get("candidate_accounts", [])
    opportunities = state.get("market_opportunities", [])
    cases = state.get("interlocution_cases", [])
    outbox = state.get("outbox", [])
    inbox = state.get("inbox", [])
    offers = state.get("offers", [])
    proposals = state.get("proposals", [])
    deals = state.get("deals", [])

    verified = [x for x in accounts if x.get("verified_company")]
    buyers = [x for x in verified if x.get("type") == "buyer"]
    suppliers = [x for x in verified if x.get("type") == "supplier"]
    demand_buyers = [x for x in buyers if x.get("demand_signal")]
    contactable = [x for x in verified if x.get("commercial_channel_verified")]
    email_verified = [x for x in verified if x.get("verified_contact")]
    requirement_ready = [x for x in cases if x.get("supplier_rfq_ready")]
    sent = [x for x in outbox if x.get("status") == "sent"]
    real_offers = [x for x in offers if x.get("source") != "demo/simulación"]
    viable_deals = [x for x in deals if x.get("economics", {}).get("viable")]
    close_ready = [x for x in deals if x.get("stage") in {"listo para cerrar", "autorizado para cierre", "listo para cierre aprobado"}]

    funnel = {
        "research_leads": len(leads),
        "candidate_accounts": len(accounts),
        "verified_companies": len(verified),
        "verified_buyers": len(buyers),
        "verified_suppliers": len(suppliers),
        "buyers_with_public_demand": len(demand_buyers),
        "verified_commercial_channels": len(contactable),
        "verified_corporate_emails": len(email_verified),
        "evidence_backed_opportunities": len(opportunities),
        "interlocution_cases": len(cases),
        "requirements_ready_for_rfq": len(requirement_ready),
        "outbound_sent": len(sent),
        "inbound_received": len(inbox),
        "real_offers": len(real_offers),
        "proposals": len(proposals),
        "viable_deals": len(viable_deals),
        "close_ready": len(close_ready),
    }

    conversion = {
        "lead_to_candidate_pct": _rate(len(accounts), len(leads)),
        "candidate_to_verified_pct": _rate(len(verified), len(accounts)),
        "verified_buyer_to_demand_pct": _rate(len(demand_buyers), len(buyers)),
        "verified_to_contactable_pct": _rate(len(contactable), len(verified)),
        "opportunity_to_requirement_ready_pct": _rate(len(requirement_ready), len(opportunities)),
        "sent_to_response_pct": _rate(len(inbox), len(sent)),
        "real_offer_to_proposal_pct": _rate(len(proposals), len(real_offers)),
    }

    telemetry = state.get("connector_telemetry", {})
    health = {
        "postgres_connected": bool(telemetry.get("postgres", {}).get("connected")),
        "smtp_configured": bool(telemetry.get("mail", {}).get("smtp_configured")),
        "imap_configured": bool(telemetry.get("mail", {}).get("imap_configured")),
        "live_outbound": bool(telemetry.get("live_outbound")),
        "scout_errors_last_tick": int(telemetry.get("scout", {}).get("errors") or 0),
        "verification_errors_last_tick": int(telemetry.get("company_verification", {}).get("errors") or 0),
        "contact_errors_last_tick": int(telemetry.get("contact_intelligence", {}).get("errors") or 0),
    }

    bottlenecks = []
    if len(suppliers) and not len(buyers):
        bottlenecks.append("buyer_gap")
    if len(buyers) and not len(demand_buyers):
        bottlenecks.append("demand_gap")
    if len(verified) and not len(contactable):
        bottlenecks.append("contact_gap")
    if len(opportunities) and not len(requirement_ready):
        bottlenecks.append("requirement_gap")
    if len(real_offers) and not len(proposals):
        bottlenecks.append("proposal_gap")

    executive_management = executive_management_cycle(state)
    capital_margin = capital_margin_tick(state)
    business_controller = business_controller_tick(state)

    # Negotiation Intelligence learns only from persisted evidence and can prepare at most one bounded,
    # nonbinding proactive supplier negotiation for the next controlled outbound cycle.
    negotiation_intelligence = negotiation_intelligence_tick(state)

    # Order-to-Cash closes the economic loop after a REAL transaction: delivery, acceptance, invoicing,
    # payment follow-up and customer success. Simulation transactions are explicitly excluded.
    order_to_cash = order_to_cash_tick(state)

    venture_attribution = propagate_venture_attribution(state)
    venture_builder = venture_builder_tick(state)

    # Deal Room is last so dossiers capture management, capital, negotiation and post-sale context.
    deal_room = deal_room_tick(state)

    report = {
        "updated_at": utcnow(),
        "funnel": funnel,
        "conversion": conversion,
        "health": health,
        "bottlenecks": bottlenecks,
        "executive_management": executive_management,
        "capital_margin_intelligence": capital_margin,
        "business_controller": business_controller,
        "negotiation_intelligence": negotiation_intelligence,
        "order_to_cash": order_to_cash,
        "venture_attribution": venture_attribution,
        "venture_builder": venture_builder,
        "deal_room": deal_room,
    }
    state["business_kpis"] = report
    return report
