from __future__ import annotations

"""Use the Instagram Login Graph host for LUMEN's Instagram publishing token.

LUMEN authenticates the professional account through Instagram Login, whose API
base is graph.instagram.com. Publishing is two-phase: create a media container,
wait until Meta reports the container ready, then publish it.
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict

import social_distribution


VERSION = "1.1-instagram-login-publish-transport"


def _container_status(base: str, creation_id: str, token: str) -> Dict[str, Any]:
    query = urllib.parse.urlencode(
        {
            "fields": "status_code,status",
            "access_token": token,
        }
    )
    url = f"{base.rsplit('/', 1)[0]}/{creation_id}?{query}"
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "LUMEN-B2B/1.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            raw = response.read(12000).decode("utf-8", errors="replace")
            return json.loads(raw or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read(12000).decode("utf-8", errors="replace") if exc.fp else ""
        raise RuntimeError(f"instagram_container_status_http_{exc.code}:{raw[:700]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"instagram_container_status_connection:{exc.reason}") from exc


def _wait_until_ready(base: str, creation_id: str, token: str) -> Dict[str, Any]:
    last: Dict[str, Any] = {}
    # Images normally become ready quickly. Keep the explicit approval request bounded
    # while avoiding the race where media_publish is called before Meta finishes ingesting.
    for attempt in range(8):
        if attempt:
            time.sleep(1.5)
        last = _container_status(base, creation_id, token)
        code = str(last.get("status_code") or "").upper()
        if code in {"FINISHED", "PUBLISHED"}:
            return last
        if code in {"ERROR", "EXPIRED"}:
            raise RuntimeError(
                f"instagram_container_{code.lower()}:{str(last.get('status') or '')[:500]}"
            )
    raise RuntimeError(
        f"instagram_container_not_ready:{str(last.get('status_code') or 'UNKNOWN')}:{str(last.get('status') or '')[:500]}"
    )


def _instagram_login_publish(job: Dict[str, Any]) -> Dict[str, Any]:
    image_url = str(job.get("image_url") or job.get("creative_asset_url") or "").strip()
    if not image_url:
        raise RuntimeError("instagram_media_asset_required")

    user_id = str(social_distribution.INSTAGRAM_USER_ID or "").strip()
    token = str(social_distribution.INSTAGRAM_ACCESS_TOKEN or "").strip()
    version = (
        os.getenv("LUMEN_INSTAGRAM_GRAPH_VERSION", "").strip()
        or str(social_distribution.META_GRAPH_VERSION or "").strip()
        or "v26.0"
    )
    if version and not version.startswith("v"):
        version = "v" + version
    if not user_id or not token:
        raise RuntimeError("instagram_publish_credentials_missing")

    base = f"https://graph.instagram.com/{version}/{user_id}"
    create_payload = {
        "image_url": image_url,
        "caption": social_distribution._text(job),
        "access_token": token,
    }
    status, body, _ = social_distribution._request_json(base + "/media", create_payload, {}, form=True)
    creation_id = str(body.get("id") or "").strip()
    if status < 200 or status >= 300 or not creation_id:
        raise RuntimeError(f"instagram_container_failed:{status}:{str(body)[:500]}")

    ready = _wait_until_ready(base, creation_id, token)
    print(
        {
            "instagram_publish_container": {
                "status": str(ready.get("status_code") or "FINISHED"),
                "creation_id_present": bool(creation_id),
                "token_exposed": False,
            }
        },
        flush=True,
    )

    publish_payload = {"creation_id": creation_id, "access_token": token}
    try:
        pstatus, pbody, _ = social_distribution._request_json(
            base + "/media_publish", publish_payload, {}, form=True
        )
    except Exception as exc:
        print(
            {
                "instagram_publish_transport": {
                    "status": "publish_failed",
                    "error": f"{type(exc).__name__}: {str(exc)[:700]}",
                    "token_exposed": False,
                }
            },
            flush=True,
        )
        raise

    post_id = str(pbody.get("id") or "").strip()
    if pstatus < 200 or pstatus >= 300 or not post_id:
        raise RuntimeError(f"instagram_publish_no_receipt:{pstatus}:{str(pbody)[:500]}")

    print(
        {
            "instagram_publish_transport": {
                "status": "published",
                "external_post_id_present": True,
                "token_exposed": False,
            }
        },
        flush=True,
    )
    return {
        "provider": "instagram_graph_instagram_login",
        "external_post_id": post_id,
        "external_url": None,
    }


social_distribution._instagram = _instagram_login_publish

print(
    {
        "instagram_graph_transport_runtime": {
            "version": VERSION,
            "status": "active",
            "graph_host": "graph.instagram.com",
            "container_readiness_poll": True,
            "token_exposed": False,
        }
    },
    flush=True,
)
