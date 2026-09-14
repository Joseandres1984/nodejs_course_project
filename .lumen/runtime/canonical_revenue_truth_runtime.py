from __future__ import annotations

"""Canonical Revenue Truth for LUMEN.

Defines one evidence-backed commercial truth consumed by Revenue Allocator, CRD,
Autonomy OS, First Cash and the causal funnel. Raw legacy rows remain preserved for
audit, but they cannot drive closing priority unless they satisfy the canonical gates.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List

import autonomy_operating_system

VERSION = "1.0-canonical-revenue-truth"
MIN_OPPORTUNITY_SCORE = 75.0
TRACEABLE_SOURCES = {"public_evidence", "manual_verified", "verified_inbound", "formal_quote"}
TERMINAL_DEAL_STAGES = {"closed", "lost", "cancelled", "canceled", "cerrado", "perdido", "cancelado"}
CLOSE_READY_STAGES = {"listo para cerrar", "close_ready", "autorizado para cierre"}
CLOSE_PATH_STAGES = {"oferta", "offer", "proposal", "propuesta", "negotiation", "negociacion", "negociación", "preclose", "pre_close", "close_ready", "listo para cerrar", "autorizado para cierre"}

_ORIGINAL_CANONICAL_CASES = autonomy_operating_system._canonical_cases


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _account_map(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(x.get("id")): x for x in state.get("candidate_accounts", []) or [] if isinstance(x, dict) and x.get("id")}


def _opportunity_assessment(state: Dict[str, Any], opp: Dict[str, Any], accounts: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    oid = str(opp.get("id") or "")
    buyer = accounts.get(str(opp.get("buyer_account_id") or ""), {})
    supplier = accounts.get(str(opp.get("supplier_account_id") or ""), {})
    reasons: List[str] = []

    source = _norm(opp.get("source"))
    status = _norm(opp.get("status"))
    evidence = [str(x) for x in (opp.get("evidence_refs") or []) if str(x or "").strip()]
    score = _f(opp.get("score") or opp.get("portfolio_priority_score"))

    if not oid:
        reasons.append("missing_opportunity_id")
    if source in {"demo", "demo/simulación", "simulation", "simulated"}:
        reasons.append("non_real_source")
    elif source and source not in TRACEABLE_SOURCES and not opp.get("source_traceable"):
        reasons.append("source_not_canonical")
    if status in {"parked_collection_focus", "cancelled", "canceled", "rejected", "invalid"}:
        reasons.append("opportunity_not_active")
    if not buyer or buyer.get("type") != "buyer" or not buyer.get("verified_company"):
        reasons.append("buyer_not_verified")
    if not buyer.get("demand_signal"):
        reasons.append("buyer_demand_not_verified")
    if not supplier or supplier.get("type") != "supplier" or not supplier.get("verified_company"):
        reasons.append("supplier_not_verified")
    if score < MIN_OPPORTUNITY_SCORE:
        reasons.append("opportunity_score_below_threshold")
    if len(evidence) < 2:
        reasons.append("insufficient_traceable_evidence")

    canonical = not reasons
    return {
        "id": oid,
        "canonical": canonical,
        "reasons": reasons,
        "score": round(score, 1),
        "buyer_account_id": opp.get("buyer_account_id"),
        "supplier_account_id": opp.get("supplier_account_id"),
        "requirement_confirmed": bool(opp.get("requirement_confirmed")),
        "buyer_channel_verified": bool(opp.get("buyer_channel_verified") or buyer.get("commercial_channel_verified")),
        "supplier_channel_verified": bool(opp.get("supplier_channel_verified") or supplier.get("commercial_channel_verified")),
        "evidence_count": len(evidence),
        "source": opp.get("source"),
        "status": opp.get("status"),
    }


def _linked_real_offer(state: Dict[str, Any], deal: Dict[str, Any], opportunity_id: str) -> bool:
    deal_id = str(deal.get("id") or "")
    for row in state.get("offers", []) or []:
        if not isinstance(row, dict):
            continue
        if _norm(row.get("source")) in {"demo", "demo/simulación", "simulation", "simulated"}:
            continue
        if (deal_id and str(row.get("deal_id") or "") == deal_id) or (opportunity_id and str(row.get("opportunity_id") or "") == opportunity_id):
            return True
    return False


def _linked_proposal(state: Dict[str, Any], deal: Dict[str, Any], opportunity_id: str) -> bool:
    deal_id = str(deal.get("id") or "")
    for row in state.get("proposals", []) or []:
        if not isinstance(row, dict):
            continue
        if (deal_id and str(row.get("deal_id") or "") == deal_id) or (opportunity_id and str(row.get("opportunity_id") or "") == opportunity_id):
            return True
    return False


def _deal_assessment(state: Dict[str, Any], deal: Dict[str, Any], canonical_opportunities: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    did = str(deal.get("id") or "")
    oid = str(deal.get("opportunity_id") or "")
    opp = canonical_opportunities.get(oid)
    reasons: List[str] = []
    stage = _norm(deal.get("stage"))
    source = _norm(deal.get("source"))

    if not did:
        reasons.append("missing_deal_id")
    if not oid:
        reasons.append("missing_opportunity_link")
    elif opp is None:
        reasons.append("linked_opportunity_not_canonical")
    if source in {"demo", "demo/simulación", "simulation", "simulated"}:
        reasons.append("non_real_source")
    elif source and source not in TRACEABLE_SOURCES and not deal.get("source_traceable"):
        reasons.append("deal_source_not_canonical")

    if opp:
        opp_buyer = str(opp.get("buyer_account_id") or "")
        opp_supplier = str(opp.get("supplier_account_id") or "")
        deal_buyer = str(deal.get("buyer_account_id") or "")
        deal_supplier = str(deal.get("supplier_account_id") or "")
        if deal_buyer and opp_buyer and deal_buyer != opp_buyer:
            reasons.append("buyer_lineage_mismatch")
        if deal_supplier and opp_supplier and deal_supplier != opp_supplier:
            reasons.append("supplier_lineage_mismatch")

    canonical = not reasons
    terminal = stage in TERMINAL_DEAL_STAGES
    active = canonical and not terminal
    requirement_confirmed = bool(opp and opp.get("requirement_confirmed"))
    has_real_offer = _linked_real_offer(state, deal, oid) if canonical else False
    has_proposal = _linked_proposal(state, deal, oid) if canonical else False
    close_path_eligible = bool(
        active
        and requirement_confirmed
        and has_real_offer
        and (has_proposal or stage in CLOSE_PATH_STAGES)
    )
    close_ready = bool(canonical and stage in CLOSE_READY_STAGES)

    return {
        "id": did,
        "opportunity_id": oid or None,
        "canonical": canonical,
        "active": active,
        "terminal": terminal,
        "close_path_eligible": close_path_eligible,
        "close_ready": close_ready,
        "requirement_confirmed": requirement_confirmed,
        "has_real_offer": has_real_offer,
        "has_proposal": has_proposal,
        "stage": deal.get("stage"),
        "reasons": reasons,
    }


def canonical_revenue_truth_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    accounts = _account_map(state)
    opp_assessments = [
        _opportunity_assessment(state, x, accounts)
        for x in state.get("market_opportunities", []) or []
        if isinstance(x, dict)
    ]
    canonical_opp_map = {x["id"]: x for x in opp_assessments if x.get("canonical") and x.get("id")}

    deal_assessments = [
        _deal_assessment(state, x, canonical_opp_map)
        for x in state.get("deals", []) or []
        if isinstance(x, dict)
    ]

    canonical_opps = [x for x in opp_assessments if x.get("canonical")]
    quarantined_opps = [x for x in opp_assessments if not x.get("canonical")]
    canonical_deals = [x for x in deal_assessments if x.get("canonical")]
    quarantined_deals = [x for x in deal_assessments if not x.get("canonical")]
    active_deals = [x for x in canonical_deals if x.get("active")]
    close_path = [x for x in canonical_deals if x.get("close_path_eligible")]
    close_ready = [x for x in canonical_deals if x.get("close_ready")]

    buyers = [x for x in accounts.values() if x.get("type") == "buyer" and x.get("verified_company")]
    demand_buyers = [x for x in buyers if x.get("demand_signal")]
    real_offers = [x for x in state.get("offers", []) or [] if isinstance(x, dict) and _norm(x.get("source")) not in {"demo", "demo/simulación", "simulation", "simulated"}]
    proposals = [x for x in state.get("proposals", []) or [] if isinstance(x, dict)]
    readiness = state.get("external_market_readiness", {}) or {}
    reasons = readiness.get("ineligibility_reasons", {}) or {}

    if close_path and not close_ready:
        lane = "closing"
        target = "canonical_close_ready"
        reason = "Existe al menos un deal canónico con requerimiento confirmado y oferta real; corresponde empujarlo hacia cierre seguro."
    elif canonical_opps and not real_offers:
        lane = "quote_creation"
        target = "real_offers"
        reason = "Existen oportunidades canónicas pero todavía no hay ofertas reales; priorizar RFQ y cotización comparable."
    elif demand_buyers and not canonical_opps:
        lane = "opportunity_building"
        target = "canonical_opportunities"
        reason = "Existe demanda verificada pero ninguna oportunidad supera todavía los gates canónicos de evidencia."
    elif int(readiness.get("eligible_external_prospects") or 0) <= 0 and (int(reasons.get("company_not_verified") or 0) + int(reasons.get("contact_not_verified") or 0)) > 0:
        lane = "verification_contact"
        target = "eligible_external_prospects"
        reason = "La salida comercial está bloqueada por verificación de identidad/contacto."
    else:
        lane = "demand_discovery"
        target = "buyers_with_verified_demand"
        reason = "No existe todavía una ruta canónica suficientemente madura; ampliar demanda verificada sin degradar calidad."

    snapshot = {
        "version": VERSION,
        "status": "active",
        "updated_at": utcnow(),
        "truth_rule": "raw_activity_never_drives_closing; only traceable evidence-backed opportunity lineage may create canonical deals",
        "recommended_lane": lane,
        "target_metric": target,
        "reason": reason,
        "counts": {
            "raw_market_opportunities": len(opp_assessments),
            "canonical_opportunities": len(canonical_opps),
            "quarantined_opportunities": len(quarantined_opps),
            "raw_deals": len(deal_assessments),
            "canonical_deals": len(canonical_deals),
            "canonical_active_deals": len(active_deals),
            "closing_eligible_deals": len(close_path),
            "canonical_close_ready": len(close_ready),
            "buyers_with_verified_demand": len(demand_buyers),
            "real_offers": len(real_offers),
            "proposals": len(proposals),
        },
        "canonical_opportunity_ids": [x["id"] for x in canonical_opps],
        "canonical_deal_ids": [x["id"] for x in canonical_deals],
        "closing_eligible_deal_ids": [x["id"] for x in close_path],
        "quarantined_opportunities": quarantined_opps[:20],
        "quarantined_deals": quarantined_deals[:20],
        "governance": {
            "legacy_rows_preserved_for_audit": True,
            "legacy_rows_can_drive_closing": False,
            "binding_actions_remain_human_gated": True,
            "evidence_threshold_lowered": False,
        },
    }
    state["canonical_revenue_truth"] = snapshot
    return snapshot


def _canonical_cases_with_truth(state: Dict[str, Any]):
    truth = canonical_revenue_truth_tick(state)
    allowed_opps = set(str(x) for x in truth.get("canonical_opportunity_ids", []) or [])
    allowed_deals = set(str(x) for x in truth.get("canonical_deal_ids", []) or [])
    rows = list(_ORIGINAL_CANONICAL_CASES(state) or [])
    filtered = []
    for case in rows:
        source_type = str(case.get("source_type") or "")
        source_id = str(case.get("source_id") or "")
        if source_type == "opportunity" and source_id not in allowed_opps:
            continue
        if source_type == "deal" and source_id not in allowed_deals:
            continue
        filtered.append(case)
    return filtered


autonomy_operating_system._canonical_cases = _canonical_cases_with_truth
print({"canonical_revenue_truth_runtime": {"version": VERSION, "status": "active", "autonomy_filter": True}}, flush=True)
