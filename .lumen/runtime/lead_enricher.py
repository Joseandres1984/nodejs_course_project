from __future__ import annotations

import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html import unescape
from typing import Any, Dict, List

MAX_ENRICH_PER_TICK = max(1, min(5, int(os.getenv("LUMEN_ENRICH_MAX_LEADS", "2"))))
MAX_BYTES = 450_000
USER_AGENT = "LUMEN-B2B/1.0 (+business-research; public-web-only)"

BLOCKED_HOSTS = {
    "linkedin.com", "www.linkedin.com", "facebook.com", "www.facebook.com",
    "instagram.com", "www.instagram.com", "youtube.com", "www.youtube.com",
    "x.com", "twitter.com", "www.twitter.com", "reddit.com", "www.reddit.com",
}
ROLE_PREFIXES = {
    "info", "ventas", "venta", "comercial", "contacto", "contact",
    "compras", "compras1", "sales", "cotizaciones", "presupuestos",
    "administracion", "atencion", "clientes", "customer", "office",
}
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
HREF_RE = re.compile(r"href=[\"']([^\"']+)[\"']", re.I)
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def status() -> Dict[str, Any]:
    return {"configured": True, "max_leads_per_tick": MAX_ENRICH_PER_TICK, "public_web_only": True}


def _log(state: Dict[str, Any], msg: str) -> None:
    state.setdefault("activity", []).insert(0, {"ts": utcnow(), "msg": msg})
    state["activity"] = state["activity"][:100]


def _host(url: str) -> str:
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _registrable_hint(host: str) -> str:
    parts = [p for p in host.lower().split(".") if p]
    if len(parts) <= 2:
        return host.lower()
    if parts[-2:] in (["com", "ar"], ["com", "br"], ["com", "mx"]):
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _fetch(url: str) -> tuple[str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    with urllib.request.urlopen(req, timeout=18) as resp:
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if "text/html" not in ctype and "application/xhtml+xml" not in ctype:
            return "", resp.geturl()
        raw = resp.read(MAX_BYTES)
        return raw.decode("utf-8", errors="replace"), resp.geturl()


def _text(html: str) -> str:
    text = TAG_RE.sub(" ", html)
    return WS_RE.sub(" ", unescape(text)).strip()


def _contact_candidates(html: str, base_url: str) -> List[str]:
    out: List[str] = []
    for href in HREF_RE.findall(html):
        lower = href.lower()
        if any(x in lower for x in ("contacto", "contact", "empresa", "nosotros", "about")):
            url = urllib.parse.urljoin(base_url, href)
            if url.startswith(("http://", "https://")) and _host(url) == _host(base_url) and url not in out:
                out.append(url)
        if len(out) >= 2:
            break
    return out


def _role_emails(html: str, host: str) -> List[str]:
    domain_hint = _registrable_hint(host)
    found: List[str] = []
    for email in EMAIL_RE.findall(html):
        email = email.lower().strip(".,;:()[]<>\"'")
        local, _, domain = email.partition("@")
        if not domain or _registrable_hint(domain) != domain_hint:
            continue
        if local.split("+")[0] not in ROLE_PREFIXES:
            continue
        if email not in found:
            found.append(email)
    return found[:5]


def _keyword_fit(category: str, text: str) -> float:
    words = [w.lower() for w in re.findall(r"[A-Za-zÁÉÍÓÚáéíóúÑñ0-9]+", category) if len(w) >= 4]
    if not words:
        return 0.0
    lower = text.lower()
    hits = sum(1 for w in words if w in lower)
    return hits / max(1, len(words))


def enrich_lead(lead: Dict[str, Any]) -> Dict[str, Any]:
    url = (lead.get("url") or "").strip()
    host = _host(url)
    if not url.startswith(("http://", "https://")) or not host or host in BLOCKED_HOSTS:
        lead.update({"enrichment_status": "skipped", "enrichment_reason": "unsupported_or_blocked_host", "enriched_at": utcnow()})
        return {"status": "skipped", "emails": 0}

    html, final_url = _fetch(url)
    if not html:
        lead.update({"enrichment_status": "review_required", "enrichment_reason": "non_html_or_empty", "enriched_at": utcnow()})
        return {"status": "review_required", "emails": 0}

    combined_html = html
    evidence_urls = [final_url]
    for contact_url in _contact_candidates(html, final_url)[:1]:
        try:
            contact_html, contact_final = _fetch(contact_url)
            if contact_html:
                combined_html += "\n" + contact_html
                evidence_urls.append(contact_final)
        except Exception:
            pass

    text = _text(combined_html)[:120_000]
    emails = _role_emails(combined_html, _host(final_url))
    fit = _keyword_fit(str(lead.get("category") or ""), text)
    confidence = min(0.85, 0.50 + (0.15 if text else 0) + min(0.10, fit * 0.10) + (0.10 if emails else 0))

    lead.update({
        "final_url": final_url,
        "domain": _host(final_url),
        "evidence_urls": evidence_urls[:3],
        "public_contact_candidates": emails,
        "category_evidence_score": round(fit, 2),
        "confidence": round(max(float(lead.get("confidence", 0.0)), confidence), 2),
        "enrichment_status": "evidence_collected",
        "status": "evidence_collected",
        "verified_company": False,
        "verified_contact": False,
        "enriched_at": utcnow(),
    })
    return {"status": "evidence_collected", "emails": len(emails)}


def enrich_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    leads = state.setdefault("research_leads", [])
    candidates = [x for x in leads if x.get("status") in {"research_required", "retry_enrichment"}][:MAX_ENRICH_PER_TICK]
    stats = {"attempted": 0, "enriched": 0, "emails_found": 0, "skipped": 0, "errors": 0}
    for lead in candidates:
        stats["attempted"] += 1
        try:
            result = enrich_lead(lead)
            if result["status"] == "evidence_collected":
                stats["enriched"] += 1
                stats["emails_found"] += int(result.get("emails", 0))
            else:
                stats["skipped"] += 1
        except Exception as exc:
            stats["errors"] += 1
            lead.update({"enrichment_status": "retry", "status": "retry_enrichment", "enrichment_error": str(exc)[:180], "enriched_at": utcnow()})
    if stats["attempted"]:
        _log(state, f"Lead Enricher investigó {stats['attempted']} leads: {stats['enriched']} con evidencia y {stats['emails_found']} contactos comerciales candidatos.")
    return stats
