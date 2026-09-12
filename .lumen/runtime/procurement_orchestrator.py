from __future__ import annotations

from typing import Any, Dict

from supplier_network import supplier_network_tick


def _deal_map(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(x.get("id")): x for x in state.get("deals", []) if x.get("id")}


def procurement_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    report = supplier_network_tick(state)
    deals = _deal_map(state)
    risk_index = state.get("counterparty_risk_index", {}) or {}
    by_opp = {str(x.get("opportunity_id") or ""): x for x in state.get("interlocution_cases", []) if x.get("opportunity_id")}
    deep_by_opp = {str(x.get("opportunity_id") or ""): x for x in state.get("deep_dive_cases", []) if x.get("opportunity_id")}
    applied = 0
    missing_deep_dive = 0
    risk_filtered = 0

    for squad in state.get("supplier_squads", []) or []:
        deal = deals.get(str(squad.get("deal_id") or ""), {})
        opp_id = str(deal.get("opportunity_id") or "")
        original_members = list(squad.get("squad") or [])
        members = []
        for member in original_members:
            account_id = str(member.get("account_id") or "")
            risk = risk_index.get(account_id, {}) or {}
            if risk.get("risk_tier") == "BLOCKED" or risk.get("can_outreach") is False:
                risk_filtered += 1
                continue
            enriched = dict(member)
            enriched["counterparty_risk_tier"] = risk.get("risk_tier")
            enriched["counterparty_risk_score"] = risk.get("risk_score")
            members.append(enriched)

        squad["squad_pre_risk_filter"] = original_members
        squad["squad"] = members
        squad["risk_filtered_members"] = len(original_members) - len(members)
        if not members:
            squad["status"] = "blocked_by_counterparty_risk"
        elif len(members) < len(original_members):
            squad["status"] = "risk_filtered_squad"

        if not opp_id or not members:
            continue
        interlocution = by_opp.get(opp_id)
        if not interlocution:
            continue
        anchor = members[0]
        if "supplier_account_id_pre_network" not in interlocution:
            interlocution["supplier_account_id_pre_network"] = interlocution.get("supplier_account_id")
        interlocution["supplier_account_id"] = anchor.get("account_id")
        interlocution["supplier_network_squad"] = [x.get("account_id") for x in members]
        interlocution["supplier_network_status"] = squad.get("status")

        deep = deep_by_opp.get(opp_id)
        if deep:
            if "supplier_alternatives_pre_network" not in deep:
                deep["supplier_alternatives_pre_network"] = list(deep.get("supplier_alternatives") or [])
            deep["supplier_alternatives"] = [
                {
                    "id": x.get("account_id"),
                    "name": x.get("supplier"),
                    "market": x.get("market"),
                    "source": "supplier_network_squad",
                    "squad_role": x.get("role"),
                    "supplier_network_score": x.get("network_score"),
                    "supplier_squad_score": x.get("squad_score"),
                    "commercial_channel_verified": bool(x.get("verified_contact")),
                    "counterparty_risk_tier": x.get("counterparty_risk_tier"),
                    "counterparty_risk_score": x.get("counterparty_risk_score"),
                }
                for x in members[1:]
            ]
            deep["supplier_network_overlay"] = {
                "deal_id": squad.get("deal_id"),
                "status": squad.get("status"),
                "supplier_count": len(members),
                "risk_filtered_members": squad.get("risk_filtered_members"),
            }
        else:
            missing_deep_dive += 1
        applied += 1

    result = {
        **report,
        "revops_overlays_applied": applied,
        "squads_without_deep_dive_case": missing_deep_dive,
        "risk_filtered_members": risk_filtered,
        "overlay_rule": "RevOps supplier pool is limited to the evidence-ranked squad after Counterparty Risk removes blocked/uncontactable members; original alternatives are retained for audit.",
    }
    state["procurement_orchestrator"] = result
    return result
