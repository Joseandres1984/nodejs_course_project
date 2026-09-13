from __future__ import annotations

import mail_resilience  # installs resilient connector patches
import mail_connector
from app import STATE, load_state, save_state


def main() -> None:
    if not load_state():
        print({"mail_recovery": {"status": "state_unavailable"}}, flush=True)
        return
    recovery = mail_resilience._prepare_safe_retries(STATE)
    outbound = mail_connector.send_pending(STATE, True)
    persisted = bool(save_state())
    probe = recovery.get("probe") or STATE.get("mail_transport_health", {}) or {}
    print({
        "mail_recovery": {
            "transport_ok": probe.get("ok"),
            "transport_route": probe.get("route"),
            "transport_error": probe.get("error"),
            "failed_canaries": recovery.get("failed_canaries", 0),
            "requeued": recovery.get("requeued", 0),
            "sent": outbound.get("sent", 0),
            "failed": outbound.get("failed", 0),
            "blocked": outbound.get("blocked", 0),
            "persisted": persisted,
        }
    }, flush=True)


if __name__ == "__main__":
    main()
