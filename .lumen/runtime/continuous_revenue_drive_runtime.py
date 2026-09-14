"""LUMEN Continuous Revenue Drive."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from canonical_revenue_truth_runtime import canonical_revenue_truth_tick

VERSION = "1.1-continuous-revenue-drive-canonical"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _score_actions(state: Dict[str, Any], truth: Dict[str, Any]) -> List[Dict[str, Any]]:
    funnel = _safe_dict(state.get("business_funnel"))
    readiness = _safe_dict(state.get("external_market_readiness"))
    acquisition = _safe_dict(state.get("acquisition_campaigns"))
    distribution = _safe_dict(state.get("distribution_operator"))
    counts = truth.get("counts", {}) or {}
    actions: List[Dict[str, Any]] = []

    def add(priority: int, lane: str, action: str, reason: str, metric: str) -> None:
        actions.append({"priority": priority, "lane": lane, "action": action, "reason": reason, "success_metric": metric, "binding": False})

    canonical_opps = int(counts.get("canonical_opportunities") or 0)
    closing_eligible = int(counts.get("closing_eligible_deals") or 0)
    close_ready = int(counts.get("canonical_close_ready") or 0)
    demand_buyers = int(counts.get("buyers_with_verified_demand") or 0)
    real_offers = int(counts.get("real_offers") or 0)
    verified_buyers = int(funnel.get("verified_buyers") or 0)
    verified_channels = int(funnel.get("verified_commercial_channels") or 0)
    verified_emails = int(funnel.get("verified_corporate_emails") or 0)
    eligible = int(readiness.get("eligible_external_prospects") or 0)
    clicks = int(acquisition.get("clicks") or 0)
    converted_leads = int(acquisition.get("leads") or 0)

    if closing_eligible > 0 and close_ready <= 0:
        add(100, "closing", "Advance the strongest canonical deal toward a safe close-ready state using only non-binding preparation.", "At least one evidence-backed deal is genuinely on the closing path.", "canonical_close_ready > 0")
    if canonical_opps > 0 and real_offers <= 0:
        add(98, "quote_creation", "Turn canonical opportunities into comparable supplier RFQs and real quotes.", "Evidence-backed opportunities exist but no real supplier offer is registered.", "real_offers > 0")
    if canonical_opps <= 0 and demand_buyers > 0:
        add(100, "opportunity_building", "Convert the strongest verified demand signals into canonical evidence-backed opportunities.", f"{demand_buyers} verified-demand buyer(s) exist but canonical opportunities remain at zero.", "canonical_opportunities > 0")
    if eligible <= 0 and verified_buyers > 0:
        add(92, "verification_contact", "Repair prospect eligibility by verifying company identity and corporate contact channels.", "Verified buyers exist but there are no currently eligible external prospects.", "eligible_external_prospects > 0")
    if verified_channels < verified_buyers:
        add(88, "verification_contact", "Enrich missing corporate contact channels for verified buyers using public evidence.", "Verified commercial channels trail verified buyers.", "verified_commercial_channels >= verified_buyers")
    if verified_emails < verified_buyers:
        add(84, "verification_contact", "Prefer verified corporate email/form discovery for buyers lacking a usable channel.", "Verified corporate emails trail verified buyers.", "verified_corporate_emails increases")
    if clicks > 0 and converted_leads <= 0:
        add(82, "acquisition", "Analyze landing/message friction and prepare stronger organic variants from observed clicks.", "Campaigns have clicks but no converted leads.", "click_to_lead_rate > 0")
    if int(distribution.get("awaiting_connector") or 0) > 0:
        add(60, "distribution", "Keep connector-dependent jobs prepared while active capacity stays on owned-channel conversion work.", "Some jobs require connector authorization.", "owned_live/clicks/leads increase")

    actions.sort(key=lambda row: (-int(row["priority"]), str(row["lane"])))
    return actions[:12]


def continuous_revenue_drive_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    truth = canonical_revenue_truth_tick(state)
    actions = _score_actions(state, truth)
    scout = _safe_dict(state.get("scout"))
    governor = _safe_dict(scout.get("search_budget_governor"))
    search_remaining = int(governor.get("effective_total_remaining") or scout.get("budget_remaining_total") or 0)
    budget_exhausted = bool(scout.get("budget_exhausted")) or search_remaining <= 0
    mode = "SEARCH_PLUS_CONVERSION" if not budget_exhausted else "CONVERSION_WITHOUT_IDLE"
    primary = actions[0] if actions else {
        "priority": 50, "lane": str(truth.get("recommended_lane") or "learning"),
        "action": "Audit recent outcomes and execute the next canonical non-binding commercial step.",
        "reason": str(truth.get("reason") or "No stronger queued action was detected."),
        "success_metric": str(truth.get("target_metric") or "measurable commercial progress"), "binding": False,
    }
    previous = _safe_dict(state.get("continuous_revenue_drive"))
    snapshot = {
        "version": VERSION, "updated_at": _now(), "status": "active", "mode": mode,
        "objective": "maximize verified commercial progress toward realized profitable revenue",
        "never_idle": True, "search_budget_exhausted": budget_exhausted, "search_remaining": search_remaining,
        "primary_lane": primary.get("lane"), "primary_action": primary.get("action"),
        "primary_reason": primary.get("reason"), "primary_success_metric": primary.get("success_metric"),
        "priority_queue": actions, "canonical_truth_version": truth.get("version"),
        "canonical_truth_counts": truth.get("counts"),
        "reallocation_rule": "follow the canonical revenue stage; never jump to closing from raw legacy deal activity",
        "learning_rule": "increase attention to tactics that improve verified conversion metrics; demote stale duplicate or low-yield tactics",
        "autonomy_guardrails": {
            "binding_contracts": "human_required", "payments_orders_financial_commitments": "human_required",
            "material_legal_liability": "human_required", "production_code_changes": "human_required",
            "new_external_connectors_accounts": "human_required", "paid_media_spend": "human_required",
        },
        "improvement_signal": {
            "primary_lane_changed": previous.get("primary_lane") is not None and previous.get("primary_lane") != primary.get("lane"),
            "metric_changed": previous.get("primary_success_metric") is not None and previous.get("primary_success_metric") != primary.get("success_metric"),
        },
        "persisted": True,
    }
    state["continuous_revenue_drive"] = snapshot
    meta = _safe_dict(state.get("meta_autonomy"))
    if meta:
        meta["company_mode"] = "REVENUE_EXECUTION"
        meta["revenue_directive"] = "canonical_revenue_progress"
        meta["management_priority"] = "repair_current_revenue_bottleneck"
        meta["management_department"] = str(primary.get("lane") or "RevOps")
        state["meta_autonomy"] = meta
    return snapshot


def _install() -> None:
    try:
        import executive_secretary
    except Exception as exc:
        print({"continuous_revenue_drive_install": {"status": "error", "error": str(exc)}})
        return
    original = getattr(executive_secretary, "secretary_tick", None)
    if not callable(original) or getattr(original, "_continuous_revenue_drive_wrapped", False):
        return
    def wrapped(state: Dict[str, Any]):
        crd = continuous_revenue_drive_tick(state)
        print({"continuous_revenue_drive": crd})
        return original(state)
    wrapped._continuous_revenue_drive_wrapped = True
    wrapped._continuous_revenue_drive_original = original
    executive_secretary.secretary_tick = wrapped
    print({"continuous_revenue_drive_install": {"status": "active", "version": VERSION}})

_install()
