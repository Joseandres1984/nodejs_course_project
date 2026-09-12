from __future__ import annotations

import re
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from autonomy_governor import record_decision

MAX_PER_TICK = 24

LOW_QUALITY_HOST_HINTS = {
    "linkedin.com", "facebook.com", "instagram.com", "youtube.com", "x.com", "twitter.com",
    "mercadolibre.com", "mercadolibre.com.ar", "amazon.com", "reddit.com", "pinterest.com",
    "wikipedia.org", "scribd.com", "slideshare.net", "indeed.com", "glassdoor.com",
}
DIRECTORY_HINTS = (
    "directorio", "guia", "listado", "ranking", "top ", "empleos", "trabajo", "vacante",
    "noticias", "news", "blog", "foro", "marketplace", "clasificados",
)
BUSINESS_TERMS = {
    "empresa", "industria", "industrial", "fabricante", "distribuidor", "distribuidora",
    "proveedor", "proveedores", "soluciones", "servicios", "ingenieria", "ingeniería",
    "mantenimiento", "suministros", "comercial", "ventas", "productos", "tecnologia", "tecnología",
}
BUYER_TERMS = {"compras", "abastecimiento", "mantenimiento", "planta", "industria", "servicios", "ingenieria", "ingeniería"}
SUPPLIER_TERMS = {"fabricante", "distribuidor", "distribuidora", "proveedor", "representante", "stock", "productos", "catalogo", "catálogo"}
ARGENTINA_HINTS = {"argentina", ".com.ar", ".ar", "buenos aires", "caba", "cordoba", "córdoba", "santa fe", "mendoza"}
STOPWORDS = {"para", "con", "una", "uno", "del", "las", "los", "por", "que", "and", "the", "argentina", "empresa"}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _log(state: Dict[str, Any], msg: str) -> None:
    state.setdefault("activity", []).insert(0, {"ts": utcnow(), "msg": msg})
    state["activity"] = state["activity"][:100]


def _host(url: str) -> str:
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _canonical_domain(host: str) -> str:
    parts = [p for p in host.split(".") if p]
    if len(parts) <= 2:
        return host
    if len(parts) >= 3 and parts[-2:] == ["com", "ar"]:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _tokens(text: str) -> List[str]:
    return [x.lower() for x in re.findall(r"[A-Za-zÁÉÍÓÚáéíóúÑñ0-9]+", text or "") if len(x) >= 4 and x.lower() not in STOPWORDS]


def _contains_any(text: str, terms) -> bool:
    low = (text or "").lower()
    return any(term in low for term in terms)


def _category_fit(category: str, text: str) -> Tuple[int, List[str]]:
    cat = list(dict.fromkeys(_tokens(category)))
    low = (text or "").lower()
    hits = [t for t in cat if t in low]
    if not cat:
        return 0, []
    ratio = len(hits) / len(cat)
    return round(ratio * 30), hits


def _source_quality(url: str, title: str, snippet: str) -> Tuple[int, List[str]]:
    host = _host(url)
    combined = f"{title} {snippet}".lower()
    reasons: List[str] = []
    if not host:
        return 0, ["URL sin dominio interpretable"]
    if any(host == x or host.endswith("." + x) for x in LOW_QUALITY_HOST_HINTS):
        return 0, ["Fuente de baja calidad para validación corporativa"]
    score = 18
    reasons.append("Dominio web identificable")
    if url.lower().endswith(".pdf") or ".pdf?" in url.lower():
        score -= 8; reasons.append("Resultado PDF: requiere confirmar entidad")
    if _contains_any(combined, DIRECTORY_HINTS):
        score -= 8; reasons.append("Posible directorio/noticia/listado")
    if host.endswith(".com.ar") or host.endswith(".ar"):
        score += 5; reasons.append("Dominio con señal local Argentina")
    return max(0, min(25, score)), reasons


def score_lead(lead: Dict[str, Any]) -> Dict[str, Any]:
    title = str(lead.get("title") or "")
    snippet = str(lead.get("snippet") or "")
    category = str(lead.get("category") or "")
    url = str(lead.get("url") or "")
    lead_type = str(lead.get("type") or "")
    combined = f"{title} {snippet} {url}"

    category_score, matched = _category_fit(category, combined)
    source_score, source_reasons = _source_quality(url, title, snippet)
    business_score = 15 if _contains_any(combined, BUSINESS_TERMS) else 5
    role_terms = SUPPLIER_TERMS if lead_type == "supplier" else BUYER_TERMS
    role_score = 15 if _contains_any(combined, role_terms) else 6
    # Expansion leads should not be penalized merely for being outside Argentina. Locality is a small confidence
    # signal only; the Growth/Trade layers decide market attractiveness separately from company identity quality.
    lead_market = str(lead.get("growth_market") or lead.get("market") or "").strip().lower()
    local_score = 10 if _contains_any(combined, ARGENTINA_HINTS) or lead_market == "argentina" else 7 if lead_market else 4
    specificity = 5 if title and len(title.strip()) >= 8 else 1

    penalties = 0
    reasons = list(source_reasons)
    if category_score:
        reasons.append("Coincidencia con categoría: " + ", ".join(matched[:5]))
    else:
        penalties += 12; reasons.append("Sin coincidencia clara con la categoría")
    if business_score >= 15:
        reasons.append("Señal empresarial/B2B presente")
    if role_score >= 15:
        reasons.append("Señal compatible con rol " + ("proveedor" if lead_type == "supplier" else "comprador"))
    if lead_market and lead_market != "argentina":
        reasons.append(f"Lead de expansión identificado en mercado {lead.get('growth_market') or lead.get('market')}")
    if source_score == 0:
        penalties += 18
    if not snippet.strip():
        penalties += 5; reasons.append("Sin snippet suficiente")

    raw = category_score + source_score + business_score + role_score + local_score + specificity - penalties
    score = max(0, min(100, int(raw)))
    if score >= 75:
        tier, status, next_action = "A", "qualified_candidate", "Validar sitio corporativo y evidencia comercial antes de promover"
    elif score >= 55:
        tier, status, next_action = "B", "research_required", "Profundizar evidencia de empresa y encaje comercial"
    elif score >= 38:
        tier, status, next_action = "C", "low_priority", "Mantener en observación; no usar para outreach"
    else:
        tier, status, next_action = "D", "rejected_noise", "Descartar salvo nueva evidencia"

    return {
        "lead_score": score,
        "tier": tier,
        "qualification_status": status,
        "qualification_reasons": reasons[:8],
        "next_research_action": next_action,
        "confidence": round(min(0.92, 0.30 + score / 160.0), 2),
        "domain": _canonical_domain(_host(url)),
        "category_matches": matched[:8],
    }


