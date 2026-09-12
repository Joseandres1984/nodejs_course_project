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
from opportunity_deep_dive import deep_dive_tick
from quote_engine import quote_tick
from preclose_gate import preclose_tick
from relationship_memory import relationship_tick
from counterparty_scorecards import scorecards_tick
from profit_learning import learning_tick
from executive_director import plan_tick
from entrepreneurial_drive import drive_tick
from mission_scout import mission_scout_tick
from professional_os import professional_os_tick
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
    scout = scout_tick(STATE)
    intelligence = qualify_tick(STATE)
    verification = verification_tick(STATE)
    demand_intelligence = demand_intelligence_tick(STATE)
    contacts = contact_tick(STATE)

    # 2) Build only evidence-backed opportunities and formalize the buyer requirement.
    market_pipeline = build_market_pipeline(STATE)
    interlocutor = interlocutor_tick(STATE)

    # 3) Treat the strongest real opportunities as dedicated attack dossiers. Deep Dive can spend a small
    # bounded research budget to deepen buyer evidence and build supplier competition, but never lowers trust gates.
    deep_dive = deep_dive_tick(STATE)

    # 4) Receive counterpart responses, normalize quotes and only then let commercial autopilot advance.
    inbox = fetch_unseen(STATE)
    applied = apply_inbox_to_deals(STATE)
    quotes = quote_tick(STATE)
    result = autopilot_tick("worker autónomo")

    # 5) No real deal may remain close-ready without identity, terms, tax/payment and human approval controls.
    preclose = preclose_tick(STATE)

    # 6) Maintain observable commercial memory and objective counterparty scorecards.
    relationships = relationship_tick(STATE)
    scorecards = scorecards_tick(STATE)

    # 7) Learn which categories and search strategies repeatedly produce real commercial progress.
    # Sparse evidence is shrunk toward neutral so LUMEN does not overfit one lucky result.
    profit_learning = learning_tick(STATE)

    # 8) Executive layer chooses the highest-value bottleneck; Entrepreneurial Drive combines it with
    # learned profit signals and turns it into a persistent mission portfolio.
    executive_plan = plan_tick(STATE)
    entrepreneurial_drive = drive_tick(STATE)

    # 9) Mission Scout spends remaining research budget according to the learned exploit/explore policy.
    # New leads still pass through the normal verification pipeline; no trust gate is bypassed.
    mission_scout = mission_scout_tick(STATE)

    # 10) Professional OS converts all current signals into one ranked operating queue, prepares follow-ups,
    # supplier competition boards, approval briefs, postmortems and real post-sale expansion plans.
    professional_os = professional_os_tick(STATE)

    # 11) Every outbound message, including follow-ups materialized by Professional OS, must pass both reviews.
    communication = review_outbox(STATE)
    quality = quality_tick(STATE)
    outbound = send_pending(STATE, LIVE_OUTBOUND)

    STATE["connector_telemetry"] = {
        "updated_at": utcnow(),
        "scout": scout,
        "scout_status": scout_status(),
        "mission_scout": mission_scout,
        "lead_intelligence": intelligence,
        "company_verification": verification,
        "demand_intelligence": demand_intelligence,
        "contact_intelligence": contacts,
        "market_pipeline": market_pipeline,
        "interlocutor": interlocutor,
        "opportunity_deep_dive": deep_dive,
        "quote_engine": quotes,
        "preclose_gate": preclose,
        "relationships": relationships,
        "scorecards": scorecards,
        "profit_learning": profit_learning,
        "executive_plan": executive_plan,
        "entrepreneurial_drive": entrepreneurial_drive,
        "professional_os": professional_os,
        "communication": communication,
        "quality_gate": quality,
        "inbox": inbox,
        "applied": applied,
        "outbound": outbound,
        "mail": mail_status(),
        "postgres": dict(DB_STATUS),
        "live_outbound": bool(LIVE_OUTBOUND),
    }

    # 12) KPIs are computed after telemetry so health and funnel metrics reflect this exact cycle.
    business_kpis = kpi_tick(STATE)
    STATE["connector_telemetry"]["business_kpis"] = business_kpis

    STATE["research_lead_count"] = len(STATE.get("research_leads", []))
    STATE["candidate_account_count"] = len(STATE.get("candidate_accounts", []))
    STATE["verified_company_count"] = sum(1 for x in STATE.get("candidate_accounts", []) if x.get("verified_company"))
    STATE["verified_corporate_contact_count"] = sum(1 for x in STATE.get("candidate_accounts", []) if x.get("commercial_channel_verified"))
    STATE["market_opportunity_count"] = len(STATE.get("market_opportunities", []))
    STATE["interlocution_case_count"] = len(STATE.get("interlocution_cases", []))
    STATE["deep_dive_case_count"] = len(STATE.get("deep_dive_cases", []))
    STATE["operating_action_count"] = len(STATE.get("operating_action_queue", []))
    STATE["decision_ledger_count"] = len(STATE.get("decision_ledger", []))
    persisted_after_connectors = save_state()

    print({
        "result": result,
        "scout": scout,
        "scout_status": scout_status(),
        "mission_scout": mission_scout,
        "lead_intelligence": intelligence,
        "company_verification": verification,
        "demand_intelligence": demand_intelligence,
        "contact_intelligence": contacts,
        "market_pipeline": market_pipeline,
        "interlocutor": interlocutor,
        "deep_dive_primary_case": deep_dive.get("primary_case_id"),
        "deep_dive_primary_win_score": deep_dive.get("primary_win_score"),
        "deep_dive_primary_next_action": deep_dive.get("primary_next_action"),
        "deep_dive_research": deep_dive.get("research", {}),
        "quote_engine": quotes,
        "preclose_gate": preclose,
        "relationships": relationships,
        "scorecards": scorecards,
        "profit_learning_primary_category": profit_learning.get("primary_category"),
        "profit_learning_exploit_pct": profit_learning.get("exploit_pct"),
        "profit_learning_explore_pct": profit_learning.get("explore_pct"),
        "executive_primary": executive_plan.get("primary", {}).get("code"),
        "entrepreneurial_primary": entrepreneurial_drive.get("primary", {}).get("action"),
        "active_missions": entrepreneurial_drive.get("active_missions", 0),
        "stale_deals": entrepreneurial_drive.get("stale_deals", 0),
        "kill_candidates": entrepreneurial_drive.get("kill_candidates", 0),
        "professional_os_top_action": (professional_os.get("top_action") or {}).get("title"),
        "professional_os_queue_size": professional_os.get("queue_size", 0),
        "professional_os_autonomous": professional_os.get("autonomous_actions", 0),
        "professional_os_human": professional_os.get("human_decisions_required", 0),
        "followups_materialized": professional_os.get("followups_materialized", 0),
        "supplier_competitions": professional_os.get("supplier_competitions", 0),
        "approval_briefs": professional_os.get("approval_briefs", 0),
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
        "deep_dive_case_count": STATE.get("deep_dive_case_count", 0),
        "operating_action_count": STATE.get("operating_action_count", 0),
        "decision_ledger_count": STATE.get("decision_ledger_count", 0),
    }, flush=True)

    if not result.get("persisted") or not persisted_after_connectors:
        raise SystemExit(2)
