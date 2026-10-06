from __future__ import annotations

"""D1 bridge for the zero-cost Instagram approval console.

The Cloudflare control Worker never touches LUMEN's compressed state directly. It writes signed-in
operator commands to a small D1 queue. This bridge validates each command against the current
immutable content fingerprint, folds the approval/rejection into canonical state, and exports a
minimal pending-post projection back to D1 for the console.
"""

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import app as lumen_app
import d1_persistence_runtime as d1

VERSION = "1.3-zero-instagram-control-bridge-travel-monetization"
APPROVAL_TTL_HOURS = 24
MAX_COMMANDS = 25
SAFE_TRAVEL_POLICY_VERSION = "1.0-owned-travel-affiliate-zero-spend"
SAFE_TRAVEL_MIN_QA = 95
SAFE_TRAVEL_DAILY_LIMIT = 1
SAFE_TRAVEL_AUTHORITY = "user_authorized_owned_travel_affiliate_policy_20261006"

# One-time recovery for the three exact posts José explicitly approved in the control console on
# 2026-09-21, whose button commands did not reach the canonical D1 queue because the deployed
# console Worker had drifted behind the repository version. This list can never authorize a future
# post: IDs are immutable and approval is additionally bound to each current content fingerprint.
EXPLICIT_APPROVAL_RECOVERY_IDS = {
    "DIST-3ADEE9154FA8",
    "DIST-90AC7FE4D0F0",
    "DIST-C9C06F669D70",
}
RECOVERY_MARKER = "instagram_approval_recovery_20260921"


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now() -> str:
    return _now_dt().isoformat()


def _fingerprint(job: Dict[str, Any]) -> str:
    parts = [
        str(job.get("id") or ""),
        str(job.get("campaign_id") or ""),
        str(job.get("variant_id") or ""),
        str(job.get("audience") or ""),
        str(job.get("copy") or ""),
        str(job.get("tracking_url") or ""),
        str(job.get("creative_asset_url") or ""),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _rows(result: Any) -> List[Dict[str, Any]]:
    statements = d1._result_statements(result)
    if not statements:
        return []
    return d1._statement_rows(statements[0])


def _ensure_schema() -> None:
    d1._request({"batch": [
        {"sql": "CREATE TABLE IF NOT EXISTS lumen_instagram_control_posts (job_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, audience TEXT, campaign_id TEXT, caption TEXT, image_url TEXT, state_status TEXT, approval_status TEXT, last_error TEXT, created_at TEXT, updated_at TEXT NOT NULL)", "params": []},
        {"sql": "CREATE TABLE IF NOT EXISTS lumen_instagram_control_commands (id TEXT PRIMARY KEY, job_id TEXT NOT NULL, fingerprint TEXT NOT NULL, action TEXT NOT NULL, created_at TEXT NOT NULL, processed INTEGER NOT NULL DEFAULT 0, processed_at TEXT, result TEXT)", "params": []},
        {"sql": "CREATE INDEX IF NOT EXISTS idx_lumen_instagram_control_commands_pending ON lumen_instagram_control_commands(processed, created_at)", "params": []},
    ]})


def _jobs() -> Dict[str, Dict[str, Any]]:
    return {
        str(row.get("id") or ""): row
        for row in lumen_app.STATE.get("distribution_operator_jobs", []) or []
        if isinstance(row, dict) and str(row.get("channel") or "") == "instagram" and str(row.get("id") or "")
    }


def _approval_store() -> Dict[str, Dict[str, Any]]:
    raw = lumen_app.STATE.get("instagram_publish_approvals")
    if isinstance(raw, dict):
        return raw
    store: Dict[str, Dict[str, Any]] = {}
    if isinstance(raw, list):
        for row in raw:
            if isinstance(row, dict) and row.get("job_id"):
                store[str(row["job_id"])] = row
    lumen_app.STATE["instagram_publish_approvals"] = store
    return store


def _audit(status: str, job_id: str, authority: str) -> None:
    audit = lumen_app.STATE.setdefault("instagram_publish_audit", [])
    audit.append({"ts": _now(), "status": status, "job_id": job_id, "authority": authority, "source": "zero_control_worker"})
    lumen_app.STATE["instagram_publish_audit"] = audit[-500:]


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "si", "sí", "on", "enabled", "required"}


