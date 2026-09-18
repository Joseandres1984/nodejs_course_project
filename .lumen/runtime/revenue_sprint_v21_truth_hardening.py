from __future__ import annotations

"""Truth hardening for Revenue Sprint 2.1.

Two strict rules are enforced here:
1. A generic opportunity evidence reference is not sufficient to populate RFQ fields. Eligible
   requirement evidence must be buyer-bound or carry previously proven exact source/account lineage.
2. A dedicated First Cash professional case belongs only to its exact opportunity/team, even when
   two opportunities share the same buyer account. Buyer/category similarity may support research,
   but cannot cross-assign the dedicated execution case.

This runtime only narrows evidence and case routing; it never broadens authority or creates data.
"""

from typing import Any, Dict, List

import commercial_truth_repair_runtime as truth
import mission_team_runtime
import revenue_sprint_v21_conversion_runtime as conversion

VERSION = "2.1.2-strict-lineage-and-case-isolation"
_ORIGINAL_LINK_AFTER_CONVERSION = mission_team_runtime._link_professional_cases


def _valid_url(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(("http://", "https://"))


def _strict_exact_source_urls(state: Dict[str, Any], case: Dict[str, Any], opp: Dict[str, Any]) -> List[str]:
    buyer_id = str(case.get("buyer_account_id") or opp.get("buyer_account_id") or "")
    accounts = conversion._accounts(state)
    buyer = accounts.get(buyer_id) or {}
    urls: List[str] = []

    # Evidence stored directly on the buyer is already scoped to that account by the demand layer.
    for key in ("demand_evidence_url", "procurement_evidence_url"):
        value = buyer.get(key)
        if _valid_url(value):
            urls.append(value)
    for key in ("demand_evidence_urls", "procurement_evidence_urls"):
        for value in buyer.get(key, []) or []:
            if _valid_url(value):
                urls.append(value)

    # Some procurement records carry an explicit buyer/account reference. Exact id equality is
    # acceptable; category/title similarity is deliberately not.
    for signal in truth._all_procurement_signals(state):
        signal_buyer_ids = {
            str(signal.get("buyer_account_id") or ""),
            str(signal.get("account_id") or ""),
            str(signal.get("buyer_id") or ""),
        }
        signal_buyer_ids.discard("")
        value = signal.get("url") or signal.get("source_url")
        if buyer_id and buyer_id in signal_buyer_ids and _valid_url(value):
            urls.append(value)

    # Opportunity evidence is allowed only when a previous exact lineage runtime proved that the
    # procurement source came through this buyer's source lead/account chain.
    exact_opp_lineage = str(opp.get("procurement_lineage") or "") == "buyer_account_source_lead_id_exact"
    exact_buyer_lineage = str(buyer.get("demand_evidence_lineage") or "") == "source_lead_id_exact"
    if exact_opp_lineage or exact_buyer_lineage:
        for value in opp.get("evidence_refs", []) or []:
            if _valid_url(value):
                urls.append(value)

    # Existing field evidence may be reused only if its URL is already in the exact set above.
    exact = list(dict.fromkeys(urls))
    exact_set = set(exact)
    requirement = case.get("requirement", {}) or {}
    for evidence in (requirement.get("field_evidence", {}) or {}).values():
        if not isinstance(evidence, dict):
            continue
        value = evidence.get("url")
        if value in exact_set:
            exact.append(value)

    return list(dict.fromkeys(exact))


def _link_cases_with_exact_first_cash_isolation(state: Dict[str, Any]) -> List[str]:
    focus_ids = list(_ORIGINAL_LINK_AFTER_CONVERSION(state) or [])
    teams = {
        str(x.get("opportunity_id") or ""): x
        for x in state.get("mission_teams", []) or []
        if isinstance(x, dict) and x.get("status") == "active" and x.get("opportunity_id")
    }
    cases = [x for x in state.get("professional_cases", []) or [] if isinstance(x, dict)]
    first_cash_cases = [x for x in cases if x.get("first_cash") and x.get("first_cash_opportunity_id")]
    exact_case_ids: List[str] = []

    for case in first_cash_cases:
        oid = str(case.get("first_cash_opportunity_id") or "")
        team = teams.get(oid)
        cid = str(case.get("id") or "")
        if not team or not cid:
            continue
        team_id = str(team.get("id") or "")
        # Dedicated case: exactly one team, exactly one opportunity.
        case["mission_team_ids"] = [team_id] if team_id else []
        case["mission_team_priority"] = 120
        case["mission_team_stage"] = team.get("stage")
        case["mission_team_task"] = team.get("current_task")
        case["first_cash_exact_team_binding"] = True
        case["first_cash_bound_opportunity_id"] = oid
        exact_case_ids.append(cid)

        current = [str(x) for x in team.get("focus_case_ids", []) or [] if x]
        # Remove other dedicated First Cash cases from this team, preserve ordinary supporting cases.
        other_first_cash_ids = {
            str(x.get("id") or "")
            for x in first_cash_cases
            if str(x.get("first_cash_opportunity_id") or "") != oid
        }
        current = [x for x in current if x not in other_first_cash_ids and x != cid]
        team["focus_case_ids"] = [cid] + current
        team["first_cash_exact_case_id"] = cid

    # Rebuild global focus list so exact First Cash cases are guaranteed to survive at the front.
    existing_global = [str(x) for x in state.get("mission_team_focus_case_ids", []) or [] if x]
    others = [x for x in existing_global if x not in set(exact_case_ids)]
    state["mission_team_focus_case_ids"] = list(dict.fromkeys(exact_case_ids + others))[:mission_team_runtime.MAX_FOCUS_CASES]

    binding = state.setdefault("first_cash_case_binding", {})
    binding["exact_opportunity_isolation"] = True
    binding["exact_team_case_ids"] = exact_case_ids
    binding["linked_focus_cases"] = len(exact_case_ids)
    binding["linked_focus_case_ids"] = exact_case_ids
    binding["updated_at"] = conversion._now()
    return state["mission_team_focus_case_ids"]


conversion._exact_source_urls = _strict_exact_source_urls
mission_team_runtime._link_professional_cases = _link_cases_with_exact_first_cash_isolation

print({
    "revenue_sprint_v21_truth_hardening": {
        "version": VERSION,
        "status": "active",
        "buyer_bound_evidence_required": True,
        "category_only_evidence_rejected_for_rfq_fields": True,
        "exact_lineage_required_for_opportunity_evidence_refs": True,
        "first_cash_exact_opportunity_isolation": True,
        "inference_allowed": False,
        "spend_changed": False,
        "binding_authority_changed": False,
    }
}, flush=True)
