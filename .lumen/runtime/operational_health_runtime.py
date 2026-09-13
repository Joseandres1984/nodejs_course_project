from __future__ import annotations

from typing import Any, Dict

import autonomous_coo


VERSION = "1.0-truthful-operational-health"

# Delivery probes/canaries are diagnostics. A historical failed canary must not permanently lower
# business operational health once the production transport has been repaired. Real commercial
# send failures remain fully penalized and require delivery review before retry.
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


def truthful_backlogs(state: Dict[str, Any]) -> Dict[str, int]:
    base = dict(_ORIGINAL_BACKLOGS(state) or {})
    failed = [x for x in state.get("outbox", []) or [] if x.get("status") == "send_failed"]
    diagnostic_failed = sum(1 for x in failed if _is_diagnostic_outbound(x))
    commercial_failed = len(failed) - diagnostic_failed

    # `outbound_failed` is intentionally the unresolved commercial backlog used by the COO health
    # score. Diagnostic failures stay visible separately instead of being hidden or deleted.
    base["outbound_failed"] = max(0, commercial_failed)
    base["outbound_diagnostic_failed"] = max(0, diagnostic_failed)
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
    result["health_semantics_version"] = VERSION
    result["diagnostic_outbound_failures"] = int(backlogs.get("outbound_diagnostic_failed") or 0)
    result["commercial_outbound_failures"] = int(backlogs.get("outbound_failed") or 0)
    result["health_policy"] = "diagnostic_canary_failures_tracked_separately; unresolved_commercial_failures_penalize_health"
    state["autonomous_coo"] = result
    return result


autonomous_coo._backlogs = truthful_backlogs
autonomous_coo.operations_control_tick = truthful_operations_control_tick
