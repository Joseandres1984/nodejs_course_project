from __future__ import annotations

"""Truth hardening for Revenue Sprint 2.1 exact requirement completion.

A generic opportunity evidence reference is not sufficient to populate RFQ fields. This shim
narrows eligible sources to buyer-bound demand evidence, explicitly buyer-tagged procurement
signals, or opportunity evidence whose lineage was already proven by exact source-lead/account
linkage. It only narrows evidence; it never broadens authority or creates data.
"""

from typing import Any, Dict, List

import commercial_truth_repair_runtime as truth
import revenue_sprint_v21_conversion_runtime as conversion

VERSION = "2.1.1-strict-procurement-lineage"


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


conversion._exact_source_urls = _strict_exact_source_urls

print({
    "revenue_sprint_v21_truth_hardening": {
        "version": VERSION,
        "status": "active",
        "buyer_bound_evidence_required": True,
        "category_only_evidence_rejected_for_rfq_fields": True,
        "exact_lineage_required_for_opportunity_evidence_refs": True,
        "inference_allowed": False,
        "spend_changed": False,
        "binding_authority_changed": False,
    }
}, flush=True)
