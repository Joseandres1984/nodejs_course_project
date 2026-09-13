from __future__ import annotations

import json

from app import STATE, DB_STATUS, load_state

load_state()
coo = STATE.get("autonomous_coo", {}) or {}
failed = []
for item in STATE.get("outbox", []) or []:
    if item.get("status") != "send_failed":
        continue
    failed.append({
        "id": item.get("id"),
        "source": item.get("source"),
        "failed_at": item.get("failed_at"),
        "smtp_route": item.get("smtp_route"),
        "email_provider": item.get("email_provider"),
        "provider_message_id_present": bool(item.get("email_provider_message_id")),
        "https_retry_count": int(item.get("https_retry_count") or 0),
        "last_error": str(item.get("last_error") or "")[:180],
    })
print(json.dumps({
    "db_connected": bool(DB_STATUS.get("connected")),
    "health_score": coo.get("health_score"),
    "status": coo.get("status"),
    "warnings": coo.get("warnings"),
    "blockers": coo.get("blockers"),
    "mail_transport_health": STATE.get("mail_transport_health"),
    "failed_outbox_count": len(failed),
    "failed_outbox": failed,
}, ensure_ascii=False), flush=True)
