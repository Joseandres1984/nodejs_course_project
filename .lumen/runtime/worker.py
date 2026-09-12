from datetime import datetime, timezone

from app import load_state, seed_demo, autopilot_tick, STATE, DB_STATUS, save_state, LIVE_OUTBOUND
from mail_connector import fetch_unseen, apply_inbox_to_deals, send_pending, connector_status as mail_status
from scout_connector import scout_tick, status as scout_status
from lead_intelligence import qualify_tick
from company_verifier import verification_tick
from market_pipeline import build_market_pipeline


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


if __name__ == "__main__":
    loaded = load_state()
    if not loaded or not STATE.get("buyers"):
        seed_demo()

    scout = scout_tick(STATE)
    intelligence = qualify_tick(STATE)
    verification = verification_tick(STATE)
    market_pipeline = build_market_pipeline(STATE)
    inbox = fetch_unseen(STATE)
    applied = apply_inbox_to_deals(STATE)
    result = autopilot_tick("worker autónomo")
    outbound = send_pending(STATE, LIVE_OUTBOUND)

    STATE["connector_telemetry"] = {
        "updated_at": utcnow(),
        "scout": scout,
        "scout_status": scout_status(),
        "lead_intelligence": intelligence,
        "company_verification": verification,
        "market_pipeline": market_pipeline,
        "inbox": inbox,
        "applied": applied,
        "outbound": outbound,
        "mail": mail_status(),
        "postgres": dict(DB_STATUS),
        "live_outbound": bool(LIVE_OUTBOUND),
    }
    STATE["research_lead_count"] = len(STATE.get("research_leads", []))
    STATE["candidate_account_count"] = len(STATE.get("candidate_accounts", []))
    STATE["verified_company_count"] = sum(1 for x in STATE.get("candidate_accounts", []) if x.get("verified_company"))
    STATE["market_opportunity_count"] = len(STATE.get("market_opportunities", []))
    STATE["decision_ledger_count"] = len(STATE.get("decision_ledger", []))
    persisted_after_connectors = save_state()

    print({
        "result": result,
        "scout": scout,
        "scout_status": scout_status(),
        "lead_intelligence": intelligence,
        "company_verification": verification,
        "market_pipeline": market_pipeline,
        "inbox": inbox,
        "applied": applied,
        "outbound": outbound,
        "mail": mail_status(),
        "postgres": DB_STATUS,
        "persisted_after_connectors": persisted_after_connectors,
        "research_lead_count": STATE.get("research_lead_count", 0),
        "candidate_account_count": STATE.get("candidate_account_count", 0),
        "verified_company_count": STATE.get("verified_company_count", 0),
        "market_opportunity_count": STATE.get("market_opportunity_count", 0),
        "decision_ledger_count": STATE.get("decision_ledger_count", 0),
    }, flush=True)

    if not result.get("persisted") or not persisted_after_connectors:
        raise SystemExit(2)
