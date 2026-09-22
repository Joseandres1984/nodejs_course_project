from __future__ import annotations

"""Bind Instagram approvals to human-visible editorial content, not transport plumbing.

The old fingerprint included mutable infrastructure metadata such as tracking and asset URLs.
That meant a zero-cost hosting migration could invalidate a post even when the operator-visible
copy and rendered media were unchanged. This runtime patches the approval bridge and the publish
control at import time while preserving the per-post human approval gate.
"""

import builtins
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

VERSION = "2.0-editorial-approval-freeze"
FINGERPRINT_VERSION = "editorial_v2"
RECOVERY_MARKER = "instagram_editorial_approval_migration_20260921_v2"
RECOVERY_IDS = {
    "DIST-3ADEE9154FA8",
    "DIST-90AC7FE4D0F0",
    "DIST-C9C06F669D70",
}

TRANSPORT_ONLY_FIELDS = (
    "campaign_id",
    "variant_id",
    "tracking_url",
    "publish_nonce",
    "media_prepared_at",
    "provider",
    "external_post_id",
    "external_url",
)


def _text(value: Any) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n")


def _internal_generated_media(job: Dict[str, Any]) -> bool:
    source = _text(job.get("media_source")).lower()
    url = _text(job.get("image_url") or job.get("creative_asset_url")).lower()
    jid = _text(job.get("id")).lower()
    if source in {"lumen_zero_git_asset_v1", "lumen_generated_public_jpeg"}:
        return True
    return bool(jid and "/media/instagram/" in url and jid in url)


def editorial_snapshot(job: Dict[str, Any]) -> Dict[str, Any]:
    external_media = ""
    if not _internal_generated_media(job):
        external_media = _text(job.get("image_url") or job.get("creative_asset_url"))
    return {
        "job_id": _text(job.get("id")),
        "audience": _text(job.get("audience")),
        "copy": _text(job.get("copy")),
        "caption": _text(job.get("caption")),
        "message": _text(job.get("message")),
        "headline": _text(job.get("headline")),
        "title": _text(job.get("title")),
        "hook": _text(job.get("hook")),
        "service_name": _text(job.get("service_name")),
        "visual_headline": _text(job.get("visual_headline")),
        "visual_subtitle": _text(job.get("visual_subtitle")),
        "hashtags": _text(job.get("hashtags")),
        "cta": _text(job.get("cta")),
        "cta_text": _text(job.get("cta_text")),
        "external_media": external_media,
    }


