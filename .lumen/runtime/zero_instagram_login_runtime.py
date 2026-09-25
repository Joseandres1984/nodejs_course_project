from __future__ import annotations

"""Instagram Login transport adapter for LUMEN Zero.

The existing social distributor was written for the Instagram Graph API through
Facebook Login (graph.facebook.com). The connected @lumen.b2b credential is an
Instagram Login credential and is valid through graph.instagram.com instead.

This adapter changes transport only. It does not create approvals, bypass the
human gate, enable paid media, or authorize future posts.
"""

import os
from typing import Any, Dict

import social_distribution

VERSION = "1.0-zero-instagram-login"


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

    publish_payload = {"creation_id": creation_id, "access_token": token}
    pstatus, pbody, _ = social_distribution._request_json(base + "/media_publish", publish_payload, {}, form=True)
    post_id = str(pbody.get("id") or "").strip()
    if pstatus < 200 or pstatus >= 300 or not post_id:
        raise RuntimeError(f"instagram_publish_no_receipt:{pstatus}:{str(pbody)[:500]}")

    return {
        "provider": "instagram_api_instagram_login",
        "external_post_id": post_id,
        "external_url": f"https://www.instagram.com/lumen.b2b/",
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
        "human_approval_gate_changed": False,
        "paid_media_enabled": False,
    }
    print({"zero_instagram_login_runtime": report}, flush=True)
    return report


INSTALL_REPORT = install()
