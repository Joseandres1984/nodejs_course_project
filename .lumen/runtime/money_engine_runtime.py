"""LUMEN Money Engine.

Truth-first monetization director for existing LUMEN assets. It coordinates four
revenue lanes without increasing search spend, outbound caps, paid media or binding
authority: First Cash B2B, paid services, Intelligence and referral/success-fee.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

VERSION = "1.0-money-engine"
MAX_EXISTING_NEW_OUTBOUND_PER_DAY = 3
FIRST_CASH_IDS = ("MKT-00043", "MKT-00044", "MKT-00045")
SERVICE_ORDER: Tuple[Tuple[str, str, int], ...] = (
    ("SRV-QUOTECHECK", "QuoteCheck", 59),
    ("SRV-SUPPLIERCHECK", "SupplierCheck", 79),
    ("SRV-TENDER-HUNTER", "Tender Hunter", 99),
    ("SRV-SOURCING-EXPRESS", "Sourcing Express", 149),
    ("SRV-B2B-PROSPECTING", "B2B Prospecting", 199),
    ("SRV-EXPORT-SCOUT", "Export Scout", 249),
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _d(v: Any) -> Dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _l(state: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    v = state.get(key)
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


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


def _service_id(row: Dict[str, Any]) -> str:
    for key in ("service_id", "product_id", "service_code", "product_code", "recommended_service_id"):
        value = str(row.get(key) or "").strip().upper()
        if value:
            return value
    offer = _d(row.get("recommended_offer"))
    return str(offer.get("service_id") or offer.get("product_id") or "").strip().upper()


def _realized(state: Dict[str, Any]) -> float:
    service = _d(state.get("service_revenue_runtime"))
    intel = _d(state.get("intelligence_revenue_engine"))
    finance = _d(_d(state.get("business_kpis")).get("finance"))
    values = [
        _f(service.get("realized_service_revenue_usd")),
        _f(intel.get("realized_revenue_usd")),
        _f(finance.get("realized_profit_usd") or finance.get("realized_company_profit_usd")),
    ]
    return max(0.0, sum(values))


def _first_cash_truth(state: Dict[str, Any]) -> Dict[str, Any]:
    sprint = _d(state.get("revenue_sprint_v2"))
    completion = _d(sprint.get("requirement_completion"))
    focus = list(sprint.get("first_cash_focus_opportunity_ids") or FIRST_CASH_IDS)[:3]
    teams = _l(state, "mission_teams")
    cases = _l(state, "professional_cases")
    team_by_opp = {str(x.get("opportunity_id") or ""): x for x in teams}
    case_by_opp: Dict[str, Dict[str, Any]] = {}
    for case in cases:
        oid = str(case.get("first_cash_opportunity_id") or case.get("opportunity_id") or "")
        if not oid:
            cid = str(case.get("case_id") or case.get("id") or "")
            if cid.startswith("CASE-FIRSTCASH-"):
                oid = cid.replace("CASE-FIRSTCASH-", "", 1)
        if oid:
            case_by_opp[oid] = case
    items = []
    for oid in focus:
        oid = str(oid)
        team = team_by_opp.get(oid, {})
        case = case_by_opp.get(oid, {})
        items.append({
            "opportunity_id": oid,
            "stage": str(case.get("stage") or team.get("stage") or "unknown"),
            "status": str(case.get("status") or "unknown"),
            "progress_pct": _i(case.get("progress_pct")),
            "stagnant_cycles": _i(team.get("stagnant_cycles")),
            "next_action": str(case.get("next_action") or team.get("current_task") or "Complete exact buyer requirement with observed evidence."),
        })
    return {
        "focus_ids": focus,
        "items": items,
        "requirement_ready": _i(completion.get("ready_after") or completion.get("rfq_ready_from_exact_official_evidence")),
        "exact_fields_added": _i(completion.get("exact_fields_added")),
        "max_stagnant_cycles": max([_i(x.get("stagnant_cycles")) for x in items] or [0]),
    }


def _service_truth(state: Dict[str, Any]) -> Dict[str, Any]:
    runtime = _d(state.get("service_growth_pipeline")) or _d(state.get("service_revenue_runtime"))
    pipeline = _l(state, "service_sales_pipeline")
    opps = _l(state, "service_revenue_opportunities")
    return {
        "pipeline": _i(runtime.get("pipeline_total"), len(pipeline)),
        "prepared": _i(runtime.get("outreach_prepared"), sum(1 for x in opps if str(x.get("status") or "") == "prepared_not_sent")),
        "contacted": _i(runtime.get("real_contacted")),
        "inquiries": _i(runtime.get("inbound_service_leads") or _d(runtime.get("service_inquiries")).get("total")),
        "proposals": _i(runtime.get("proposal_drafts") or runtime.get("proposal_sent_verified")),
        "won": _i(runtime.get("won")),
        "realized_usd": _f(runtime.get("realized_service_revenue_usd")),
    }


def _intelligence_truth(state: Dict[str, Any]) -> Dict[str, Any]:
    runtime = _d(state.get("intelligence_revenue_engine"))
    return {
        "verified_candidates": _i(runtime.get("verified_candidates")),
        "outbound_attention": str(runtime.get("outbound_attention") or "0/0"),
        "contacted": _i(runtime.get("real_contacted")),
        "replies": _i(runtime.get("replies")),
        "inquiries": _i(runtime.get("public_inquiries")),
        "realized_usd": _f(runtime.get("realized_revenue_usd")),
    }


def _referral_truth(state: Dict[str, Any]) -> Dict[str, Any]:
    partner = _d(state.get("partner_network"))
    retail = _d(_d(_d(state.get("scout")).get("retail_velocity")).get("consumer_goods_unit"))
    metrics = _d(retail.get("metrics"))
    top = retail.get("top_priorities") if isinstance(retail.get("top_priorities"), list) else []
    candidates = []
    for row in top:
        if not isinstance(row, dict):
            continue
        if str(row.get("stage") or "") == "partner_agreement_required":
            candidates.append({
                "product_key": row.get("product_key"),
                "product": row.get("product"),
                "partner_stores": _i(row.get("partner_stores")),
                "supplier_leads": _i(row.get("supplier_leads")),
                "commercial_score": _f(row.get("commercial_score")),
                "next_action": "Prepare a non-binding success-fee/referral proposal; activation requires human approval.",
            })
    candidates.sort(key=lambda x: (-x["commercial_score"], -x["partner_stores"]))
    return {
        "stores_total": _i(partner.get("stores_total"), _i(metrics.get("partner_stores"))),
        "agreement_required": _i(partner.get("agreement_required")),
        "active_partners": _i(partner.get("active_partners")),
        "active_referral_offers": _i(partner.get("referral_offers_active"), _i(metrics.get("active_referral_offers"))),
        "candidates": candidates[:5],
    }


def _outbound_remaining(state: Dict[str, Any]) -> int:
    outbound = _d(state.get("outbound_engine"))
    if outbound.get("daily_remaining") not in (None, ""):
        return max(0, _i(outbound.get("daily_remaining")))
    startup = _d(state.get("startup_outbound_engine"))
    return max(0, _i(startup.get("daily_remaining")))


def _lane_plan(first: Dict[str, Any], service: Dict[str, Any], intel: Dict[str, Any], referral: Dict[str, Any], realized: float) -> Dict[str, int]:
    if realized > 0:
        # Keep a diversified portfolio after first validation; proven lanes can be
        # promoted by downstream measured learning without making up attribution.
        return {"first_cash": 35, "paid_services": 35, "intelligence": 20, "referral": 10}
    if first.get("max_stagnant_cycles", 0) >= 6 and first.get("requirement_ready", 0) <= 0:
        return {"first_cash": 40, "paid_services": 30, "intelligence": 20, "referral": 10}
    return {"first_cash": 55, "paid_services": 25, "intelligence": 15, "referral": 5}


def _money_tasks(first: Dict[str, Any], service: Dict[str, Any], intel: Dict[str, Any], referral: Dict[str, Any]) -> List[Dict[str, Any]]:
    tasks: List[Dict[str, Any]] = []
    primary = first.get("items", [{}])[0] if first.get("items") else {}
    tasks.append({
        "id": "MONEY-FIRSTCASH-001", "priority": 100, "lane": "first_cash", "owner_role": "revops+research_analyst",
        "object_id": primary.get("opportunity_id") or "MKT-00043",
        "action": primary.get("next_action") or "Complete exact buyer requirement with observed evidence.",
        "success_metric": "requirements_ready_for_rfq > 0", "binding": False,
    })
    tasks.append({
        "id": "MONEY-SERVICE-001", "priority": 96, "lane": "paid_services", "owner_role": "revops+negotiator",
        "object_id": "SRV-QUOTECHECK",
        "action": "Prioritize a verified-fit QuoteCheck prospect and move prepared outreach to provider-accepted contact when the existing outbound window allows it.",
        "success_metric": "service_real_contacted > 0", "binding": False,
    })
    tasks.append({
        "id": "MONEY-SERVICE-002", "priority": 94, "lane": "paid_services", "owner_role": "revops+negotiator",
        "object_id": "SRV-SUPPLIERCHECK",
        "action": "Prioritize a verified-fit SupplierCheck prospect with transparent launch price and one concrete CTA.",
        "success_metric": "service_reply_or_inquiry > 0", "binding": False,
    })
    tasks.append({
        "id": "MONEY-INTEL-001", "priority": 90, "lane": "intelligence", "owner_role": "market_manager+revops",
        "object_id": "SRV-TENDER-HUNTER",
        "action": "Use existing verified candidates and procurement intelligence to sell a bounded Tender Hunter/Opportunity intelligence deliverable without new paid search.",
        "success_metric": "intelligence_real_contacted > 0", "binding": False,
    })
    if referral.get("candidates"):
        c = referral["candidates"][0]
        tasks.append({
            "id": "MONEY-REFERRAL-001", "priority": 82, "lane": "referral", "owner_role": "market_manager+negotiator",
            "object_id": c.get("product_key") or "referral_candidate",
            "action": c.get("next_action"),
            "success_metric": "nonbinding_partner_proposal_prepared > 0", "binding": False,
            "human_gate": "partner agreement activation",
        })
    tasks.append({
        "id": "MONEY-ACQUISITION-001", "priority": 78, "lane": "paid_services", "owner_role": "market_manager",
        "object_id": "MINI-QUOTECHECK",
        "action": "Promote a low-friction Mini QuoteCheck entry offer on already-owned/pre-authorized surfaces; no paid media and no fabricated results.",
        "success_metric": "service_inquiries > 0", "binding": False,
    })
    return tasks


def _tag_existing_rows(state: Dict[str, Any], first: Dict[str, Any]) -> Dict[str, int]:
    tagged_first = 0
    focus_rank = {str(oid): 100 - idx * 3 for idx, oid in enumerate(first.get("focus_ids") or FIRST_CASH_IDS)}
    for key in ("market_opportunities", "mission_teams", "professional_cases"):
        for row in _l(state, key):
            oid = str(row.get("opportunity_id") or row.get("first_cash_opportunity_id") or row.get("id") or "")
            if oid.startswith("CASE-FIRSTCASH-"):
                oid = oid.replace("CASE-FIRSTCASH-", "", 1)
            if oid in focus_rank:
                row["money_lane"] = "first_cash"
                row["money_priority"] = focus_rank[oid]
                tagged_first += 1
    service_priority = {sid: 96 - idx * 2 for idx, (sid, _, _) in enumerate(SERVICE_ORDER)}
    tagged_services = 0
    for key in ("service_sales_pipeline", "service_revenue_opportunities", "intelligence_candidates", "intelligence_service_candidates", "intelligence_revenue_candidates"):
        for row in _l(state, key):
            sid = _service_id(row)
            if sid in service_priority:
                row["money_lane"] = "paid_services" if sid in {"SRV-QUOTECHECK", "SRV-SUPPLIERCHECK", "SRV-SOURCING-EXPRESS", "SRV-B2B-PROSPECTING"} else "intelligence"
                row["money_priority"] = service_priority[sid]
                tagged_services += 1
    return {"first_cash_rows": tagged_first, "service_or_intelligence_rows": tagged_services}


def money_engine_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    first = _first_cash_truth(state)
    service = _service_truth(state)
    intel = _intelligence_truth(state)
    referral = _referral_truth(state)
    realized = _realized(state)
    remaining = _outbound_remaining(state)
    attention = _lane_plan(first, service, intel, referral, realized)
    tasks = _money_tasks(first, service, intel, referral)
    tagged = _tag_existing_rows(state, first)

    slot_plan = [
        {"slot": 1, "lane": "first_cash", "purpose": "buyer requirement clarification / next verified First Cash step", "send_authority": "existing_cap_only"},
        {"slot": 2, "lane": "paid_services", "purpose": "QuoteCheck or SupplierCheck verified-fit outreach", "send_authority": "existing_cap_only"},
        {"slot": 3, "lane": "best_remaining", "purpose": "Intelligence, service, referral proposal or First Cash according to verified money proximity", "send_authority": "existing_cap_only"},
    ]
    if remaining <= 0:
        launch_status = "prepared_for_next_available_outbound_window"
    else:
        launch_status = "eligible_for_existing_outbound_window"

    snap = {
        "version": VERSION,
        "updated_at": _now(),
        "status": "ACTIVE",
        "objective": "maximize verified progress toward first realized revenue",
        "launch_status": launch_status,
        "realized_revenue_truth_usd": round(realized, 2),
        "lanes": {
            "first_cash": first,
            "paid_services": service,
            "intelligence": intel,
            "referral": referral,
        },
        "attention_pct": attention,
        "existing_outbound": {
            "daily_remaining": remaining,
            "existing_daily_cap_reference": MAX_EXISTING_NEW_OUTBOUND_PER_DAY,
            "slot_plan": slot_plan,
            "cap_increased": False,
        },
        "tasks": tasks,
        "tagged_existing_rows": tagged,
        "anti_stagnation": {
            "active": first.get("max_stagnant_cycles", 0) >= 6 and first.get("requirement_ready", 0) <= 0,
            "rule": "keep First Cash alive while reallocating reversible attention to other monetizable lanes when verified stage movement stalls",
        },
        "truth_rules": [
            "prepared_is_not_contacted",
            "provider_accepted_is_not_delivered",
            "delivered_is_not_replied",
            "email_is_not_offer",
            "partner_candidate_is_not_active_partner",
            "revenue_requires_realized_evidence",
        ],
        "human_gates": [
            "binding contracts or acceptance of binding terms",
            "payments/orders/financial commitments",
            "binding partner/referral agreement activation",
            "paid media spend",
            "new external connector/account authorization",
            "per-post Instagram approval where existing policy requires it",
        ],
        "search_spend_increased": False,
        "outbound_caps_increased": False,
        "paid_media_enabled": False,
        "binding_authority_changed": False,
        "persisted": True,
    }
    state["money_engine"] = snap
    state["money_engine_tasks"] = tasks

    crd = _d(state.get("continuous_revenue_drive"))
    if crd:
        crd["money_engine_version"] = VERSION
        crd["money_engine_attention_pct"] = attention
        crd["money_engine_launch_status"] = launch_status
        state["continuous_revenue_drive"] = crd
    meta = _d(state.get("meta_autonomy"))
    if meta:
        meta["company_mode"] = "REVENUE_EXECUTION"
        meta["revenue_directive"] = "monetize_existing_assets_across_four_lanes"
        meta["management_priority"] = "move_verified_stage_toward_cash"
        meta["management_department"] = "Money Engine / RevOps"
        state["meta_autonomy"] = meta
    return snap


def _install() -> None:
    try:
        import executive_secretary
    except Exception as exc:
        print({"money_engine_install": {"status": "error", "error": str(exc)}})
        return
    original = getattr(executive_secretary, "secretary_tick", None)
    if not callable(original) or getattr(original, "_money_engine_wrapped", False):
        return

    def wrapped(state: Dict[str, Any]):
        money = money_engine_tick(state)
        print({"money_engine": {
            "version": VERSION,
            "status": money.get("status"),
            "launch_status": money.get("launch_status"),
            "attention_pct": money.get("attention_pct"),
            "tasks": len(money.get("tasks") or []),
            "daily_remaining": _d(money.get("existing_outbound")).get("daily_remaining"),
            "realized_revenue_truth_usd": money.get("realized_revenue_truth_usd"),
            "search_spend_increased": False,
            "outbound_caps_increased": False,
            "binding_authority_changed": False,
        }}, flush=True)
        return original(state)

    wrapped._money_engine_wrapped = True
    wrapped._money_engine_original = original
    executive_secretary.secretary_tick = wrapped
    print({"money_engine_install": {
        "version": VERSION,
        "status": "active",
        "lanes": ["first_cash", "paid_services", "intelligence", "referral"],
        "search_spend_increased": False,
        "outbound_caps_increased": False,
        "binding_authority_changed": False,
    }}, flush=True)


_install()
