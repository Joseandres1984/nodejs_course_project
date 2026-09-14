from __future__ import annotations

from typing import Any, Dict

import continuous_learning_runtime

VERSION = "1.0-commercial-learning-v2-log"
_ORIGINAL_TICK = continuous_learning_runtime.continuous_learning_tick


def _logged_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(_ORIGINAL_TICK(state) or {})
    report = state.get("commercial_learning_v2", {}) or {}
    sources = report.get("source_reputation", {}) or {}
    experiments = report.get("experiments", {}) or {}
    anti = report.get("anti_drift", {}) or {}
    ttr = report.get("time_to_revenue", {}) or {}
    brains = report.get("two_brain", {}) or {}
    board = report.get("review_board", {}) or {}
    memory = report.get("business_memory", {}) or {}
    print({
        "commercial_learning_v2": {
            "status": report.get("status"),
            "source_reputation": sources,
            "experiment": experiments.get("active") or experiments.get("latest"),
            "experiment_total": experiments.get("total"),
            "experiment_promoted": experiments.get("promoted"),
            "experiment_demoted": experiments.get("demoted"),
            "anti_drift": anti,
            "time_to_revenue": {
                "cases_tracked": ttr.get("cases_tracked"),
                "stale_cases": ttr.get("stale_cases"),
                "actions_injected": ttr.get("actions_injected"),
                "top_time_pressure": list(ttr.get("top_time_pressure", []) or [])[:3],
            },
            "two_brain": {
                "execution_attention_pct": (brains.get("execution_brain", {}) or {}).get("attention_pct"),
                "exploration_attention_pct": (brains.get("exploration_brain", {}) or {}).get("attention_pct"),
            },
            "review_board": board,
            "business_memory": {
                "best_categories": list(memory.get("best_categories", []) or [])[:3],
                "source_champions": [x.get("domain") for x in list(memory.get("source_champions", []) or [])[:3]],
                "responsive_relationships": list(memory.get("responsive_relationships", []) or [])[:3],
                "top_suppliers": list(memory.get("top_suppliers", []) or [])[:3],
            },
        }
    }, flush=True)
    return result


continuous_learning_runtime.continuous_learning_tick = _logged_tick
print({"commercial_learning_v2_log_runtime": {"version": VERSION, "status": "active"}}, flush=True)
