from __future__ import annotations

import copy

from app import STATE, load_state, save_state
import https_mail_transport

if not load_state():
    print({"resend_canary": {"status": "state_unavailable"}}, flush=True)
    raise SystemExit(2)

candidate = None
for item in STATE.get("outbox", []) or []:
    if item.get("source") != "distribution_operator_canary":
        continue
    if item.get("status") not in {"send_failed", "ready"}:
        continue
    if item.get("quality_gate") != "passed" or not item.get("communication_reviewed") or not item.get("contact_verified"):
        continue
    candidate = item
    break

if not candidate:
    print({"resend_canary": {"status": "no_eligible_failed_or_ready_canary"}}, flush=True)
    raise SystemExit(4)

probe_state = copy.deepcopy(STATE)
probe_item = copy.deepcopy(candidate)
probe_item["status"] = "ready"
probe_state["outbox"] = [probe_item]

stats = https_mail_transport.https_send_pending(probe_state, True)
result_item = probe_state["outbox"][0]

report = {
    "status": "sent" if int(stats.get("sent") or 0) == 1 and result_item.get("status") == "sent" else "failed",
    "sent": int(stats.get("sent") or 0),
    "failed": int(stats.get("failed") or 0),
    "blocked": int(stats.get("blocked") or 0),
    "provider": result_item.get("email_provider"),
    "provider_message_id_present": bool(result_item.get("email_provider_message_id")),
    "transport_route": result_item.get("smtp_route"),
    "error": str(result_item.get("last_error") or "")[:500] or None,
}

if report["status"] == "sent":
    for key in ("status", "sent_at", "email_provider", "email_provider_message_id", "smtp_route"):
        if key in result_item:
            candidate[key] = result_item.get(key)
    candidate.pop("last_error", None)
    STATE["mail_transport_health"] = copy.deepcopy(probe_state.get("mail_transport_health", {}))
    save_state()

print({"resend_canary": report}, flush=True)
raise SystemExit(0 if report["status"] == "sent" else 5)
