from __future__ import annotations

from typing import Any, Dict


def propagate_venture_attribution(state: Dict[str, Any]) -> Dict[str, int]:
    stats = {"accounts": 0, "opportunities": 0, "interlocutions": 0, "deals": 0, "transactions": 0, "conflicts": 0}

    leads = {str(x.get("id")): x for x in state.get("research_leads", []) if x.get("id")}
    accounts = {str(x.get("id")): x for x in state.get("candidate_accounts", []) if x.get("id")}
    opportunities = {str(x.get("id")): x for x in state.get("market_opportunities", []) if x.get("id")}

    for account in accounts.values():
        lead = leads.get(str(account.get("source_lead_id") or ""), {})
        venture_id = lead.get("venture_id")
        if venture_id and not account.get("venture_id"):
            account["venture_id"] = venture_id
            account["venture_type"] = lead.get("venture_type")
            account["venture_market"] = lead.get("venture_market")
            account["venture_validation"] = bool(lead.get("venture_validation"))
            stats["accounts"] += 1

    for opportunity in opportunities.values():
        buyer = accounts.get(str(opportunity.get("buyer_account_id") or ""), {})
        supplier = accounts.get(str(opportunity.get("supplier_account_id") or ""), {})
        buyer_venture = str(buyer.get("venture_id") or "")
        supplier_venture = str(supplier.get("venture_id") or "")
        venture_id = ""
        if buyer_venture and supplier_venture and buyer_venture != supplier_venture:
            opportunity["venture_attribution_conflict"] = True
            stats["conflicts"] += 1
        elif buyer_venture or supplier_venture:
            venture_id = buyer_venture or supplier_venture
        if venture_id and not opportunity.get("venture_id"):
            opportunity["venture_id"] = venture_id
            opportunity["venture_validation"] = True
            stats["opportunities"] += 1

    for case in state.get("interlocution_cases", []) or []:
        opp = opportunities.get(str(case.get("opportunity_id") or ""), {})
        venture_id = opp.get("venture_id")
        if venture_id and not case.get("venture_id"):
            case["venture_id"] = venture_id
            case["venture_validation"] = True
            stats["interlocutions"] += 1

    for deal in state.get("deals", []) or []:
        opp = opportunities.get(str(deal.get("opportunity_id") or ""), {})
        venture_id = opp.get("venture_id")
        if venture_id and not deal.get("venture_id"):
            deal["venture_id"] = venture_id
            deal["venture_validation"] = True
            stats["deals"] += 1

    deals = {str(x.get("id")): x for x in state.get("deals", []) if x.get("id")}
    for txn in state.get("transactions", []) or []:
        deal = deals.get(str(txn.get("deal_id") or ""), {})
        venture_id = deal.get("venture_id")
        if venture_id and not txn.get("venture_id"):
            txn["venture_id"] = venture_id
            stats["transactions"] += 1

    state["venture_attribution_stats"] = stats
    return stats
