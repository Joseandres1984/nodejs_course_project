from __future__ import annotations

"""Instagram Login transport adapter for LUMEN Zero.

The connected @lumen.b2b credential uses Instagram Login and therefore publishes
through graph.instagram.com. This adapter changes transport only: it never
creates approvals, bypasses the human gate, enables paid media, or authorizes
future posts.
"""

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict

import social_distribution

VERSION = "1.1-zero-instagram-login-media-ready"
MEDIA_READY_TIMEOUT_SECONDS = 40
MEDIA_READY_POLL_SECONDS = 2


def _get_json(url: str, token: str) -> tuple[int, Dict[str, Any]]:
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read(16000).decode("utf-8", errors="replace")
            try:
                body = json.loads(raw) if raw else {}
            except Exception:
                body = {"raw": raw[:1000]}
            return int(resp.status), body
    except urllib.error.HTTPError as exc:
        raw = exc.read(16000).decode("utf-8", errors="replace") if exc.fp else ""
        raise RuntimeError(f"instagram_status_http_{exc.code}:{raw[:700]}") from exc


def _wait_until_media_ready(version: str, creation_id: str, token: str) -> Dict[str, Any]:
    deadline = time.monotonic() + MEDIA_READY_TIMEOUT_SECONDS
    last: Dict[str, Any] = {}
    status_url = f"https://graph.instagram.com/{version}/{creation_id}?fields=status_code,status"

    while time.monotonic() < deadline:
        http_status, body = _get_json(status_url, token)
        if http_status < 200 or http_status >= 300:
            raise RuntimeError(f"instagram_status_unexpected_http:{http_status}")
        last = body if isinstance(body, dict) else {}
        code = str(last.get("status_code") or "").upper().strip()
        if code in {"FINISHED", "PUBLISHED"}:
            return last
        if code in {"ERROR", "EXPIRED"}:
            safe_status = str(last.get("status") or "")[:400]
            raise RuntimeError(f"instagram_media_processing_{code.lower()}:{safe_status}")
        time.sleep(MEDIA_READY_POLL_SECONDS)

    code = str(last.get("status_code") or "UNKNOWN").upper().strip()
    safe_status = str(last.get("status") or "")[:300]
    raise RuntimeError(f"instagram_media_processing_timeout:{code}:{safe_status}")


def _instagram_login(job: Dict[str, Any]) -> Dict[str, Any]:
    image_url = str(job.get("image_url") or job.get("creative_asset_url") or "").strip()
    if not image_url:
        raise RuntimeError("instagram_media_asset_required")

    user_id = str(social_distribution.INSTAGRAM_USER_ID or "").strip()
    token = str(social_distribution.INSTAGRAM_ACCESS_TOKEN or "").strip()
    version = str(social_distribution.META_GRAPH_VERSION or "v26.0").strip()
    if version and not version.startswith("v"):
        version = f"v{version}"
    if not user_id or not token:
        raise RuntimeError("instagram_login_connector_not_ready")

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

    _wait_until_media_ready(version, creation_id, token)

    publish_payload = {"creation_id": creation_id, "access_token": token}
    pstatus, pbody, _ = social_distribution._request_json(base + "/media_publish", publish_payload, {}, form=True)
    post_id = str(pbody.get("id") or "").strip()
    if pstatus < 200 or pstatus >= 300 or not post_id:
        raise RuntimeError(f"instagram_publish_no_receipt:{pstatus}:{str(pbody)[:500]}")

    return {
        "provider": "instagram_api_instagram_login",
        "external_post_id": post_id,
        "external_url": "https://www.instagram.com/lumen.b2b/",
    }


def install() -> Dict[str, Any]:
    mode = (os.getenv("LUMEN_INSTAGRAM_API_MODE") or "instagram_login").strip().lower()
    if mode != "instagram_login":
        return {"status": "skipped", "version": VERSION, "mode": mode}
    social_distribution._instagram = _instagram_login
    report = {
        "status": "installed",
        "version": VERSION,
        "mode": "instagram_login",
        "waits_for_media_ready": True,
        "human_approval_gate_changed": False,
        "paid_media_enabled": False,
    }
    print({"zero_instagram_login_runtime": report}, flush=True)
    return report


INSTALL_REPORT = install()
