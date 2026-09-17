from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, Tuple

from app import STATE, load_state, save_state
import a2a_gateway_runtime


VERSION = "1.0-a2a-public-registration"
REGISTRY_NAME = "A2A Registry Community"
REGISTRY_ENDPOINT = "https://a2aregistry.org/api/agents/register"
PRIMARY_CARD_URI = f"{a2a_gateway_runtime.BASE_URL}/.well-known/agent-card.json"
LEGACY_CARD_URI = f"{a2a_gateway_runtime.BASE_URL}/.well-known/agent.json"
USER_AGENT = "LUMEN-A2A-Registrar/1.0"


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _post_registration(card_uri: str) -> Tuple[int | None, Dict[str, Any] | str]:
    payload = json.dumps({"wellKnownURI": card_uri}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        REGISTRY_ENDPOINT,
        data=payload,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            raw = response.read(131072).decode("utf-8", errors="replace")
            try:
                body: Dict[str, Any] | str = json.loads(raw) if raw else {}
            except Exception:
                body = raw[:4000]
            return int(getattr(response, "status", 200)), body
    except urllib.error.HTTPError as exc:
        raw = exc.read(131072).decode("utf-8", errors="replace")
        try:
            body = json.loads(raw) if raw else {}
        except Exception:
            body = raw[:4000]
        return int(exc.code), body
    except Exception as exc:
        return None, f"{type(exc).__name__}: {str(exc)[:500]}"


def _summary(value: Dict[str, Any] | str) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, dict) else str(value)
    except Exception:
        text = str(value)
    return " ".join(text.split())[:1800]


def ensure_public_registration() -> Dict[str, Any]:
    load_state()
    network = STATE.setdefault("agent_network", {})
    registration = network.setdefault("public_registry_registration", {})

    if registration.get("status") in {"registered", "already_registered"}:
        return registration

    attempts = max(0, int(registration.get("attempts") or 0)) + 1
    attempted_at = utcnow()

    http_status, body = _post_registration(PRIMARY_CARD_URI)
    used_uri = PRIMARY_CARD_URI
    response_text = _summary(body)

    # Some registries still validate the legacy discovery URI. Retry only when the
    # canonical registration was explicitly rejected; never duplicate a successful call.
    if http_status is not None and http_status >= 400 and http_status != 409:
        legacy_status, legacy_body = _post_registration(LEGACY_CARD_URI)
        if legacy_status is not None and (200 <= legacy_status < 300 or legacy_status == 409):
            http_status, body = legacy_status, legacy_body
            used_uri = LEGACY_CARD_URI
            response_text = _summary(legacy_body)

    lower = response_text.lower()
    if http_status is not None and 200 <= http_status < 300:
        status = "registered"
    elif http_status == 409 or "already registered" in lower or "already exists" in lower:
        status = "already_registered"
    else:
        status = "registration_failed"

    registration.update({
        "version": VERSION,
        "registry": REGISTRY_NAME,
        "registry_endpoint": REGISTRY_ENDPOINT,
        "status": status,
        "well_known_uri": used_uri,
        "http_status": http_status,
        "attempts": attempts,
        "last_attempt_at": attempted_at,
        "response_summary": response_text,
        "cost_usd": 0,
        "credentials_required": False,
        "binding_authority_changed": False,
        "autonomous_purchase": False,
        "autonomous_payment": False,
    })
    save_state()
    return registration


try:
    _result = ensure_public_registration()
    print({
        "a2a_public_registration_runtime": {
            "version": VERSION,
            "registry": _result.get("registry"),
            "status": _result.get("status"),
            "http_status": _result.get("http_status"),
            "well_known_uri": _result.get("well_known_uri"),
            "attempts": _result.get("attempts"),
            "cost_usd": 0,
        }
    }, flush=True)
except Exception as exc:
    print({"a2a_public_registration_runtime": {"status": "degraded_fail_open", "error": f"{type(exc).__name__}: {str(exc)[:300]}"}}, flush=True)
