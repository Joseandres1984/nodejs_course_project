from __future__ import annotations

"""Protect an upstream verified-demand gap from stale conversion-lane hysteresis.

Conversion hysteresis is useful for avoiding strategy thrash, but it must not hold LUMEN in a
secondary lane when a canonical prerequisite is absent. If verified buyers exist and none has a
verified demand signal, no canonical opportunity can be created. In that exact state the canonical
`demand_discovery` lane preempts hysteresis immediately. All evidence, search-budget, outbound and
binding-action gates remain unchanged.

The same bootstrap point installs bounded Demand Recovery and Revenue Expansion. Demand Recovery may
only reorder buyers that Demand Intelligence already considers eligible. Revenue Expansion only
materializes zero-cost, nonbinding monetization lanes and catalog priorities; neither module widens
search, evidence, outbound, payment or binding authority.
"""

from datetime import datetime, timezone
from typing import Any, Dict

# Importing conversion_autonomy_runtime first intentionally installs its normal hysteresis wrapper.
# This module then adds one narrow upstream-prerequisite guard on top of that finished behavior.
import conversion_autonomy_runtime  # noqa: F401
import revenue_allocator_runtime

VERSION = "1.2-upstream-demand-recovery-revenue-expansion"
_ORIGINAL_RESOLVE = revenue_allocator_runtime._resolve_lane_with_anti_drift


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _resolve_with_upstream_guard(
    state: Dict[str, Any],
    truth: Dict[str, Any],
    metrics: Dict[str, int],
) -> Dict[str, Any]:
    resolved = dict(_ORIGINAL_RESOLVE(state, truth, metrics) or {})
    canonical_lane = str(truth.get("recommended_lane") or "")
    verified_buyers = int(metrics.get("verified_buyers") or 0)
    buyers_with_demand = int(metrics.get("buyers_with_demand") or 0)

    upstream_gap = (
        canonical_lane == "demand_discovery"
        and verified_buyers > 0
        and buyers_with_demand == 0
    )
    if not upstream_gap:
        resolved["upstream_prerequisite_guard"] = False
        return resolved

    previous_lane = str(resolved.get("lane") or canonical_lane)
    memory = state.setdefault("revenue_lane_hysteresis", {})
    switched = previous_lane != "demand_discovery" or str(memory.get("current_lane") or "") != "demand_discovery"
    memory.update(
        {
            "version": "1.1-upstream-prerequisite-aware",
            "current_lane": "demand_discovery",
            "hold_cycles": 1,
            "pending_lane": None,
            "pending_count": 0,
            "current_metric_value": buyers_with_demand,
            "last_desired_lane": "demand_discovery",
            "switched_this_cycle": switched,
            "upstream_prerequisite_preempted_hysteresis": True,
            "updated_at": _utcnow(),
        }
    )

    resolved.update(
        {
            "lane": "demand_discovery",
            "base_lane": "demand_discovery",
            "success_metric": revenue_allocator_runtime.LANE_SUCCESS_METRICS["demand_discovery"],
            "reason": str(truth.get("reason") or "Hay un gap de demanda verificada que bloquea oportunidades canónicas."),
            "anti_drift_applied": False,
            "anti_drift_guard_reason": "upstream_verified_demand_gap_preempts_hysteresis",
            "hysteresis": dict(memory),
            "upstream_prerequisite_guard": True,
            "previous_lane_preempted": previous_lane if previous_lane != "demand_discovery" else None,
        }
    )
    state["revenue_lane_upstream_guard"] = {
        "version": VERSION,
        "status": "active",
        "canonical_lane": "demand_discovery",
        "previous_lane": previous_lane,
        "verified_buyers": verified_buyers,
        "buyers_with_verified_demand": buyers_with_demand,
        "hysteresis_preempted": switched,
        "search_cap_changed": False,
        "evidence_thresholds_changed": False,
        "outbound_gate_relaxed": False,
        "binding_authority_changed": False,
        "updated_at": _utcnow(),
    }
    return resolved


revenue_allocator_runtime._resolve_lane_with_anti_drift = _resolve_with_upstream_guard

# Install Demand Recovery before worker_entry imports the production Demand Intelligence path.
# The recovery report uses the prior persisted Director state; the candidate-order patch then
# affects this cycle immediately. Any exception leaves the original production behavior intact.
try:
    import demand_recovery_runtime  # noqa: F401

    demand_recovery_runtime.run_once()
except Exception as exc:
    print(
        {
            "demand_recovery": {
                "status": "degraded_fail_open",
                "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                "fallback": "original_demand_intelligence_candidate_order",
                "search_cap_changed": False,
                "minimum_demand_score_unchanged": 75,
                "cooldowns_bypassed": False,
                "requirements_inferred": False,
                "outbound_gate_relaxed": False,
                "binding_authority_changed": False,
                "monetary_budget_usd": 0,
            }
        },
        flush=True,
    )

# Revenue Expansion runs before the worker cycle so every commercial engine can see the latest
# monetization catalog and priority order. It changes attention/catalog only; no charge, payment,
# discount, contract or additional search/outbound authority is created here.
try:
    import app as _revenue_app
    import revenue_expansion_runtime

    if _revenue_app.load_state():
        _revenue_report = dict(revenue_expansion_runtime.run_once(_revenue_app.STATE) or {})
        _revenue_report["persisted"] = bool(_revenue_app.save_state())
        print(
            {
                "revenue_expansion": {
                    "version": _revenue_report.get("version"),
                    "status": _revenue_report.get("status"),
                    "lane_priority": _revenue_report.get("lane_priority"),
                    "counts": _revenue_report.get("counts"),
                    "realized_revenue_truth_usd": _revenue_report.get("realized_revenue_truth_usd"),
                    "monetary_budget_usd": _revenue_report.get("monetary_budget_usd"),
                    "search_cap_changed": _revenue_report.get("search_cap_changed"),
                    "outbound_caps_changed": _revenue_report.get("outbound_caps_changed"),
                    "binding_authority_changed": _revenue_report.get("binding_authority_changed"),
                    "persisted": _revenue_report.get("persisted"),
                }
            },
            flush=True,
        )
except Exception as exc:
    print(
        {
            "revenue_expansion": {
                "status": "degraded_fail_open",
                "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                "monetary_budget_usd": 0,
                "search_cap_changed": False,
                "outbound_caps_changed": False,
                "binding_authority_changed": False,
            }
        },
        flush=True,
    )

print(
    {
        "revenue_lane_upstream_guard_runtime": {
            "version": VERSION,
            "status": "active",
            "rule": "verified_buyers_and_zero_verified_demand_preempt_conversion_hysteresis",
            "demand_recovery": "bounded_priority_patch_installed",
            "revenue_expansion": "zero_cost_nonbinding_lanes_installed",
            "search_cap_changed": False,
            "evidence_thresholds_changed": False,
            "outbound_gate_relaxed": False,
            "binding_authority_changed": False,
        }
    },
    flush=True,
)
