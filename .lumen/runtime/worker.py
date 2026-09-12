from datetime import datetime, timezone

from app import load_state, seed_demo, autopilot_tick, STATE, DB_STATUS, save_state, LIVE_OUTBOUND
from mail_connector import fetch_unseen, apply_inbox_to_deals, send_pending, connector_status as mail_status
from scout_connector import scout_tick, status as scout_status
from lead_intelligence import qualify_tick
from company_verifier import verification_tick
from demand_intelligence import demand_intelligence_tick
from contact_intelligence import contact_tick
from market_pipeline import build_market_pipeline
from interlocutor_engine import interlocutor_tick
from quote_engine import quote_tick
from preclose_gate import preclose_tick
from relationship_memory import relationship_tick
from counterparty_scorecards import scorecards_tick
from executive_director import plan_tick
from entrepreneurial_drive import drive_tick
from communication_director import review_outbox
from quality_gate import quality_tick
from business_kpis import kpi_tick


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


if __name__ == "__main__":
    loaded = load_state()
    if not loaded or not STATE.get("buyers"):
        seed_demo()

    # 1) Observe the market and convert raw public signals into verified evidence.
    # Scout consumes the entrepreneurial mission selected on the previous cycle,
    # creating a closed planning -> action -> evidence -> planning loop.
    scout = scout_tick(STATE)
    intelligence = qualify_tick(STATE)
    verification = verification_tick(STATE)
    demand_intelligence = demand_intelligence_tick(STATE)
    contacts = contact_tick(STATE)

    # 2) Build only evidence-backed opportunities and manage LUMEN's role as B2B interlocutor.
    market_pipeline = build_market_pipeline(STATE)
    interlocutor = interlocutor_tick(STATE)

    # 3) Receive counterpart responses, normalize quotes and only then let commercial autopilot advance.
    inbox = fetch_unseen(STATE)
    applied = apply_inbox_to_deals(STATE)
    quotes = quote_tick(STATE)
    result = autopilot_tick("worker autónomo")

    # 4) No real deal may remain close-ready without identity, terms, tax/payment and human approval controls.
    preclose = preclose_tick(STATE)

    # 5) Maintain observable commercial memory and objective counterparty scorecards.
    relationships = relationship_tick(STATE)
    scorecards = scorecards_tick(STATE)

    # 6) Executive layer chooses the highest-value bottleneck; Entrepreneurial Drive turns it into
    # a persistent mission portfolio, tracks stagnation and allocates attention for the next cycle.
    executive_plan = plan_tick(STATE)
    entrepreneurial_drive = drive_tick(STATE)

    # 7) Every outbound message must pass relationship-oriented communication review AND quality authorization.
    communication = review_outbox(STATE)
    quality = quality_tick(STATE)
    outbound = send_pending(STATE, LIVE_OUTBOUND)

    STATE["connector_telemetry"] = {
        "updated_at": utcnow(),
        "scout": scout,
        "scout_status": scout_status(),
        "lead_intelligence": intelligence,
        "company_verification": verification,
        "demand_intelligence": demand_intelligence,
        "contact_intelligence": contacts,
        "market_pipeline": market_pipeline,
        "interlocutor": interlocutor,
        "quote_engine": quotes,
        "preclose_gate": preclose,
        "relationships": relationships,
        "scorecards": scorecards,
        "executive_plan": executive_plan,
        "entrepreneurial_drive": entrepreneurial_drive,
        "communication": communication,
        "quality_gate": quality,
        "inbox": inbox,
        "applied": applied,
        "outbound": outbound,
        "mail": mail_status(),
        "postgres": dict(DB_STATUS),
        "live_outbound": bool(LIVE_OUTBOUND),
    }

    # 8) KPIs are computed after telemetry so health and funnel metrics reflect this exact cycle.
    business_kpis = kpi_tick(STATE)
    STATE["connector_telemetry"]["business_kpis"] = business_kpis

    STATE["research_lead_count"] = len(STATE.get("research_leads", []))
    STATE["candidate_account_count"] = len(STATE.get("candidate_accounts", []))
    STATE["verified_company_count"] = sum(1 for x in STATE.get("candidate_accounts", []) if x.get("verified_company"))
    STATE["verified_corporate_contact_count"] = sum(1 for x in STATE.get("candidate_accounts", []) if x.get("commercial_channel_verified"))
    STATE["market_opportunity_count"] = len(STATE.get("market_opportunities", []))
    STATE["interlocution_case_count"] = len(STATE.get("interlocution_cases", []))
    STATE["decision_ledger_count"] = len(STATE.get("decision_ledger", []))
    persisted_after_connectors = save_state()

    print({
        "result": result,
        "scout": scout,
        "scout_status": scout_status(),
        "lead_intelligence": intelligence,
        "company_verification": verification,
        "demand_intelligence": demand_intelligence,
        "contact_intelligence": contacts,
        "market_pipeline": market_pipeline,
        "interlocutor": interlocutor,
        "quote_engine": quotes,
        "preclose_gate": preclose,
        "relationships": relationships,
        "scorecards": scorecards,
        "executive_primary": executive_plan.get("primary", {}).get("code"),
        "entrepreneurial_primary": entrepreneurial_drive.get("primary", {}).get("action"),
        "active_missions": entrepreneurial_drive.get("active_missions", 0),
        "stale_deals": entrepreneurial_drive.get("stale_deals", 0),
        "kill_candidates": entrepreneurial_drive.get("kill_candidates", 0),
        "communication": communication,
        "quality_gate": quality,
        "inbox": inbox,
        "applied": applied,
        "outbound": outbound,
        "mail": mail_status(),
        "postgres": DB_STATUS,
        "business_funnel": business_kpis.get("funnel", {}),
        "business_bottlenecks": business_kpis.get("bottlenecks", []),
        "persisted_after_connectors": persisted_after_connectors,
        "research_lead_count": STATE.get("research_lead_count", 0),
        "candidate_account_count": STATE.get("candidate_account_count", 0),
        "verified_company_count": STATE.get("verified_company_count", 0),
        "verified_corporate_contact_count": STATE.get("verified_corporate_contact_count", 0),
        "market_opportunity_count": STATE.get("market_opportunity_count", 0),
        "interlocution_case_count": STATE.get("interlocution_case_count", 0),
        "decision_ledger_count": STATE.get("decision_ledger_count", 0),
    }, flush=True)

    if not result.get("persisted") or not persisted_after_connectors:
        raise SystemExit(2)
