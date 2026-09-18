from __future__ import annotations

from typing import Any, Dict

import intelligence_revenue_runtime as intelligence


VERSION = "1.0-intelligence-commercial-quality-gate"
_ORIGINAL_ELIGIBLE = intelligence._eligible_candidate

FREE_MAIL_DOMAINS = {
    "gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "icloud.com", "live.com", "proton.me", "protonmail.com"
}

NOISE_DOMAINS = {
    # Search/social/content platforms: useful as research sources, not acquisition targets here.
    "google.com", "tiktok.com", "facebook.com", "instagram.com", "youtube.com", "reddit.com",
    "wordpress.com", "wixsite.com", "webnode.com.ar", "shutterstock.com", "etsy.com",
    # Job boards / recruiting aggregators found by public-web research.
    "glassdoor.com", "glassdoor.com.ar", "jooble.org", "jobsora.com", "bumeran.com.ar",
    "zonajobs.com.ar", "trabajo.org", "opcionempleo.com.ar", "bebee.com",
    # News / editorial domains that were entering the commercial corpus as research evidence.
    "infobae.com", "lanacion.com.ar", "forbesargentina.com", "iprofesional.com",
    # Market-research/report sellers: valuable evidence sources, but excluded from this product lane.
    "mordorintelligence.com", "mordorintelligence.ar", "databridgemarketresearch.com",
    "gminsights.com", "theinsightpartners.com", "futuremarketreport.com", "reportprime.com",
    "sphericalinsights.com", "indexbox.io", "fortunebusinessinsights.com",
    # Generic public information / registry surfaces are research sources, not sales targets.
    "infoleg.gob.ar", "boletinoficial.gov.ar", "proquest.com", "baidu.com",
}


def _domain(value: Any) -> str:
    text = str(value or "").strip().lower()
    if "@" in text:
        text = text.rsplit("@", 1)[-1]
    text = text.split("/", 1)[0].split(":", 1)[0].strip(". ")
    if text.startswith("www."):
        text = text[4:]
    return text


def _same_domain(email_domain: str, official_domain: str) -> bool:
    if not email_domain or not official_domain:
        return False
    return email_domain == official_domain or email_domain.endswith("." + official_domain) or official_domain.endswith("." + email_domain)


def _quality_eligible(account: Dict[str, Any]) -> bool:
    if not _ORIGINAL_ELIGIBLE(account):
        return False
    # Revenue acquisition should use a contact that LUMEN has actually verified, not merely a scraped address.
    if not account.get("verified_contact"):
        return False
    email_domain = _domain(account.get("commercial_email"))
    official_domain = _domain(account.get("official_domain") or account.get("domain"))
    if not email_domain or email_domain in FREE_MAIL_DOMAINS:
        return False
    if not _same_domain(email_domain, official_domain):
        return False
    if official_domain in NOISE_DOMAINS or email_domain in NOISE_DOMAINS:
        return False
    return True


if not getattr(intelligence, "_lumen_intelligence_quality_gate_installed", False):
    intelligence._eligible_candidate = _quality_eligible
    intelligence._lumen_intelligence_quality_gate_installed = True

print({
    "intelligence_quality_gate": {
        "version": VERSION,
        "status": "active",
        "verified_contact_required": True,
        "corporate_domain_match_required": True,
        "free_mail_blocked": True,
        "research_noise_domains_blocked": len(NOISE_DOMAINS),
        "paid_spend": False,
    }
}, flush=True)
