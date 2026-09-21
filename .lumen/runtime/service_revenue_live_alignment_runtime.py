from __future__ import annotations

"""Late-bound paid-service alignment for LUMEN Zero.

Revenue OS v3.1 aligns service attention during bootstrap, but the normal worker can verify or
re-activate accounts later in the same cycle. This patch re-runs the *existing* strict eligibility
alignment at the exact moment outbound asks for eligible prospects. It does not widen eligibility,
change caps, bypass cooldowns, or authorize any binding action; it only makes a prospect that is
already queueable use the relevant paid-service message when a service fit exists.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List

import outbound_engine
import revenue_os_v31_alignment_runtime as alignment_runtime
import service_revenue_outbound_runtime as service_bridge
import service_revenue_runtime


VERSION = "1.0-late-bound-service-outbound-alignment"


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _eligible_with_live_service_alignment(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    # Always start from the original strict outbound gate captured before service prioritization.
    # This preserves company/contact verification, corporate-domain matching, suppression, risk,
    # recency/cooldown and minimum-score requirements exactly as the production sender defines them.
    strict = list(service_bridge._ORIGINAL_ELIGIBLE(state) or [])
    queueable = alignment_runtime._queueable_new_prospects(
        state,
        strict,
        outbound_engine._sequence_id,
    )

    alignment = alignment_runtime.align_strict_service_attention(
        state,
        queueable,
        service_revenue_runtime,
    )

    # The existing service bridge now sees the freshly activated rows and decorates only those
    # strict prospects with service context. Its existing queue/message hooks remain authoritative.
    prospects = list(service_bridge._eligible_service_first(state) or [])

    state["service_revenue_live_alignment"] = {
        "version": VERSION,
        "status": "active",
        "strict_outbound_eligible_now": len(strict),
        "strict_new_sequence_queueable_now": len(queueable),
        "selected_service_candidates_now": int(alignment.get("selected_service_candidates") or 0),
        "seeded_service_matches_now": int(alignment.get("seeded_service_matches") or 0),
        "existing_service_matches_now": int(alignment.get("existing_service_matches") or 0),
        "service_ready_in_returned_set": sum(1 for x in prospects if x.get("service_revenue_ready")),
        "same_outbound_daily_cap": int(outbound_engine.MAX_NEW_PER_DAY),
        "same_outbound_cycle_cap": int(outbound_engine.MAX_NEW_PER_CYCLE),
        "eligibility_gate_relaxed": False,
        "cooldown_bypassed": False,
        "paid_spend": False,
        "binding_authority_changed": False,
        "updated_at": _utcnow(),
        "alignment": alignment,
    }
    return prospects


if not getattr(outbound_engine, "_lumen_live_service_alignment_installed", False):
    outbound_engine._eligible = _eligible_with_live_service_alignment
    outbound_engine._lumen_live_service_alignment_installed = True

print({
    "service_revenue_live_alignment": {
        "version": VERSION,
        "status": "installed",
        "timing": "at_outbound_eligibility_evaluation",
        "eligibility_gate_relaxed": False,
        "outbound_caps_changed": False,
        "cooldown_bypassed": False,
        "paid_spend": False,
        "binding_authority_changed": False,
    }
}, flush=True)
