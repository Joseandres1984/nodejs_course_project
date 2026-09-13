from __future__ import annotations

import runpy

import closer_orchestrator
import war_room
from demand_hunter import demand_hunter_tick
from portfolio_resilience import adjust_lane, resilience_tick


_original_war_room_tick = war_room.war_room_tick
_original_score_lane = closer_orchestrator._score_lane


def _war_room_with_demand_hunter(state):
    demand_report = demand_hunter_tick(state)
    resilience_report = resilience_tick(state)
    report = _original_war_room_tick(state)
    report["demand_hunter"] = demand_report
    report["portfolio_resilience"] = resilience_report
    state["war_room"] = report
    return report


def _score_lane_with_resilience(state, opp):
    lane = _original_score_lane(state, opp)
    return adjust_lane(state, lane)


war_room.war_room_tick = _war_room_with_demand_hunter
closer_orchestrator._score_lane = _score_lane_with_resilience

# Execute the production worker unchanged after installing reversible hooks.
runpy.run_module("worker", run_name="__main__")
