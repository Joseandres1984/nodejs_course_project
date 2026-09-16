from __future__ import annotations

"""Align External Market Readiness with provider-accepted outbound truth."""

from typing import Any, Dict

import commercial_truth_repair_runtime as truth
import external_market_readiness

VERSION = "1.0-external-market-truth"
_ORIGINAL_TICK = external_market_readiness.external_market_readiness_tick


def external_market_readiness_truth_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    report = dict(_ORIGINAL_TICK(state) or {})
    outbox = list(state.get("outbox", []) or [])
    accepted = [x for x in outbox if truth._provider_accepted(x)]
    delivered = [
        x for x in accepted
        if str(x.get("provider_last_event") or "").lower() == "delivered" or x.get("delivered_at")
    ]
    raw_sent = [x for x in outbox if str(x.get("status") or "").lower() in {"sent", "delivered"}]
    eligible = int(report.get("eligible_external_prospects") or 0)

    report["outbox_sent_recorded_raw"] = len(raw_sent)
    report["outbox_provider_accepted"] = len(accepted)
    report["outbox_delivered_verified"] = len(delivered)
    report["outbox_sent_or_delivered"] = len(accepted)
    report["truth_rule"] = "external_activity_counts_provider_accepted_only; delivery_reported_separately"
    if not report.get("primary_blocker") and report.get("mail_transport_ready") and report.get("outbound_live") and eligible > 0:
        report["status"] = "ACTIVE" if accepted else "READY"
    report["version"] = VERSION
    state["external_market_readiness"] = report
    return report


external_market_readiness.external_market_readiness_tick = external_market_readiness_truth_tick

print(
    {
        "external_market_truth_runtime": {
            "version": VERSION,
            "status": "active",
            "provider_acceptance_required_for_sent": True,
            "verified_delivery_separate": True,
            "binding_authority_changed": False,
        }
    },
    flush=True,
)
