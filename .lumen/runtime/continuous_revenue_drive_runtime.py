"""LUMEN Continuous Revenue Drive.

Keeps the autonomous company productive when one resource pool (for example
external search) is exhausted. It does not authorize binding contracts,
payments, legal commitments, production self-modification, or new external
accounts/connectors.

This module is intentionally additive and reversible: importing it installs
small runtime wrappers around existing ticks so LUMEN always records a
revenue-oriented fallback plan and keeps reallocating attention to the current
commercial bottleneck.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List

VERSION = "1.0-continuous-revenue-drive"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _score_actions(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build a ranked queue of useful non-binding work from existing state."""
    funnel = _safe_dict(state.get("business_funnel"))
    readiness = _safe_dict(state.get("external_market_readiness"))
    workforce = _safe_dict(state.get("agent_workforce"))
    professional = _safe_dict(state.get("professional_casework"))
    acquisition = _safe_dict(state.get("acquisition_campaigns"))
    distribution = _safe_dict(state.get("distribution_operator"))

    actions: List[Dict[str, Any]] = []

    def add(priority: int, lane: str, action: str, reason: str, metric: str) -> None:
        actions.append({
            "priority": priority,
            "lane": lane,
            "action": action,
            "reason": reason,
            "success_metric": metric,
            "binding": False,
        })

    verified_buyers = int(funnel.get("verified_buyers") or 0)
    demand_buyers = int(funnel.get("buyers_with_public_demand") or 0)
    verified_channels = int(funnel.get("verified_commercial_channels") or 0)
    verified_emails = int(funnel.get("verified_corporate_emails") or 0)
    opportunities = int(funnel.get("evidence_backed_opportunities") or workforce.get("workload", {}).get("opportunities") or 0)
    quotes = int(workforce.get("workload", {}).get("quotes") or 0)
    proposals = int(funnel.get("proposals") or workforce.get("workload", {}).get("proposals") or 0)
    close_ready = int(funnel.get("close_ready") or workforce.get("workload", {}).get("close_ready") or 0)
    leads = int(funnel.get("research_leads") or workforce.get("workload", {}).get("pending_leads") or 0)
    eligible = int(readiness.get("eligible_external_prospects") or 0)
    clicks = int(acquisition.get("clicks") or 0)
    converted_leads = int(acquisition.get("leads") or 0)

    if close_ready <= 0:
        add(100, "closing", "Advance the strongest active deal toward a safe close-ready state using only non-binding preparation.",
            "No close-ready deal exists yet.", "close_ready > 0")
    if quotes <= 0:
        add(96, "revops", "Convert verified demand into quote-ready requirements and supplier comparison work.",
            "There are no registered quotes yet.", "quotes > 0")
    if opportunities <= 0 and demand_buyers > 0:
        add(94, "opportunity", "Turn verified buyers with public demand into evidence-backed opportunities.",
            f"{demand_buyers} buyer(s) have public demand but no evidence-backed opportunity is recorded.", "evidence_backed_opportunities > 0")
    if eligible <= 0 and verified_buyers > 0:
        add(92, "contact", "Repair prospect eligibility: verify company identity and corporate contact channels for the best buyers.",
            f"{verified_buyers} verified buyer(s) exist but there are no currently eligible external prospects.", "eligible_external_prospects > 0")
    if verified_channels < verified_buyers:
        add(88, "contact", "Enrich missing corporate contact channels for verified buyers using public evidence.",
            f"Verified channels ({verified_channels}) trail verified buyers ({verified_buyers}).", "verified_commercial_channels >= verified_buyers")
    if verified_emails < verified_buyers:
        add(84, "contact", "Prefer verified corporate email/form discovery for buyers lacking a usable channel.",
            f"Verified corporate emails ({verified_emails}) trail verified buyers ({verified_buyers}).", "verified_corporate_emails increases")
    if clicks > 0 and converted_leads <= 0:
        add(82, "acquisition", "Analyze landing/message friction and prepare stronger organic variants from observed clicks.",
            f"Campaigns have {clicks} click(s) and 0 converted leads.", "click_to_lead_rate > 0")
    if leads > 0:
        add(76, "research", "Re-rank existing research backlog by proximity to revenue; work highest-confidence buyer cases first.",
            f"{leads} research lead(s) remain available even if fresh search budget is exhausted.", "verified buyer/contact/opportunity counts increase")
    if int(distribution.get("awaiting_connector") or 0) > 0:
        add(60, "distribution", "Keep external-connector jobs prepared, but spend active capacity on owned channels and conversion work.",
            "Some distribution jobs require a connector authorization that cannot be granted autonomously.", "owned_live/clicks/leads increase")

    actions.sort(key=lambda row: (-int(row["priority"]), str(row["lane"])))
    return actions[:12]


