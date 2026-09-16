from __future__ import annotations

"""Backlog-aware throughput for prospect verification/contact research.

Raises breadth (accounts per cycle) only when there is meaningful pending work.
It does not relax evidence thresholds, increase pages per account, infer personal
emails, or change outreach authority.
"""

from typing import Any, Dict

import company_verifier
import contact_intelligence
import growth_prospector


VERSION = "1.0-backlog-aware-prospect-throughput"
BASE_VERIFY = 4
HIGH_VERIFY = 6
BASE_CONTACT = 5
HIGH_CONTACT = 6
BASE_B_PROMOTIONS = 4
HIGH_B_PROMOTIONS = 6
BACKLOG_THRESHOLD = 20


def _counts(state: Dict[str, Any]) -> Dict[str, int]:
    accounts = list(state.get("candidate_accounts", []) or [])
    verification = sum(
        1 for row in accounts
        if not row.get("verified_company")
        and str(row.get("status") or "") in {"verification_required", "research_required", ""}
    )
    contact = sum(
        1 for row in accounts
        if row.get("verified_company")
        and not (row.get("verified_contact") or row.get("commercial_channel_verified"))
    )
    return {"verification_backlog": verification, "contact_backlog": contact}


def apply(state: Dict[str, Any]) -> Dict[str, Any]:
    counts = _counts(state)
    verify = HIGH_VERIFY if counts["verification_backlog"] >= BACKLOG_THRESHOLD else BASE_VERIFY
    contact = HIGH_CONTACT if counts["contact_backlog"] >= BACKLOG_THRESHOLD else BASE_CONTACT
    promotions = HIGH_B_PROMOTIONS if counts["verification_backlog"] < BACKLOG_THRESHOLD * 2 else BASE_B_PROMOTIONS

    company_verifier.MAX_PER_TICK = verify
    contact_intelligence.MAX_ACCOUNTS_PER_TICK = contact
    growth_prospector.MAX_B_PROMOTIONS = promotions

    report = {
        "version": VERSION,
        "status": "active",
        **counts,
        "verification_accounts_per_cycle": verify,
        "contact_accounts_per_cycle": contact,
        "tier_b_promotions_per_cycle": promotions,
        "evidence_thresholds_unchanged": True,
        "pages_per_account_unchanged": True,
        "personal_email_inference": False,
        "outreach_authority_unchanged": True,
    }
    state["prospect_throughput"] = report
    return report


print({
    "prospect_throughput_runtime": {
        "version": VERSION,
        "status": "active",
        "max_verification_accounts": HIGH_VERIFY,
        "max_contact_accounts": HIGH_CONTACT,
        "evidence_thresholds_unchanged": True,
    }
}, flush=True)
