from __future__ import annotations

"""Fail-open runtime bridge for LUMEN Cognitive Core v1.

The bridge is called after the existing Autonomy Core learning tick. Default mode
is shadow: LUMEN may reason and persist a recommendation, but no tool can execute.
"""

import os
from typing import Any, Dict

import cognitive_core_v1

VERSION = "1.0-cognitive-core-bridge"
DEFAULT_EVERY_N_TICKS = 3


def _int_env(name: str, default: int) -> int:
    try:
        return int(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        return default


def cognitive_core_bridge_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    if not cognitive_core_v1.cognitive_core_enabled():
        disabled = {
            "version": VERSION,
            "status": "disabled",
            "mode": os.getenv("LUMEN_COGNITIVE_CORE_V1_MODE", "shadow"),
            "executed": False,
        }
        state["cognitive_core_bridge_v1"] = disabled
        return disabled

    scheduler = state.get("cognitive_core_v1_scheduler")
    if not isinstance(scheduler, dict):
        scheduler = {}
    ticks = max(0, int(scheduler.get("ticks") or 0)) + 1
    every = max(1, min(48, _int_env("LUMEN_COGNITIVE_CORE_V1_EVERY_N_TICKS", DEFAULT_EVERY_N_TICKS)))
    scheduler.update({"ticks": ticks, "every_n_ticks": every})
    state["cognitive_core_v1_scheduler"] = scheduler

    if ticks != 1 and ticks % every != 0:
        skipped = {
            "version": VERSION,
            "status": "cadence_skip",
            "mode": os.getenv("LUMEN_COGNITIVE_CORE_V1_MODE", "shadow"),
            "tick": ticks,
            "every_n_ticks": every,
            "executed": False,
        }
        state["cognitive_core_bridge_v1"] = skipped
        return skipped

    try:
        result = cognitive_core_v1.run_cognitive_core(state)
        summary = {
            "version": VERSION,
            "status": result.get("status"),
            "mode": result.get("mode"),
            "provider": result.get("provider"),
            "cycle_id": result.get("cycle_id"),
            "action_type": (result.get("proposal") or {}).get("action_type"),
            "authority": (result.get("policy") or {}).get("authority"),
            "requires_approval": (result.get("policy") or {}).get("requires_approval"),
            "executed": (result.get("execution") or {}).get("executed", False),
            "tick": ticks,
            "every_n_ticks": every,
            "guardrails": result.get("guardrails"),
        }
    except Exception as exc:
        summary = {
            "version": VERSION,
            "status": "degraded_fail_open",
            "mode": os.getenv("LUMEN_COGNITIVE_CORE_V1_MODE", "shadow"),
            "error": f"{type(exc).__name__}: {str(exc)[:240]}",
            "executed": False,
            "tick": ticks,
            "every_n_ticks": every,
        }

    state["cognitive_core_bridge_v1"] = summary
    return summary
