from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict

from outbound_web import app

INSTAGRAM_ACCESS_TOKEN = os.getenv("LUMEN_INSTAGRAM_ACCESS_TOKEN", "").strip()
INSTAGRAM_USER_ID = os.getenv("LUMEN_INSTAGRAM_USER_ID", "").strip()
INSTAGRAM_GRAPH_BASE = os.getenv("LUMEN_INSTAGRAM_GRAPH_BASE", "https://graph.instagram.com").rstrip("/")
INSTAGRAM_GRAPH_VERSION = os.getenv("LUMEN_INSTAGRAM_GRAPH_VERSION", "v26.0").strip() or "v26.0"
SUBSCRIBED_FIELDS = [
    "comments",
    "messages",
    "messaging_postbacks",
    "message_edit",
    "message_reactions",
    "messaging_seen",
    "messaging_referral",
]

SUBSCRIPTION_STATUS: Dict[str, Any] = {
    "configured": bool(INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_USER_ID),
    "ok": False,
    "subscribed_fields": [],
    "error": None,
}


def _request(method: str, path: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    query = dict(params or {})
    query["access_token"] = INSTAGRAM_ACCESS_TOKEN
    url = f"{INSTAGRAM_GRAPH_BASE}/{INSTAGRAM_GRAPH_VERSION}/{path.lstrip('/')}?{urllib.parse.urlencode(query)}"
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "LUMEN-B2B/1.0"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")[:700]
        except Exception:
            detail = ""
        raise RuntimeError(f"Instagram subscription HTTP {exc.code}: {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Instagram subscription connection error: {exc.reason}") from exc


def ensure_instagram_subscription() -> Dict[str, Any]:
    status = {
        "configured": bool(INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_USER_ID),
        "ok": False,
        "subscribed_fields": [],
        "error": None,
    }
    if not status["configured"]:
        status["error"] = "missing_access_token_or_user_id"
        SUBSCRIPTION_STATUS.clear(); SUBSCRIPTION_STATUS.update(status)
        return status

    try:
        result = _request(
            "POST",
            f"{INSTAGRAM_USER_ID}/subscribed_apps",
            {"subscribed_fields": ",".join(SUBSCRIBED_FIELDS)},
        )
        if not result.get("success"):
            raise RuntimeError(f"unexpected subscribe response: {result}")

        current = _request("GET", f"{INSTAGRAM_USER_ID}/subscribed_apps")
        fields: list[str] = []
        for item in current.get("data", []) if isinstance(current, dict) else []:
            if isinstance(item, dict):
                for field in item.get("subscribed_fields", []) or []:
                    if field not in fields:
                        fields.append(str(field))
        status["subscribed_fields"] = fields
        status["ok"] = all(field in fields for field in ("messages", "comments"))
    except Exception as exc:
        status["error"] = f"{type(exc).__name__}: {str(exc)[:500]}"

    SUBSCRIPTION_STATUS.clear(); SUBSCRIPTION_STATUS.update(status)
    print({"instagram_account_subscription": status}, flush=True)
    return status


# Account-level webhook subscription is required in addition to the app-level
# fields selected in Meta's dashboard. This POST is idempotent.
ensure_instagram_subscription()


@app.get("/health/instagram/subscription", include_in_schema=False)
def instagram_subscription_health():
    """Safe status endpoint; never returns the Instagram access token."""
    return dict(SUBSCRIPTION_STATUS)
