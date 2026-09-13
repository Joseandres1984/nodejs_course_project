from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import distribution_operator


VERSION = "1.0-social"
LIVE_OUTBOUND = os.getenv("LUMEN_SOCIAL_LIVE_OUTBOUND", "false").lower() == "true"
MAX_PER_CYCLE = max(0, min(3, int(os.getenv("LUMEN_SOCIAL_CANARY_MAX_PER_CYCLE", "1"))))
MAX_PER_DAY = max(0, min(12, int(os.getenv("LUMEN_SOCIAL_CANARY_MAX_PER_DAY", "3"))))

META_PAGE_ID = os.getenv("LUMEN_META_PAGE_ID", "").strip()
META_PAGE_ACCESS_TOKEN = os.getenv("LUMEN_META_PAGE_ACCESS_TOKEN", "").strip()
META_GRAPH_VERSION = os.getenv("LUMEN_META_GRAPH_VERSION", "").strip()
INSTAGRAM_USER_ID = os.getenv("LUMEN_INSTAGRAM_USER_ID", "").strip()
INSTAGRAM_ACCESS_TOKEN = os.getenv("LUMEN_INSTAGRAM_ACCESS_TOKEN", "").strip() or META_PAGE_ACCESS_TOKEN
LINKEDIN_ACCESS_TOKEN = os.getenv("LUMEN_LINKEDIN_ACCESS_TOKEN", "").strip()
LINKEDIN_ORGANIZATION_URN = os.getenv("LUMEN_LINKEDIN_ORGANIZATION_URN", "").strip()
LINKEDIN_VERSION = os.getenv("LUMEN_LINKEDIN_VERSION", "").strip()
SOCIAL_WEBHOOK_URL = os.getenv("LUMEN_SOCIAL_WEBHOOK_URL", "").strip()
SOCIAL_WEBHOOK_TOKEN = os.getenv("LUMEN_SOCIAL_WEBHOOK_TOKEN", "").strip()

_original_distribution_tick = distribution_operator.distribution_operator_tick


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _day() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _text(job: Dict[str, Any]) -> str:
    body = " ".join(str(job.get("copy") or "").split()).strip()
    url = str(job.get("tracking_url") or "").strip()
    if url and url not in body:
        body = (body + "\n\n" + url).strip()
    return body[:2800]


def connector_status() -> Dict[str, Any]:
    return {
        "version": VERSION,
        "live_outbound": LIVE_OUTBOUND,
        "facebook": {
            "ready": bool(META_PAGE_ID and META_PAGE_ACCESS_TOKEN and META_GRAPH_VERSION),
            "missing": [name for name, value in (
                ("LUMEN_META_PAGE_ID", META_PAGE_ID),
                ("LUMEN_META_PAGE_ACCESS_TOKEN", META_PAGE_ACCESS_TOKEN),
                ("LUMEN_META_GRAPH_VERSION", META_GRAPH_VERSION),
            ) if not value],
        },
        "instagram": {
            "ready": bool(INSTAGRAM_USER_ID and INSTAGRAM_ACCESS_TOKEN and META_GRAPH_VERSION),
            "requires_media_asset": True,
            "missing": [name for name, value in (
                ("LUMEN_INSTAGRAM_USER_ID", INSTAGRAM_USER_ID),
                ("LUMEN_INSTAGRAM_ACCESS_TOKEN", INSTAGRAM_ACCESS_TOKEN),
                ("LUMEN_META_GRAPH_VERSION", META_GRAPH_VERSION),
            ) if not value],
        },
        "linkedin_company": {
            "ready": bool(LINKEDIN_ACCESS_TOKEN and LINKEDIN_ORGANIZATION_URN and LINKEDIN_VERSION),
            "missing": [name for name, value in (
                ("LUMEN_LINKEDIN_ACCESS_TOKEN", LINKEDIN_ACCESS_TOKEN),
                ("LUMEN_LINKEDIN_ORGANIZATION_URN", LINKEDIN_ORGANIZATION_URN),
                ("LUMEN_LINKEDIN_VERSION", LINKEDIN_VERSION),
            ) if not value],
        },
        "generic_webhook": {
            "ready": bool(SOCIAL_WEBHOOK_URL),
            "auth_configured": bool(SOCIAL_WEBHOOK_TOKEN),
        },
    }


