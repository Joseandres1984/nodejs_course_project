from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from autonomous_goal_planner import autonomous_goal_planner_tick
from autonomous_management_runtime import executive_management_cycle
from business_controller import business_controller_tick
from capital_margin_intelligence import capital_margin_tick
from closing_orchestrator import closing_orchestrator_tick
from commission_settlement import commission_settlement_tick
from data_truth_engine import data_truth_tick, enforce_truth_on_closing
from deal_room import deal_room_tick
from decision_calibration import decision_calibration_tick
from growth_treasury import growth_treasury_tick
from negotiation_intelligence import negotiation_intelligence_tick
from order_to_cash import order_to_cash_tick
from portfolio_optimizer_v2 import portfolio_optimizer_v2_tick
from self_improvement_lab import self_improvement_tick
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
        "research_leads": len(leads), "candidate_accounts": len(accounts), "verified_companies": len(verified),
        "verified_buyers": len(buyers), "verified_suppliers": len(suppliers), "buyers_with_public_demand": len(demand_buyers),
        "verified_commercial_channels": len(contactable), "verified_corporate_emails": len(email_verified),
        "evidence_backed_opportunities": len(opportunities), "interlocution_cases": len(cases),
        "requirements_ready_for_rfq": len(requirement_ready), "outbound_sent": len(sent), "inbound_received": len(inbox),
        "real_offers": len(real_offers), "proposals": len(proposals), "viable_deals": len(viable_deals), "close_ready": len(close_ready),
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
    if len(suppliers) and not len(buyers): bottlenecks.append("buyer_gap")
    if len(buyers) and not len(demand_buyers): bottlenecks.append("demand_gap")
    if len(verified) and not len(contactable): bottlenecks.append("contact_gap")
    if len(opportunities) and not len(requirement_ready): bottlenecks.append("requirement_gap")
    if len(real_offers) and not len(proposals): bottlenecks.append("proposal_gap")

    # Truth first: stale/unknown facts are explicitly downgraded before economic prioritization.
    data_truth = data_truth_tick(state)

    executive_management = executive_management_cycle(state)
    capital_margin = capital_margin_tick(state)
    business_controller = business_controller_tick(state)
    negotiation_intelligence = negotiation_intelligence_tick(state)

    # Closing Orchestrator refreshes payment routing and protects LUMEN's economic entitlement.
    closing_orchestrator = closing_orchestrator_tick(state)
    truth_close_guard = enforce_truth_on_closing(state)
    closing_orchestrator = state.get("closing_orchestrator", {}) or closing_orchestrator
    payment_rails = state.get("payment_rails", {}) or {}

    order_to_cash = order_to_cash_tick(state)
    commission_settlement = commission_settlement_tick(state)

    # Growth planning uses only commission cash actually received.
    growth_treasury = growth_treasury_tick(state)
    venture_attribution = propagate_venture_attribution(state)
    venture_builder = venture_builder_tick(state)

    # Superior economic layer: define the active profit goal, calibrate confidence from observed outcomes,
    # then rank opportunities with truth/freshness + calibration penalties before allocating attention.
    goal_planner = autonomous_goal_planner_tick(state)
    decision_calibration = decision_calibration_tick(state)
    portfolio_optimizer = portfolio_optimizer_v2_tick(state, goal_planner)

    # Self-improvement diagnoses systematic failures and proposes bounded tests/change-sets.
    # It may autonomously schedule reversible low-authority tests, but never deploys code by itself.
    self_improvement = self_improvement_tick(state)

    # Deal Room is last so each dossier captures final truth, calibration, goal and portfolio decisions.
    deal_room = deal_room_tick(state)

    report = {
        "updated_at": utcnow(), "funnel": funnel, "conversion": conversion, "health": health, "bottlenecks": bottlenecks,
        "data_truth_engine": data_truth, "data_truth_close_guard": truth_close_guard,
        "decision_calibration": decision_calibration, "self_improvement_lab": self_improvement,
        "executive_management": executive_management, "capital_margin_intelligence": capital_margin,
        "business_controller": business_controller, "negotiation_intelligence": negotiation_intelligence,
        "closing_orchestrator": closing_orchestrator,
        "order_to_cash": order_to_cash, "payment_rails": payment_rails,
        "commission_settlement": commission_settlement, "growth_treasury": growth_treasury,
        "venture_attribution": venture_attribution, "venture_builder": venture_builder,
        "autonomous_goal_planner": goal_planner, "portfolio_optimizer": portfolio_optimizer,
        "deal_room": deal_room,
    }
    state["business_kpis"] = report
    return report
