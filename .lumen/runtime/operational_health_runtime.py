from __future__ import annotations

from typing import Any, Dict

import autonomous_coo


VERSION = "1.1-truthful-operational-health"

# Delivery probes/canaries are diagnostics. A historical failed canary must not permanently lower
# business operational health once the production transport has been repaired. Real current
# commercial send failures remain fully penalized and require delivery review before retry.
_DIAGNOSTIC_SOURCE_HINTS = (
    "canary",
    "probe",
    "test_mail",
    "mail_test",
)

_ORIGINAL_BACKLOGS = autonomous_coo._backlogs
_ORIGINAL_TICK = autonomous_coo.operations_control_tick


def _is_diagnostic_outbound(item: Dict[str, Any]) -> bool:
    source = str(item.get("source") or "").strip().lower()
    campaign = str(item.get("campaign") or item.get("campaign_id") or "").strip().lower()
    kind = str(item.get("kind") or item.get("message_kind") or "").strip().lower()
    combined = " ".join((source, campaign, kind))
    return any(hint in combined for hint in _DIAGNOSTIC_SOURCE_HINTS)


def _is_historical_transport_review(item: Dict[str, Any]) -> bool:
    """Recognize failures written by the legacy SMTP path before the HTTPS transport existed.

    The legacy connector stored `send_failed` + `last_error` but did not stamp `failed_at`, provider,
    or route. The current HTTPS path always stamps `failed_at` for a real current failure. We keep
    these legacy rows visible for manual delivery review, but they are historical evidence rather
    than proof that the present transport is unhealthy.
    """
    if item.get("status") != "send_failed" or _is_diagnostic_outbound(item):
        return False
    return not any(
        item.get(key)
        for key in ("failed_at", "email_provider", "email_provider_message_id", "smtp_route")
    )


def truthful_backlogs(state: Dict[str, Any]) -> Dict[str, int]:
    base = dict(_ORIGINAL_BACKLOGS(state) or {})
    failed = [x for x in state.get("outbox", []) or [] if x.get("status") == "send_failed"]
    diagnostic_failed = sum(1 for x in failed if _is_diagnostic_outbound(x))
    historical_review = sum(1 for x in failed if _is_historical_transport_review(x))
    current_commercial_failed = max(0, len(failed) - diagnostic_failed - historical_review)

    # Only a current unresolved commercial failure lowers operational health. Diagnostic and legacy
    # failures stay auditable in separate counters; nothing is deleted and nothing is auto-retried.
    base["outbound_failed"] = current_commercial_failed
    base["outbound_diagnostic_failed"] = diagnostic_failed
    base["outbound_historical_delivery_review"] = historical_review
    base["outbound_failed_total"] = len(failed)
    return base


def truthful_operations_control_tick(
    state: Dict[str, Any],
    db_status: Dict[str, Any],
    *,
    live_outbound: bool,
    persistence_result: bool | None = None,
) -> Dict[str, Any]:
    result = dict(
        _ORIGINAL_TICK(
            state,
            db_status,
            live_outbound=live_outbound,
            persistence_result=persistence_result,
        )
        or {}
    )
    backlogs = truthful_backlogs(state)
    historical_review = int(backlogs.get("outbound_historical_delivery_review") or 0)
    diagnostic_failed = int(backlogs.get("outbound_diagnostic_failed") or 0)
    current_failed = int(backlogs.get("outbound_failed") or 0)

    result["health_semantics_version"] = VERSION
    result["diagnostic_outbound_failures"] = diagnostic_failed
    result["historical_delivery_reviews"] = historical_review
    result["commercial_outbound_failures"] = current_failed
    result["operational_attention"] = {
        "historical_delivery_reviews": historical_review,
        "diagnostic_failures": diagnostic_failed,
        "current_commercial_failures": current_failed,
        "requires_manual_delivery_review": historical_review > 0,
    }
    result["health_policy"] = (
        "current_commercial_failures_penalize_health; diagnostic_and_legacy_transport_failures_"
        "remain_visible_as_attention_without_misrepresenting_current_system_health"
    )
    state["autonomous_coo"] = result
    return result


autonomous_coo._backlogs = truthful_backlogs
autonomous_coo.operations_control_tick = truthful_operations_control_tick
