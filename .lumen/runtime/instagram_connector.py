from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import Depends

from app import auth
from outbound_web import app

INSTAGRAM_ACCESS_TOKEN = os.getenv("LUMEN_INSTAGRAM_ACCESS_TOKEN", "").strip()
INSTAGRAM_USER_ID = os.getenv("LUMEN_INSTAGRAM_USER_ID", "").strip()
INSTAGRAM_USERNAME = os.getenv("LUMEN_INSTAGRAM_USERNAME", "").strip()
INSTAGRAM_GRAPH_BASE = os.getenv("LUMEN_INSTAGRAM_GRAPH_BASE", "https://graph.instagram.com").rstrip("/")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _graph_get(path: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if not INSTAGRAM_ACCESS_TOKEN:
        raise RuntimeError("Instagram access token is not configured")

    query = urllib.parse.urlencode(params or {})
    url = f"{INSTAGRAM_GRAPH_BASE}/{path.lstrip('/')}"
    if query:
        url = f"{url}?{query}"

    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {INSTAGRAM_ACCESS_TOKEN}",
            "Accept": "application/json",
            "User-Agent": "LUMEN-B2B/1.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = response.read().decode("utf-8")
            return json.loads(payload or "{}")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")[:500]
        except Exception:
            detail = ""
        raise RuntimeError(f"Instagram Graph HTTP {exc.code}: {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Instagram Graph connection error: {exc.reason}") from exc


def get_instagram_profile() -> Dict[str, Any]:
    target = INSTAGRAM_USER_ID or "me"
    data = _graph_get(target, {"fields": "user_id,username,id"})
    username = str(data.get("username") or INSTAGRAM_USERNAME or "")
    user_id = str(data.get("user_id") or data.get("id") or INSTAGRAM_USER_ID or "")
    return {
        "user_id": user_id,
        "username": username,
        "connected": bool(user_id or username),
    }


def instagram_status() -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "configured": bool(INSTAGRAM_ACCESS_TOKEN),
        "connected": False,
        "username": INSTAGRAM_USERNAME or None,
        "user_id": INSTAGRAM_USER_ID or None,
        "checked_at": _now_iso(),
    }
    if not INSTAGRAM_ACCESS_TOKEN:
        base["status"] = "not_configured"
        return base

    try:
        profile = get_instagram_profile()
        base.update(profile)
        base["status"] = "connected" if profile.get("connected") else "unexpected_response"
    except Exception as exc:
        base["status"] = "error"
        base["error"] = f"{type(exc).__name__}: {str(exc)[:350]}"
    return base


@app.get("/health/instagram", include_in_schema=False)
def instagram_health():
    """Safe health endpoint. Never returns the access token."""
    return instagram_status()


@app.get("/api/integrations/instagram/status", include_in_schema=False)
def instagram_private_status(_=Depends(auth)):
    """Authenticated integration status for the LUMEN command center."""
    return instagram_status()
