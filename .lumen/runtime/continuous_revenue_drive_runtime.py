"""LUMEN Continuous Revenue Drive."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from canonical_revenue_truth_runtime import canonical_revenue_truth_tick

VERSION = "1.4-first-cash-priority"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _safe_dict(v: Any) -> Dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _safe_list(v: Any) -> List[Any]:
    return v if isinstance(v, list) else []


def _i(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _realized_cash_usd(state: Dict[str, Any]) -> float:
    finance = _safe_dict(_safe_dict(state.get("business_kpis")).get("finance"))
    cfo = _safe_dict(_safe_dict(state.get("cfo_war_room")).get("financial_snapshot"))
    services = _safe_dict(state.get("service_revenue_runtime"))
    service_legacy = _safe_dict(state.get("service_growth_pipeline"))
    intelligence = _safe_dict(state.get("intelligence_revenue_engine"))
    continuous = _safe_dict(_safe_dict(state.get("continuous_revenue_drive")).get("intelligence_revenue"))
    values = [
        finance.get("realized_profit_usd"),
        finance.get("realized_company_profit_usd"),
        cfo.get("realized_profit_usd"),
        services.get("realized_service_revenue_usd"),
        service_legacy.get("realized_service_revenue_usd"),
        intelligence.get("realized_revenue_usd"),
        continuous.get("realized_intelligence_revenue_usd"),
    ]
    return max([_f(x) for x in values if x not in (None, "")] or [0.0])


def _first_cash_inventory(state: Dict[str, Any]) -> Dict[str, int]:
    services = _safe_dict(state.get("service_revenue_runtime"))
    service_legacy = _safe_dict(state.get("service_growth_pipeline"))
    intelligence = _safe_dict(state.get("intelligence_revenue_engine"))
    continuous = _safe_dict(_safe_dict(state.get("continuous_revenue_drive")).get("intelligence_revenue"))
    service_pipeline = max(
        _i(services.get("pipeline_total")),
        _i(service_legacy.get("pipeline_total")),
        len(_safe_list(state.get("service_revenue_opportunities"))),
        len(_safe_list(state.get("service_sales_pipeline"))),
    )
    intelligence_candidates = max(
        _i(intelligence.get("verified_candidates")),
        _i(continuous.get("verified_product_fit_candidates")),
    )
    return {
        "service_pipeline": service_pipeline,
        "intelligence_candidates": intelligence_candidates,
    }


def _score_actions(state: Dict[str, Any], truth: Dict[str, Any]) -> List[Dict[str, Any]]:
    funnel = _safe_dict(state.get("business_funnel"))
    readiness = _safe_dict(state.get("external_market_readiness"))
    acquisition = _safe_dict(state.get("acquisition_campaigns"))
    distribution = _safe_dict(state.get("distribution_operator"))
    c = truth.get("counts", {}) or {}
    actions: List[Dict[str, Any]] = []

    def add(p: int, lane: str, action: str, reason: str, metric: str) -> None:
        actions.append({
            "priority": p,
            "lane": lane,
            "action": action,
            "reason": reason,
            "success_metric": metric,
            "binding": False,
        })

    copps = _i(c.get("canonical_opportunities"))
    closing = _i(c.get("closing_eligible_deals"))
    ready = _i(c.get("canonical_close_ready"))
    demand = _i(c.get("buyers_with_verified_demand"))
    offers = _i(c.get("canonical_real_offers"))
    vb = _i(c.get("verified_buyers") or funnel.get("verified_buyers"))
    vc = _i(funnel.get("verified_commercial_channels"))
    ve = _i(funnel.get("verified_corporate_emails"))
    eligible = _i(readiness.get("eligible_external_prospects"))
    clicks = _i(acquisition.get("clicks"))
    leads = _i(acquisition.get("leads"))

    realized_cash = _realized_cash_usd(state)
    first_cash = _first_cash_inventory(state)
    service_pipeline = _i(first_cash.get("service_pipeline"))
    intelligence_candidates = _i(first_cash.get("intelligence_candidates"))

    # Until the first verified cash is recorded, use the already-prepared, verified service and
    # intelligence inventory as the operating priority. This is deliberately a non-binding lane:
    # price/terms/acceptance/payment authority is unchanged and remains behind the existing human gates.
    if realized_cash <= 0.0 and (service_pipeline > 0 or intelligence_candidates > 0):
        add(
            120,
            "first_cash_services",
            "Treat first verified cash as operating priority #1. Work the strongest already-verified service/intelligence candidates through contact -> reply -> diagnosis/proposal-ready, improve the message or rotate the segment when stale, and prepare the shortest truthful path to checkout/collection. Escalate any price, binding term, acceptance or payment action that requires human approval. Keep canonical demand discovery running in parallel.",
            f"Realized cash is USD 0 while {service_pipeline} service pipeline item(s) and {intelligence_candidates} verified intelligence candidate(s) are already available; converting existing inventory is the shortest zero-cost path to first cash.",
            "realized_profit_usd > 0",
        )

    if closing > 0 and ready <= 0:
        add(100, "closing", "Advance the strongest canonical deal toward a safe close-ready state using only non-binding preparation.", "At least one evidence-backed deal is genuinely on the closing path.", "canonical_close_ready > 0")
    if copps > 0 and offers <= 0:
        add(100, "quote_creation", "Turn canonical opportunities into comparable supplier RFQs and real quotes.", "Evidence-backed opportunities exist but no canonical-linked supplier offer is registered.", "canonical_real_offers > 0")
    if copps <= 0 and demand > 0:
        add(100, "opportunity_building", "Convert the strongest verified demand signals into canonical evidence-backed opportunities.", f"{demand} verified-demand buyer(s) exist but canonical opportunities remain at zero.", "canonical_opportunities > 0")
    if vb > 0 and demand <= 0:
        add(100, "demand_discovery", "Find exact public purchase/requirement evidence for verified buyers using stored evidence first and bounded public search next.", f"{vb} verified buyer(s) exist but none has verified public demand; no canonical opportunity can exist yet.", "buyers_with_verified_demand > 0")
    if eligible <= 0 and vb > 0:
        add(92, "verification_contact", "Repair prospect eligibility by verifying company identity and corporate contact channels.", "Verified buyers exist but there are no currently eligible external prospects.", "eligible_external_prospects > 0")
    if vc < vb:
        add(88, "verification_contact", "Enrich missing corporate contact channels for verified buyers using public evidence.", "Verified commercial channels trail verified buyers.", "verified_commercial_channels >= verified_buyers")
    if ve < vb:
        add(84, "verification_contact", "Prefer verified corporate email/form discovery for buyers lacking a usable channel.", "Verified corporate emails trail verified buyers.", "verified_corporate_emails increases")
    if clicks > 0 and leads <= 0:
        add(82, "acquisition", "Analyze landing/message friction and prepare stronger organic variants from observed clicks.", "Campaigns have clicks but no converted leads.", "click_to_lead_rate > 0")
    if _i(distribution.get("awaiting_connector")) > 0:
        add(60, "distribution", "Keep connector-dependent jobs prepared while active capacity stays on owned-channel conversion work.", "Some jobs require connector authorization.", "owned_live/clicks/leads increase")

    actions.sort(key=lambda x: (-_i(x.get("priority")), str(x.get("lane"))))
    canonical_lane = str(truth.get("recommended_lane") or "")
    first_cash_active = any(x.get("lane") == "first_cash_services" for x in actions)
    if first_cash_active:
        actions.sort(key=lambda x: (0 if x.get("lane") == "first_cash_services" else 1, -_i(x.get("priority")), str(x.get("lane"))))
    elif canonical_lane:
        actions.sort(key=lambda x: (0 if x.get("lane") == canonical_lane else 1, -_i(x.get("priority"))))
    return actions[:12]


def continuous_revenue_drive_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    truth = canonical_revenue_truth_tick(state)
    actions = _score_actions(state, truth)
    scout = _safe_dict(state.get("scout"))
    gov = _safe_dict(scout.get("search_budget_governor"))
    remaining = _i(gov.get("effective_total_remaining") or scout.get("budget_remaining_total"))
    exhausted = bool(scout.get("budget_exhausted")) or remaining <= 0
    mode = "SEARCH_PLUS_CONVERSION" if not exhausted else "CONVERSION_WITHOUT_IDLE"
    primary = actions[0] if actions else {
        "priority": 50,
        "lane": str(truth.get("recommended_lane") or "learning"),
        "action": "Execute the next canonical non-binding commercial step.",
        "reason": str(truth.get("reason") or "No stronger queued action was detected."),
        "success_metric": str(truth.get("target_metric") or "measurable commercial progress"),
        "binding": False,
    }
    previous = _safe_dict(state.get("continuous_revenue_drive"))
    snap = {
        "version": VERSION,
        "updated_at": _now(),
        "status": "active",
        "mode": mode,
        "objective": "first verified cash, then scalable realized profitable revenue",
        "never_idle": True,
        "search_budget_exhausted": exhausted,
        "search_remaining": remaining,
        "primary_lane": primary.get("lane"),
        "primary_action": primary.get("action"),
        "primary_reason": primary.get("reason"),
        "primary_success_metric": primary.get("success_metric"),
        "priority_queue": actions,
        "first_cash": {
            "active": primary.get("lane") == "first_cash_services",
            "realized_cash_usd": _realized_cash_usd(state),
            **_first_cash_inventory(state),
        },
        "canonical_truth_version": truth.get("version"),
        "canonical_truth_counts": truth.get("counts"),
        "reallocation_rule": "first verified cash outranks non-cash optimization while realized cash is zero; canonical revenue work continues in parallel and stage gates cannot be skipped",
        "learning_rule": "increase attention to tactics that improve verified conversion metrics; rotate stale message/segment tactics without widening authority",
        "autonomy_guardrails": {
            "binding_contracts": "human_required",
            "payments_orders_financial_commitments": "human_required",
            "material_legal_liability": "human_required",
            "production_code_changes": "human_required",
            "new_external_connectors_accounts": "human_required",
            "paid_media_spend": "human_required",
        },
        "improvement_signal": {
            "primary_lane_changed": previous.get("primary_lane") is not None and previous.get("primary_lane") != primary.get("lane"),
            "metric_changed": previous.get("primary_success_metric") is not None and previous.get("primary_success_metric") != primary.get("success_metric"),
        },
        "persisted": True,
    }
    state["continuous_revenue_drive"] = snap
    meta = _safe_dict(state.get("meta_autonomy"))
    if meta:
        meta["company_mode"] = "REVENUE_EXECUTION"
        if primary.get("lane") == "first_cash_services":
            meta["revenue_directive"] = "first_verified_cash"
            meta["management_priority"] = "first_cash"
        else:
            meta["revenue_directive"] = "canonical_revenue_progress"
            meta["management_priority"] = "repair_current_revenue_bottleneck"
        meta["management_department"] = str(primary.get("lane") or "RevOps")
        state["meta_autonomy"] = meta
    return snap


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
import money_engine_runtime  # noqa: E402,F401
