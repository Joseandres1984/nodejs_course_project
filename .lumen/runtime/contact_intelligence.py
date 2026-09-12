from __future__ import annotations

import ipaddress
import re
import socket
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html import unescape
from typing import Any, Dict, List, Tuple

from autonomy_governor import record_decision

MAX_ACCOUNTS_PER_TICK = 2
MAX_PAGES_PER_ACCOUNT = 3
MAX_BYTES = 250_000
USER_AGENT = "LUMEN-B2B/1.0 corporate-contact-research"

GENERIC_LOCALPARTS = {
    "info", "contacto", "contact", "ventas", "sales", "comercial", "commercial",
    "compras", "purchasing", "procurement", "proveedores", "suppliers", "cotizaciones",
    "administracion", "administración", "atencion", "atencioncliente", "servicioalcliente",
}

CONTACT_HINTS = (
    "contacto", "contact", "ventas", "sales", "comercial", "compras", "proveedores",
    "supplier", "procurement", "cotizacion", "cotización",
)

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
HREF_RE = re.compile(r"href=[\"']([^\"']+)[\"']", re.I)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _log(state: Dict[str, Any], message: str) -> None:
    state.setdefault("activity", []).insert(0, {"ts": utcnow(), "msg": message})
    state["activity"] = state["activity"][:100]


def _host(url: str) -> str:
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _is_public_host(host: str) -> bool:
    if not host or host in {"localhost", "localhost.localdomain"}:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return False
    for info in infos:
        raw = info[4][0]
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            return False
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False
    return True


def _safe_url(url: str, official_domain: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        return False
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if not host or not official_domain:
        return False
    if not (host == official_domain or host.endswith("." + official_domain)):
        return False
    return _is_public_host(host)


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, official_domain: str):
        super().__init__()
        self.official_domain = official_domain

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urljoin(req.full_url, newurl)
        if not _safe_url(target, self.official_domain):
            raise urllib.error.HTTPError(target, code, "Unsafe redirect blocked", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, target)


def _fetch(url: str, official_domain: str) -> Tuple[str, str]:
    if not _safe_url(url, official_domain):
        raise ValueError("URL no permitida para investigación corporativa")
    opener = urllib.request.build_opener(_SafeRedirect(official_domain))
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    with opener.open(req, timeout=18) as resp:
        final_url = resp.geturl()
        if not _safe_url(final_url, official_domain):
            raise ValueError("Redirección fuera del dominio oficial")
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if "text/html" not in ctype and "application/xhtml+xml" not in ctype:
            return "", final_url
        return resp.read(MAX_BYTES).decode("utf-8", errors="replace"), final_url


def _candidate_pages(html: str, base_url: str, official_domain: str) -> List[str]:
    urls: List[str] = []
    for href in HREF_RE.findall(html or ""):
        absolute = urllib.parse.urljoin(base_url, unescape(href))
        low = absolute.lower()
        if any(hint in low for hint in CONTACT_HINTS) and _safe_url(absolute, official_domain):
            urls.append(absolute)
    return list(dict.fromkeys(urls))[: MAX_PAGES_PER_ACCOUNT - 1]


def _generic_emails(html: str, official_domain: str) -> List[str]:
    found: List[str] = []
    for email in EMAIL_RE.findall(unescape(html or "")):
        email = email.strip().lower().strip(".,;:()[]<>")
        if "@" not in email:
            continue
        local, domain = email.rsplit("@", 1)
        domain = domain.lower().removeprefix("www.")
        if domain != official_domain and not domain.endswith("." + official_domain):
            continue
        normalized_local = local.replace("-", "").replace("_", "").replace(".", "")
        if local in GENERIC_LOCALPARTS or normalized_local in GENERIC_LOCALPARTS:
            found.append(email)
    return list(dict.fromkeys(found))


def _contact_form_url(html: str, base_url: str, official_domain: str) -> str | None:
    for href in HREF_RE.findall(html or ""):
        absolute = urllib.parse.urljoin(base_url, unescape(href))
        if any(hint in absolute.lower() for hint in ("contacto", "contact")) and _safe_url(absolute, official_domain):
            return absolute
    return None


