from __future__ import annotations

"""Revenue Sprint 2.2: First Cash RFQ accelerator.

This layer turns already-verified evidence into faster *truthful* progress for the three First Cash
cases without consuming additional search budget or widening commercial authority.

It does four bounded things:
1. Reuses the official-document cache produced by procurement_document_enrichment_runtime when the
   exact requirement bridge runs (the producer and consumer previously used different state keys).
2. Prioritizes buyer-bound First Cash procurement documents in the existing two-document public GET
   budget before generic procurement documents.
3. Lets a First Cash professional case traverse consecutive zero-search stages in one cycle when
   company identity, exact demand evidence and/or corporate contact were already verified elsewhere.
4. Stops the dedicated First Cash case from spending effort on supplier matching while the RFQ
   minimum (technical scope, quantity, delivery location) is still incomplete.

No missing requirement is inferred. No search/send cap, payment, contract, purchase or binding action
is changed.
"""

from typing import Any, Dict, List

import commercial_truth_repair_runtime as truth
import procurement_document_enrichment_runtime as document_enrichment
import professional_casework
import revenue_sprint_v21_conversion_runtime as conversion

VERSION = "2.2-first-cash-rfq-accelerator"
MAX_FREE_STAGE_HOPS = 4

_CURRENT_REQUIREMENT_BRIDGE = truth._apply_procurement_requirement_evidence
_ORIGINAL_WORK_CASE = professional_casework._work_case
_ORIGINAL_LINKED_CURRENT_URLS = document_enrichment._linked_current_urls


