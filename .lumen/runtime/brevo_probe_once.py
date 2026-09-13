from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

API_KEY = os.getenv("LUMEN_BREVO_API_KEY", "").strip()
FROM_EMAIL = os.getenv("LUMEN_BREVO_FROM_EMAIL", "").strip().lower()
FROM_NAME = os.getenv("LUMEN_BREVO_FROM_NAME", "LUMEN B2B").strip() or "LUMEN B2B"
BASE = "https://api.brevo.com/v3"


def request(method: str, path: str, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={
            "api-key": API_KEY,
            "accept": "application/json",
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read(20000).decode("utf-8", errors="replace")
            body = json.loads(raw) if raw else {}
            return int(resp.status), body
    except urllib.error.HTTPError as exc:
        raw = exc.read(20000).decode("utf-8", errors="replace") if exc.fp else ""
        try:
            body = json.loads(raw) if raw else {}
        except Exception:
            body = {"raw": raw[:1000]}
        return int(exc.code), body


def die(message: str, details=None):
    print(json.dumps({"brevo_probe": {"ok": False, "error": message, "details": details}}, ensure_ascii=False), flush=True)
    raise SystemExit(1)


if not API_KEY:
    die("missing_api_key")
if not FROM_EMAIL or "@" not in FROM_EMAIL:
    die("missing_or_invalid_from_email")

account_status, account = request("GET", "/account")
if account_status != 200:
    die("account_auth_failed", {"status": account_status, "response": account})

senders_status, senders_payload = request("GET", "/senders")
if senders_status != 200:
    die("sender_list_failed", {"status": senders_status, "response": senders_payload})

senders = senders_payload.get("senders", []) if isinstance(senders_payload, dict) else []
match = None
for sender in senders:
    if str(sender.get("email") or "").strip().lower() == FROM_EMAIL:
        match = sender
        break
if not match:
    die("configured_sender_not_found_in_brevo", {"from": FROM_EMAIL, "sender_count": len(senders)})

payload = {
    "sender": {"email": FROM_EMAIL, "name": FROM_NAME},
    "to": [{"email": FROM_EMAIL, "name": "LUMEN verification"}],
    "subject": "LUMEN · verificación Brevo",
    "textContent": "Prueba técnica interna de LUMEN. Si recibís este mensaje, el remitente Brevo está operativo.",
}
send_status, send_result = request("POST", "/smtp/email", payload)
message_id = str(send_result.get("messageId") or send_result.get("message_id") or "") if isinstance(send_result, dict) else ""
if send_status != 201 or not message_id:
    die("transactional_canary_failed", {"status": send_status, "response": send_result})

safe_sender = {
    "id": match.get("id"),
    "email": match.get("email"),
    "name": match.get("name"),
    "active": match.get("active"),
}
print(json.dumps({
    "brevo_probe": {
        "ok": True,
        "account_auth": True,
        "sender_present": True,
        "sender": safe_sender,
        "transactional_canary_accepted": True,
        "message_id": message_id,
    }
}, ensure_ascii=False), flush=True)
