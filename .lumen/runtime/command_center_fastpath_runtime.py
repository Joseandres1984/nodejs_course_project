from __future__ import annotations

"""Read fastpath for the owner Command Center.

The full dashboard is intentionally rich, but several browser requests can arrive together while the
worker is persisting a large state. This runtime prevents request stampedes without changing any
business state or authorization rule:
- successful authenticated GET responses for /command-center and /api/control-tower are cached for a
  few seconds in process memory;
- cache keys include a SHA-256 digest of the exact Authorization header, so a cached owner response
  is never served to a different or unauthenticated caller;
- concurrent cache misses are coalesced through one asyncio lock;
- the Command Center alert UI is redirected to a compact authenticated read-only endpoint instead of
  fetching the entire control-tower payload just to obtain alert cards.

No cached response is persisted. A restart clears the cache immediately.
"""

import asyncio
import hashlib
import time
from typing import Any, Dict, Tuple

from fastapi import Depends, Request
from fastapi.responses import Response

from app import STATE, app, auth, load_state
from executive_alerts import executive_alert_tick

VERSION = "1.0-command-center-read-fastpath"
HTML_TTL_SECONDS = 20
API_TTL_SECONDS = 10
_MAX_CACHE_ENTRIES = 8
_CACHE: Dict[Tuple[str, str], Dict[str, Any]] = {}
_LOCK = asyncio.Lock()


def _auth_digest(request: Request) -> str:
    raw = str(request.headers.get("authorization") or "")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest() if raw else ""


def _ttl(path: str) -> int:
    return HTML_TTL_SECONDS if path == "/command-center" else API_TTL_SECONDS


def _cache_key(request: Request) -> Tuple[str, str]:
    return request.url.path, _auth_digest(request)


def _fresh(row: Dict[str, Any], ttl: int) -> bool:
    return bool(row and (time.monotonic() - float(row.get("stored_at") or 0.0)) <= ttl)


def _response_from_cache(row: Dict[str, Any]) -> Response:
    headers = dict(row.get("headers", {}) or {})
    headers["X-Lumen-Fastpath"] = "hit"
    return Response(
        content=row.get("body", b""),
        status_code=int(row.get("status_code") or 200),
        headers=headers,
        media_type=row.get("media_type"),
    )


def _compact_cache() -> None:
    if len(_CACHE) <= _MAX_CACHE_ENTRIES:
        return
    ordered = sorted(_CACHE.items(), key=lambda kv: float(kv[1].get("stored_at") or 0.0))
    for key, _ in ordered[: max(0, len(_CACHE) - _MAX_CACHE_ENTRIES)]:
        _CACHE.pop(key, None)


@app.get("/api/control-tower/alerts", include_in_schema=False)
def compact_control_tower_alerts(_=Depends(auth)):
    loaded = load_state()
    alerts = executive_alert_tick(STATE) if loaded else (STATE.get("executive_alerts", {}) or {})
    return {
        "ok": bool(loaded),
        "executive_alerts": alerts,
        "last_tick": STATE.get("last_tick"),
        "ticks": int(STATE.get("ticks") or 0),
        "read_only": True,
        "persisted_by_this_request": False,
        "version": VERSION,
    }


@app.middleware("http")
async def command_center_read_fastpath(request: Request, call_next):
    path = request.url.path
    if request.method != "GET" or path not in {"/command-center", "/api/control-tower"}:
        return await call_next(request)

    # Never cache or serve a response for a request that did not present credentials.
    # Invalid credentials get a different digest and therefore cannot hit a previously successful row.
    auth_digest = _auth_digest(request)
    if not auth_digest:
        return await call_next(request)

    key = _cache_key(request)
    ttl = _ttl(path)
    row = _CACHE.get(key) or {}
    if _fresh(row, ttl):
        return _response_from_cache(row)

    async with _LOCK:
        row = _CACHE.get(key) or {}
        if _fresh(row, ttl):
            return _response_from_cache(row)

        response = await call_next(request)
        if int(response.status_code) != 200:
            return response

        body = b""
        async for chunk in response.body_iterator:
            body += chunk

        content_type = str(response.headers.get("content-type") or "")
        media_type = content_type.split(";", 1)[0].strip() or None
        if path == "/command-center" and body:
            text = body.decode("utf-8", errors="replace")
            # The alert action script needs only executive alerts. Avoid loading and serializing the
            # entire control tower a second time immediately after the HTML request.
            text = text.replace("fetch('/api/control-tower'", "fetch('/api/control-tower/alerts'")
            text = text.replace('fetch("/api/control-tower"', 'fetch("/api/control-tower/alerts"')
            body = text.encode("utf-8")

        headers = {
            k: v for k, v in response.headers.items()
            if k.lower() not in {"content-length", "transfer-encoding", "content-encoding"}
        }
        headers["X-Lumen-Fastpath"] = "miss"
        _CACHE[key] = {
            "stored_at": time.monotonic(),
            "body": body,
            "status_code": int(response.status_code),
            "headers": {k: v for k, v in headers.items() if k.lower() != "x-lumen-fastpath"},
            "media_type": media_type,
        }
        _compact_cache()
        return Response(content=body, status_code=response.status_code, headers=headers, media_type=media_type)


print({
    "command_center_fastpath_runtime": {
        "version": VERSION,
        "status": "active",
        "html_ttl_seconds": HTML_TTL_SECONDS,
        "api_ttl_seconds": API_TTL_SECONDS,
        "authenticated_cache_only": True,
        "concurrent_miss_coalescing": True,
        "compact_alert_endpoint": "/api/control-tower/alerts",
        "state_mutation_authority_changed": False,
    }
}, flush=True)