def _clean(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _current_signal_urls(state: Dict[str, Any]) -> set[str]:
    return set(truth._signal_map(state).keys())


def _opportunity_for_case(state: Dict[str, Any], case: Dict[str, Any]) -> Dict[str, Any]:
    oid = str(case.get("first_cash_opportunity_id") or case.get("opportunity_id") or "")
    return conversion._opportunities(state).get(oid, {})


def _requirement_case_for(state: Dict[str, Any], case: Dict[str, Any]) -> Dict[str, Any]:
    oid = str(case.get("first_cash_opportunity_id") or case.get("opportunity_id") or "")
    return conversion._interlocution_by_opp(state).get(oid, {})


def _exact_current_urls(state: Dict[str, Any], case: Dict[str, Any], opp: Dict[str, Any]) -> List[str]:
    current = _current_signal_urls(state)
    return [url for url in conversion._exact_source_urls(state, case, opp) if url in current]


def _bridge_with_public_document_cache(state: Dict[str, Any]) -> Dict[str, int]:
    """Expose the actual public-document cache to v2.1 only during the bridge call.

    The alias is temporary so the large document excerpts are not persisted twice.
    """
    sentinel = object()
    previous = state.get("procurement_document_cache", sentinel)
    state["procurement_document_cache"] = state.get("public_procurement_document_cache", []) or []
    try:
        return dict(_CURRENT_REQUIREMENT_BRIDGE(state) or {})
    finally:
        if previous is sentinel:
            state.pop("procurement_document_cache", None)
        else:
            state["procurement_document_cache"] = previous


def _first_cash_document_priority(state: Dict[str, Any]) -> List[str]:
    """Put strict First Cash evidence first inside the existing MAX_DOCS_PER_CYCLE budget."""
    signals = _current_signal_urls(state)
    opps = conversion._opportunities(state)
    interlocution = conversion._interlocution_by_opp(state)
    exact: List[str] = []
    for oid in conversion._first_cash_focus_ids(state):
        opp = opps.get(str(oid), {})
        if not opp:
            continue
        requirement_case = dict(interlocution.get(str(oid), {}) or {})
        requirement_case.setdefault("buyer_account_id", opp.get("buyer_account_id"))
        for url in conversion._exact_source_urls(state, requirement_case, opp):
            if url in signals:
                exact.append(url)
    generic = list(_ORIGINAL_LINKED_CURRENT_URLS(state) or [])
    prioritized = list(dict.fromkeys(exact + generic))
    state["first_cash_document_priority"] = {
        "version": VERSION,
        "strict_first_cash_urls": len(list(dict.fromkeys(exact))),
        "eligible_total": len(prioritized),
        "max_docs_per_cycle_unchanged": document_enrichment.MAX_DOCS_PER_CYCLE,
        "search_provider_queries_used": 0,
        "updated_at": conversion._now(),
    }
    return prioritized


def _sync_checklist(state: Dict[str, Any], case: Dict[str, Any]) -> Dict[str, Any]:
    requirement_case = _requirement_case_for(state, case)
    requirement = requirement_case.get("requirement", {}) or {}
    checklist = {
        "technical_scope": requirement.get("technical_scope") not in (None, "", [], {}),
        "quantity": requirement.get("quantity") not in (None, "", [], {}),
        "delivery_location": requirement.get("delivery_location") not in (None, "", [], {}),
        "supplier_rfq_ready": bool(requirement_case.get("supplier_rfq_ready")),
    }
    case["first_cash_requirement_checklist"] = checklist
    case["first_cash_missing_fields"] = [
        field for field in ("technical_scope", "quantity", "delivery_location") if not checklist[field]
    ]
    return checklist


def _refresh_requirements_once(state: Dict[str, Any]) -> Dict[str, int]:
    tick = int(state.get("ticks") or 0)
    report = state.setdefault("first_cash_rfq_accelerator", {})
    if int(report.get("requirement_bridge_tick", -1)) == tick:
        return dict(report.get("requirement_bridge", {}) or {})
    bridge = _bridge_with_public_document_cache(state)
    report["requirement_bridge_tick"] = tick
    report["requirement_bridge"] = bridge
    report["updated_at"] = conversion._now()
    return bridge


def _advance_exact_demand(state: Dict[str, Any], case: Dict[str, Any], opp: Dict[str, Any]) -> bool:
    urls = _exact_current_urls(state, case, opp)
    if not urls:
        return False
    case.setdefault("facts", {})["demand"] = {
        "verified_existing": True,
        "basis": "buyer_bound_current_official_procurement",
        "evidence_urls": urls[:6],
    }
    professional_casework._advance(
        case,
        "Demanda confirmada por evidencia oficial vigente ligada exactamente al comprador/oportunidad.",
    )
    case["next_action"] = "Completar alcance técnico, cantidad y lugar de entrega con evidencia exacta"
    return True


def _free_verified_hops(
    state: Dict[str, Any],
    case: Dict[str, Any],
    source: Dict[str, Any],
    cycle_searches: Dict[str, int],
) -> int:
    hops = 0
    opp = _opportunity_for_case(state, case)
    while hops < MAX_FREE_STAGE_HOPS:
        stage = str(case.get("stage") or "")
        if stage == "identity" and source.get("verified_company"):
            professional_casework._identity(state, case, source, cycle_searches)
            hops += 1
            continue
        if stage == "demand" and _advance_exact_demand(state, case, opp):
            hops += 1
            continue
        existing_email = _clean(source.get("verified_email") or source.get("email") or source.get("contact_email"))
        if stage == "contact" and (source.get("verified_contact") or existing_email):
            professional_casework._contact(state, case, source, cycle_searches)
            hops += 1
            continue
        break
    return hops


def _record_accelerator_state(state: Dict[str, Any], case: Dict[str, Any], free_hops: int) -> None:
    tick = int(state.get("ticks") or 0)
    report = state.setdefault("first_cash_rfq_accelerator", {})
    if int(report.get("tick", -1)) != tick:
        bridge_tick = report.get("requirement_bridge_tick")
        bridge = report.get("requirement_bridge")
        report.clear()
        report.update({
            "version": VERSION,
            "status": "active",
            "tick": tick,
            "free_stage_hops": 0,
            "cases_touched": [],
            "missing_by_case": {},
            "requirement_bridge_tick": bridge_tick,
            "requirement_bridge": bridge or {},
        })
    report["free_stage_hops"] = int(report.get("free_stage_hops") or 0) + int(free_hops or 0)
    cid = str(case.get("id") or "")
    touched = list(report.get("cases_touched", []) or [])
    if cid and cid not in touched:
        touched.append(cid)
    report["cases_touched"] = touched[:6]
    missing = dict(report.get("missing_by_case", {}) or {})
    if cid:
        missing[cid] = list(case.get("first_cash_missing_fields", []) or [])
    report["missing_by_case"] = missing
    report["rfq_ready_total"] = sum(
        1
        for x in state.get("professional_cases", []) or []
        if isinstance(x, dict) and x.get("first_cash") and (x.get("first_cash_requirement_checklist", {}) or {}).get("supplier_rfq_ready")
    )
    report["search_spend_increased"] = False
    report["outbound_caps_increased"] = False
    report["binding_authority_changed"] = False
    report["updated_at"] = conversion._now()


def _first_cash_work_case(state: Dict[str, Any], case: Dict[str, Any], cycle_searches: Dict[str, int]) -> str:
    if not case.get("first_cash"):
        return _ORIGINAL_WORK_CASE(state, case, cycle_searches)

    _refresh_requirements_once(state)
    checklist = _sync_checklist(state, case)
    stage = str(case.get("stage") or "triage")

    # Do not burn the scarce search budget on supplier matching before the requirement can be quoted.
    if stage in {"supplier_match", "buyer_fit", "thesis"} and not checklist.get("supplier_rfq_ready"):
        case["status"] = "active"
        case["last_worked_at"] = professional_casework.utcnow()
        case["cycles_worked"] = int(case.get("cycles_worked") or 0) + 1
        case["next_action"] = "Cerrar requisito exacto: " + ", ".join(case.get("first_cash_missing_fields", []) or [])
        _record_accelerator_state(state, case, 0)
        return "waiting"

    result = _ORIGINAL_WORK_CASE(state, case, cycle_searches)
    if result == "parked":
        _record_accelerator_state(state, case, 0)
        return result

    source = professional_casework._source_for_case(state, case)
    free_hops = _free_verified_hops(state, case, source, cycle_searches) if source else 0

    # The document enrichment stage may have populated exact official text earlier in this same cycle.
    _refresh_requirements_once(state)
    checklist = _sync_checklist(state, case)
    if checklist.get("supplier_rfq_ready"):
        case["status"] = "ready_for_handoff"
        case["next_action"] = "Solicitar ofertas comparables a proveedores validados"
        case["first_cash_rfq_ready"] = True
        result = "ready"
    elif str(case.get("stage") or "") in {"supplier_match", "buyer_fit", "thesis"}:
        case["status"] = "active"
        case["next_action"] = "Cerrar requisito exacto: " + ", ".join(case.get("first_cash_missing_fields", []) or [])

    _record_accelerator_state(state, case, free_hops)
    return result


# Install after v2.1 strict-lineage hooks. These wrappers only reuse existing verified evidence.
truth._apply_procurement_requirement_evidence = _bridge_with_public_document_cache
document_enrichment._linked_current_urls = _first_cash_document_priority
professional_casework._work_case = _first_cash_work_case

print({
    "revenue_sprint_v22_first_cash_accelerator": {
        "version": VERSION,
        "status": "installed",
        "public_document_cache_bridge": True,
        "first_cash_document_priority": True,
        "zero_search_verified_stage_hops": True,
        "supplier_match_waits_for_rfq_minimum": True,
        "search_spend_increased": False,
        "outbound_caps_increased": False,
        "binding_authority_changed": False,
    }
}, flush=True)
