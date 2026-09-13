from __future__ import annotations

import copy
import os
import runpy

import autonomous_distribution
import closer_orchestrator
import demand_hunter
import retail_velocity_radar
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
    # Give the retail radar a bounded share of the existing search budget first; it leaves at least one
    # query reserved for the core B2B scout and never exceeds its own small daily cap.
    retail_report = retail_velocity_radar.retail_velocity_tick(state)
    scout_report = _original_scout_tick(state)
    demand_report = demand_hunter.demand_hunter_tick(state)
    scout_report["demand_hunter"] = demand_report
    scout_report["retail_velocity"] = retail_report
    return scout_report


def _war_room_with_resilience(state):
    resilience_report = resilience_tick(state)
    report = _original_war_room_tick(state)
    distribution_report = autonomous_distribution.distribution_tick(state)
    report["demand_hunter"] = state.get("demand_hunter", {})
    report["retail_velocity"] = state.get("retail_velocity_radar", {})
    report["portfolio_resilience"] = resilience_report
    report["autonomous_distribution"] = distribution_report
    state["war_room"] = report
    return report


def _score_lane_with_resilience(state, opp):
    lane = _original_score_lane(state, opp)
    return adjust_lane(state, lane)


def _market_canary_probe():
    """Exercise the real Market inquiry handler and Lead Intelligence on an isolated state copy.

    The probe never persists the synthetic buyer, listing, lead, event, or candidate account. Only the
    PASS/FAIL summary is written to production state, so business KPIs and learning remain uncontaminated.
    """
    version = str(os.getenv("LUMEN_MARKET_CANARY_PROBE_VERSION", "")).strip()
    if not version:
        return None

    from app import STATE, load_state, save_state
    import alert_main
    from lead_intelligence import qualify_tick

    load_state()
    previous = STATE.get("market_canary_probe", {}) or {}
    if str(previous.get("version") or "") == version and previous.get("passed") is True:
        print({"market_canary_probe": {"version": version, "passed": True, "status": "already_verified"}}, flush=True)
        return previous

    probe_state = {
        "autonomous_listings": [{
            "id": "LST-CANARY-PROBE",
            "category": "instrumentación de presión",
            "market": "Argentina",
            "status": "published",
            "title": "Canary de integración LUMEN Market",
        }],
        "market_inquiries": [],
        "distribution_events": [],
        "research_leads": [],
        "candidate_accounts": [],
        "activity": [],
        "decision_ledger": [],
    }

    original_state = alert_main.STATE
    original_save = alert_main.save_state
    response_status = None
    error = None
    qualification = {}
    try:
        alert_main.STATE = probe_state
        alert_main.save_state = lambda: True
        response = alert_main.market_inquiry_submit(
            listing_id="LST-CANARY-PROBE",
            company="Canary Industrial Argentina",
            name="LUMEN Integration Probe",
            email="compras@canary-industrial.example",
            need="Compras y abastecimiento de industria: requerimos instrumentación de presión para mantenimiento de planta.",
            phone="",
            quantity="2 unidades",
            deadline="30 días",
            delivery_location="Buenos Aires, Argentina",
            website="",
        )
        response_status = int(getattr(response, "status_code", 0) or 0)
        qualification = qualify_tick(probe_state)
    except Exception as exc:
        error = f"{type(exc).__name__}: {str(exc)[:240]}"
    finally:
        alert_main.STATE = original_state
        alert_main.save_state = original_save

    inquiry_ok = len(probe_state.get("market_inquiries", [])) == 1
    event_ok = any(x.get("event") == "inquiry" for x in probe_state.get("distribution_events", []))
    lead_ok = any(x.get("direct_inbound_demand") for x in probe_state.get("research_leads", []))
    candidate_ok = int(qualification.get("candidates_created") or 0) >= 1
    passed = bool(response_status == 200 and inquiry_ok and event_ok and lead_ok and candidate_ok and not error)

    summary = {
        "version": version,
        "passed": passed,
        "response_status": response_status,
        "inquiry_created": inquiry_ok,
        "distribution_event_created": event_ok,
        "buyer_lead_created": lead_ok,
        "lead_intelligence_processed": int(qualification.get("processed") or 0),
        "candidate_account_created": candidate_ok,
        "synthetic_business_data_persisted": False,
        "excluded_from_business_kpis": True,
        "error": error,
    }
    STATE["market_canary_probe"] = copy.deepcopy(summary)
    if not save_state():
        summary["summary_persisted"] = False
    else:
        summary["summary_persisted"] = True
    print({"market_canary_probe": summary}, flush=True)
    return summary


demand_hunter._score = _institutional_demand_score
autonomous_distribution._choose_channels = _owned_market_first_channels
scout_connector.scout_tick = _scout_with_demand_hunter
war_room.war_room_tick = _war_room_with_resilience
closer_orchestrator._score_lane = _score_lane_with_resilience

# Execute the production worker unchanged after installing reversible hooks.
runpy.run_module("worker", run_name="__main__")

# One-shot, non-polluting integration verification when its version is explicitly enabled.
_market_canary_probe()
