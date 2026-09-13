from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict

import outbound_engine
from https_mail_transport import transport_status

VERSION = "1.1-outbound-recovery"
MAX_RECOVERY_PER_CYCLE = 2
MAX_RECOVERY_RETRIES = 2
_ORIGINAL_TICK = outbound_engine.outbound_engine_tick


def _suppressed(state: Dict[str, Any], email: str) -> bool:
    target = str(email or "").strip().lower()
    if not target:
        return True
    if target in {str(x).strip().lower() for x in state.get("opt_out", []) or []}:
        return True
    for row in state.get("email_suppression", []) or []:
        if isinstance(row, dict) and str(row.get("email") or "").strip().lower() == target:
            return True
        if isinstance(row, str) and row.strip().lower() == target:
            return True
    return False


def _successful_recent_contact(state: Dict[str, Any], email: str) -> bool:
    """Only a verified successful send opens the recontact cooldown.

    queued/ready/blocked/send_failed attempts never reached the counterparty and must not freeze a
    valid prospect for RECONTACT_DAYS. This preserves anti-spam cooldown after real delivery while
    allowing bounded transport recovery after a failed attempt.
    """
    target = str(email or "").strip().lower()
    cutoff = outbound_engine.utcnow_dt() - timedelta(days=outbound_engine.RECONTACT_DAYS)
    for item in reversed(state.get("outbox", []) or []):
        if str(item.get("contact") or "").strip().lower() != target:
            continue
        if item.get("source") not in {"outbound_engine", "distribution_operator_canary"}:
            continue
        if str(item.get("status") or "") not in {"sent", "delivered"}:
            continue
        when = outbound_engine._parse(item.get("delivered_at") or item.get("sent_at"))
        if when and when >= cutoff:
            return True
    return False


# Patch eligibility semantics before the original Outbound Engine evaluates prospects.
outbound_engine._recently_contacted = _successful_recent_contact


def _recover_failed_outbound(state: Dict[str, Any]) -> int:
    transport = transport_status()
    if not transport.get("ready"):
        return 0

    recovered = 0
    for item in state.get("outbox", []) or []:
        if recovered >= MAX_RECOVERY_PER_CYCLE:
            break
        if item.get("source") != "outbound_engine" or item.get("status") != "send_failed":
            continue
        if int(item.get("https_recovery_count") or 0) >= MAX_RECOVERY_RETRIES:
            continue
        email = str(item.get("contact") or "").strip().lower()
        if not item.get("contact_verified") or _suppressed(state, email):
            continue
        # Preserve existing communication and quality gates. We never revive a message that did not
        # already pass them; this is transport recovery, not a way around commercial governance.
        if item.get("quality_gate") != "passed" or not item.get("communication_reviewed"):
            continue

        item["https_recovery_count"] = int(item.get("https_recovery_count") or 0) + 1
        item["last_transport_error"] = item.pop("last_error", None)
        item["status"] = "ready"
        item["recovery_reason"] = "previous_delivery_failed_before_verified_contact; retry_same_message_over_ready_https_provider"
        recovered += 1
    return recovered


def recovery_outbound_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    recovered = _recover_failed_outbound(state)
    report = dict(_ORIGINAL_TICK(state) or {})
    report["recovery_runtime_version"] = VERSION
    report["failed_messages_requeued"] = recovered
    report["transport_ready_for_recovery"] = bool(transport_status().get("ready"))
    report["recent_contact_policy"] = "sent_or_delivered_only"
    state["outbound_engine"] = report
    return report


if not getattr(outbound_engine, "_lumen_outbound_recovery_installed", False):
    outbound_engine.outbound_engine_tick = recovery_outbound_tick
    outbound_engine._lumen_outbound_recovery_installed = True
