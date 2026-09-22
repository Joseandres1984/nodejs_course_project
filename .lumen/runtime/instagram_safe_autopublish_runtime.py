from __future__ import annotations

"""Safe autonomous publishing policy for LUMEN-owned Instagram editorial posts.

This runtime preserves the existing immutable-content approval machinery, but may
issue a policy approval for LUMEN's own IGPRO editorial posts when they pass the
existing quality gate and contain no structured or textual risk signals. Manual
approval/rejection remains authoritative for everything else.
"""

import builtins
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

VERSION = "1.0-safe-autonomous-instagram-publishing"
MIN_QA_SCORE = 90
AUTO_APPROVER = "lumen_policy_auto"

_BLOCKED_TEXT_TOKENS = (
    "garantizado",
    "éxito asegurado",
    "100% seguro",
    "sin riesgo",
    "comprá ahora",
    "compra ahora",
    "pagá ahora",
    "paga ahora",
    "transferí ahora",
    "transfiere ahora",
    "depositá ahora",
    "deposita ahora",
    "firmá ahora",
    "firma ahora",
    "aceptamos términos",
    "aceptamos los términos",
    "contrato vinculante",
    "obligación vinculante",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _text(value).lower() in {"1", "true", "yes", "si", "sí", "on", "enabled", "required"}


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now() -> str:
    return _now_dt().isoformat()


def _safe_editorial_candidate(job: Dict[str, Any]) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    jid = _text(job.get("id"))

    if _text(job.get("channel")).lower() != "instagram":
        reasons.append("not_instagram")
    if not jid.startswith("IGPRO-") or not _truthy(job.get("editorial_pro_v1")):
        reasons.append("not_lumen_pro_editorial")

    try:
        qa_score = int(float(job.get("editorial_qa_score") or 0))
    except (TypeError, ValueError):
        qa_score = 0
    if qa_score < MIN_QA_SCORE:
        reasons.append("qa_below_threshold")

    if not _text(job.get("caption") or job.get("copy")):
        reasons.append("missing_caption")
    if not _text(job.get("headline")):
        reasons.append("missing_headline")

    # Explicit safety/governance flags always win over autonomy.
    blocking_flags = (
        "requires_human_review",
        "requires_budget_approval",
        "requires_legal_review",
        "requires_compliance_review",
        "binding_action",
        "binding_terms",
        "financial_commitment",
        "payment_required",
        "purchase_required",
        "order_required",
        "paid_media",
        "paid_spend",
        "new_connector_authorization_required",
        "sensitive_content",
    )
    for key in blocking_flags:
        if _truthy(job.get(key)):
            reasons.append(key)

    qa_reasons = {str(x).strip().lower() for x in (job.get("editorial_qa_reasons") or []) if str(x).strip()}
    if qa_reasons.intersection({"unsupported_claim", "replacement_character"}):
        reasons.append("qa_risk_reason")

    visible = " ".join(
        _text(job.get(key))
        for key in ("headline", "visual_subtitle", "caption", "copy", "cta")
    ).lower()
    for token in _BLOCKED_TEXT_TOKENS:
        if token in visible:
            reasons.append(f"blocked_text:{token}")

    return not reasons, reasons


def _policy_approve(module: Any, state: Dict[str, Any], job: Dict[str, Any]) -> Tuple[bool, List[str]]:
    jid = _text(job.get("id"))
    approvals = module._approval_store(state)
    existing = approvals.get(jid) or {}
    status = _text(existing.get("status")).upper()

    if status == "REJECTED":
        return False, ["explicit_human_rejection"]
    if module._approval_valid(state, job):
        return False, []

    eligible, reasons = _safe_editorial_candidate(job)
    if not eligible:
        return False, reasons

    now = _now_dt()
    fingerprint = module._content_fingerprint(job)
    approval: Dict[str, Any] = {
        "job_id": jid,
        "status": "APPROVED",
        "approved_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=int(getattr(module, "APPROVAL_TTL_HOURS", 24)))).isoformat(),
        "approved_by": AUTO_APPROVER,
        "approval_mode": "safe_autonomous",
        "policy_version": VERSION,
        "qa_score": int(float(job.get("editorial_qa_score") or 0)),
        "content_fingerprint": fingerprint,
        "attempts": int(existing.get("attempts") or 0) if status in {"APPROVED_RETRY", "APPROVED_WAITING_CONNECTOR"} else 0,
        "last_error": None,
        "authority": "owned_channel_safe_editorial_policy",
        "monetary_budget_usd": 0,
        "binding_authority_changed": False,
    }

    freeze = sys.modules.get("instagram_approval_freeze_runtime")
    if freeze is not None:
        approval["fingerprint_version"] = getattr(freeze, "FINGERPRINT_VERSION", "editorial_v2")
        snapshot_fn = getattr(freeze, "editorial_snapshot", None)
        if callable(snapshot_fn):
            approval["approved_snapshot"] = snapshot_fn(job)

    approvals[jid] = approval
    job["status"] = "approved_safe_autonomous"
    job["autopublish_policy"] = VERSION
    job["autopublish_approved_at"] = now.isoformat()
    module._append_audit(
        state,
        {
            "status": "AUTO_APPROVED_SAFE_EDITORIAL",
            "job_id": jid,
            "authority": "owned_channel_safe_editorial_policy",
            "policy_version": VERSION,
            "qa_score": approval["qa_score"],
            "monetary_budget_usd": 0,
            "binding_authority_changed": False,
        },
    )
    return True, []


def _patch_publish_control(module: Any) -> None:
    if getattr(module, "_SAFE_AUTOPUBLISH_V1", False):
        return
    if not hasattr(module, "instagram_publish_control_tick") or not hasattr(module, "_approval_store"):
        return

    original_tick = module.instagram_publish_control_tick
    original_attempt = module.attempt_publish_approved

    def attempt_with_authority_truth(state: Dict[str, Any], job_id: str) -> Dict[str, Any]:
        result = dict(original_attempt(state, job_id) or {})
        approval = module._approval_store(state).get(str(job_id)) or {}
        if _text(approval.get("approved_by")) == AUTO_APPROVER:
            result["approval_mode"] = "safe_autonomous"
            result["policy_version"] = VERSION
            if result.get("status") == "PUBLISHED":
                for row in reversed(state.get("instagram_publish_audit", []) or []):
                    if isinstance(row, dict) and _text(row.get("job_id")) == str(job_id) and row.get("status") == "PUBLISHED":
                        row["authority"] = "owned_channel_safe_editorial_policy"
                        row["approval_mode"] = "safe_autonomous"
                        row["policy_version"] = VERSION
                        break
        return result

    module.attempt_publish_approved = attempt_with_authority_truth

    def safe_autopublish_tick(state: Dict[str, Any]) -> Dict[str, Any]:
        auto_approved = 0
        blocked: Dict[str, int] = {}
        human_review_required = 0

        for job in state.get("distribution_operator_jobs", []) or []:
            if not isinstance(job, dict) or _text(job.get("channel")).lower() != "instagram":
                continue
            if module._receipt_for_job(state, _text(job.get("id"))):
                continue
            approval = module._approval_store(state).get(_text(job.get("id"))) or {}
            if _text(approval.get("status")).upper() == "REJECTED":
                human_review_required += 1
                blocked["explicit_human_rejection"] = blocked.get("explicit_human_rejection", 0) + 1
                continue
            if module._approval_valid(state, job):
                continue
            approved, reasons = _policy_approve(module, state, job)
            if approved:
                auto_approved += 1
            else:
                human_review_required += 1
                for reason in reasons or ["policy_not_eligible"]:
                    blocked[reason] = blocked.get(reason, 0) + 1

        snapshot = dict(original_tick(state) or {})
        snapshot.update(
            {
                "version": VERSION,
                "approval_mode": "safe_auto_with_human_exceptions",
                "safe_autonomous_publish": True,
                "safe_autopublish_min_qa": MIN_QA_SCORE,
                "auto_approved_this_tick": auto_approved,
                "human_review_required": human_review_required,
                "blocked_reason_counts": blocked,
                "approval_required_per_post": False,
                "human_approval_required_for_exceptions": True,
                "monetary_budget_usd": 0,
                "binding_authority_changed": False,
                "binding_rule": "LUMEN may auto-publish only owned IGPRO editorial content that passes QA and safety policy; exceptions remain human-gated",
                "updated_at": _now(),
            }
        )
        state["instagram_publish_control"] = snapshot
        return snapshot

    module.instagram_publish_control_tick = safe_autopublish_tick
    module._SAFE_AUTOPUBLISH_V1 = True
    print(
        {
            "instagram_safe_autopublish": {
                "version": VERSION,
                "status": "active",
                "owned_editorial_only": True,
                "min_qa": MIN_QA_SCORE,
                "human_review_for_exceptions": True,
                "monetary_budget_usd": 0,
                "binding_authority_changed": False,
            }
        },
        flush=True,
    )


_ORIGINAL_IMPORT = builtins.__import__
_IN_HOOK = False


def _patch_loaded_target() -> None:
    module = sys.modules.get("instagram_publish_control")
    if module is not None and hasattr(module, "instagram_publish_control_tick"):
        _patch_publish_control(module)


def _lumen_import(name: str, globals=None, locals=None, fromlist=(), level=0):
    global _IN_HOOK
    if _IN_HOOK:
        return _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)
    _IN_HOOK = True
    try:
        module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)
    finally:
        _IN_HOOK = False
    _patch_loaded_target()
    return module


builtins.__import__ = _lumen_import
_patch_loaded_target()