def _candidate_key(lead: Dict[str, Any]) -> str:
    return "|".join([
        str(lead.get("type") or ""),
        str(lead.get("category") or "").lower(),
        str(lead.get("domain") or "").lower(),
    ])


def qualify_tick(state: Dict[str, Any]) -> Dict[str, int]:
    leads = state.setdefault("research_leads", [])
    accounts = state.setdefault("candidate_accounts", [])
    stats = {"processed": 0, "tier_a": 0, "tier_b": 0, "rejected": 0, "duplicates": 0, "candidates_created": 0}

    queue = [x for x in leads if not x.get("qualified_at")][:MAX_PER_TICK]
    known_keys = {str(x.get("candidate_key")) for x in accounts if x.get("candidate_key")}
    seen_leads: set[str] = set()

    for lead in queue:
        stats["processed"] += 1
        result = score_lead(lead)
        lead.update(result)
        lead["qualified_at"] = utcnow()
        key = _candidate_key(lead)

        if key in seen_leads:
            lead["qualification_status"] = "duplicate"
            lead["next_research_action"] = "Consolidar evidencia con la cuenta principal"
            stats["duplicates"] += 1
            record_decision(
                state, engine="Lead Intelligence", object_type="research_lead", object_id=str(lead.get("id")),
                decision="duplicate", reason="Mismo dominio/categoría/rol ya procesado en este ciclo",
                action="classify_lead", confidence=float(lead.get("confidence") or 0), evidence_refs=[str(lead.get("url") or "")],
            )
            continue
        seen_leads.add(key)

        if lead["tier"] == "A": stats["tier_a"] += 1
        elif lead["tier"] == "B": stats["tier_b"] += 1
        elif lead["tier"] == "D": stats["rejected"] += 1

        record_decision(
            state, engine="Lead Intelligence", object_type="research_lead", object_id=str(lead.get("id")),
            decision=f"tier_{str(lead.get('tier')).lower()}",
            reason="; ".join(str(x) for x in lead.get("qualification_reasons", [])[:5]),
            action="classify_lead", confidence=float(lead.get("confidence") or 0), evidence_refs=[str(lead.get("url") or "")],
            allowed=lead.get("tier") != "D",
        )

        if lead["tier"] == "A" and key not in known_keys and lead.get("domain"):
            account = {
                "id": f"ACC-{len(accounts)+1:05d}",
                "candidate_key": key,
                "type": lead.get("type"),
                "category": lead.get("category"),
                "name_hint": lead.get("title"),
                "domain": lead.get("domain"),
                "source_url": lead.get("url"),
                "source_lead_id": lead.get("id"),
                "lead_score": lead.get("lead_score"),
                "confidence": lead.get("confidence"),
                "market": lead.get("growth_market") or lead.get("market"),
                "growth_market": lead.get("growth_market"),
                "growth_kind": lead.get("growth_kind"),
                "growth_hypothesis_key": lead.get("growth_hypothesis_key"),
                "growth_research_only": bool(lead.get("growth_research_only")),
                "status": "verification_required",
                "verified_company": False,
                "verified_contact": False,
                "next_action": "Verificar identidad de la empresa y evidencia en su sitio oficial",
                "created_at": utcnow(),
            }
            accounts.append(account)
            known_keys.add(key)
            stats["candidates_created"] += 1
            record_decision(
                state, engine="Lead Intelligence", object_type="candidate_account", object_id=account["id"],
                decision="created_for_verification", reason="Lead Tier A con dominio y encaje suficientes para verificación corporativa",
                action="verify_company", confidence=float(account.get("confidence") or 0), evidence_refs=[str(account.get("source_url") or "")],
            )

    if stats["processed"]:
        _log(state, f"Lead Intelligence calificó {stats['processed']} leads: {stats['tier_a']} A, {stats['tier_b']} B, {stats['rejected']} descartados y {stats['candidates_created']} cuentas candidatas nuevas.")
    state["lead_intelligence_stats"] = {**stats, "updated_at": utcnow(), "candidate_accounts_total": len(accounts)}
    return stats
