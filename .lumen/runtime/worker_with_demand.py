from __future__ import annotations

import copy
import os
import runpy
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import autonomous_distribution
import closer_orchestrator
import demand_hunter
import retail_velocity_radar
import scout_connector
import war_room
from portfolio_resilience import adjust_lane, resilience_tick


# Search-budget policy: reset by Argentina calendar day and protect a small retail quota
# so core B2B research cannot consume every query before the retail radar runs.
_SCOUT_TIMEZONE_NAME = str(os.getenv("LUMEN_SCOUT_TIMEZONE", "America/Argentina/Buenos_Aires")).strip() or "America/Argentina/Buenos_Aires"
try:
    _SCOUT_TIMEZONE = ZoneInfo(_SCOUT_TIMEZONE_NAME)
except Exception:
    _SCOUT_TIMEZONE = timezone(timedelta(hours=-3))

_RETAIL_RESERVED_QUERIES = max(
    1,
    min(
        max(1, int(scout_connector.DAILY_QUERY_BUDGET) - 1),
        int(os.getenv("LUMEN_RETAIL_RESERVED_BUDGET", str(retail_velocity_radar.DAILY_RETAIL_BUDGET))),
    ),
)


def _market_date() -> str:
    return datetime.now(_SCOUT_TIMEZONE).strftime("%Y-%m-%d")


def _market_scout_budget(state):
    today = _market_date()
    daily = int(scout_connector.DAILY_QUERY_BUDGET)
    budget = state.setdefault(
        "scout_budget",
        {
            "date": today,
            "timezone": _SCOUT_TIMEZONE_NAME,
            "queries_used": 0,
            "daily_budget": daily,
        },
    )

    # The timezone marker intentionally forces a one-time migration/reset from the old UTC budget.
    if budget.get("date") != today or budget.get("timezone") != _SCOUT_TIMEZONE_NAME:
        budget.clear()
        budget.update(
            {
                "date": today,
                "timezone": _SCOUT_TIMEZONE_NAME,
                "queries_used": 0,
                "daily_budget": daily,
                "reset_reason": "market_day_or_timezone_changed",
                "reset_at": scout_connector.utcnow(),
            }
        )

    budget["daily_budget"] = daily
    budget["queries_used"] = max(0, int(budget.get("queries_used", 0)))
    total_remaining = max(0, daily - budget["queries_used"])

    retail_budget = state.get("retail_velocity_budget", {}) or {}
    retail_used_today = 0
    if retail_budget.get("date") == today and retail_budget.get("timezone") == _SCOUT_TIMEZONE_NAME:
        retail_used_today = max(0, int(retail_budget.get("queries_used", 0)))

    reserved_daily = min(_RETAIL_RESERVED_QUERIES, max(0, daily - 1))
    reserved_remaining = max(0, reserved_daily - min(reserved_daily, retail_used_today))
    general_remaining = max(0, total_remaining - reserved_remaining)

    # Existing Scout/Demand code reads queries_remaining. Give it only the general pool.
    # Retail uses queries_remaining_total below, so its protected share remains available.
    budget["queries_remaining_total"] = total_remaining
    budget["retail_reserved_daily"] = reserved_daily
    budget["retail_reserved_used"] = min(reserved_daily, retail_used_today)
    budget["retail_reserved_remaining"] = reserved_remaining
    budget["general_queries_remaining"] = general_remaining
    budget["queries_remaining"] = general_remaining
    budget["timezone"] = _SCOUT_TIMEZONE_NAME
    return budget


def _market_retail_budget(state):
    today = _market_date()
    daily = int(retail_velocity_radar.DAILY_RETAIL_BUDGET)
    row = state.setdefault(
        "retail_velocity_budget",
        {
            "date": today,
            "timezone": _SCOUT_TIMEZONE_NAME,
            "queries_used": 0,
        },
    )
    if row.get("date") != today or row.get("timezone") != _SCOUT_TIMEZONE_NAME:
        row.clear()
        row.update(
            {
                "date": today,
                "timezone": _SCOUT_TIMEZONE_NAME,
                "queries_used": 0,
                "reset_at": scout_connector.utcnow(),
            }
        )
    row["daily_budget"] = daily
    row["queries_used"] = max(0, int(row.get("queries_used", 0)))
    row["queries_remaining"] = max(0, daily - row["queries_used"])
    row["timezone"] = _SCOUT_TIMEZONE_NAME
    return row


def _market_retail_consume_search_budget(state) -> bool:
    own = _market_retail_budget(state)
    global_budget = _market_scout_budget(state)
    total_remaining = max(
        0,
        int(global_budget.get("daily_budget") or scout_connector.DAILY_QUERY_BUDGET)
        - int(global_budget.get("queries_used") or 0),
    )
    if total_remaining <= 0 or int(own.get("queries_remaining") or 0) <= 0:
        return False

    global_budget["queries_used"] = int(global_budget.get("queries_used") or 0) + 1
    own["queries_used"] = int(own.get("queries_used") or 0) + 1
    _market_retail_budget(state)
    _market_scout_budget(state)
    return True


_original_scout_status = scout_connector.status


def _scout_status_with_budget_policy():
    report = _original_scout_status()
    report["budget_timezone"] = _SCOUT_TIMEZONE_NAME
    report["retail_reserved_queries"] = _RETAIL_RESERVED_QUERIES
    return report


# Install budget hooks before the production scout tick is captured.
scout_connector._budget = _market_scout_budget
scout_connector.status = _scout_status_with_budget_policy
retail_velocity_radar._retail_budget = _market_retail_budget
retail_velocity_radar._consume_search_budget = _market_retail_consume_search_budget


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
    # Retail receives its own protected daily quota first. The global cap still applies, while the
    # remaining general pool is shared by the core B2B scout and demand hunter.
    retail_report = retail_velocity_radar.retail_velocity_tick(state)
    after_retail = _market_scout_budget(state)
    retail_report["global_search_budget_remaining"] = int(after_retail.get("queries_remaining_total") or 0)
    retail_report["retail_reserved_remaining"] = int(after_retail.get("retail_reserved_remaining") or 0)
    retail_report["budget_timezone"] = _SCOUT_TIMEZONE_NAME

    scout_report = _original_scout_tick(state)
    demand_report = demand_hunter.demand_hunter_tick(state)
    final_budget = _market_scout_budget(state)

    scout_report["demand_hunter"] = demand_report
    scout_report["retail_velocity"] = retail_report
    scout_report["budget_used_today"] = int(final_budget.get("queries_used") or 0)
    scout_report["budget_remaining"] = int(final_budget.get("general_queries_remaining") or 0)
    scout_report["budget_remaining_total"] = int(final_budget.get("queries_remaining_total") or 0)
    scout_report["retail_reserved_remaining"] = int(final_budget.get("retail_reserved_remaining") or 0)
    scout_report["budget_timezone"] = _SCOUT_TIMEZONE_NAME
    scout_report["budget_exhausted"] = int(final_budget.get("general_queries_remaining") or 0) <= 0
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
