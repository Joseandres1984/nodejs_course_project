from __future__ import annotations

import runpy

import closer_orchestrator
import demand_hunter
import war_room
from portfolio_resilience import adjust_lane, resilience_tick


_original_war_room_tick = war_room.war_room_tick
_original_score_lane = closer_orchestrator._score_lane
_original_demand_score = demand_hunter._score


def _institutional_demand_score(category, item):
    scoring = _original_demand_score(category, item)
    host = str(scoring.get("host") or "")
    institutional = host.endswith(".gob.ar") or host.endswith(".gov.ar") or host.endswith(".edu.ar")
    if institutional and int(scoring.get("demand_hits") or 0) > 0 and int(scoring.get("category_hits") or 0) > 0:
        scoring["score"] = min(100, int(scoring.get("score") or 0) + 10)
        scoring["institutional_source"] = True
    else:
        scoring["institutional_source"] = False
    return scoring


def _war_room_with_demand_hunter(state):
    demand_report = demand_hunter.demand_hunter_tick(state)
    resilience_report = resilience_tick(state)
    report = _original_war_room_tick(state)
    report["demand_hunter"] = demand_report
    report["portfolio_resilience"] = resilience_report
    state["war_room"] = report
    return report


def _score_lane_with_resilience(state, opp):
    lane = _original_score_lane(state, opp)
    return adjust_lane(state, lane)


demand_hunter._score = _institutional_demand_score
war_room.war_room_tick = _war_room_with_demand_hunter
closer_orchestrator._score_lane = _score_lane_with_resilience

# Execute the production worker unchanged after installing reversible hooks.
runpy.run_module("worker", run_name="__main__")