def continuous_revenue_drive_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    """Persist a continuous, outcome-driven fallback plan into state."""
    actions = _score_actions(state)
    scout = _safe_dict(state.get("scout"))
    governor = _safe_dict(scout.get("search_budget_governor"))
    search_remaining = int(governor.get("effective_total_remaining") or scout.get("budget_remaining_total") or 0)
    budget_exhausted = bool(scout.get("budget_exhausted")) or search_remaining <= 0

    mode = "SEARCH_PLUS_CONVERSION" if not budget_exhausted else "CONVERSION_WITHOUT_IDLE"
    primary = actions[0] if actions else {
        "priority": 50,
        "lane": "learning",
        "action": "Audit recent outcomes and generate the next reversible commercial experiment.",
        "reason": "No stronger queued action was detected.",
        "success_metric": "measurable commercial progress",
        "binding": False,
    }

    previous = _safe_dict(state.get("continuous_revenue_drive"))
    previous_metric = previous.get("primary_success_metric")
    previous_lane = previous.get("primary_lane")

    snapshot = {
        "version": VERSION,
        "updated_at": _now(),
        "status": "active",
        "mode": mode,
        "objective": "maximize verified commercial progress toward realized profitable revenue",
        "never_idle": True,
        "search_budget_exhausted": budget_exhausted,
        "search_remaining": search_remaining,
        "primary_lane": primary.get("lane"),
        "primary_action": primary.get("action"),
        "primary_reason": primary.get("reason"),
        "primary_success_metric": primary.get("success_metric"),
        "priority_queue": actions,
        "reallocation_rule": "move capacity to the highest-value non-binding bottleneck whenever another lane is blocked",
        "learning_rule": "increase attention to tactics that improve verified conversion metrics; demote stale, duplicate or low-yield tactics",
        "fallback_when_search_exhausted": [
            "verify and enrich existing buyer/company identities",
            "resolve corporate contacts and channels",
            "convert demand evidence into opportunity and requirement records",
            "prepare supplier comparisons and quote-ready packages",
            "improve owned-channel acquisition creatives from observed behavior",
            "advance active deals with non-binding protective preparation",
            "review failed or stale cases and reopen with a different reversible tactic",
        ],
        "autonomy_guardrails": {
            "binding_contracts": "human_required",
            "payments_orders_financial_commitments": "human_required",
            "material_legal_liability": "human_required",
            "production_code_changes": "human_required",
            "new_external_connectors_accounts": "human_required",
            "paid_media_spend": "human_required",
        },
        "improvement_signal": {
            "primary_lane_changed": previous_lane is not None and previous_lane != primary.get("lane"),
            "metric_changed": previous_metric is not None and previous_metric != primary.get("success_metric"),
        },
        "persisted": True,
    }
    state["continuous_revenue_drive"] = snapshot

    # Nudge existing strategic state toward revenue execution without bypassing
    # any action-level gates.
    meta = _safe_dict(state.get("meta_autonomy"))
    if meta:
        meta["company_mode"] = "REVENUE_EXECUTION"
        meta["revenue_directive"] = "continuous_conversion_progress"
        meta["management_priority"] = "repair_current_revenue_bottleneck"
        meta["management_department"] = str(primary.get("lane") or "RevOps")
        state["meta_autonomy"] = meta

    return snapshot


def _install() -> None:
    """Patch the existing secretary tick to refresh CRD once per worker cycle.

    executive_secretary.secretary_tick is already called near the end of each
    worker cycle, after business state has been refreshed and before save_state.
    Wrapping it gives CRD a stable, additive hook without modifying core files.
    """
    try:
        import executive_secretary  # type: ignore
    except Exception as exc:  # pragma: no cover
        print({"continuous_revenue_drive_install": {"status": "error", "error": str(exc)}})
        return

    original = getattr(executive_secretary, "secretary_tick", None)
    if not callable(original) or getattr(original, "_continuous_revenue_drive_wrapped", False):
        return

    def wrapped(state: Dict[str, Any]):
        crd = continuous_revenue_drive_tick(state)
        print({"continuous_revenue_drive": crd})
        return original(state)

    wrapped._continuous_revenue_drive_wrapped = True  # type: ignore[attr-defined]
    wrapped._continuous_revenue_drive_original = original  # type: ignore[attr-defined]
    executive_secretary.secretary_tick = wrapped
    print({"continuous_revenue_drive_install": {"status": "active", "version": VERSION}})


_install()
