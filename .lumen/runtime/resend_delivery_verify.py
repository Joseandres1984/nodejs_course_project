from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from app import STATE, load_state

key = os.getenv("LUMEN_RESEND_API_KEY", "").strip()
if not key or not load_state():
    print({"resend_delivery_verify": {"status": "missing_key_or_state"}}, flush=True)
    raise SystemExit(2)

rows = [
    x for x in (STATE.get("outbox", []) or [])
    if x.get("source") == "distribution_operator_canary"
    and x.get("status") == "sent"
    and x.get("email_provider") == "resend"
    and x.get("email_provider_message_id")
]
rows.sort(key=lambda x: str(x.get("sent_at") or ""), reverse=True)
if not rows:
    print({"resend_delivery_verify": {"status": "no_persisted_resend_canary"}}, flush=True)
    raise SystemExit(3)

message_id = str(rows[0]["email_provider_message_id"])
last = None
for attempt in range(1, 7):
    req = urllib.request.Request(
        f"https://api.resend.com/emails/{message_id}",
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read(12000).decode("utf-8", errors="replace") or "{}")
            event = str(payload.get("last_event") or "").lower()
            last = {
                "status": "ok",
                "attempt": attempt,
                "http_status": int(resp.status),
                "message_id_present": True,
                "last_event": event or None,
                "created_at_present": bool(payload.get("created_at")),
            }
            if event == "delivered":
                print({"resend_delivery_verify": last}, flush=True)
                raise SystemExit(0)
            if event in {"bounced", "complained", "failed", "canceled", "cancelled"}:
                print({"resend_delivery_verify": last}, flush=True)
                raise SystemExit(7)
    except urllib.error.HTTPError as exc:
        body = exc.read(1000).decode("utf-8", errors="replace") if exc.fp else ""
        last = {"status": "api_error", "attempt": attempt, "http_status": int(exc.code), "error": body[:300]}
    except SystemExit:
        raise
    except Exception as exc:
        last = {"status": "probe_error", "attempt": attempt, "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
    time.sleep(5)

print({"resend_delivery_verify": last or {"status": "unknown"}}, flush=True)
raise SystemExit(6)
