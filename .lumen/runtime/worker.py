from app import load_state, seed_demo, autopilot_tick, STATE, DB_STATUS, save_state, LIVE_OUTBOUND
from mail_connector import fetch_unseen, apply_inbox_to_deals, send_pending, connector_status as mail_status
from scout_connector import scout_tick, status as scout_status

if __name__ == "__main__":
    loaded = load_state()
    if not loaded or not STATE.get("buyers"):
        seed_demo()

    scout = scout_tick(STATE)
    inbox = fetch_unseen(STATE)
    applied = apply_inbox_to_deals(STATE)
    result = autopilot_tick("worker autónomo")
    outbound = send_pending(STATE, LIVE_OUTBOUND)
    persisted_after_connectors = save_state()

    print({
        "result": result,
        "scout": scout,
        "scout_status": scout_status(),
        "inbox": inbox,
        "applied": applied,
        "outbound": outbound,
        "mail": mail_status(),
        "postgres": DB_STATUS,
        "persisted_after_connectors": persisted_after_connectors,
    }, flush=True)

    if not result.get("persisted") or not persisted_after_connectors:
        raise SystemExit(2)
