from __future__ import annotations

"""One-time, fail-closed repair for three explicit Instagram approvals.

The editorial-v2 migration already stored the human-visible fingerprint for each of the three
posts. During that same production cycle the legacy validator ran before the new validator was
patched and changed only their status to CONTENT_CHANGED. This repair is allowed to restore an
approval only when:

1. the job is one of the three immutable IDs explicitly approved by the operator;
2. D1 still proves the latest processed command for that job was approve -> approved;
3. the stored editorial-v2 fingerprint still exactly matches the current human-visible content;
4. the post is not rejected and has not already been published.

It cannot authorize any future post and cannot preserve approval across a visible content change.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import app as lumen_app
import instagram_approval_freeze_runtime as freeze
import zero_instagram_control_bridge_runtime as bridge

VERSION = "1.0-post-patch-approval-finalizer"
MARKER = "instagram_explicit_approval_finalize_20260921_v1"


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now() -> str:
    return _now_dt().isoformat()


def _latest_commands() -> Dict[str, Dict[str, Any]]:
    placeholders = ",".join("?" for _ in freeze.RECOVERY_IDS)
    result = bridge.d1._request({
        "sql": (
            "SELECT job_id,action,processed,result,created_at,processed_at "
            f"FROM lumen_instagram_control_commands WHERE job_id IN ({placeholders}) "
            "AND processed=1 ORDER BY created_at DESC"
        ),
        "params": sorted(freeze.RECOVERY_IDS),
    })
    latest: Dict[str, Dict[str, Any]] = {}
    for row in bridge._rows(result):
        jid = str(row.get("job_id") or "")
        if jid in freeze.RECOVERY_IDS and jid not in latest:
            latest[jid] = row
    return latest


def run_once() -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "version": VERSION,
        "status": "ok",
        "restored": 0,
        "already_valid": 0,
        "published_preserved": 0,
        "rejected_preserved": 0,
        "blocked_command_proof": 0,
        "blocked_visible_change": 0,
        "missing": 0,
        "future_posts_authorized": False,
        "updated_at": _now(),
    }
    try:
        if not lumen_app.load_state():
            raise RuntimeError("state_unavailable")
        previous = lumen_app.STATE.get(MARKER)
        if isinstance(previous, dict) and previous.get("completed"):
            report["status"] = "already_completed"
            report["previous"] = previous
            print({"instagram_explicit_approval_finalize": report}, flush=True)
            return report

        jobs = bridge._jobs()
        approvals = bridge._approval_store()
        commands = _latest_commands()
        receipts = {
            str(row.get("distribution_job_id") or "")
            for row in lumen_app.STATE.get("distribution_receipts", []) or []
            if isinstance(row, dict) and str(row.get("distribution_job_id") or "")
        }
        restored_ids = []
        all_resolved = True
        now = _now_dt()

        for jid in sorted(freeze.RECOVERY_IDS):
            job = jobs.get(jid)
            if not job:
                report["missing"] += 1
                all_resolved = False
                continue

            approval = approvals.get(jid) or {}
            status = str(approval.get("status") or "").upper()
            if jid in receipts or status == "PUBLISHED":
                report["published_preserved"] += 1
                continue
            if status == "REJECTED":
                report["rejected_preserved"] += 1
                continue

            command = commands.get(jid) or {}
            command_ok = (
                str(command.get("action") or "").lower() == "approve"
                and str(command.get("result") or "").lower() == "approved"
            )
            if not command_ok:
                report["blocked_command_proof"] += 1
                all_resolved = False
                continue

            current_fingerprint = freeze.editorial_fingerprint(job)
            stored_fingerprint = str(approval.get("content_fingerprint") or "")
            editorial_v2 = str(approval.get("fingerprint_version") or "") == freeze.FINGERPRINT_VERSION
            if not editorial_v2 or not stored_fingerprint or stored_fingerprint != current_fingerprint:
                report["blocked_visible_change"] += 1
                all_resolved = False
                continue

            if status in {
                "APPROVED",
                "APPROVED_WAITING_CONNECTOR",
                "APPROVED_RETRY",
                "APPROVED_DAILY_CAP",
                "APPROVED_WAITING_MEDIA",
            }:
                report["already_valid"] += 1
                continue

            # CONTENT_CHANGED is safe to restore here only because the persisted editorial-v2
            # fingerprint still matches exactly. The legacy validator changed the status, not the
            # approved editorial snapshot.
            approval["status"] = "APPROVED"
            approval["expires_at"] = (now + timedelta(hours=24)).isoformat()
            approval["attempts"] = 0
            approval["last_error"] = None
            approval["revalidated_after_runtime_patch_at"] = now.isoformat()
            approval["revalidation_basis"] = "explicit_command_plus_exact_editorial_v2_fingerprint_match"
            job["status"] = "approved"
            restored_ids.append(jid)
            report["restored"] += 1

            audit = lumen_app.STATE.setdefault("instagram_publish_audit", [])
            audit.append({
                "ts": _now(),
                "status": "APPROVED_EDITORIAL_V2_RESTORED_AFTER_LEGACY_VALIDATOR",
                "job_id": jid,
                "authority": "explicit_human_approval_preserved",
                "source": "instagram_approval_finalize_runtime",
            })
            lumen_app.STATE["instagram_publish_audit"] = audit[-500:]

        lumen_app.STATE[MARKER] = {
            "completed": bool(all_resolved),
            "completed_at": _now() if all_resolved else None,
            "restored_ids": restored_ids,
            "authorized_ids": sorted(freeze.RECOVERY_IDS),
            "future_posts_authorized": False,
            "fingerprint_version": freeze.FINGERPRINT_VERSION,
            "visible_content_must_match": True,
        }
        if not lumen_app.save_state():
            raise RuntimeError("state_persistence_failed")
        report["completed"] = bool(all_resolved)
    except Exception as exc:
        report["status"] = "degraded_fail_closed"
        report["last_error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
    print({"instagram_explicit_approval_finalize": report}, flush=True)
    return report
