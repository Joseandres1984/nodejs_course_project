from __future__ import annotations

import ipaddress
import os
import re
import socket
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from html import unescape
from typing import Any, Dict, List, Tuple

from autonomy_governor import record_decision

MAX_ACCOUNTS_PER_TICK = max(1, min(5, int(os.getenv("LUMEN_CONTACT_ACCOUNTS_PER_TICK", "3"))))
MAX_PAGES_PER_ACCOUNT = max(3, min(10, int(os.getenv("LUMEN_CONTACT_MAX_PAGES", "6"))))
MAX_RESEARCH_ATTEMPTS = max(1, min(5, int(os.getenv("LUMEN_CONTACT_MAX_ATTEMPTS", "3"))))
RETRY_NO_EMAIL_HOURS = max(6, min(168, int(os.getenv("LUMEN_CONTACT_RETRY_HOURS", "12"))))
MAX_BYTES = 250_000
USER_AGENT = "LUMEN-B2B/1.1 corporate-contact-research"

GENERIC_LOCALPARTS = {
    "info", "contacto", "contact", "ventas", "sales", "comercial", "commercial",
    "compras", "purchasing", "procurement", "proveedores", "suppliers", "cotizaciones",
    "administracion", "administración", "atencion", "atencioncliente", "servicioalcliente",
}

CONTACT_HINTS = (
    "contacto", "contact", "ventas", "sales", "comercial", "compras", "proveedores",
    "supplier", "procurement", "cotizacion", "cotización",
)

COMMON_CONTACT_PATHS = (
    "/contacto", "/contact", "/ventas", "/sales", "/comercial", "/compras",
    "/proveedores", "/suppliers", "/procurement",
)

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
HREF_RE = re.compile(r"href=[\"']([^\"']+)[\"']", re.I)


def utcnow_dt() -> datetime:
    return datetime.now(timezone.utc)


def utcnow() -> str:
    return utcnow_dt().strftime("%Y-%m-%d %H:%M:%S UTC")


