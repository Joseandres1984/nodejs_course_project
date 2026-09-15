from __future__ import annotations

"""LUMEN conversion sprint guardrails.

This runtime is intentionally narrow: it tightens commercial truth, concentrates
attention on requirement/RFQ/quote conversion, prevents repeated failed experiments
from restarting unchanged, and bounds no-effect learning observations. It never
widens binding authority.
"""
from typing import Any, Dict

import autonomy_operating_system
import commercial_learning_v2_runtime
import continuous_learning_runtime
import continuous_revenue_drive_runtime
import revenue_allocator_runtime

VERSION = "1.1-conversion-sprint"
LEARNING_NO_EFFECT_SAMPLE_CAP = 24


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _linked(row: Dict[str, Any], deal_id: str, opportunity_id: str) -> bool:
    return bool(
        (deal_id and str(row.get("deal_id") or "") == deal_id)
        or (opportunity_id and str(row.get("opportunity_id") or "") == opportunity_id)
    )


def _real_offer(row: Dict[str, Any]) -> bool:
    if _norm(row.get("source")) in {"demo", "demo/simulación", "simulation", "simulated"}:
        return False
    if row.get("simulation") or row.get("probe"):
        return False
    return bool(
        row.get("amount") not in (None, "")
        or row.get("document_id")
        or row.get("source_message_id")
        or row.get("quote_id")
        or row.get("normalized_quote_id")
    )


def _proposal_evidence(state: Dict[str, Any], deal_id: str, opportunity_id: str, source: Dict[str, Any]) -> bool:
    if any(source.get(k) for k in ("proposal_id", "proposal_document_id", "proposal_sent_at", "buyer_offer_sent_at")):
        return True
    for row in state.get("proposals", []) or []:
        if isinstance(row, dict) and _linked(row, deal_id, opportunity_id) and not row.get("simulation"):
            return True
    proposal_kinds = {"proposal", "buyer_proposal", "commercial_proposal", "quote_to_buyer", "offer_to_buyer"}
    for row in state.get("outbox", []) or []:
        if not isinstance(row, dict) or not _linked(row, deal_id, opportunity_id):
            continue
        if str(row.get("status") or "").lower() not in {"sent", "delivered"}:
            continue
        if _norm(row.get("kind")) in proposal_kinds:
            return True
    return False


_ORIGINAL_EVIDENCE_STAGE = autonomy_operating_system._evidence_stage


def _strict_evidence_stage(state: Dict[str, Any], source: Dict[str, Any], source_type: str) -> str:
    stage = _ORIGINAL_EVIDENCE_STAGE(state, source, source_type)
    ranks = autonomy_operating_system.STAGE_RANK
    if ranks.get(stage, 0) < ranks["OFERTA"]:
        return stage

    source_id = str(source.get("id") or "")
    deal_id = str(source.get("deal_id") or (source_id if source_type == "deal" else ""))
    opportunity_id = str(source.get("opportunity_id") or (source_id if source_type == "opportunity" else ""))

    # COBRO must remain evidence-led by the original settlement logic.
    if stage == "COBRO":
        return stage

    real_offer = any(
        isinstance(row, dict) and _linked(row, deal_id, opportunity_id) and _real_offer(row)
        for row in state.get("offers", []) or []
    )
    proposal = _proposal_evidence(state, deal_id, opportunity_id, source)

    # A generic outbound email is never enough to claim OFERTA/NEGOCIACION/CIERRE.
    if proposal:
        return stage
    if real_offer:
        return "COTIZACION"

    if any(source.get(k) for k in ("supplier_account_id", "supplier_id", "supplier", "supplier_matches")):
        return "PROVEEDORES"
    if any(source.get(k) for k in ("requirement", "requirement_spec", "technical_scope", "pliego_url", "document_id")):
        return "REQUISITOS"
    if any(source.get(k) for k in ("buyer_account_id", "buyer_id", "buyer", "buyer_identity", "buyer_company")):
        return "COMPRADOR"
    return "DEMANDA"


autonomy_operating_system._evidence_stage = _strict_evidence_stage


