from __future__ import annotations

import runpy

import autonomous_distribution
import closer_orchestrator
import demand_hunter
import scout_connector
import war_room
from portfolio_resilience import adjust_lane, resilience_tick


_original_scout_tick = scout_connector.scout_tick
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


def _owned_market_first_channels(category, metrics, learning):
    """LUMEN Market is the owned primary channel; other channels only amplify it."""
    market_score = autonomous_distribution._channel_score(
        category, "lumen_public_catalog", metrics, learning
    )
    email_score = autonomous_distribution._channel_score(
        category, "targeted_b2b_email", metrics, learning
    )
    external = [
        {
            "channel": channel,
            "score": autonomous_distribution._channel_score(category, channel, metrics, learning),
        }
        for channel in ("linkedin_company", "mercadolibre", "b2b_directories")
    ]
    external.sort(key=lambda row: row["score"], reverse=True)

    selected = [{
        "channel": "lumen_public_catalog",
        "score": max(90.0, market_score),
        "execution_mode": "autonomous_owned_primary_channel",
        "connector_required": False,
        "priority": 1,
    }]

    if email_score >= 45:
        selected.append({
            "channel": "targeted_b2b_email",
            "score": email_score,
            "execution_mode": "managed_by_existing_revops",
            "connector_required": False,
            "priority": 2,
        })

    if external and external[0]["score"] >= 70:
        selected.append({
            **external[0],
            "execution_mode": "optional_amplification_when_connector_authorized",
            "connector_required": True,
            "priority": 3,
        })
    return selected


def _scout_with_demand_hunter(state):
    scout_report = _original_scout_tick(state)
    demand_report = demand_hunter.demand_hunter_tick(state)
    scout_report["demand_hunter"] = demand_report
    return scout_report


def _war_room_with_resilience(state):
    resilience_report = resilience_tick(state)
    report = _original_war_room_tick(state)
    distribution_report = autonomous_distribution.distribution_tick(state)
    report["demand_hunter"] = state.get("demand_hunter", {})
    report["portfolio_resilience"] = resilience_report
    report["autonomous_distribution"] = distribution_report
    state["war_room"] = report
    return report


def _score_lane_with_resilience(state, opp):
    lane = _original_score_lane(state, opp)
    return adjust_lane(state, lane)


demand_hunter._score = _institutional_demand_score
autonomous_distribution._choose_channels = _owned_market_first_channels
scout_connector.scout_tick = _scout_with_demand_hunter
war_room.war_room_tick = _war_room_with_resilience
closer_orchestrator._score_lane = _score_lane_with_resilience

# Execute the production worker unchanged after installing reversible hooks.
runpy.run_module("worker", run_name="__main__")
