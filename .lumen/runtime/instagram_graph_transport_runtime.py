from __future__ import annotations

"""Use the Instagram Login Graph host for LUMEN's Instagram publishing token.

LUMEN authenticates the professional account through Instagram Login, whose API
base is graph.instagram.com. The legacy social dispatcher used the Facebook
Graph host, which expects a different token family and can reject the Instagram
Login token with OAuth code 190 before the media container is created.
"""

import os
from typing import Any, Dict

import social_distribution


VERSION = "1.0.1-instagram-login-publish-transport"


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

    publish_payload = {"creation_id": creation_id, "access_token": token}
    pstatus, pbody, _ = social_distribution._request_json(base + "/media_publish", publish_payload, {}, form=True)
    post_id = str(pbody.get("id") or "").strip()
    if pstatus < 200 or pstatus >= 300 or not post_id:
        raise RuntimeError(f"instagram_publish_no_receipt:{pstatus}:{str(pbody)[:500]}")

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
            "token_exposed": False,
        }
    },
    flush=True,
)
