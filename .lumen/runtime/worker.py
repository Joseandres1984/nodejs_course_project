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
from document_intelligence import document_intelligence_tick
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
from commercial_execution import commercial_execution_tick
from enterprise_knowledge import enterprise_knowledge_tick
from executive_director import plan_tick
from entrepreneurial_drive import drive_tick
from mission_scout import mission_scout_tick
from professional_os import professional_os_tick
from financial_chief_of_staff import financial_priority_tick
from communication_director import review_outbox
from quality_gate import quality_tick
from business_kpis import kpi_tick
from autonomous_coo import begin_operations_cycle, run_guarded, operations_control_tick


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def guarded(name, fn, *, critical=False, default=None):
    return run_guarded(STATE, name, fn, critical=critical, default={} if default is None else default)


if __name__ == "__main__":
    loaded = load_state()

    if not loaded and DB_STATUS.get("configured") and not DB_STATUS.get("connected"):
        print({
            "status": "safe_boot_abort",
            "reason": "persistence_unavailable",
            "postgres": DB_STATUS,
            "live_outbound": False,
        }, flush=True)
        raise SystemExit(3)

    if not loaded or not STATE.get("buyers"):
        seed_demo()

    operations_preflight = begin_operations_cycle(STATE, DB_STATUS, LIVE_OUTBOUND)

    # 1) Observe the market. Each engine is isolated: one exception cannot kill the entire company cycle.
    scout = guarded("Scout Connector", lambda: scout_tick(STATE))
    intelligence = guarded("Lead Intelligence", lambda: qualify_tick(STATE))
    verification = guarded("Company Verification", lambda: verification_tick(STATE))
    demand_intelligence = guarded("Demand Intelligence", lambda: demand_intelligence_tick(STATE))
    contacts = guarded("Contact Intelligence", lambda: contact_tick(STATE))

    # 2) Build evidence-backed opportunities and formalize buyer requirements.
    market_pipeline = guarded("Market Pipeline", lambda: build_market_pipeline(STATE))
    interlocutor = guarded("Interlocutor Engine", lambda: interlocutor_tick(STATE))

    # 3) Pursue strongest real opportunities with bounded Deep Dive research.
    deep_dive = guarded("Opportunity Deep Dive", lambda: deep_dive_tick(STATE))

    # 4) Receive responses and attach each email to its commercial case/deal before document parsing.
    inbox = guarded("Mail Inbox", lambda: fetch_unseen(STATE))
    applied = guarded("Inbox Deal Linker", lambda: apply_inbox_to_deals(STATE))

    # 5) Document Intelligence extracts PDF/XLS/XLSX/CSV/TXT evidence, materializes formal quotes only when
    # sender + deal are traceable, and never fabricates values from scanned/ambiguous documents.
    document_intelligence = guarded("Document Intelligence", lambda: document_intelligence_tick(STATE))
    quotes = guarded("Quote Engine", lambda: quote_tick(STATE))

    # 6) Legacy commercial autopilot remains isolated and persistence-aware.
    result = guarded(
        "Commercial Autopilot",
        lambda: autopilot_tick("worker autónomo"),
        critical=True,
        default={"persisted": False, "status": "autopilot_failed"},
    )

    # 7) Keep binding-risk controls independent from commercial execution.
    preclose = guarded("Preclose Gate", lambda: preclose_tick(STATE), critical=True)

    # 8) Commercial memory and counterparty scorecards.
    relationships = guarded("Relationship Memory", lambda: relationship_tick(STATE))
    scorecards = guarded("Counterparty Scorecards", lambda: scorecards_tick(STATE))

    # 9) Finance, learning and strategy.
    cfo = guarded("CFO", lambda: cfo_tick(STATE))
    profit_learning = guarded("Self-Learning Profit Engine", lambda: learning_tick(STATE))
    war_room = guarded("War Room", lambda: war_room_tick(STATE))
    corporate_brain = guarded("Corporate Brain", lambda: corporate_brain_tick(STATE))
    growth_expansion = guarded("Growth & Expansion Brain", lambda: growth_expansion_tick(STATE))
    trade_logistics = guarded("International Trade & Logistics Brain", lambda: trade_logistics_tick(STATE))

    # 10) RevOps owns the commercial conversation loop: requirement -> RFQ -> quote clarification ->
    # nonbinding negotiation -> next best action. It only materializes messages to verified corporate emails.
    commercial_execution = guarded("Commercial Execution Brain / RevOps", lambda: commercial_execution_tick(STATE))

    # 11) Enterprise Knowledge Graph turns documents, companies, quotes, opportunities, deals and outcomes into
    # persistent connected memory. Historical prices remain evidence only; they are never treated as current terms.
    enterprise_knowledge = guarded("Enterprise Knowledge Graph", lambda: enterprise_knowledge_tick(STATE))

    # 12) Executive allocation and autonomous market execution.
    executive_plan = guarded("Executive Director", lambda: plan_tick(STATE))
    entrepreneurial_drive = guarded("Entrepreneurial Drive", lambda: drive_tick(STATE))
    mission_scout = guarded("Mission Scout", lambda: mission_scout_tick(STATE))

    # 13) Operating system and money-prioritized action queue.
    professional_os = guarded("Professional OS", lambda: professional_os_tick(STATE))
    financial_chief = guarded("Financial Chief of Staff", lambda: financial_priority_tick(STATE))

    # 14) Outbound safety engines are critical. If either fails, Autonomous COO keeps outbound closed.
    communication = guarded("Communication Director", lambda: review_outbox(STATE), critical=True)
    quality = guarded("Quality Gate", lambda: quality_tick(STATE), critical=True)

    # 15) Autonomous COO evaluates system health, data integrity, persistence and engine failures.
    coo = operations_control_tick(
        STATE,
        DB_STATUS,
        live_outbound=LIVE_OUTBOUND,
        persistence_result=bool(result.get("persisted")),
    )
    safe_live_outbound = bool(LIVE_OUTBOUND and coo.get("operational_guard", {}).get("outbound_allowed"))

    # 16) Mail is fail-closed: production outbound only runs after COO + communication + quality authorization.
    outbound = guarded(
        "Mail Outbound",
        lambda: send_pending(STATE, safe_live_outbound),
        critical=True,
    )

    STATE["connector_telemetry"] = {
        "updated_at": utcnow(),
        "operations_preflight": operations_preflight,
        "autonomous_coo": coo,
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
        "document_intelligence": document_intelligence,
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
        "commercial_execution": commercial_execution,
        "enterprise_knowledge": enterprise_knowledge,
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
        "live_outbound_requested": bool(LIVE_OUTBOUND),
        "live_outbound_allowed": safe_live_outbound,
    }

    # 17) KPIs are informational and cannot stop core operations if their renderer fails.
    business_kpis = guarded("Business KPIs", lambda: kpi_tick(STATE))
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
    business_kpis["documents"] = {
        "documents": document_intelligence.get("documents"),
        "extracted": document_intelligence.get("extracted"),
        "ocr_required": document_intelligence.get("ocr_required"),
        "quotes_detected": document_intelligence.get("quotes_detected"),
        "offers_materialized": document_intelligence.get("offers_materialized"),
        "directive": document_intelligence.get("directive", {}),
    }
    business_kpis["enterprise_knowledge"] = {
        "nodes": enterprise_knowledge.get("nodes"),
        "edges": enterprise_knowledge.get("edges"),
        "historical_prices": enterprise_knowledge.get("historical_prices"),
        "categories": enterprise_knowledge.get("categories"),
        "company_profiles": enterprise_knowledge.get("company_profiles"),
        "reuse_candidates": enterprise_knowledge.get("reuse_candidates"),
        "directive": enterprise_knowledge.get("directive", {}),
    }
    business_kpis["commercial_execution"] = {
        "active_cases": commercial_execution.get("active_cases"),
        "status_counts": commercial_execution.get("status_counts", {}),
        "messages_created": commercial_execution.get("messages_created"),
        "inbound": commercial_execution.get("inbound", {}),
        "primary_case_id": commercial_execution.get("directive", {}).get("primary_case_id"),
        "primary_status": commercial_execution.get("directive", {}).get("primary_status"),
        "primary_next_action": commercial_execution.get("directive", {}).get("primary_next_action"),
    }
    business_kpis["operations"] = {
        "status": coo.get("status"),
        "health_score": coo.get("health_score"),
        "outbound_allowed": safe_live_outbound,
        "blockers": coo.get("operational_guard", {}).get("blockers", []),
        "warnings": coo.get("operational_guard", {}).get("warnings", []),
        "recovery_actions": coo.get("recovery_actions", []),
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
    STATE["document_count"] = len(STATE.get("document_registry", []))
    STATE["knowledge_node_count"] = len(STATE.get("enterprise_knowledge_graph", {}).get("nodes", []))
    STATE["knowledge_edge_count"] = len(STATE.get("enterprise_knowledge_graph", {}).get("edges", []))
    STATE["operating_action_count"] = len(STATE.get("operating_action_queue", []))
    STATE["decision_ledger_count"] = len(STATE.get("decision_ledger", []))

    persisted_after_connectors = save_state()

    finance_snapshot = cfo.get("financial_snapshot", {})
    primary_money = war_room.get("primary_money_move") or {}
    strategy = corporate_brain.get("strategy", {}) or {}
    objectives = corporate_brain.get("objectives", {}) or {}
    growth_primary = growth_expansion.get("primary_expansion") or {}
    trade_primary = trade_logistics.get("primary_directive") or {}
    revops_directive = commercial_execution.get("directive", {}) or {}
    document_directive = document_intelligence.get("directive", {}) or {}
    knowledge_directive = enterprise_knowledge.get("directive", {}) or {}
    print({
        "result": result,
        "autonomous_coo_status": coo.get("status"),
        "autonomous_coo_health_score": coo.get("health_score"),
        "autonomous_coo_blockers": coo.get("operational_guard", {}).get("blockers", []),
        "autonomous_coo_warnings": coo.get("operational_guard", {}).get("warnings", []),
        "outbound_requested": bool(LIVE_OUTBOUND),
        "outbound_allowed": safe_live_outbound,
        "engine_failures": len(coo.get("engine_health", {}).get("failed_now", [])),
        "engine_circuits_open": len(coo.get("engine_health", {}).get("circuits_open", [])),
        "data_integrity_critical": coo.get("data_integrity", {}).get("critical", 0),
        "recovery_actions": coo.get("recovery_actions", [])[:5],
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
        "document_count": document_intelligence.get("documents"),
        "document_ocr_required": document_directive.get("ocr_required"),
        "document_quotes_detected": document_intelligence.get("quotes_detected"),
        "document_offers_materialized": document_intelligence.get("offers_materialized"),
        "quote_engine": quotes,
        "knowledge_nodes": enterprise_knowledge.get("nodes"),
        "knowledge_edges": enterprise_knowledge.get("edges"),
        "knowledge_historical_prices": enterprise_knowledge.get("historical_prices"),
        "knowledge_reuse_candidates": knowledge_directive.get("reuse_candidates"),
        "preclose_gate": preclose,
        "cfo_risk_adjusted_expected_profit_usd": finance_snapshot.get("risk_adjusted_expected_profit_usd"),
        "cfo_realized_profit_usd": finance_snapshot.get("realized_profit_usd"),
        "profit_learning_primary_category": profit_learning.get("primary_category"),
        "war_room_primary_deal": primary_money.get("deal_id") or primary_money.get("deep_dive_case_id"),
        "war_room_money_score": primary_money.get("money_score"),
        "corporate_strategy_mode": strategy.get("mode"),
        "corporate_strategy_epoch": strategy.get("epoch"),
        "corporate_strategy_streak": strategy.get("streak_cycles"),
        "corporate_monthly_objectives": len(objectives.get("monthly", [])),
        "corporate_quarterly_objectives": len(objectives.get("quarterly", [])),
        "growth_ready": growth_expansion.get("readiness", {}).get("ready"),
        "growth_primary_market": growth_primary.get("market"),
        "growth_primary_category": growth_primary.get("category"),
        "trade_mode": trade_primary.get("mode"),
        "trade_deal_id": trade_primary.get("deal_id"),
        "trade_landed_savings_pct": trade_primary.get("landed_savings_pct"),
        "revops_primary_case": revops_directive.get("primary_case_id"),
        "revops_primary_status": revops_directive.get("primary_status"),
        "revops_primary_next_action": revops_directive.get("primary_next_action"),
        "revops_active_cases": revops_directive.get("active_cases"),
        "revops_messages_created": commercial_execution.get("messages_created"),
        "revops_inbound": commercial_execution.get("inbound", {}),
        "executive_primary": executive_plan.get("primary", {}).get("code"),
        "entrepreneurial_primary": entrepreneurial_drive.get("primary", {}).get("action"),
        "professional_os_top_action": (financial_chief.get("top_action") or {}).get("title"),
        "professional_os_queue_size": financial_chief.get("queue_size", 0),
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
        "deep_dive_case_count": STATE.get("deep_dive_case_count", 0),
        "operating_action_count": STATE.get("operating_action_count", 0),
        "decision_ledger_count": STATE.get("decision_ledger_count", 0),
    }, flush=True)

    if not bool(result.get("persisted")) or not persisted_after_connectors:
        raise SystemExit(2)
