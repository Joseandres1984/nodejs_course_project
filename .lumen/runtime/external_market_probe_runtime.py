from __future__ import annotations

from collections import Counter
from datetime import timedelta
from typing import Any, Dict

from app import STATE, load_state
import outbound_engine

VERSION = "1.1-external-market-probe"


def _successful_recent_contact(email: str) -> bool:
    target = str(email or "").strip().lower()
    cutoff = outbound_engine.utcnow_dt() - timedelta(days=outbound_engine.RECONTACT_DAYS)
    for item in reversed(STATE.get("outbox", []) or []):
        if str(item.get("contact") or "").strip().lower() != target:
            continue
        if item.get("source") not in {"outbound_engine", "distribution_operator_canary"}:
            continue
        if str(item.get("status") or "") not in {"sent", "delivered"}:
            continue
        when = outbound_engine._parse(item.get("delivered_at") or item.get("sent_at"))
        if when and when >= cutoff:
            return True
    return False


def _reason(account: Dict[str, Any]) -> str | None:
    if str(account.get("type") or "") not in {"buyer", "supplier"}:
        return "unsupported_account_type"
    if not account.get("verified_company"):
        return "company_not_verified"
    if not account.get("verified_contact"):
        return "contact_not_verified"
    email = str(account.get("commercial_email") or "").strip().lower()
    domain = outbound_engine._email_domain(email)
    official = str(account.get("domain") or "").strip().lower().removeprefix("www.")
    if not domain:
        return "no_valid_email"
    if domain in outbound_engine.FREE_DOMAINS:
        return "free_mail_domain"
    if official and domain != official and not domain.endswith("." + official):
        return "email_domain_mismatch"
    if str(account.get("contact_policy") or "public_corporate_channels_only") != "public_corporate_channels_only":
        return "contact_policy_block"
    if outbound_engine._suppressed(STATE, email):
        return "suppressed_or_optout"
    if not outbound_engine._risk_allows(STATE, account):
        return "counterparty_risk_block"
    relation = outbound_engine._relationship(STATE, account, email)
    if relation.get("opted_out") or relation.get("relationship_state") in {"do_not_contact", "cooldown"}:
        return "relationship_cooldown"
    if _successful_recent_contact(email):
        return "recent_successful_contact_window"
    score, _ = outbound_engine._score(STATE, account)
    if score < outbound_engine.MIN_SCORE:
        return "below_outbound_score"
    return None


def probe() -> Dict[str, Any]:
    load_state()
    accounts = [x for x in STATE.get("candidate_accounts", []) or [] if str(x.get("type") or "") in {"buyer", "supplier"}]
    reason_counts: Counter[str] = Counter()
    rows = []
    eligible = 0
    for account in accounts:
        reason = _reason(account)
        if reason is None:
            eligible += 1
        else:
            reason_counts[reason] += 1
        score, _ = outbound_engine._score(STATE, account)
        email = str(account.get("commercial_email") or "").strip().lower()
        recent = []
        if email:
            recent = [
                {
                    "source": x.get("source"),
                    "status": x.get("status"),
                    "quality": x.get("quality_gate"),
                    "reviewed": bool(x.get("communication_reviewed")),
                    "provider": x.get("email_provider"),
                    "error": str(x.get("last_error") or x.get("last_transport_error") or "")[:260],
                }
                for x in (STATE.get("outbox", []) or [])
                if str(x.get("contact") or "").strip().lower() == email
            ][-4:]
        rows.append({
            "id": account.get("id"),
            "type": account.get("type"),
            "verified_company": bool(account.get("verified_company")),
            "verified_contact": bool(account.get("verified_contact")),
            "email_domain": outbound_engine._email_domain(email),
            "official_domain": str(account.get("domain") or "").strip().lower().removeprefix("www."),
            "score": score,
            "reason": reason,
            "recent_outbox": recent,
        })
    outbox_counts = Counter(str(x.get("status") or "unknown") for x in STATE.get("outbox", []) or [])
    failed = [
        {
            "id": x.get("id"),
            "source": x.get("source"),
            "contact_verified": bool(x.get("contact_verified")),
            "quality": x.get("quality_gate"),
            "reviewed": bool(x.get("communication_reviewed")),
            "recovery_count": int(x.get("https_recovery_count") or x.get("https_retry_count") or 0),
            "provider": x.get("email_provider"),
            "error": str(x.get("last_error") or x.get("last_transport_error") or "")[:400],
        }
        for x in (STATE.get("outbox", []) or []) if x.get("status") == "send_failed"
    ]
    return {
        "version": VERSION,
        "commercial_accounts": len(accounts),
        "eligible": eligible,
        "reason_counts": dict(reason_counts),
        "accounts": rows,
        "outbox_status": dict(outbox_counts),
        "failed_messages": failed,
    }


print({"external_market_probe": probe()}, flush=True)
