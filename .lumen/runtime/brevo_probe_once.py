from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

API_KEY = os.getenv("LUMEN_BREVO_API_KEY", "").strip()
FROM_EMAIL = os.getenv("LUMEN_BREVO_FROM_EMAIL", "").strip().lower()
FROM_NAME = os.getenv("LUMEN_BREVO_FROM_NAME", "LUMEN B2B").strip() or "LUMEN B2B"
BASE = "https://api.brevo.com/v3"
USER_AGENT = "LUMEN-B2B/1.0 (+https://lumen-web-production-5755.up.railway.app)"


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
            "user-agent": USER_AGENT,
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


def stop(message: str, details=None, code: int = 1):
    print(json.dumps({"brevo_probe": {"ok": False, "error": message, "details": details}}, ensure_ascii=False), flush=True)
    raise SystemExit(code)


if not API_KEY:
    stop("missing_api_key")
if not FROM_EMAIL or "@" not in FROM_EMAIL:
    stop("missing_or_invalid_from_email")

account_status, _account = request("GET", "/account")
if account_status != 200:
    stop("account_auth_failed", {"status": account_status})

senders_status, senders_payload = request("GET", "/senders")
sender_list_accessible = senders_status == 200
sender_present = None
safe_sender = None
match = None
if sender_list_accessible:
    senders = senders_payload.get("senders", []) if isinstance(senders_payload, dict) else []
    match = next((s for s in senders if str(s.get("email") or "").strip().lower() == FROM_EMAIL), None)
    sender_present = bool(match)
    if match:
        safe_sender = {
            "id": match.get("id"),
            "email": match.get("email"),
            "name": match.get("name"),
            "active": match.get("active"),
        }
    else:
        create_status, create_result = request("POST", "/senders", {"email": FROM_EMAIL, "name": FROM_NAME})
        if create_status not in {200, 201}:
            stop("sender_create_failed", {"status": create_status, "response": create_result})
        print(json.dumps({
            "brevo_probe": {
                "ok": False,
                "account_auth": True,
                "sender_created": True,
                "sender_email": FROM_EMAIL,
                "verification_required": True,
                "sender_id": create_result.get("id") if isinstance(create_result, dict) else None,
            }
        }, ensure_ascii=False), flush=True)
        raise SystemExit(2)

# A successful self-addressed transactional send is the definitive operational sender test.
payload = {
    "sender": {"email": FROM_EMAIL, "name": FROM_NAME},
    "to": [{"email": FROM_EMAIL, "name": "LUMEN verification"}],
    "subject": "LUMEN · verificación Brevo",
    "textContent": "Prueba técnica interna de LUMEN. Si recibís este mensaje, el remitente Brevo está operativo.",
}
send_status, send_result = request("POST", "/smtp/email", payload)
message_id = str(send_result.get("messageId") or send_result.get("message_id") or "") if isinstance(send_result, dict) else ""
if send_status != 201 or not message_id:
    stop("transactional_canary_failed", {"status": send_status, "response": send_result})

print(json.dumps({
    "brevo_probe": {
        "ok": True,
        "account_auth": True,
        "sender_list_accessible": sender_list_accessible,
        "sender_present": sender_present,
        "sender": safe_sender,
        "transactional_canary_accepted": True,
        "message_id": message_id,
    }
}, ensure_ascii=False), flush=True)
