from __future__ import annotations

import runpy

import war_room
from demand_hunter import demand_hunter_tick


_original_war_room_tick = war_room.war_room_tick


def _war_room_with_demand_hunter(state):
    demand_report = demand_hunter_tick(state)
    report = _original_war_room_tick(state)
    report["demand_hunter"] = demand_report
    state["war_room"] = report
    return report


war_room.war_room_tick = _war_room_with_demand_hunter

# Execute the production worker unchanged after installing the reversible hook.
runpy.run_module("worker", run_name="__main__")
