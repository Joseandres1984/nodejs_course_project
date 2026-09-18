from __future__ import annotations

"""Candidate identity quality patch for LUMEN.

This runtime fixes two sources of wasted company-verification work without widening
commercial authority:
- preserve the registrable label for common multi-level country suffixes (for example
  example.com.co instead of the unusable com.co);
- keep obvious search/social/job/hosting source domains out of the company verification
  queue, and retire legacy pending candidates that point only at those sources.

No company is promoted or verified here. The original verifier remains the only authority
that can set verified_company=True.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Tuple, List
from urllib.parse import urlparse

import lead_intelligence

VERSION = "1.0-candidate-identity-quality"

# Common second-level namespace labels used under country-code TLDs. This intentionally
# uses a small deterministic heuristic rather than pretending to be a full public-suffix list.
MULTILEVEL_CC_LABELS = {
    "com", "net", "org", "edu", "gov", "gob", "mil", "co", "ac",
}

# These domains can be useful evidence sources, but they are not a corporate identity for
# the company-verification queue. Keep the list limited to unmistakable intermediaries.
NON_CORPORATE_SOURCE_HOSTS = {
    "google.com",
    "tiktok.com",
    "jooble.org",
    "jobsora.com",
    "opcionempleo.com.ar",
    "zonajobs.com.ar",
    "bumeran.com.ar",
    "glassdoor.com.ar",
    "shutterstock.com",
    "baidu.com",
    "etsy.com",
    "wordpress.com",
    "wixsite.com",
    "webnode.com.ar",
    "trafficmanager.net",
    "proquest.com",
    "calameo.com",
}

_ORIGINAL_SOURCE_QUALITY = lead_intelligence._source_quality
_ORIGINAL_QUALIFY_TICK = lead_intelligence.qualify_tick


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _host(url: Any) -> str:
    try:
        return (urlparse(str(url or "")).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _is_non_corporate_host(host: str) -> bool:
    host = str(host or "").lower().strip().removeprefix("www.")
    return any(host == item or host.endswith("." + item) for item in NON_CORPORATE_SOURCE_HOSTS)


def canonical_domain(host: str) -> str:
    host = str(host or "").lower().strip().strip(".").removeprefix("www.")
    parts = [part for part in host.split(".") if part]
    if len(parts) <= 2:
        return host

    # ccTLD with a conventional second-level namespace: company.com.ar,
    # company.com.co, company.com.mx, company.co.in, university.edu.co, etc.
    if len(parts[-1]) == 2 and parts[-2] in MULTILEVEL_CC_LABELS and len(parts) >= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _source_quality(url: str, title: str, snippet: str) -> Tuple[int, List[str]]:
    host = _host(url)
    if _is_non_corporate_host(host):
        return 0, ["Fuente intermediaria/no corporativa: no crear identidad empresarial desde este dominio"]
    return _ORIGINAL_SOURCE_QUALITY(url, title, snippet)


def _pending(account: Dict[str, Any]) -> bool:
    return (
        not bool(account.get("verified_company"))
        and (
            account.get("status") == "verification_required"
            or account.get("verification_status") == "retry_required"
        )
    )


def _repair_existing_candidates(state: Dict[str, Any]) -> Dict[str, int]:
    accounts = state.setdefault("candidate_accounts", [])
    repaired_domains = 0
    rejected_noise = 0
    duplicates_retired = 0

    # First repair legacy canonicalization only for accounts that have not passed verification.
    for account in accounts:
        if not _pending(account):
            continue
        source_host = _host(account.get("source_url"))
        if not source_host:
            continue
        repaired = canonical_domain(source_host)
        current = str(account.get("domain") or "").lower().strip()
        if repaired and repaired != current:
            account["domain"] = repaired
            account["candidate_key"] = "|".join([
                str(account.get("type") or ""),
                str(account.get("category") or "").lower(),
                repaired,
            ])
            account["domain_repaired_at"] = _now()
            account["domain_repair_version"] = VERSION
            repaired_domains += 1

        if _is_non_corporate_host(source_host):
            account.update({
                "status": "rejected_noise",
                "verification_status": "rejected_non_corporate_source",
                "verified_company": False,
                "next_action": "Descartado de verificación empresarial; conservar la fuente sólo como evidencia indirecta si corresponde",
                "identity_quality_reason": "source_domain_is_intermediary_not_company_identity",
                "identity_quality_updated_at": _now(),
            })
            rejected_noise += 1

    # Retire exact pending duplicates after domain repair. Verified accounts are never touched.
    seen: set[str] = set()
    for account in accounts:
        if not _pending(account):
            continue
        key = str(account.get("candidate_key") or "").strip()
        if not key:
            continue
        if key in seen:
            account.update({
                "status": "duplicate",
                "verification_status": "duplicate_candidate",
                "verified_company": False,
                "next_action": "Consolidar evidencia con la cuenta candidata principal",
                "identity_quality_reason": "duplicate_type_category_domain",
                "identity_quality_updated_at": _now(),
            })
            duplicates_retired += 1
        else:
            seen.add(key)

    report = {
        "repaired_domains": repaired_domains,
        "rejected_noise": rejected_noise,
        "duplicates_retired": duplicates_retired,
    }
    state["company_identity_quality"] = {
        "version": VERSION,
        "status": "active",
        **report,
        "updated_at": _now(),
        "verified_company_authority_changed": False,
    }
    return report


def qualify_tick_with_identity_quality(state: Dict[str, Any]) -> Dict[str, int]:
    # Repair legacy queue before adding fresh candidates, then run the original scorer,
    # then normalize any new country-suffix domains immediately.
    before = _repair_existing_candidates(state)
    result = dict(_ORIGINAL_QUALIFY_TICK(state) or {})
    after = _repair_existing_candidates(state)
    result["identity_domains_repaired"] = before["repaired_domains"] + after["repaired_domains"]
    result["identity_noise_rejected"] = before["rejected_noise"] + after["rejected_noise"]
    result["identity_duplicates_retired"] = before["duplicates_retired"] + after["duplicates_retired"]
    return result


# Install before worker.py captures qualify_tick.
lead_intelligence._canonical_domain = canonical_domain
lead_intelligence._source_quality = _source_quality
lead_intelligence.qualify_tick = qualify_tick_with_identity_quality

print({
    "company_identity_quality_runtime": {
        "version": VERSION,
        "status": "active",
        "multilevel_cc_domains": True,
        "obvious_non_corporate_sources_blocked": True,
        "verified_company_authority_changed": False,
    }
}, flush=True)