def research_account(account: Dict[str, Any]) -> Dict[str, Any]:
    domain = str(account.get("domain") or "").strip().lower().removeprefix("www.")
    start = str(account.get("official_url") or account.get("source_url") or "").strip()
    if not domain or not start:
        return {"researched": False, "reason": "missing_official_domain"}

    pages: List[str] = [start]
    visited: List[str] = []
    evidence: List[str] = []
    emails: List[str] = []
    form_url: str | None = None

    index = 0
    while index < len(pages) and len(visited) < MAX_PAGES_PER_ACCOUNT:
        url = pages[index]
        index += 1
        if url in visited:
            continue
        try:
            html, final_url = _fetch(url, domain)
        except Exception:
            continue
        visited.append(final_url)
        if not html:
            continue
        evidence.append(final_url)
        emails.extend(_generic_emails(html, domain))
        if not form_url:
            form_url = _contact_form_url(html, final_url, domain)
        for candidate in _candidate_pages(html, final_url, domain):
            if candidate not in pages:
                pages.append(candidate)

    emails = list(dict.fromkeys(emails))
    best_email = emails[0] if emails else None
    account["commercial_contact_researched_at"] = utcnow()
    account["commercial_contact_evidence"] = evidence[:5]
    account["commercial_email"] = best_email
    account["commercial_form_url"] = form_url
    account["commercial_channel_verified"] = bool(best_email or form_url)
    account["verified_contact"] = bool(best_email)
    account["contact_channel"] = "email" if best_email else "web_form" if form_url else None
    account["contact_source_url"] = evidence[0] if evidence else None
    account["contact_policy"] = "public_corporate_channels_only"
    account["next_action"] = (
        "Usar el canal corporativo verificado cuando el caso comercial esté suficientemente calificado"
        if account["commercial_channel_verified"]
        else "Buscar un canal corporativo público adicional; no inferir direcciones personales"
    )
    return {"researched": True, "email_verified": bool(best_email), "form_verified": bool(form_url), "pages": len(evidence)}


def contact_tick(state: Dict[str, Any]) -> Dict[str, int]:
    accounts = state.setdefault("candidate_accounts", [])
    queue = [
        x for x in accounts
        if x.get("verified_company") and not x.get("commercial_contact_researched_at")
    ][:MAX_ACCOUNTS_PER_TICK]
    stats = {"attempted": 0, "email_verified": 0, "form_verified": 0, "no_channel": 0, "errors": 0}

    for account in queue:
        stats["attempted"] += 1
        try:
            result = research_account(account)
            if result.get("email_verified"):
                stats["email_verified"] += 1
            elif result.get("form_verified"):
                stats["form_verified"] += 1
            else:
                stats["no_channel"] += 1
            record_decision(
                state,
                engine="Contact Intelligence",
                object_type="account",
                object_id=str(account.get("id") or ""),
                decision="corporate_channel_verified" if account.get("commercial_channel_verified") else "no_public_channel_verified",
                reason="Se investigaron exclusivamente canales corporativos públicos del dominio oficial; no se recolectaron ni infirieron contactos personales.",
                action="research_public_corporate_contact",
                confidence=0.95 if account.get("commercial_email") else 0.75 if account.get("commercial_form_url") else 0.45,
                evidence_refs=list(account.get("commercial_contact_evidence") or [])[:5],
            )
        except Exception as exc:
            account["commercial_contact_researched_at"] = utcnow()
            account["commercial_contact_error"] = str(exc)[:160]
            stats["errors"] += 1

    state["contact_intelligence_stats"] = {**stats, "updated_at": utcnow()}
    if stats["attempted"]:
        _log(state, f"Contact Intelligence revisó {stats['attempted']} empresas: {stats['email_verified']} emails corporativos y {stats['form_verified']} formularios verificados.")
    return stats
