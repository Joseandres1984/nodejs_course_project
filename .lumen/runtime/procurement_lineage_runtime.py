from __future__ import annotations

"""Preserve exact procurement evidence lineage across lead -> account -> opportunity -> RFQ case.

Existing buyer-identity resolution stores the originating research lead id and procurement URL on
the lead, but the base lead-to-account promotion does not always copy that provenance. This runtime
repairs and *confirms* that lineage strictly by exact source_lead_id/account id; it never links
evidence by category, title or semantic similarity.

Important truth rule: lineage is a relationship fact, not a side effect of inserting a new URL.
If an exact source lead and its procurement URL were already copied by an earlier runtime, the
lineage marker must still be set. Otherwise valid existing evidence remains unusable by strict RFQ
gates even though the exact lead -> buyer relationship is already present.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List

import interlocutor_engine

VERSION = "1.1-exact-lineage-confirmation"
_ORIGINAL_INTERLOCUTOR_TICK = interlocutor_engine.interlocutor_tick


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _urls_from_lead(lead: Dict[str, Any]) -> List[str]:
    urls: List[str] = []
    for key in ("demand_evidence_url", "procurement_evidence_url"):
        value = lead.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            urls.append(value)
    for key in ("demand_evidence_urls", "procurement_evidence_urls"):
        for value in lead.get(key, []) or []:
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                urls.append(value)
    return list(dict.fromkeys(urls))


def _sync_lineage(state: Dict[str, Any]) -> Dict[str, int]:
    leads = {
        str(x.get("id") or ""): x
        for x in state.get("research_leads", []) or []
        if isinstance(x, dict) and x.get("id")
    }
    accounts = {
        str(x.get("id") or ""): x
        for x in state.get("candidate_accounts", []) or []
        if isinstance(x, dict) and x.get("id")
    }
    stats = {
        "accounts_linked": 0,
        "accounts_lineage_confirmed": 0,
        "account_urls_added": 0,
        "opportunities_linked": 0,
        "opportunities_lineage_confirmed": 0,
        "opportunity_refs_added": 0,
    }

    for account in accounts.values():
        if str(account.get("type") or "") != "buyer":
            continue
        source_lead_id = str(account.get("source_lead_id") or "")
        lead = leads.get(source_lead_id, {})
        if not lead:
            continue
        urls = _urls_from_lead(lead)
        if not urls:
            continue

        before = list(account.get("demand_evidence_urls", []) or [])
        merged = list(dict.fromkeys(before + urls))[-12:]
        added = max(0, len(merged) - len(before))
        previous_lineage = str(account.get("demand_evidence_lineage") or "")
        previous_source = str(account.get("demand_evidence_source_lead_id") or "")

        # Exact source_lead_id equality proves the provenance whether or not the URL was already
        # present. Never require a new insertion merely to acknowledge an already-existing exact link.
        account["demand_evidence_urls"] = merged
        account["demand_evidence_url"] = account.get("demand_evidence_url") or urls[0]
        account["demand_evidence_source_lead_id"] = lead.get("id")
        account["demand_evidence_lineage"] = "source_lead_id_exact"
        account["demand_evidence_lineage_updated_at"] = _now()
        if lead.get("public_demand_hint") or lead.get("demand_signal") or lead.get("direct_inbound_demand"):
            account["public_demand_hint"] = True

        if added > 0:
            stats["accounts_linked"] += 1
            stats["account_urls_added"] += added
        if previous_lineage != "source_lead_id_exact" or previous_source != source_lead_id:
            stats["accounts_lineage_confirmed"] += 1

    for opp in state.get("market_opportunities", []) or []:
        if not isinstance(opp, dict):
            continue
        buyer_id = str(opp.get("buyer_account_id") or "")
        buyer = accounts.get(buyer_id, {})
        if not buyer or str(buyer.get("demand_evidence_lineage") or "") != "source_lead_id_exact":
            continue
        urls = list(buyer.get("demand_evidence_urls", []) or [])
        if not urls:
            continue

        before = [str(x) for x in opp.get("evidence_refs", []) or [] if x]
        merged = list(dict.fromkeys(before + urls))[:12]
        added = max(0, len(merged) - len(before))
        previous_lineage = str(opp.get("procurement_lineage") or "")

        # buyer_account_id is an exact canonical id and the buyer's source-lead provenance is exact.
        # Therefore existing refs can be lineage-confirmed even when this cycle adds zero new URLs.
        opp["evidence_refs"] = merged
        opp["buyer_demand_evidence_urls"] = urls[:8]
        opp["procurement_lineage"] = "buyer_account_source_lead_id_exact"
        opp["procurement_lineage_buyer_account_id"] = buyer_id
        opp["updated_at"] = _now()

        if added > 0:
            stats["opportunities_linked"] += 1
            stats["opportunity_refs_added"] += added
        if previous_lineage != "buyer_account_source_lead_id_exact":
            stats["opportunities_lineage_confirmed"] += 1

    state["procurement_lineage"] = {
        "version": VERSION,
        "status": "active",
        **stats,
        "link_policy": "exact_source_lead_id_and_buyer_account_id_only",
        "existing_exact_evidence_can_confirm_lineage": True,
        "category_similarity_used": False,
        "updated_at": _now(),
    }
    return stats


def _interlocutor_with_lineage(state: Dict[str, Any]) -> Dict[str, Any]:
    lineage = _sync_lineage(state)
    report = dict(_ORIGINAL_INTERLOCUTOR_TICK(state) or {})
    report["procurement_lineage_accounts_linked"] = lineage["accounts_linked"]
    report["procurement_lineage_accounts_confirmed"] = lineage["accounts_lineage_confirmed"]
    report["procurement_lineage_opportunities_linked"] = lineage["opportunities_linked"]
    report["procurement_lineage_opportunities_confirmed"] = lineage["opportunities_lineage_confirmed"]
    report["procurement_lineage_refs_added"] = lineage["opportunity_refs_added"]
    return report


interlocutor_engine.interlocutor_tick = _interlocutor_with_lineage

print(
    {
        "procurement_lineage_runtime": {
            "version": VERSION,
            "status": "active",
            "link_policy": "exact_source_lead_id_and_buyer_account_id_only",
            "existing_exact_evidence_can_confirm_lineage": True,
            "category_similarity_used": False,
            "binding_authority_changed": False,
        }
    },
    flush=True,
)

# Worker entry imports procurement lineage before worker_journal. Loading the Revenue Sprint hooks
# here guarantees its First Cash Mission Team activation shim is installed before the production
# Mission Team tick, while preserving the lineage runtime's own behavior and authority boundaries.
import revenue_sprint_v2_runtime  # noqa: E402,F401
import revenue_sprint_v2_team_fix  # noqa: E402,F401
