from __future__ import annotations

import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html import unescape
from typing import Any, Dict, List

MAX_PER_TICK = max(1, min(4, int(os.getenv("LUMEN_VERIFY_MAX_ACCOUNTS", "2"))))
MAX_BYTES = 350_000
USER_AGENT = "LUMEN-B2B/1.0 business-research"
BUSINESS_TERMS = (
    "empresa", "compañía", "compania", "industria", "industrial", "productos", "servicios",
    "soluciones", "fabricante", "distribuidor", "proveedor", "ingenieria", "ingeniería",
    "mantenimiento", "ventas", "comercial", "clientes", "nosotros", "quienes somos",
)
SUPPLIER_TERMS = ("fabricante", "distribuidor", "distribuidora", "proveedor", "representante", "productos", "stock", "catalogo", "catálogo")
BUYER_CONTEXT_TERMS = ("planta", "producción", "produccion", "mantenimiento", "operaciones", "ingeniería", "ingenieria", "industria", "servicios")
STOPWORDS = {"para", "con", "una", "uno", "del", "las", "los", "por", "que", "and", "the", "argentina", "empresa"}
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
META_DESC_RE = re.compile(r"<meta[^>]+(?:name=[\"']description[\"'][^>]+content=[\"']([^\"']+)|content=[\"']([^\"']+)[\"'][^>]+name=[\"']description[\"'])", re.I | re.S)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _log(state: Dict[str, Any], msg: str) -> None:
    state.setdefault("activity", []).insert(0, {"ts": utcnow(), "msg": msg})
    state["activity"] = state["activity"][:100]


def _tokens(text: str) -> List[str]:
    return [x.lower() for x in re.findall(r"[A-Za-zÁÉÍÓÚáéíóúÑñ0-9]+", text or "") if len(x) >= 4 and x.lower() not in STOPWORDS]


def _clean_text(html: str) -> str:
    return WS_RE.sub(" ", unescape(TAG_RE.sub(" ", html))).strip()


def _fetch(url: str) -> tuple[str, str, int]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    with urllib.request.urlopen(req, timeout=18) as resp:
        status = int(getattr(resp, "status", 200) or 200)
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if "text/html" not in ctype and "application/xhtml+xml" not in ctype:
            return "", resp.geturl(), status
        raw = resp.read(MAX_BYTES)
        return raw.decode("utf-8", errors="replace"), resp.geturl(), status


def _homepage(account: Dict[str, Any]) -> List[str]:
    domain = str(account.get("domain") or "").strip()
    source = str(account.get("source_url") or "").strip()
    urls: List[str] = []
    if domain:
        urls.extend([f"https://{domain}/", f"http://{domain}/"])
    if source.startswith(("http://", "https://")):
        urls.append(source)
    return list(dict.fromkeys(urls))[:3]


def _title(html: str) -> str:
    match = TITLE_RE.search(html or "")
    return WS_RE.sub(" ", unescape(match.group(1))).strip()[:220] if match else ""


def _description(html: str) -> str:
    match = META_DESC_RE.search(html or "")
    if not match:
        return ""
    value = next((x for x in match.groups() if x), "")
    return WS_RE.sub(" ", unescape(value)).strip()[:500]


def _contains(text: str, terms) -> int:
    low = (text or "").lower()
    return sum(1 for x in terms if x in low)


def _category_match(category: str, text: str) -> tuple[int, List[str]]:
    words = list(dict.fromkeys(_tokens(category)))
    low = text.lower()
    hits = [w for w in words if w in low]
    if not words:
        return 0, []
    return round(35 * len(hits) / len(words)), hits


def verify_account(account: Dict[str, Any]) -> Dict[str, Any]:
    html = ""; final_url = ""; http_status = 0; error = ""
    for url in _homepage(account):
        try:
            html, final_url, http_status = _fetch(url)
            if html:
                break
        except Exception as exc:
            error = str(exc)[:160]

    if not html:
        account.update({
            "verification_status": "retry_required",
            "verification_error": error or "No se obtuvo HTML corporativo",
            "verified_company": False,
            "verified_at": utcnow(),
        })
        return {"verified": False, "retry": True}

    title = _title(html)
    description = _description(html)
    text = _clean_text(html)[:100_000]
    combined = f"{title} {description} {text}"
    category_score, hits = _category_match(str(account.get("category") or ""), combined)
    business_hits = _contains(combined, BUSINESS_TERMS)
    role_terms = SUPPLIER_TERMS if account.get("type") == "supplier" else BUYER_CONTEXT_TERMS
    role_hits = _contains(combined, role_terms)

    score = 25  # reachable first-party domain
    score += min(20, business_hits * 4)
    score += category_score
    score += min(15, role_hits * 3)
    score = max(0, min(100, score))
    verified = score >= 70 and business_hits >= 2 and (category_score >= 12 or role_hits >= 2)

    reasons: List[str] = ["Sitio web accesible y asociado al dominio candidato"]
    if business_hits >= 2: reasons.append("Contenido corporativo suficiente")
    if hits: reasons.append("Coincidencia de categoría: " + ", ".join(hits[:5]))
    if role_hits >= 2: reasons.append("Contexto compatible con rol comercial esperado")
    if not verified: reasons.append("Evidencia insuficiente para promover automáticamente")

    account.update({
        "verification_status": "verified_company" if verified else "evidence_insufficient",
        "verification_score": score,
        "verified_company": verified,
        "verified_contact": False,
        "official_url": final_url,
        "http_status": http_status,
        "site_title": title,
        "site_description": description,
        "category_matches": hits[:8],
        "verification_reasons": reasons[:8],
        "verified_at": utcnow(),
        "next_action": (
            "Buscar señal de demanda/intención y contacto comercial verificado"
            if verified and account.get("type") == "buyer"
            else "Validar catálogo/capacidad y contacto comercial verificado"
            if verified
            else "Conseguir evidencia adicional o descartar"
        ),
    })
    return {"verified": verified, "retry": False}


def verification_tick(state: Dict[str, Any]) -> Dict[str, int]:
    accounts = state.setdefault("candidate_accounts", [])
    queue = [x for x in accounts if x.get("status") == "verification_required" or x.get("verification_status") == "retry_required"][:MAX_PER_TICK]
    stats = {"attempted": 0, "verified": 0, "insufficient": 0, "retry": 0, "errors": 0}
    for account in queue:
        stats["attempted"] += 1
        try:
            result = verify_account(account)
            if result.get("verified"):
                account["status"] = "verified_company"
                stats["verified"] += 1
            elif result.get("retry"):
                account["status"] = "verification_required"
                stats["retry"] += 1
            else:
                account["status"] = "evidence_insufficient"
                stats["insufficient"] += 1
        except Exception as exc:
            account.update({"verification_status": "retry_required", "verification_error": str(exc)[:160], "verified_at": utcnow()})
            stats["errors"] += 1

    state["company_verification_stats"] = {**stats, "updated_at": utcnow(), "verified_accounts_total": sum(1 for x in accounts if x.get("verified_company"))}
    if stats["attempted"]:
        _log(state, f"Company Verification revisó {stats['attempted']} cuentas: {stats['verified']} verificadas, {stats['insufficient']} insuficientes y {stats['retry']} para reintento.")
    return stats