def _request_json(url: str, payload: Dict[str, Any], headers: Dict[str, str], form: bool = False) -> Tuple[int, Dict[str, Any], Dict[str, str]]:
    if form:
        data = urllib.parse.urlencode(payload).encode("utf-8")
        req_headers = {"Content-Type": "application/x-www-form-urlencoded", **headers}
    else:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req_headers = {"Content-Type": "application/json", **headers}
    req = urllib.request.Request(url, data=data, headers=req_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read(16000).decode("utf-8", errors="replace")
            try:
                body = json.loads(raw) if raw else {}
            except Exception:
                body = {"raw": raw[:1000]}
            return int(resp.status), body, {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as exc:
        raw = exc.read(16000).decode("utf-8", errors="replace") if exc.fp else ""
        raise RuntimeError(f"http_{exc.code}:{raw[:1000]}") from exc


def _facebook(job: Dict[str, Any]) -> Dict[str, Any]:
    url = f"https://graph.facebook.com/{META_GRAPH_VERSION}/{META_PAGE_ID}/feed"
    payload = {
        "message": _text(job),
        "access_token": META_PAGE_ACCESS_TOKEN,
    }
    tracking = str(job.get("tracking_url") or "").strip()
    if tracking:
        payload["link"] = tracking
    status, body, _ = _request_json(url, payload, {}, form=True)
    post_id = str(body.get("id") or "").strip()
    if status < 200 or status >= 300 or not post_id:
        raise RuntimeError(f"facebook_publish_no_receipt:{status}:{str(body)[:500]}")
    return {
        "provider": "meta_graph",
        "external_post_id": post_id,
        "external_url": f"https://www.facebook.com/{post_id}",
    }


def _linkedin(job: Dict[str, Any]) -> Dict[str, Any]:
    payload = {
        "author": LINKEDIN_ORGANIZATION_URN,
        "commentary": _text(job),
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    headers = {
        "Authorization": f"Bearer {LINKEDIN_ACCESS_TOKEN}",
        "X-Restli-Protocol-Version": "2.0.0",
        "Linkedin-Version": LINKEDIN_VERSION,
    }
    status, body, response_headers = _request_json("https://api.linkedin.com/rest/posts", payload, headers)
    post_id = str(response_headers.get("x-restli-id") or body.get("id") or "").strip()
    if status != 201 or not post_id:
        raise RuntimeError(f"linkedin_publish_no_receipt:{status}:{str(body)[:500]}")
    return {
        "provider": "linkedin_posts_api",
        "external_post_id": post_id,
        "external_url": None,
    }


def _instagram(job: Dict[str, Any]) -> Dict[str, Any]:
    image_url = str(job.get("image_url") or job.get("creative_asset_url") or "").strip()
    if not image_url:
        raise RuntimeError("instagram_media_asset_required")
    base = f"https://graph.facebook.com/{META_GRAPH_VERSION}/{INSTAGRAM_USER_ID}"
    create_payload = {
        "image_url": image_url,
        "caption": _text(job),
        "access_token": INSTAGRAM_ACCESS_TOKEN,
    }
    status, body, _ = _request_json(base + "/media", create_payload, {}, form=True)
    creation_id = str(body.get("id") or "").strip()
    if status < 200 or status >= 300 or not creation_id:
        raise RuntimeError(f"instagram_container_failed:{status}:{str(body)[:500]}")
    publish_payload = {"creation_id": creation_id, "access_token": INSTAGRAM_ACCESS_TOKEN}
    pstatus, pbody, _ = _request_json(base + "/media_publish", publish_payload, {}, form=True)
    post_id = str(pbody.get("id") or "").strip()
    if pstatus < 200 or pstatus >= 300 or not post_id:
        raise RuntimeError(f"instagram_publish_no_receipt:{pstatus}:{str(pbody)[:500]}")
    return {
        "provider": "instagram_graph",
        "external_post_id": post_id,
        "external_url": None,
    }


def _webhook(job: Dict[str, Any]) -> Dict[str, Any]:
    headers: Dict[str, str] = {}
    if SOCIAL_WEBHOOK_TOKEN:
        headers["Authorization"] = f"Bearer {SOCIAL_WEBHOOK_TOKEN}"
    payload = {
        "job_id": job.get("id"),
        "campaign_id": job.get("campaign_id"),
        "variant_id": job.get("variant_id"),
        "audience": job.get("audience"),
        "channel": job.get("channel"),
        "copy": _text(job),
        "tracking_url": job.get("tracking_url"),
        "image_url": job.get("image_url") or job.get("creative_asset_url"),
    }
    status, body, _ = _request_json(SOCIAL_WEBHOOK_URL, payload, headers)
    post_id = str(body.get("external_post_id") or body.get("post_id") or "").strip()
    external_url = str(body.get("external_url") or body.get("url") or "").strip()
    if status < 200 or status >= 300 or not (post_id or external_url):
        raise RuntimeError(f"social_webhook_no_receipt:{status}:{str(body)[:500]}")
    return {
        "provider": str(body.get("provider") or "social_webhook"),
        "external_post_id": post_id or None,
        "external_url": external_url or None,
    }


def _direct_ready(channel: str, status: Dict[str, Any]) -> bool:
    row = status.get(channel, {}) if isinstance(status.get(channel), dict) else {}
    return bool(row.get("ready"))


def _publish(job: Dict[str, Any], status: Dict[str, Any]) -> Dict[str, Any]:
    channel = str(job.get("channel") or "")
    if channel == "facebook" and _direct_ready(channel, status):
        return _facebook(job)
    if channel == "linkedin_company" and _direct_ready(channel, status):
        return _linkedin(job)
    if channel == "instagram" and _direct_ready(channel, status):
        return _instagram(job)
    if status.get("generic_webhook", {}).get("ready"):
        return _webhook(job)
    raise RuntimeError("authorized_social_connector_not_ready")


def _daily_successes(state: Dict[str, Any]) -> int:
    today = _day()
    return sum(1 for x in state.get("social_dispatch_audit", []) or [] if x.get("local_day") == today and x.get("status") == "verified_published")


def _receipt_exists(state: Dict[str, Any], job: Dict[str, Any]) -> bool:
    return any(
        str(x.get("distribution_job_id") or "") == str(job.get("id") or "")
        and (x.get("external_post_id") or x.get("external_url"))
        for x in state.get("distribution_receipts", []) or []
    )


def _record_receipt(state: Dict[str, Any], job: Dict[str, Any], result: Dict[str, Any]) -> None:
    receipts = state.setdefault("distribution_receipts", [])
    row = {
        "receipt_id": f"SOC-{len(receipts)+1:06d}",
        "distribution_job_id": job.get("id"),
        "queue_key": job.get("queue_key"),
        "campaign_id": job.get("campaign_id"),
        "variant_id": job.get("variant_id"),
        "channel": job.get("channel"),
        "provider": result.get("provider"),
        "external_post_id": result.get("external_post_id"),
        "external_url": result.get("external_url"),
        "published_at": utcnow(),
        "received_at": utcnow(),
        "verified": True,
    }
    receipts.append(row)
    state["distribution_receipts"] = receipts[-1000:]
    job.update({
        "status": "verified_published",
        "provider": row["provider"],
        "external_post_id": row["external_post_id"],
        "external_url": row["external_url"],
        "published_at": row["published_at"],
    })


def dispatch_social(state: Dict[str, Any]) -> Dict[str, Any]:
    status = connector_status()
    audit: List[Dict[str, Any]] = state.setdefault("social_dispatch_audit", [])
    jobs = state.get("distribution_operator_jobs", []) or []
    remaining = min(MAX_PER_CYCLE, max(0, MAX_PER_DAY - _daily_successes(state)))
    stats = {
        "version": VERSION,
        "live_outbound": LIVE_OUTBOUND,
        "ready_channels": [c for c in ("facebook", "instagram", "linkedin_company") if _direct_ready(c, status)],
        "webhook_ready": bool(status.get("generic_webhook", {}).get("ready")),
        "eligible": 0,
        "attempted": 0,
        "verified_published": 0,
        "failed": 0,
        "awaiting_media": 0,
        "awaiting_connector": 0,
        "daily_remaining": remaining,
    }

    for job in jobs:
        channel = str(job.get("channel") or "")
        if channel not in {"facebook", "instagram", "linkedin_company"}:
            continue
        if job.get("status") == "verified_published" or _receipt_exists(state, job):
            continue
        stats["eligible"] += 1

        direct_ready = _direct_ready(channel, status)
        webhook_ready = bool(status.get("generic_webhook", {}).get("ready"))
        if channel == "instagram" and direct_ready and not (job.get("image_url") or job.get("creative_asset_url")) and not webhook_ready:
            job["status"] = "awaiting_media_asset"
            stats["awaiting_media"] += 1
            continue
        if not (direct_ready or webhook_ready):
            job["status"] = "awaiting_authorized_connector"
            stats["awaiting_connector"] += 1
            continue
        if not LIVE_OUTBOUND:
            job["status"] = "connector_ready_live_disabled"
            continue
        if remaining <= 0:
            job["status"] = "social_daily_cap_reached"
            continue

        stats["attempted"] += 1
        job["attempts"] = int(job.get("attempts") or 0) + 1
        job["last_attempt_at"] = utcnow()
        try:
            result = _publish(job, status)
            _record_receipt(state, job, result)
            stats["verified_published"] += 1
            remaining -= 1
            audit.append({
                "ts": utcnow(), "local_day": _day(), "status": "verified_published",
                "job_id": job.get("id"), "channel": channel, "provider": result.get("provider"),
                "external_post_id": result.get("external_post_id"), "external_url": result.get("external_url"),
            })
        except Exception as exc:
            error = f"{type(exc).__name__}: {str(exc)[:700]}"
            if "instagram_media_asset_required" in error:
                job["status"] = "awaiting_media_asset"
                stats["awaiting_media"] += 1
            else:
                job["status"] = "social_publish_failed"
                stats["failed"] += 1
            job["last_error"] = error
            audit.append({
                "ts": utcnow(), "local_day": _day(), "status": job.get("status"),
                "job_id": job.get("id"), "channel": channel, "error": error,
            })
    state["social_dispatch_audit"] = audit[-500:]
    stats["daily_remaining"] = remaining
    state["social_connector_health"] = {"checked_at": utcnow(), **status}
    state["social_distribution"] = stats
    return stats


def social_distribution_tick(state: Dict[str, Any], *args: Any, **kwargs: Any) -> Dict[str, Any]:
    report = dict(_original_distribution_tick(state, *args, **kwargs) or {})
    social = dispatch_social(state)
    jobs = state.get("distribution_operator_jobs", []) or []
    report["social"] = social
    report["external_verified"] = sum(1 for x in jobs if x.get("status") == "verified_published")
    report["awaiting_connector"] = sum(1 for x in jobs if x.get("status") in {"awaiting_authorized_connector", "connector_ready_live_disabled"})
    report["awaiting_media"] = sum(1 for x in jobs if x.get("status") == "awaiting_media_asset")
    state["distribution_operator"] = report
    return report


distribution_operator.distribution_operator_tick = social_distribution_tick
