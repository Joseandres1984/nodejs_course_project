from __future__ import annotations

"""Bridge the Autonomy Core into the completed worker learning phase."""

from typing import Any, Dict

import autonomy_core_runtime
import continuous_learning_runtime

VERSION = "1.0-autonomy-core-bridge"

_ORIGINAL_CONTINUOUS_LEARNING_TICK = continuous_learning_runtime.continuous_learning_tick


def _continuous_learning_with_autonomy_core(state: Dict[str, Any]) -> Dict[str, Any]:
    report = dict(_ORIGINAL_CONTINUOUS_LEARNING_TICK(state) or {})
    core = autonomy_core_runtime.autonomy_core_tick(state)
    counts = dict(core.get("counts", {}) or {})
    print({
        "autonomy_core": {
            "version": core.get("version"),
            "status": core.get("status"),
            "mode": core.get("mode"),
            "learning_cycle": core.get("learning_cycle"),
            "goals": counts.get("goals"),
            "experiences": counts.get("experiences"),
            "lessons": counts.get("lessons"),
            "promoted_lessons": counts.get("promoted_lessons"),
            "open_peer_help": counts.get("open_peer_help"),
            "open_research_missions": counts.get("open_research_missions"),
            "skill_agents": counts.get("skill_agents"),
            "critic_issues": counts.get("critic_issues"),
            "role_attention": core.get("role_attention"),
            "binding_authority_changed": (core.get("authority") or {}).get("binding_authority_changed"),
        }
    }, flush=True)
    return report


if not getattr(continuous_learning_runtime.continuous_learning_tick, "_autonomy_core_wrapped", False):
    _continuous_learning_with_autonomy_core._autonomy_core_wrapped = True
    _continuous_learning_with_autonomy_core._autonomy_core_original = _ORIGINAL_CONTINUOUS_LEARNING_TICK
    continuous_learning_runtime.continuous_learning_tick = _continuous_learning_with_autonomy_core

print({"autonomy_core_bridge_runtime": {"version": VERSION, "status": "active"}}, flush=True)
