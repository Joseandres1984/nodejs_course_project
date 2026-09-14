from __future__ import annotations

from typing import Any, Dict

import autonomy_operating_system
from opportunity_factory_runtime import opportunity_factory_tick
from revenue_funnel_runtime import revenue_funnel_tick

VERSION = "1.1-revenue-execution-bridge"
_ORIGINAL_AUTONOMY_TICK = autonomy_operating_system.autonomy_tick


def _autonomy_with_revenue_execution(state: Dict[str, Any]) -> Dict[str, Any]:
    factory: Dict[str, Any]
    funnel: Dict[str, Any]
    errors = []
    try:
        factory = dict(opportunity_factory_tick(state) or {})
    except Exception as exc:
        factory = {"status": "degraded_fail_open", "error": f"{type(exc).__name__}: {str(exc)[:220]}"}
        errors.append({"engine": "opportunity_factory", "error": factory["error"]})
    try:
        funnel = dict(revenue_funnel_tick(state) or {})
    except Exception as exc:
        funnel = {"status": "degraded_fail_open", "error": f"{type(exc).__name__}: {str(exc)[:220]}"}
        errors.append({"engine": "revenue_funnel", "error": funnel["error"]})

    report = dict(_ORIGINAL_AUTONOMY_TICK(state) or {})
    report["opportunity_factory"] = {
        "status": factory.get("status"),
        "signals_reviewed": factory.get("signals_reviewed"),
        "ready_for_pipeline": factory.get("ready_for_pipeline"),
        "enrichment_required": factory.get("enrichment_required"),
        "opportunities_materialized": factory.get("opportunities_materialized"),
        "actions_injected": factory.get("actions_injected"),
    }
    report["revenue_funnel"] = {
        "status": funnel.get("status"),
        "counts": funnel.get("counts"),
        "deltas": funnel.get("deltas"),
        "bottleneck": funnel.get("bottleneck"),
    }
    report["revenue_execution_errors"] = errors
    state["autonomy_operating_system"] = report
    print({
        "revenue_execution_v2": {
            "opportunity_factory": report["opportunity_factory"],
            "revenue_funnel": report["revenue_funnel"],
            "errors": errors,
        }
    }, flush=True)
    return report


autonomy_operating_system.autonomy_tick = _autonomy_with_revenue_execution
print({"revenue_execution_bridge_runtime": {"version": VERSION, "status": "active", "hooks": ["opportunity_factory", "revenue_funnel"]}}, flush=True)