# Concentrate quote-creation execution on supplier sourcing, RevOps, negotiation and evidence quality.
revenue_allocator_runtime.LANE_WEIGHTS["quote_creation"] = {
    "buyer_hunter": 0.04,
    "supplier_hunter": 0.23,
    "market_scout": 0.02,
    "research_analyst": 0.12,
    "revops": 0.30,
    "negotiator": 0.17,
    "market_manager": 0.02,
    "risk_quality": 0.06,
    "finance": 0.04,
}

_ORIGINAL_TWO_BRAIN_WEIGHTS = revenue_allocator_runtime._two_brain_weights


def _conversion_two_brain_weights(state: Dict[str, Any], lane: str):
    weights, explore = _ORIGINAL_TWO_BRAIN_WEIGHTS(state, lane)
    truth = state.get("canonical_revenue_truth", {}) or {}
    counts = truth.get("counts", {}) or {}
    sprint = lane == "quote_creation" and int(counts.get("canonical_opportunities") or 0) > 0 and int(counts.get("canonical_real_offers") or 0) == 0
    if not sprint:
        return weights, explore

    target_explore = 0.20
    base = dict(revenue_allocator_runtime.LANE_WEIGHTS["quote_creation"])
    exploration_roles = {"buyer_hunter", "market_scout"}
    current_explore = sum(base.get(k, 0.0) for k in exploration_roles) or 1e-9
    current_execute = max(1e-9, 1.0 - current_explore)
    for role in base:
        if role in exploration_roles:
            base[role] = base[role] / current_explore * target_explore
        else:
            base[role] = base[role] / current_execute * (1.0 - target_explore)
    total = sum(base.values()) or 1.0
    return {k: v / total for k, v in base.items()}, 20


revenue_allocator_runtime._two_brain_weights = _conversion_two_brain_weights


# After two consecutive failed tests in the same lane, the next experiment must test a distinct lane.
_ORIGINAL_EXPERIMENTS = commercial_learning_v2_runtime._experiments
_LANE_METRICS = {
    "closing": "canonical_close_ready",
    "quote_creation": "canonical_real_offers",
    "opportunity_building": "canonical_opportunities",
    "verification_contact": "eligible_external_prospects",
    "demand_discovery": "buyers_with_verified_demand",
}


def _guarded_experiments(state: Dict[str, Any], anti: Dict[str, Any]) -> Dict[str, Any]:
    rows = list(state.get("revenue_experiments", []) or [])
    active = next((x for x in reversed(rows) if x.get("status") == "TESTING"), None)
    if active is not None:
        return _ORIGINAL_EXPERIMENTS(state, anti)

    demoted = [x for x in rows if x.get("status") == "DEMOTED"]
    allocator = dict(state.get("revenue_allocator", {}) or {})
    current_lane = str(allocator.get("lane") or "")
    force = False
    rotated_from = None
    rotated_to = None

    if len(demoted) >= 2:
        last_two = demoted[-2:]
        lanes = [str(x.get("lane") or "") for x in last_two]
        if lanes[0] and lanes[0] == lanes[1] == current_lane:
            suggestion = str(anti.get("recommended_lane") or "").strip()
            if suggestion in _LANE_METRICS and suggestion != current_lane:
                rotated_to = suggestion
            else:
                rotated_to = "verification_contact" if current_lane != "verification_contact" else "opportunity_building"
            force = True
            rotated_from = current_lane

    if not force:
        return _ORIGINAL_EXPERIMENTS(state, anti)

    original_allocator = state.get("revenue_allocator")
    patched = dict(allocator)
    patched["lane"] = rotated_to
    patched["success_metric"] = _LANE_METRICS[rotated_to]
    state["revenue_allocator"] = patched
    try:
        result = _ORIGINAL_EXPERIMENTS(state, anti)
    finally:
        state["revenue_allocator"] = original_allocator

    candidate = result.get("active") or result.get("latest")
    if isinstance(candidate, dict):
        candidate["forced_rotation"] = True
        candidate["rotated_from_lane"] = rotated_from
        candidate["rotation_reason"] = "two_consecutive_demotions_same_lane"
    result["forced_rotation"] = True
    result["rotated_from_lane"] = rotated_from
    result["rotated_to_lane"] = rotated_to
    return result


