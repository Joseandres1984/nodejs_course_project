from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _relationship(state: Dict[str, Any], account_id: str) -> Dict[str, Any]:
    key = f"account:{account_id}"
    return next((x for x in state.get("commercial_relationships", []) if x.get("key") == key), {})


def _contact_score(account: Dict[str, Any]) -> int:
    if account.get("verified_contact") and account.get("commercial_email"):
        return 15
    if account.get("commercial_channel_verified"):
        return 10
    return 0


def _relationship_score(relation: Dict[str, Any]) -> int:
    outbound = int(relation.get("outbound_count") or 0)
    responses = int(relation.get("response_count") or 0)
    if not outbound:
        return 5 if relation.get("commercial_channel") else 0
    ratio = min(1.0, responses / max(1, outbound))
    return round(ratio * 15)


def _role_score(account: Dict[str, Any]) -> int:
    if account.get("type") == "buyer":
        if account.get("demand_signal"):
            return 15
        return round(min(15, float(account.get("demand_score") or 0) * 0.15))
    matches = len(account.get("category_matches") or [])
    return min(15, 5 + matches * 3) if account.get("verified_company") else 0


def _risk_flags(account: Dict[str, Any], relation: Dict[str, Any]) -> list[str]:
    flags: list[str] = []
    if not account.get("verified_company"):
        flags.append("company_unverified")
    if not account.get("commercial_channel_verified"):
        flags.append("commercial_channel_missing")
    if account.get("type") == "buyer" and not account.get("demand_signal"):
        flags.append("demand_not_verified")
    if relation.get("relationship_state") == "cooldown":
        flags.append("relationship_cooldown")
    if relation.get("opted_out"):
        flags.append("do_not_contact")
    return flags


def scorecards_tick(state: Dict[str, Any]) -> Dict[str, int]:
    accounts = state.setdefault("candidate_accounts", [])
    stats = {"scored": 0, "high_quality": 0, "watchlist": 0, "blocked": 0}

    for account in accounts:
        relation = _relationship(state, str(account.get("id") or ""))
        verification = round(float(account.get("verification_score") or 0) * 0.35)
        lead_quality = round(float(account.get("lead_score") or 0) * 0.20)
        contactability = _contact_score(account)
        relationship = _relationship_score(relation)
        role_fit = _role_score(account)
        score = max(0, min(100, verification + lead_quality + contactability + relationship + role_fit))
        flags = _risk_flags(account, relation)

        if "do_not_contact" in flags or "company_unverified" in flags:
            tier = "blocked"
            stats["blocked"] += 1
        elif score >= 75 and not flags:
            tier = "A"
            stats["high_quality"] += 1
        elif score >= 55:
            tier = "B"
        else:
            tier = "watchlist"
            stats["watchlist"] += 1

        account["counterparty_scorecard"] = {
            "score": score,
            "tier": tier,
            "verification": verification,
            "lead_quality": lead_quality,
            "contactability": contactability,
            "relationship": relationship,
            "role_fit": role_fit,
            "risk_flags": flags,
            "updated_at": utcnow(),
            "method": "observable_evidence_only",
        }
        stats["scored"] += 1

    state["counterparty_scorecard_stats"] = {**stats, "updated_at": utcnow()}
    return stats
