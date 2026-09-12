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
from cfo_engine import cfo_tick
from profit_learning import learning_tick
from war_room import war_room_tick
from corporate_brain import corporate_brain_tick
from growth_expansion import growth_expansion_tick
from trade_logistics import trade_logistics_tick
from executive_director import plan_tick
from entrepreneurial_drive import drive_tick
from mission_scout import mission_scout_tick
from professional_os import professional_os_tick
from financial_chief_of_staff import financial_priority_tick
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

    # 3) Treat the strongest real opportunities as dedicated attack dossiers.
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

    # 7) CFO separates pipeline, probability-weighted profit, risk-adjusted profit, committed economics,
    # realized economics, collection exposure and concentration. It never invents a cash balance or runway.
    cfo = cfo_tick(STATE)

    # 8) Learn which categories and search strategies repeatedly produce real commercial progress.
    profit_learning = learning_tick(STATE)

    # 9) War Room ranks where money is most likely to be created before strategy is chosen.
    war_room = war_room_tick(STATE)

    # 10) Corporate Brain converts current economics + learning + funnel state into persistent monthly/quarterly
    # objectives, controlled experiments and a stable long-horizon strategy. It can steer reversible allocation only.
    corporate_brain = corporate_brain_tick(STATE)

    # 11) Growth & Expansion Brain tests lookalike buyers, adjacent markets and international supplier depth.
    # It spends only a bounded shared research budget and every discovered lead still goes through normal trust gates.
    growth_expansion = growth_expansion_tick(STATE)

    # 12) International Trade & Logistics models landed cost only from explicit, traceable trade inputs and compares
    # local vs. cross-border sourcing only when currency, technical equivalence and cost coverage are sufficient.
    trade_logistics = trade_logistics_tick(STATE)

    # 13) Executive Director receives strategy + growth + trade options while resolving hard operational gaps first.
    executive_plan = plan_tick(STATE)
    entrepreneurial_drive = drive_tick(STATE)

    # 14) Mission Scout executes current research using Corporate Brain allocation + Entrepreneurial Drive.
    mission_scout = mission_scout_tick(STATE)

    # 15) Professional OS turns current signals into a ranked action queue and operational artifacts.
    professional_os = professional_os_tick(STATE)

    # 16) Financial Chief of Staff merges War Room priorities into the operating queue.
    financial_chief = financial_priority_tick(STATE)

    # 17) Every outbound message must pass relationship-oriented communication review AND quality authorization.
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
        "cfo": cfo,
        "profit_learning": profit_learning,
        "war_room": war_room,
        "corporate_brain": corporate_brain,
        "growth_expansion": growth_expansion,
        "trade_logistics": trade_logistics,
        "executive_plan": executive_plan,
        "entrepreneurial_drive": entrepreneurial_drive,
        "professional_os": professional_os,
        "financial_chief_of_staff": financial_chief,
        "communication": communication,
        "quality_gate": quality,
        "inbox": inbox,
        "applied": applied,
        "outbound": outbound,
        "mail": mail_status(),
        "postgres": dict(DB_STATUS),
        "live_outbound": bool(LIVE_OUTBOUND),
    }

    # 18) KPIs are computed after telemetry so health and funnel metrics reflect this exact cycle.
    business_kpis = kpi_tick(STATE)
    business_kpis["finance"] = cfo.get("financial_snapshot", {})
    business_kpis["finance_warnings"] = cfo.get("warnings", [])
    business_kpis["war_room"] = {
        "primary_money_move": war_room.get("primary_money_move"),
        "alerts": war_room.get("alerts", []),
        "top_opportunities": len(war_room.get("top_money_opportunities", [])),
    }
    business_kpis["corporate_brain"] = {
        "strategy_mode": corporate_brain.get("strategy", {}).get("mode"),
        "strategy_epoch": corporate_brain.get("strategy", {}).get("epoch"),
        "strategy_streak_cycles": corporate_brain.get("strategy", {}).get("streak_cycles"),
        "monthly_objectives": corporate_brain.get("objectives", {}).get("monthly", []),
        "quarterly_objectives": corporate_brain.get("objectives", {}).get("quarterly", []),
        "active_experiments": corporate_brain.get("active_experiments", []),
    }
    business_kpis["growth_expansion"] = {
        "ready": growth_expansion.get("readiness", {}).get("ready"),
        "readiness_score": growth_expansion.get("readiness", {}).get("score"),
        "primary_expansion": growth_expansion.get("primary_expansion"),
        "research": growth_expansion.get("research"),
        "cross_sell_candidates": len(growth_expansion.get("cross_sell_investigations", [])),
        "sourcing_spread_candidates": len(growth_expansion.get("sourcing_spread_candidates", [])),
    }
    business_kpis["trade_logistics"] = {
        "cross_border_cases": trade_logistics.get("cross_border_cases"),
        "landed_cost_ready": trade_logistics.get("landed_cost_ready"),
        "trade_data_incomplete": trade_logistics.get("trade_data_incomplete"),
        "route_comparisons_ready": trade_logistics.get("route_comparisons_ready"),
        "international_suppliers_without_quotes": trade_logistics.get("international_suppliers_without_quotes"),
        "primary_directive": trade_logistics.get("primary_directive"),
    }
    STATE["business_kpis"] = business_kpis
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

    finance_snapshot = cfo.get("financial_snapshot", {})
    primary_money = war_room.get("primary_money_move") or {}
    strategy = corporate_brain.get("strategy", {}) or {}
    objectives = corporate_brain.get("objectives", {}) or {}
    growth_primary = growth_expansion.get("primary_expansion") or {}
    trade_primary = trade_logistics.get("primary_directive") or {}
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
        "cfo_risk_adjusted_expected_profit_usd": finance_snapshot.get("risk_adjusted_expected_profit_usd"),
        "cfo_realized_profit_usd": finance_snapshot.get("realized_profit_usd"),
        "cfo_collection_exposure_usd": finance_snapshot.get("gross_unsettled_receivable_usd"),
        "cfo_warnings": cfo.get("warnings", []),
        "profit_learning_primary_category": profit_learning.get("primary_category"),
        "war_room_primary_deal": primary_money.get("deal_id") or primary_money.get("deep_dive_case_id"),
        "war_room_money_score": primary_money.get("money_score"),
        "corporate_strategy_mode": strategy.get("mode"),
        "corporate_strategy_epoch": strategy.get("epoch"),
        "corporate_strategy_streak": strategy.get("streak_cycles"),
        "corporate_monthly_objectives": len(objectives.get("monthly", [])),
        "corporate_quarterly_objectives": len(objectives.get("quarterly", [])),
        "corporate_active_experiments": len(corporate_brain.get("active_experiments", [])),
        "growth_ready": growth_expansion.get("readiness", {}).get("ready"),
        "growth_readiness_score": growth_expansion.get("readiness", {}).get("score"),
        "growth_primary_kind": growth_primary.get("kind"),
        "growth_primary_market": growth_primary.get("market"),
        "growth_primary_category": growth_primary.get("category"),
        "growth_primary_score": growth_primary.get("score"),
        "growth_research": growth_expansion.get("research", {}),
        "growth_cross_sell_candidates": len(growth_expansion.get("cross_sell_investigations", [])),
        "growth_sourcing_spreads": len(growth_expansion.get("sourcing_spread_candidates", [])),
        "trade_mode": trade_primary.get("mode"),
        "trade_deal_id": trade_primary.get("deal_id"),
        "trade_landed_savings_pct": trade_primary.get("landed_savings_pct"),
        "trade_cross_border_cases": trade_logistics.get("cross_border_cases"),
        "trade_landed_cost_ready": trade_logistics.get("landed_cost_ready"),
        "trade_route_comparisons_ready": trade_logistics.get("route_comparisons_ready"),
        "executive_primary": executive_plan.get("primary", {}).get("code"),
        "entrepreneurial_primary": entrepreneurial_drive.get("primary", {}).get("action"),
        "active_missions": entrepreneurial_drive.get("active_missions", 0),
        "professional_os_top_action": (financial_chief.get("top_action") or {}).get("title"),
        "professional_os_queue_size": financial_chief.get("queue_size", 0),
        "professional_os_autonomous": financial_chief.get("autonomous_actions", 0),
        "professional_os_human": financial_chief.get("human_decisions_required", 0),
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