commercial_learning_v2_runtime._experiments = _guarded_experiments


# Improvement Ledger cannot observe a no-effect hypothesis indefinitely.
_ORIGINAL_LEDGER_UPDATE = continuous_learning_runtime._update_improvement_ledger


def _bounded_improvement_ledger(state: Dict[str, Any], metrics: Dict[str, float]):
    ledger = list(_ORIGINAL_LEDGER_UPDATE(state, metrics) or [])
    redefinition = []
    for row in ledger:
        if row.get("status") != "OBSERVING":
            continue
        samples = int(row.get("samples") or 0)
        if samples < LEARNING_NO_EFFECT_SAMPLE_CAP:
            continue
        baseline = row.get("baseline_value")
        current = row.get("current_value")
        if baseline is None or current is None:
            continue
        delta = _f(current) - _f(baseline)
        if row.get("direction") == "lower_is_better":
            delta = -delta
        tolerance = max(0.01, abs(_f(baseline)) * 0.02)
        if abs(delta) <= tolerance:
            row["status"] = "DEMOTED"
            row["decision"] = "redefine_hypothesis_after_no_effect_sample_cap"
            row["redefinition_required"] = True
            row["demotion_reason"] = f"no measurable effect after {samples} samples"
            redefinition.append({
                "id": row.get("id"),
                "code": row.get("code"),
                "samples": samples,
                "target_metric": row.get("target_metric"),
                "reason": row.get("demotion_reason"),
            })
    state["continuous_learning_redefinition_required"] = redefinition
    return ledger


continuous_learning_runtime._update_improvement_ledger = _bounded_improvement_ledger


# Make Continuous Revenue Drive expose the real subphase: first complete requirements, then RFQ/quotes.
_ORIGINAL_CRD_TICK = continuous_revenue_drive_runtime.continuous_revenue_drive_tick


def _conversion_crd_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    report = dict(_ORIGINAL_CRD_TICK(state) or {})
    counts = report.get("canonical_truth_counts", {}) or {}
    funnel = state.get("business_funnel", {}) or {}
    copps = int(counts.get("canonical_opportunities") or 0)
    offers = int(counts.get("canonical_real_offers") or 0)
    requirements_ready = int(funnel.get("requirements_ready_for_rfq") or 0)

    if copps > 0 and offers == 0:
        if requirements_ready <= 0:
            subphase = "requirement_completion"
            report["primary_action"] = "Complete buyer requirement packs for the strongest canonical opportunities, then issue supplier RFQs."
            report["primary_success_metric"] = "requirements_ready_for_rfq > 0"
        else:
            subphase = "rfq_and_quote_capture"
            report["primary_action"] = "Issue comparable RFQs to verified suppliers and capture at least one traceable real quote."
            report["primary_success_metric"] = "canonical_real_offers > 0"
        report["conversion_sprint"] = {
            "active": True,
            "subphase": subphase,
            "execution_attention_pct": 80,
            "exploration_attention_pct": 20,
            "canonical_opportunities": copps,
            "requirements_ready_for_rfq": requirements_ready,
            "canonical_real_offers": offers,
            "truth_rule": "email_sent_is_not_offer; offer_requires_traceable commercial evidence",
            "experiment_rule": "two_consecutive_demotions_force_distinct_lane_test",
            "learning_rule": f"no-effect observing hypotheses demote after {LEARNING_NO_EFFECT_SAMPLE_CAP} samples and require redefinition",
        }
    else:
        report["conversion_sprint"] = {"active": False}

    state["continuous_revenue_drive"] = report
    state["conversion_sprint"] = report.get("conversion_sprint")
    return report


continuous_revenue_drive_runtime.continuous_revenue_drive_tick = _conversion_crd_tick

print(
    {
        "conversion_sprint_runtime": {
            "version": VERSION,
            "status": "active",
            "strict_offer_truth": True,
            "quote_execution_attention_pct": 80,
            "experiment_repeat_guard": True,
            "learning_no_effect_sample_cap": LEARNING_NO_EFFECT_SAMPLE_CAP,
            "binding_authority_changed": False,
        }
    },
    flush=True,
)
