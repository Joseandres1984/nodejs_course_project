from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

key = os.getenv("LUMEN_RESEND_API_KEY", "").strip()
sender = os.getenv("LUMEN_RESEND_FROM", "").strip()
report = {
    "api_key_present": bool(key),
    "sender_present": bool(sender),
    "sender_mode": "resend_test_sender" if sender.lower().endswith("<onboarding@resend.dev>") or sender.lower() == "onboarding@resend.dev" else "custom_sender",
    "api_ok": False,
    "domains_total": None,
    "domains_verified": None,
}
if not key:
    report["error"] = "missing_api_key"
    print({"resend_probe": report}, flush=True)
    raise SystemExit(2)

req = urllib.request.Request(
    "https://api.resend.com/domains",
    headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
    method="GET",
)
try:
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read(20000).decode("utf-8", errors="replace")
        report["http_status"] = int(resp.status)
        payload = json.loads(raw) if raw else {}
        domains = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(domains, list):
            report["domains_total"] = len(domains)
            report["domains_verified"] = sum(1 for row in domains if str(row.get("status") or "").lower() == "verified")
        report["api_ok"] = 200 <= int(resp.status) < 300
except urllib.error.HTTPError as exc:
    report["http_status"] = int(exc.code)
    body = exc.read(1000).decode("utf-8", errors="replace") if exc.fp else ""
    report["error"] = body[:300]
except Exception as exc:
    report["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"

print({"resend_probe": report}, flush=True)
raise SystemExit(0 if report["api_ok"] else 3)