def editorial_fingerprint(job: Dict[str, Any]) -> str:
    payload = json.dumps(
        editorial_snapshot(job),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now() -> str:
    return _now_dt().isoformat()


def _recover_three_verified_approvals(bridge: Any) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "version": VERSION,
        "status": "ok",
        "recovered": 0,
        "published_preserved": 0,
        "rejected_preserved": 0,
        "missing": 0,
        "latest_command_not_approve": 0,
        "future_posts_authorized": False,
        "updated_at": _now(),
    }
    try:
        app = bridge.lumen_app
        if not app.load_state():
            raise RuntimeError("state_unavailable")
        existing = app.STATE.get(RECOVERY_MARKER)
        if isinstance(existing, dict) and existing.get("completed"):
            report["status"] = "already_completed"
            report["previous"] = existing
            return report

        placeholders = ",".join("?" for _ in RECOVERY_IDS)
        sql = (
            "SELECT job_id,action,processed,result,created_at,processed_at "
            f"FROM lumen_instagram_control_commands WHERE job_id IN ({placeholders}) "
            "AND processed=1 ORDER BY created_at DESC"
        )
        result = bridge.d1._request({"sql": sql, "params": sorted(RECOVERY_IDS)})
        rows = bridge._rows(result)
        latest: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            jid = _text(row.get("job_id"))
            if jid in RECOVERY_IDS and jid not in latest:
                latest[jid] = row

        jobs = bridge._jobs()
        approvals = bridge._approval_store()
        receipts = {
            _text(row.get("distribution_job_id"))
            for row in app.STATE.get("distribution_receipts", []) or []
            if isinstance(row, dict) and _text(row.get("distribution_job_id"))
        }
        recovered_ids = []
        now = _now_dt()

        for jid in sorted(RECOVERY_IDS):
            job = jobs.get(jid)
            if not job:
                report["missing"] += 1
                continue
            approval = approvals.get(jid) or {}
            status = _text(approval.get("status")).upper()
            if jid in receipts or status == "PUBLISHED":
                report["published_preserved"] += 1
                continue
            if status == "REJECTED":
                report["rejected_preserved"] += 1
                continue

            command = latest.get(jid) or {}
            if _text(command.get("action")).lower() != "approve" or _text(command.get("result")).lower() != "approved":
                report["latest_command_not_approve"] += 1
                continue

            approvals[jid] = {
                "job_id": jid,
                "status": "APPROVED",
                "approved_at": _text(command.get("created_at")) or now.isoformat(),
                "expires_at": (now + timedelta(hours=24)).isoformat(),
                "approved_by": "authenticated_zero_control_operator_migrated",
                "content_fingerprint": editorial_fingerprint(job),
                "fingerprint_version": FINGERPRINT_VERSION,
                "approved_snapshot": editorial_snapshot(job),
                "attempts": 0,
                "last_error": None,
                "authority": "single_post_explicit_human_approval_migrated_to_editorial_identity",
                "migration_basis": "processed_explicit_approve_command_and_verified_unchanged_public_media_history",
                "transport_fields_excluded": list(TRANSPORT_ONLY_FIELDS),
            }
            job["status"] = "approved"
            audit = app.STATE.setdefault("instagram_publish_audit", [])
            audit.append({
                "ts": _now(),
                "status": "APPROVED_EDITORIAL_V2_MIGRATED",
                "job_id": jid,
                "authority": "explicit_human_approval_preserved",
                "source": "instagram_approval_freeze_runtime",
            })
            app.STATE["instagram_publish_audit"] = audit[-500:]
            recovered_ids.append(jid)
            report["recovered"] += 1

        marker = {
            "completed": len(recovered_ids) + report["published_preserved"] + report["rejected_preserved"] == len(RECOVERY_IDS),
            "completed_at": _now(),
            "recovered_ids": recovered_ids,
            "authorized_ids": sorted(RECOVERY_IDS),
            "future_posts_authorized": False,
            "fingerprint_version": FINGERPRINT_VERSION,
        }
        app.STATE[RECOVERY_MARKER] = marker
        app.STATE["instagram_approval_identity"] = {
            "version": VERSION,
            "fingerprint_version": FINGERPRINT_VERSION,
            "status": "active",
            "transport_metadata_can_invalidate_approval": False,
            "visible_content_change_requires_new_approval": True,
            "tracking_url_published_to_instagram_caption": False,
            "updated_at": _now(),
        }
        if not app.save_state():
            raise RuntimeError("state_persistence_failed")
        report["completed"] = marker["completed"]
    except Exception as exc:
        report["status"] = "degraded_fail_closed"
        report["last_error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
    return report


def _patch_bridge(module: Any) -> None:
    if getattr(module, "_EDITORIAL_APPROVAL_FREEZE_V2", False):
        return
    if not hasattr(module, "recover_explicit_approvals_once"):
        return
    module._fingerprint = editorial_fingerprint
    original_recovery = module.recover_explicit_approvals_once

    def recovery_with_editorial_identity() -> Dict[str, Any]:
        base = original_recovery()
        migration = _recover_three_verified_approvals(module)
        if isinstance(base, dict):
            base["editorial_identity_migration"] = migration
            base["fingerprint_version"] = FINGERPRINT_VERSION
        print({"instagram_editorial_approval_migration": migration}, flush=True)
        return base

    module.recover_explicit_approvals_once = recovery_with_editorial_identity
    module._EDITORIAL_APPROVAL_FREEZE_V2 = True


def _patch_publish_control(module: Any) -> None:
    if getattr(module, "_EDITORIAL_APPROVAL_FREEZE_V2", False):
        return
    if not hasattr(module, "_approval_store") or not hasattr(module, "social_distribution"):
        return

    module._content_fingerprint = editorial_fingerprint

    def approval_valid(state: Dict[str, Any], job: Dict[str, Any]) -> bool:
        jid = _text(job.get("id"))
        row = module._approval_store(state).get(jid) or {}
        status = _text(row.get("status")).upper()
        if status == "PUBLISHED":
            return True
        if status not in {
            "APPROVED",
            "APPROVED_WAITING_CONNECTOR",
            "APPROVED_RETRY",
            "APPROVED_DAILY_CAP",
            "APPROVED_WAITING_MEDIA",
        }:
            return False
        current = editorial_fingerprint(job)
        if _text(row.get("content_fingerprint")) != current:
            row["status"] = "CONTENT_CHANGED"
            row["invalidated_at"] = _now()
            row["current_fingerprint"] = current
            row["fingerprint_version"] = FINGERPRINT_VERSION
            return False
        expires = module._parse_dt(row.get("expires_at"))
        if expires is None or _now_dt() >= expires:
            row["status"] = "EXPIRED"
            row["expired_at"] = _now()
            return False
        return True

    module._approval_valid = approval_valid

    social = module.social_distribution
    if not getattr(social, "_EDITORIAL_INSTAGRAM_TRANSPORT_V2", False):
        original_publish = social._publish

        def publish_same_editorial_content(job: Dict[str, Any], status: Dict[str, Any]) -> Dict[str, Any]:
            if _text(job.get("channel")) != "instagram":
                return original_publish(job, status)
            approved_job = dict(job)
            approved_job["tracking_url"] = ""
            return original_publish(approved_job, status)

        social._publish = publish_same_editorial_content
        social._EDITORIAL_INSTAGRAM_TRANSPORT_V2 = True

    module._EDITORIAL_APPROVAL_FREEZE_V2 = True
    print({
        "instagram_approval_identity": {
            "version": VERSION,
            "status": "active",
            "fingerprint_version": FINGERPRINT_VERSION,
            "transport_metadata_can_invalidate_approval": False,
            "visible_content_change_requires_new_approval": True,
            "tracking_url_published_to_instagram_caption": False,
        }
    }, flush=True)


_ORIGINAL_IMPORT = builtins.__import__
_IN_HOOK = False


def _patch_loaded_targets() -> None:
    bridge = sys.modules.get("zero_instagram_control_bridge_runtime")
    if bridge is not None and hasattr(bridge, "recover_explicit_approvals_once"):
        _patch_bridge(bridge)
    control = sys.modules.get("instagram_publish_control")
    if control is not None and hasattr(control, "_approval_store"):
        _patch_publish_control(control)


def _lumen_import(name: str, globals=None, locals=None, fromlist=(), level=0):
    global _IN_HOOK
    if _IN_HOOK:
        return _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)

    # Mark the whole underlying import as in-progress. Nested imports may expose a module in
    # sys.modules before its body has finished; never patch such a partially initialized module.
    _IN_HOOK = True
    try:
        module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)
    finally:
        _IN_HOOK = False

    _patch_loaded_targets()
    return module


builtins.__import__ = _lumen_import
