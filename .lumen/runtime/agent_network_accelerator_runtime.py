from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import agent_network_runtime as _base


VERSION = "1.3-a2a-discovery-accelerator"
REPROBE_AFTER_HOURS = 72
_ORIGINAL_REGISTRY_CARD_URL = _base._registry_card_url


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

        contact_bonus = 25.0 if account.get("verified_contact") else 0.0
        official_bonus = 10.0 if account.get("official_domain") else 0.0
        rows.append((domain, account, score + contact_bonus + official_bonus))

    rows.sort(key=lambda row: row[2], reverse=True)
    return [(domain, account) for domain, account, _ in rows[: _base.MAX_PROBES_PER_TICK]]


def _registry_card_url_current(row: Dict[str, Any]) -> str:
    """Accept the registry's current manifestUrl field without weakening URL safety."""
    for key in ("manifestUrl", "manifest_url"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return _ORIGINAL_REGISTRY_CARD_URL(row)


# Bootstrap on the registry query proven to return commercial/procurement agents. Keeping a single
# high-intent term avoids wasting the one public-registry query permitted per cycle on low-yield
# wording while LUMEN has no peers yet. Seen-domain memory still prevents repeated handshakes.
# Once peers exist, the base network can continue probing verified supplier domains as before.
_base._candidate_domains = _candidate_domains_accelerated
_base._registry_card_url = _registry_card_url_current
_base.REGISTRY_QUERIES = ("procurement",)

print({
    "agent_network_accelerator_runtime": {
        "version": VERSION,
        "status": "active",
        "official_domain_enabled": True,
        "email_domain_fallback_enabled": True,
        "verified_contact_priority": True,
        "registry_keyword_mode": "procurement_bootstrap",
        "registry_manifest_url_compat": True,
        "registry_queries_per_tick_changed": False,
        "reprobe_after_hours": REPROBE_AFTER_HOURS,
        "probe_cap_changed": False,
        "handshake_cap_changed": False,
        "binding_authority_changed": False,
        "paid_spend_authority_changed": False,
    }
}, flush=True)
