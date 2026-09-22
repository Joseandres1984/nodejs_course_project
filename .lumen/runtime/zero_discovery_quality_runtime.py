from __future__ import annotations

"""Quality hardening for LUMEN Zero public discovery.

Public RSS search is intentionally broad and can return forums, classifieds and marketplaces.
Those pages may be useful as weak market evidence, but they must never become counterparties,
professional cases or partner stores merely because a search result has a URL.

This adapter:
- filters obvious non-corporate/community/classified sources before new research leads are stored;
- requires a research lead to finish Lead Intelligence with Tier A/B before Deep Work can open a case;
- quarantines previously-created Deep Work cases and partner stores whose source is disqualified;
- leaves candidate-account verification, contact verification, outbound caps and all authority gates intact.

No search cap is increased and no paid provider is added.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List
import urllib.parse

import external_exploration_runtime
import lead_intelligence
import partner_network
import professional_casework
import scout_connector


VERSION = "1.0-zero-public-source-quality"

# These are source classes, not competitors or arbitrary companies: marketplaces/classifieds,
# community forums and general discussion surfaces are not valid corporate counterparties.
_BLOCKED_EXACT_OR_SUFFIX = {
    "craigslist.org",
    "ebay.com",
    "ebay.com.ar",
    "ebay.co.uk",
    "bikeforums.net",
    "reddit.com",
    "quora.com",
}
_NOISE_TEXT = (
    "craigslist",
    "ebay",
    "bike forum",
    "bikeforums",
    "reddit",
    "forum thread",
    "discussion forum",
    "classifieds",
    "clasificados",
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _host(url: Any) -> str:
    try:
        return (urllib.parse.urlparse(str(url or "")).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _blocked_host(host: str) -> bool:
    h = str(host or "").lower().removeprefix("www.")
    if not h:
        return False
    if any(h == item or h.endswith("." + item) for item in _BLOCKED_EXACT_OR_SUFFIX):
        return True
    # Cover country-specific eBay/Craigslist hosts without maintaining an endless TLD list.
    return h.startswith("ebay.") or ".ebay." in h or h.startswith("craigslist.") or ".craigslist." in h


def _noise_result(item: Dict[str, Any]) -> bool:
    url = str(item.get("url") or item.get("source_url") or "")
    if _blocked_host(_host(url)):
        return True
    text = " ".join(
        str(item.get(key) or "") for key in ("title", "name_hint", "snippet", "source_title")
    ).lower()
    return any(token in text for token in _NOISE_TEXT)


def _qualified_research_lead(lead: Dict[str, Any]) -> bool:
    if not lead.get("qualified_at"):
        return False
    tier = str(lead.get("tier") or "").upper()
    status = str(lead.get("qualification_status") or lead.get("status") or "").lower()
    if tier not in {"A", "B"}:
        return False
    if status in {"rejected_noise", "duplicate", "low_priority"}:
        return False
    if _noise_result(lead):
        return False
    domain = str(lead.get("domain") or "").lower().removeprefix("www.") or _host(lead.get("url"))
    return bool(domain and not _blocked_host(domain))


# Strengthen all existing module-level host deny lists as an additional defense-in-depth layer.
lead_intelligence.LOW_QUALITY_HOST_HINTS.update(_BLOCKED_EXACT_OR_SUFFIX)
professional_casework.LOW_VALUE_HOSTS.update(_BLOCKED_EXACT_OR_SUFFIX)
partner_network.LOW_VALUE_HOSTS.update(_BLOCKED_EXACT_OR_SUFFIX)

# Make future public-search queries less likely to return the known noisy source classes.
for token in (" -craigslist", " -ebay", " -reddit", " -foro", " -forum"):
    if token.strip() not in str(external_exploration_runtime.NEGATIVE):
        external_exploration_runtime.NEGATIVE += token


# External exploration already owns scout_connector._store_results at this point. Wrap that function
# instead of replacing its portfolio/dedupe logic.
_original_store_results = scout_connector._store_results


def _quality_store_results(
    state: Dict[str, Any], query: str, lead_type: str, category: str, results: List[Dict[str, str]]
) -> int:
    filtered = [item for item in (results or []) if not _noise_result(item)]
    report = state.setdefault("zero_discovery_quality", {})
    report["search_results_seen"] = int(report.get("search_results_seen") or 0) + len(results or [])
    report["search_results_rejected"] = int(report.get("search_results_rejected") or 0) + max(0, len(results or []) - len(filtered))
    report["version"] = VERSION
    report["updated_at"] = _utcnow()
    return _original_store_results(state, query, lead_type, category, filtered)


scout_connector._store_results = _quality_store_results


# Deep Work may use candidate accounts immediately, but raw research leads must first pass Lead
# Intelligence. This closes the old race where casework consumed a result before qualification.
_original_eligible_sources = professional_casework._eligible_sources
_original_casework_tick = professional_casework.professional_casework_tick


def _quality_eligible_sources(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = list(_original_eligible_sources(state) or [])
    out: List[Dict[str, Any]] = []
    for row in rows:
        if row.get("source_kind") != "research_lead":
            out.append(row)
            continue
        source = dict(row.get("source") or {})
        if _qualified_research_lead(source):
            out.append(row)
    return out


def _quarantine_bad_cases(state: Dict[str, Any]) -> int:
    leads = {str(x.get("id") or ""): x for x in state.get("research_leads", []) or []}
    quarantined = 0
    for case in state.get("professional_cases", []) or []:
        if case.get("source_kind") != "research_lead":
            continue
        if case.get("status") not in {"active", "waiting_budget", "ready_for_handoff"}:
            continue
        lead = leads.get(str(case.get("source_id") or ""), {})
        if lead and _qualified_research_lead(lead):
            continue
        case["status"] = "parked"
        case["zero_quality_quarantined"] = True
        case["quarantine_reason"] = "research_source_not_corporate_qualified"
        case["next_action"] = "Fuente descartada por Quality Gate; no usar como contraparte"
        case["quarantined_at"] = _utcnow()
        quarantined += 1
    return quarantined


def _quality_casework_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    quarantined = _quarantine_bad_cases(state)
    report = dict(_original_casework_tick(state) or {})
    report["zero_quality_version"] = VERSION
    report["sources_quarantined_this_tick"] = quarantined
    state["professional_casework"] = report
    return report


professional_casework._eligible_sources = _quality_eligible_sources
professional_casework.professional_casework_tick = _quality_casework_tick


# Partner Network historically consumed every supplier research result. Feed it only supplier leads
# that have already passed Lead Intelligence, and move previously-created noisy stores to a separate
# audit quarantine rather than deleting history.
_original_partner_sync = partner_network._sync_existing_evidence
_original_partner_tick = partner_network.partner_network_tick


def _quality_partner_sync(state: Dict[str, Any]) -> int:
    original_leads = state.get("research_leads", []) or []
    state["research_leads"] = [
        lead for lead in original_leads
        if str(lead.get("type") or "") != "supplier" or _qualified_research_lead(lead)
    ]
    try:
        return int(_original_partner_sync(state) or 0)
    finally:
        state["research_leads"] = original_leads


def _quarantine_partner_stores(state: Dict[str, Any]) -> int:
    active: List[Dict[str, Any]] = []
    quarantine = state.setdefault("partner_store_quarantine", [])
    known_quarantine = {str(x.get("id") or x.get("domain") or "") for x in quarantine}
    moved = 0
    for store in state.get("partner_stores", []) or []:
        domain = str(store.get("domain") or "").lower().removeprefix("www.")
        urls = list(store.get("source_urls", []) or [])
        noisy = _blocked_host(domain) or any(_blocked_host(_host(url)) for url in urls)
        noisy = noisy or any(any(token in str(store.get("name") or "").lower() for token in _NOISE_TEXT) for _ in [0])
        if not noisy:
            active.append(store)
            continue
        row = dict(store)
        row["commercial_status"] = "quarantined_noncorporate_source"
        row["zero_quality_quarantined"] = True
        row["quarantine_reason"] = "marketplace_classified_or_community_source"
        row["quarantined_at"] = _utcnow()
        key = str(row.get("id") or row.get("domain") or "")
        if key not in known_quarantine:
            quarantine.append(row)
            known_quarantine.add(key)
        moved += 1
    state["partner_stores"] = active
    state["partner_store_quarantine"] = quarantine[-500:]
    return moved


def _quality_partner_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    moved = _quarantine_partner_stores(state)
    report = dict(_original_partner_tick(state) or {})
    report["zero_quality_version"] = VERSION
    report["stores_quarantined_this_tick"] = moved
    report["stores_quarantined_total"] = len(state.get("partner_store_quarantine", []) or [])
    state["partner_network"] = report
    return report


partner_network._sync_existing_evidence = _quality_partner_sync
partner_network.partner_network_tick = _quality_partner_tick

print(
    {
        "zero_discovery_quality_runtime": {
            "status": "active",
            "version": VERSION,
            "raw_research_to_casework": "blocked_until_tier_a_or_b",
            "community_marketplace_counterparties": "quarantined",
            "verification_gates_relaxed": False,
            "search_cap_changed": False,
            "paid_search": False,
        }
    },
    flush=True,
)
