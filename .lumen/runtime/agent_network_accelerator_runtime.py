from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import agent_network_runtime as _base


VERSION = "1.0-a2a-discovery-accelerator"
REPROBE_AFTER_HOURS = 72


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def _eligible_again(probed_row: Any) -> bool:
    if not isinstance(probed_row, dict):
        return True
    status = str(probed_row.get("status") or "")
    # Successful discovery should not be repeatedly probed. Failed/not-found domains
    # may become A2A-capable later, so allow a bounded refresh after 72 hours.
    if status == "agent_card_found":
        return False
    ts = _parse_ts(probed_row.get("ts"))
    if ts is None:
        return True
    return (_utcnow() - ts).total_seconds() >= REPROBE_AFTER_HOURS * 3600


def _account_domain(account: Dict[str, Any]) -> str:
    for value in (
        account.get("official_domain"),
        account.get("domain"),
        account.get("email_domain"),
        account.get("website"),
        account.get("source_url"),
    ):
        domain = _base._domain(value)
        if domain:
            return domain
    return ""


def _candidate_domains_accelerated(
    state: Dict[str, Any], probed: Dict[str, Any]
) -> List[Tuple[str, Dict[str, Any]]]:
    rows: List[Tuple[str, Dict[str, Any], float]] = []
    seen: set[str] = set()

    for account in state.get("candidate_accounts", []) or []:
        if not isinstance(account, dict):
            continue
        if account.get("type") != "supplier" or not account.get("verified_company"):
            continue

        domain = _account_domain(account)
        if not domain or domain in seen:
            continue
        if domain in probed and not _eligible_again(probed.get(domain)):
            continue

        seen.add(domain)
        try:
            score = float(account.get("score") or account.get("outbound_score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0

        # Prefer suppliers whose company and commercial contact are already verified,
        # then use the existing account score. This changes selection quality only;
        # the base runtime still enforces its original per-cycle probe/handshake caps.
        contact_bonus = 25.0 if account.get("verified_contact") else 0.0
        official_bonus = 10.0 if account.get("official_domain") else 0.0
        rows.append((domain, account, score + contact_bonus + official_bonus))

    rows.sort(key=lambda row: row[2], reverse=True)
    return [(domain, account) for domain, account, _ in rows[: _base.MAX_PROBES_PER_TICK]]


# Monkey-patch only the candidate selector used by agent_network_tick. Network caps,
# SSRF protections, auth/payment blocks and binding-action guardrails remain unchanged.
_base._candidate_domains = _candidate_domains_accelerated
_base.REGISTRY_QUERIES = (
    "industrial procurement",
    "B2B sourcing",
    "industrial supplier",
    "RFQ procurement",
    "manufacturing sourcing",
    "supply chain logistics",
    "buyer procurement",
    "supplier discovery",
    "global trade sourcing",
)

print({
    "agent_network_accelerator_runtime": {
        "version": VERSION,
        "status": "active",
        "official_domain_enabled": True,
        "email_domain_fallback_enabled": True,
        "verified_contact_priority": True,
        "reprobe_after_hours": REPROBE_AFTER_HOURS,
        "probe_cap_changed": False,
        "handshake_cap_changed": False,
        "binding_authority_changed": False,
        "paid_spend_authority_changed": False,
    }
}, flush=True)
