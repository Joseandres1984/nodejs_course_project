"""Fair scheduler for company verification retries.

Keeps all existing company-verification truth gates unchanged. It only prevents
network/DNS retry cases from monopolizing the first MAX_PER_TICK slots forever:
new accounts are attempted first and retry-required accounts become eligible again
after a bounded cooldown.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import company_verifier

VERSION = "1.0-fair-verification-retries"
RETRY_HOURS = max(1, min(24, int(os.getenv("LUMEN_VERIFY_RETRY_HOURS", "6"))))
_ORIGINAL_TICK = company_verifier.verification_tick


def _parse_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _retry_due(account: Dict[str, Any], now: datetime) -> bool:
    attempted_at = _parse_utc(account.get("verified_at"))
    if attempted_at is None:
        return True
    return attempted_at <= now - timedelta(hours=RETRY_HOURS)


def verification_tick_fair(state: Dict[str, Any]) -> Dict[str, int]:
    accounts = state.setdefault("candidate_accounts", [])
    now = datetime.now(timezone.utc)

    fresh = []
    due_retries = []
    deferred_retries = []
    for account in accounts:
        is_retry = account.get("verification_status") == "retry_required"
        is_pending = account.get("status") == "verification_required"
        if is_retry:
            (due_retries if _retry_due(account, now) else deferred_retries).append(account)
        elif is_pending:
            fresh.append(account)

    # The original verifier owns evidence collection, scoring, decisions and all
    # state transitions. Give it only work that is currently due, with new
    # accounts first, so its existing MAX_PER_TICK cap remains authoritative.
    work = fresh + due_retries
    shadow = dict(state)
    shadow["candidate_accounts"] = work
    stats = dict(_ORIGINAL_TICK(shadow) or {})

    if "company_verification_stats" in shadow:
        state["company_verification_stats"] = dict(shadow["company_verification_stats"])
    stats["deferred_retry"] = len(deferred_retries)
    stats["fresh_pending"] = len(fresh)
    stats["due_retry"] = len(due_retries)
    state.setdefault("company_verification_stats", {}).update({
        "deferred_retry": len(deferred_retries),
        "fresh_pending": len(fresh),
        "due_retry": len(due_retries),
        "retry_cooldown_hours": RETRY_HOURS,
        "scheduler_version": VERSION,
    })
    return stats


company_verifier.verification_tick = verification_tick_fair