def _parse(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


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
        if href.lower().startswith("mailto:"):
            continue
        absolute = urllib.parse.urljoin(base_url, unescape(href))
        low = absolute.lower()
        if any(hint in low for hint in CONTACT_HINTS) and _safe_url(absolute, official_domain):
            urls.append(absolute)
    return list(dict.fromkeys(urls))


def _common_pages(start: str, official_domain: str) -> List[str]:
    parsed = urllib.parse.urlparse(start)
    root = f"{parsed.scheme or 'https'}://{parsed.netloc or official_domain}"
    rows: List[str] = []
    for path in COMMON_CONTACT_PATHS:
        url = urllib.parse.urljoin(root.rstrip("/") + "/", path.lstrip("/"))
        if _safe_url(url, official_domain):
            rows.append(url)
    return rows


def _allowed_email(email: str, official_domain: str) -> bool:
    value = email.strip().lower().strip(".,;:()[]<>")
    if "@" not in value:
        return False
    local, domain = value.rsplit("@", 1)
    domain = domain.lower().removeprefix("www.")
    if domain != official_domain and not domain.endswith("." + official_domain):
        return False
    normalized_local = local.replace("-", "").replace("_", "").replace(".", "")
    return local in GENERIC_LOCALPARTS or normalized_local in GENERIC_LOCALPARTS


def _generic_emails(html: str, official_domain: str) -> List[str]:
    found: List[str] = []
    decoded = unescape(html or "")
    for email in EMAIL_RE.findall(decoded):
        email = email.strip().lower().strip(".,;:()[]<>")
        if _allowed_email(email, official_domain):
            found.append(email)
    for href in HREF_RE.findall(decoded):
        if not href.lower().startswith("mailto:"):
            continue
        value = urllib.parse.unquote(href.split(":", 1)[1].split("?", 1)[0]).strip().lower()
        for candidate in re.split(r"[,;]", value):
            candidate = candidate.strip()
            if _allowed_email(candidate, official_domain):
                found.append(candidate)
    return list(dict.fromkeys(found))


def _contact_form_url(html: str, base_url: str, official_domain: str) -> str | None:
    for href in HREF_RE.findall(html or ""):
        if href.lower().startswith("mailto:"):
            continue
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
    pages.extend(_common_pages(start, domain))
    pages = list(dict.fromkeys(pages))
    visited: List[str] = []
    evidence: List[str] = []
    emails: List[str] = []
    form_url: str | None = str(account.get("commercial_form_url") or "").strip() or None

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
    account["contact_research_attempts"] = int(account.get("contact_research_attempts") or 0) + 1
    account["commercial_contact_evidence"] = list(dict.fromkeys((account.get("commercial_contact_evidence") or []) + evidence))[:8]
    if best_email:
        account["commercial_email"] = best_email
    account["commercial_form_url"] = form_url
    account["commercial_channel_verified"] = bool(account.get("commercial_email") or form_url)
    account["verified_contact"] = bool(account.get("commercial_email"))
    account["contact_channel"] = "email" if account.get("commercial_email") else "web_form" if form_url else None
    account["contact_source_url"] = evidence[0] if evidence else account.get("contact_source_url")
    account["contact_policy"] = "public_corporate_channels_only"
    account["contact_research_last_result"] = "email_verified" if account.get("commercial_email") else "form_verified" if form_url else "no_channel"
    account["next_action"] = (
        "Usar el email corporativo público verificado cuando el caso comercial esté suficientemente calificado"
        if account.get("commercial_email")
        else "Conservar formulario corporativo y reintentar búsqueda de email público de rol dentro del límite de investigación"
        if form_url
        else "Reintentar investigación pública dentro del límite; no inferir direcciones personales"
    )
    return {
        "researched": True,
        "email_verified": bool(account.get("commercial_email")),
        "form_verified": bool(form_url),
        "pages": len(evidence),
        "attempt": int(account.get("contact_research_attempts") or 0),
    }


def _retry_due(account: Dict[str, Any]) -> bool:
    if not account.get("verified_company") or account.get("verified_contact") or account.get("commercial_email"):
        return False
    attempts = int(account.get("contact_research_attempts") or 0)
    if attempts >= MAX_RESEARCH_ATTEMPTS:
        return False
    researched_at = _parse(account.get("commercial_contact_researched_at"))
    if not researched_at:
        return True
    return utcnow_dt() - researched_at >= timedelta(hours=RETRY_NO_EMAIL_HOURS)


def contact_tick(state: Dict[str, Any]) -> Dict[str, int]:
    accounts = state.setdefault("candidate_accounts", [])
    fresh = [x for x in accounts if x.get("verified_company") and not x.get("commercial_contact_researched_at")]
    retries = [x for x in accounts if _retry_due(x) and x not in fresh]
    retries.sort(key=lambda x: (int(x.get("contact_research_attempts") or 0), str(x.get("commercial_contact_researched_at") or "")))
    queue = (fresh + retries)[:MAX_ACCOUNTS_PER_TICK]
    stats = {
        "attempted": 0,
        "fresh": 0,
        "retries": 0,
        "email_verified": 0,
        "form_verified": 0,
        "no_channel": 0,
        "errors": 0,
    }

    fresh_ids = {id(x) for x in fresh}
    for account in queue:
        stats["attempted"] += 1
        if id(account) in fresh_ids:
            stats["fresh"] += 1
        else:
            stats["retries"] += 1
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
                decision="corporate_email_verified" if account.get("commercial_email") else "corporate_form_verified" if account.get("commercial_form_url") else "no_public_channel_verified",
                reason="Se investigaron únicamente canales corporativos públicos del dominio oficial, incluyendo páginas de contacto y mailto visibles; no se generaron ni infirieron direcciones personales.",
                action="research_public_corporate_contact",
                confidence=0.97 if account.get("commercial_email") else 0.78 if account.get("commercial_form_url") else 0.45,
                evidence_refs=list(account.get("commercial_contact_evidence") or [])[:8],
            )
        except Exception as exc:
            account["commercial_contact_researched_at"] = utcnow()
            account["contact_research_attempts"] = int(account.get("contact_research_attempts") or 0) + 1
            account["commercial_contact_error"] = str(exc)[:160]
            stats["errors"] += 1

    state["contact_intelligence_stats"] = {
        **stats,
        "max_pages_per_account": MAX_PAGES_PER_ACCOUNT,
        "max_attempts": MAX_RESEARCH_ATTEMPTS,
        "retry_hours": RETRY_NO_EMAIL_HOURS,
        "policy": "public_role_emails_only_no_personal_email_inference",
        "updated_at": utcnow(),
    }
    if stats["attempted"]:
        _log(state, f"Contact Intelligence revisó {stats['attempted']} empresas ({stats['retries']} reintentos): {stats['email_verified']} emails corporativos y {stats['form_verified']} formularios verificados.")
    return stats