def _number(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _safe_travel_eligibility(job: Dict[str, Any]) -> tuple[bool, List[str]]:
    reasons: List[str] = []
    jid = str(job.get("id") or "")
    caption = str(job.get("caption") or job.get("copy") or "")
    tracking_url = str(job.get("tracking_url") or "")

    if not jid.startswith("IGTRAVEL-"):
        reasons.append("not_igtravel")
    if str(job.get("channel") or "").lower() != "instagram":
        reasons.append("not_instagram")
    if str(job.get("content_mode") or "") != "travel_affiliate_acquisition":
        reasons.append("not_travel_affiliate_acquisition")
    if not _truthy(job.get("affiliate_disclosure")) or "Transparencia:" not in caption:
        reasons.append("affiliate_disclosure_missing")
    if _truthy(job.get("paid_media")) or _truthy(job.get("requires_budget_approval")):
        reasons.append("paid_or_budgeted_media")
    if _truthy(job.get("booking_authority")) or _truthy(job.get("payment_authority")):
        reasons.append("booking_or_payment_authority")
    if _number(job.get("autonomous_spend_usd"), 0.0) != 0.0:
        reasons.append("nonzero_autonomous_spend")
    if _number(job.get("visual_qa_score"), 0.0) < SAFE_TRAVEL_MIN_QA:
        reasons.append("visual_qa_below_threshold")
    if not tracking_url.startswith("https://lumen-zero-public.lumen-b2b.workers.dev/travel/"):
        reasons.append("tracking_url_not_owned_travel")
    if str(job.get("status") or "").lower() in {"published", "verified_published", "rejected_by_human", "superseded_by_regeneration"}:
        reasons.append("terminal_or_rejected_status")
    return (not reasons, sorted(set(reasons)))


def authorize_safe_travel_affiliate_job(job: Dict[str, Any]) -> Dict[str, Any]:
    """Policy-approve one zero-spend owned Travel affiliate post per UTC day.

    This does not authorize paid media, purchases, bookings, charges, contracts or arbitrary
    Instagram content. Explicit human rejection always wins.
    """
    report: Dict[str, Any] = {
        "version": SAFE_TRAVEL_POLICY_VERSION,
        "approved": False,
        "job_id": str(job.get("id") or ""),
        "daily_limit": SAFE_TRAVEL_DAILY_LIMIT,
        "min_visual_qa": SAFE_TRAVEL_MIN_QA,
        "authority": SAFE_TRAVEL_AUTHORITY,
        "scope": "owned_instagram_travel_affiliate_zero_spend_only",
        "updated_at": _now(),
    }
    jid = report["job_id"]
    if not jid:
        report["reason"] = "job_id_required"
        return report

    eligible, reasons = _safe_travel_eligibility(job)
    if not eligible:
        report["reason"] = "ineligible"
        report["reasons"] = reasons
        return report

    approvals = _approval_store()
    existing = approvals.get(jid) or {}
    existing_status = str(existing.get("status") or "").upper()
    current = _fingerprint(job)

    if existing_status == "REJECTED":
        report["reason"] = "explicit_human_rejection_preserved"
        return report
    if existing_status in {"APPROVED", "APPROVED_WAITING_CONNECTOR", "APPROVED_RETRY", "PUBLISHED"} and str(existing.get("content_fingerprint") or "") == current:
        report["approved"] = True
        report["reason"] = "already_authorized"
        report["status"] = existing_status
        return report

    receipts = {
        str(row.get("distribution_job_id") or "")
        for row in lumen_app.STATE.get("distribution_receipts", []) or []
        if isinstance(row, dict) and (row.get("external_post_id") or row.get("external_url"))
    }
    if jid in receipts:
        report["approved"] = True
        report["reason"] = "already_published"
        report["status"] = "PUBLISHED"
        return report

    today = _now_dt().date().isoformat()
    policy_approved_ids = {
        str(row.get("job_id") or "")
        for row in lumen_app.STATE.get("instagram_publish_audit", []) or []
        if isinstance(row, dict)
        and str(row.get("authority") or "") == SAFE_TRAVEL_AUTHORITY
        and str(row.get("ts") or "").startswith(today)
        and str(row.get("status") or "") == "APPROVED_SAFE_TRAVEL_AFFILIATE"
    }
    approvals_today = {
        approved_id
        for approved_id in policy_approved_ids
        if str((approvals.get(approved_id) or {}).get("status") or "").upper()
        not in {"DUPLICATE_BLOCKED", "DUPLICATE_BLOCKED_REMOTE", "REJECTED", "EXPIRED", "CONTENT_CHANGED"}
    }
    if jid not in approvals_today and len(approvals_today) >= SAFE_TRAVEL_DAILY_LIMIT:
        report["reason"] = "daily_policy_cap_reached"
        report["approved_today"] = len(approvals_today)
        return report

    now = _now_dt()
    approvals[jid] = {
        "job_id": jid,
        "status": "APPROVED",
        "approved_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=APPROVAL_TTL_HOURS)).isoformat(),
        "approved_by": "lumen_safe_travel_policy",
        "approval_mode": "safe_owned_travel_affiliate",
        "policy_version": SAFE_TRAVEL_POLICY_VERSION,
        "content_fingerprint": current,
        "attempts": 0,
        "last_error": None,
        "authority": SAFE_TRAVEL_AUTHORITY,
        "monetary_budget_usd": 0,
        "binding_authority_changed": False,
    }
    job["status"] = "approved_safe_travel_affiliate"
    job["travel_monetization_policy"] = SAFE_TRAVEL_POLICY_VERSION
    job["policy_approved_at"] = now.isoformat()
    _audit("APPROVED_SAFE_TRAVEL_AFFILIATE", jid, SAFE_TRAVEL_AUTHORITY)
    if not lumen_app.save_state():
        report["reason"] = "state_persistence_failed"
        return report

    report["approved"] = True
    report["reason"] = "safe_zero_spend_owned_channel_policy"
    report["status"] = "APPROVED"
    report["future_scope"] = "eligible_owned_travel_affiliate_only"
    return report


def consume_commands() -> Dict[str, Any]:
    report = {"version": VERSION, "status": "ok", "commands_seen": 0, "approved": 0, "rejected": 0, "stale": 0, "missing": 0, "errors": 0, "updated_at": _now()}
    try:
        _ensure_schema()
        result = d1._request({"sql": "SELECT id,job_id,fingerprint,action,created_at FROM lumen_instagram_control_commands WHERE processed=0 ORDER BY created_at ASC LIMIT ?", "params": [MAX_COMMANDS]})
        commands = _rows(result)
        report["commands_seen"] = len(commands)
        if not commands:
            print({"zero_instagram_control_consume": report}, flush=True)
            return report
        if not lumen_app.load_state():
            raise RuntimeError("state_unavailable")
        jobs = _jobs()
        approvals = _approval_store()
        acknowledgements = []
        changed = False
        for command in commands:
            cid = str(command.get("id") or "")
            jid = str(command.get("job_id") or "")
            action = str(command.get("action") or "").lower()
            supplied = str(command.get("fingerprint") or "")
            job = jobs.get(jid)
            result_label = "ignored"
            if not job:
                report["missing"] += 1
                result_label = "job_missing"
            else:
                current = _fingerprint(job)
                if not supplied or supplied != current:
                    report["stale"] += 1
                    result_label = "content_changed"
                elif action == "approve":
                    now = _now_dt()
                    approvals[jid] = {
                        "job_id": jid,
                        "status": "APPROVED",
                        "approved_at": now.isoformat(),
                        "expires_at": (now + timedelta(hours=APPROVAL_TTL_HOURS)).isoformat(),
                        "approved_by": "authenticated_zero_control_operator",
                        "content_fingerprint": current,
                        "attempts": 0,
                        "last_error": None,
                        "authority": "single_post_explicit_human_approval",
                    }
                    job["status"] = "approved"
                    _audit("APPROVED", jid, "explicit_human_approval")
                    report["approved"] += 1
                    result_label = "approved"
                    changed = True
                elif action == "reject":
                    approvals[jid] = {
                        "job_id": jid,
                        "status": "REJECTED",
                        "rejected_at": _now(),
                        "content_fingerprint": current,
                        "authority": "explicit_human_rejection",
                    }
                    job["status"] = "rejected_by_human"
                    _audit("REJECTED", jid, "explicit_human_rejection")
                    report["rejected"] += 1
                    result_label = "rejected"
                    changed = True
                else:
                    result_label = "invalid_action"
            acknowledgements.append((cid, result_label))

        lumen_app.STATE["zero_instagram_control_bridge"] = report
        if changed and not lumen_app.save_state():
            raise RuntimeError("state_persistence_failed")
        for cid, label in acknowledgements:
            d1._request({"sql": "UPDATE lumen_instagram_control_commands SET processed=1, processed_at=?, result=? WHERE id=?", "params": [_now(), label, cid]})
    except Exception as exc:
        report["status"] = "degraded_fail_open"
        report["errors"] += 1
        report["last_error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
    print({"zero_instagram_control_consume": report}, flush=True)
    return report


def recover_explicit_approvals_once() -> Dict[str, Any]:
    """Recover only the three explicit approvals already given by José in the broken console."""
    report: Dict[str, Any] = {
        "version": VERSION,
        "status": "ok",
        "requested_ids": sorted(EXPLICIT_APPROVAL_RECOVERY_IDS),
        "recovered": 0,
        "already_approved_or_published": 0,
        "rejected_preserved": 0,
        "missing": 0,
        "fingerprints": {},
        "future_posts_authorized": False,
        "updated_at": _now(),
    }
    try:
        if not lumen_app.load_state():
            raise RuntimeError("state_unavailable")
        existing_marker = lumen_app.STATE.get(RECOVERY_MARKER)
        if isinstance(existing_marker, dict) and existing_marker.get("completed"):
            report["status"] = "already_completed"
            report["previous"] = {
                "completed_at": existing_marker.get("completed_at"),
                "recovered_ids": existing_marker.get("recovered_ids", []),
            }
            print({"zero_instagram_approval_recovery": report}, flush=True)
            return report

        jobs = _jobs()
        approvals = _approval_store()
        receipts = {
            str(row.get("distribution_job_id") or "")
            for row in lumen_app.STATE.get("distribution_receipts", []) or []
            if isinstance(row, dict) and str(row.get("distribution_job_id") or "")
        }
        now = _now_dt()
        recovered_ids: List[str] = []
        missing_ids: List[str] = []

        for jid in sorted(EXPLICIT_APPROVAL_RECOVERY_IDS):
            job = jobs.get(jid)
            if not job:
                report["missing"] += 1
                missing_ids.append(jid)
                continue
            current = _fingerprint(job)
            report["fingerprints"][jid] = current[:16]
            approval = approvals.get(jid) or {}
            status = str(approval.get("status") or "").upper()
            if jid in receipts or status == "PUBLISHED":
                report["already_approved_or_published"] += 1
                continue
            if status == "REJECTED":
                report["rejected_preserved"] += 1
                continue
            if status in {"APPROVED", "APPROVED_WAITING_CONNECTOR", "APPROVED_RETRY", "APPROVED_DAILY_CAP"} and str(approval.get("content_fingerprint") or "") == current:
                report["already_approved_or_published"] += 1
                continue

            approvals[jid] = {
                "job_id": jid,
                "status": "APPROVED",
                "approved_at": now.isoformat(),
                "expires_at": (now + timedelta(hours=APPROVAL_TTL_HOURS)).isoformat(),
                "approved_by": "explicit_user_approval_recovered_2026_09_21",
                "content_fingerprint": current,
                "attempts": 0,
                "last_error": None,
                "authority": "single_post_explicit_human_approval_recovery",
            }
            job["status"] = "approved"
            _audit("APPROVED_RECOVERED", jid, "explicit_user_approval_recovered_2026_09_21")
            recovered_ids.append(jid)
            report["recovered"] += 1

        completed = not missing_ids
        lumen_app.STATE[RECOVERY_MARKER] = {
            "completed": completed,
            "completed_at": _now() if completed else None,
            "recovered_ids": recovered_ids,
            "missing_ids": missing_ids,
            "authorized_ids": sorted(EXPLICIT_APPROVAL_RECOVERY_IDS),
            "future_posts_authorized": False,
            "source": "explicit_user_confirmation_in_chat_after_broken_control_click",
        }
        if not lumen_app.save_state():
            raise RuntimeError("state_persistence_failed")
        report["completed"] = completed
    except Exception as exc:
        report["status"] = "degraded_fail_closed"
        report["last_error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
    print({"zero_instagram_approval_recovery": report}, flush=True)
    return report


def _publish_approved_before_export() -> Dict[str, Any]:
    """Deterministically flush already-approved posts after the complete worker cycle.

    This calls the existing human-approval publisher; it does not create approvals, alter content,
    widen connector authority, bypass fingerprints, or authorize future posts.
    """
    report: Dict[str, Any] = {
        "version": VERSION,
        "status": "ok",
        "publish_control_called": False,
        "published_this_tick": 0,
        "published_total": 0,
        "valid_approvals": 0,
        "future_posts_authorized": False,
        "updated_at": _now(),
    }
    try:
        if not lumen_app.load_state():
            raise RuntimeError("state_unavailable")
        import instagram_publish_control
        control = dict(instagram_publish_control.instagram_publish_control_tick(lumen_app.STATE) or {})
        report["publish_control_called"] = True
        report["published_this_tick"] = int(control.get("published_this_tick") or 0)
        report["published_total"] = int(control.get("published_total") or 0)
        report["valid_approvals"] = int(control.get("valid_approvals") or 0)
        report["publish_attempts_this_tick"] = int(control.get("publish_attempts_this_tick") or 0)
        report["waiting_connector"] = int(control.get("waiting_connector") or 0)
        report["connector_configured"] = bool(control.get("connector_configured"))
        report["approval_required_per_post"] = bool(control.get("approval_required_per_post", True))
        report["control_status"] = control.get("status")
        if not lumen_app.save_state():
            raise RuntimeError("state_persistence_failed_after_publish")
    except Exception as exc:
        report["status"] = "degraded_fail_closed"
        report["last_error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
    print({"zero_instagram_publish_flush": report}, flush=True)
    return report


def export_posts() -> Dict[str, Any]:
    report = {"version": VERSION, "status": "ok", "posts_exported": 0, "errors": 0, "updated_at": _now()}
    try:
        _ensure_schema()
        publish_flush = _publish_approved_before_export()
        report["publish_flush"] = publish_flush
        if not lumen_app.load_state():
            raise RuntimeError("state_unavailable")
        approvals = _approval_store()
        receipts = {
            str(row.get("distribution_job_id") or ""): row
            for row in lumen_app.STATE.get("distribution_receipts", []) or []
            if isinstance(row, dict) and str(row.get("distribution_job_id") or "")
        }
        batch = []
        for jid, job in _jobs().items():
            approval = approvals.get(jid) or {}
            approval_status = str(approval.get("status") or "")
            state_status = "PUBLISHED" if jid in receipts else str(job.get("status") or "prepared")
            last_error = str(approval.get("last_error") or job.get("last_error") or "")[:500]
            caption = str(job.get("copy") or job.get("caption") or "")[:4000]
            batch.append({
                "sql": "INSERT INTO lumen_instagram_control_posts(job_id,fingerprint,audience,campaign_id,caption,image_url,state_status,approval_status,last_error,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(job_id) DO UPDATE SET fingerprint=excluded.fingerprint,audience=excluded.audience,campaign_id=excluded.campaign_id,caption=excluded.caption,image_url=excluded.image_url,state_status=excluded.state_status,approval_status=excluded.approval_status,last_error=excluded.last_error,updated_at=excluded.updated_at",
                "params": [
                    jid,
                    _fingerprint(job),
                    str(job.get("audience") or "B2B")[:300],
                    str(job.get("campaign_id") or "")[:300],
                    caption,
                    str(job.get("image_url") or job.get("creative_asset_url") or "")[:1200],
                    state_status[:120],
                    approval_status[:120],
                    last_error,
                    str(job.get("created_at") or "")[:80],
                    _now(),
                ],
            })
        if batch:
            d1._request({"batch": batch})
        report["posts_exported"] = len(batch)
        report["published_receipts"] = len(receipts)
        lumen_app.STATE["zero_instagram_control_export"] = report
        lumen_app.save_state()
    except Exception as exc:
        report["status"] = "degraded_fail_open"
        report["errors"] += 1
        report["last_error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
    print({"zero_instagram_control_export": report}, flush=True)
    return report
