from __future__ import annotations

import os
import re
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

import scout_connector
import search_budget_governor


VERSION = "1.0-buyer-identity-resolver"
MAX_PER_CYCLE = max(0, min(3, int(os.getenv("LUMEN_BUYER_IDENTITY_MAX_PER_CYCLE", "1"))))
MAX_ATTEMPTS = max(1, min(5, int(os.getenv("LUMEN_BUYER_IDENTITY_MAX_ATTEMPTS", "3"))))
MIN_RESOLUTION_SCORE = max(55, min(90, int(os.getenv("LUMEN_BUYER_IDENTITY_MIN_SCORE", "68"))))
RETRY_HOURS = max(6, min(168, int(os.getenv("LUMEN_BUYER_IDENTITY_RETRY_HOURS", "24"))))

PORTAL_HOSTS = {
    "comprar.gob.ar", "argentinacompra.gov.ar", "boletinoficial.gob.ar", "contrataciones.gov.ar",
    "licitaya.com.ar", "licitaciones.com", "licitaciones.com.ar",
}
LOW_VALUE_HOSTS = {
    "facebook.com", "instagram.com", "linkedin.com", "youtube.com", "mercadolibre.com.ar",
    "mercadolibre.com", "amazon.com", "reddit.com", "pinterest.com", "wikipedia.org",
}
GENERIC_WORDS = {
    "licitacion", "licitación", "publica", "pública", "privada", "compra", "compras", "adquisicion",
    "adquisición", "cotizacion", "cotización", "solicitud", "oferta", "ofertas", "concurso", "precios",
    "pliego", "proveedores", "proveedor", "rfq", "argentina", "expediente", "proceso", "contratacion",
    "contratación", "servicio", "servicios", "suministro", "suministros",
}
DIRECTORY_TERMS = (
    "noticias", "news", "directorio", "guia", "guía", "listado", "blog", "portal de noticias",
    "empleo", "trabajo", "vacante", "marketplace",
)
BUSINESS_TERMS = (
    "empresa", "industria", "industrial", "municipalidad", "ministerio", "universidad", "hospital",
    "sociedad", "corporacion", "corporación", "compañía", "compania", "organismo", "instituto",
    "secretaria", "secretaría", "gobierno", "planta", "servicios", "ingenieria", "ingeniería",
)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _parse_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _host(url: str) -> str:
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _canonical_domain(host: str) -> str:
    parts = [x for x in str(host or "").lower().split(".") if x]
    if len(parts) <= 2:
        return ".".join(parts)
    multi = {("com", "ar"), ("org", "ar"), ("gob", "ar"), ("gov", "ar"), ("edu", "ar"), ("net", "ar")}
    if tuple(parts[-2:]) in multi and len(parts) >= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _tokens(text: str) -> List[str]:
    out: List[str] = []
    for token in re.findall(r"[A-Za-zÁÉÍÓÚáéíóúÑñ0-9]+", str(text or "")):
        low = token.lower()
        if len(low) < 4 or low in GENERIC_WORDS or low in out:
            continue
        out.append(low)
    return out


def _clean_phrase(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" -–—|:;,.\t\n")
    text = re.sub(r"\b(?:licitaci[oó]n|cotizaci[oó]n|solicitud de oferta|solicitud de cotizaci[oó]n|concurso de precios|pliego)\b", " ", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip(" -–—|:;,.\t\n")[:140]


def _candidate_phrase(signal: Dict[str, Any]) -> str:
    title = str(signal.get("title") or "")
    snippet = str(signal.get("snippet") or "")
    combined = f"{title} | {snippet}"

    patterns = (
        r"(?:organismo|entidad|comprador|comitente|contratante|requirente|raz[oó]n social|unidad ejecutora)\s*[:\-]\s*([^|.;]{5,140})",
        r"(?:municipalidad|ministerio|universidad|hospital|instituto|secretar[ií]a)\s+(?:de\s+)?[A-Za-zÁÉÍÓÚáéíóúÑñ0-9 .'-]{3,100}",
    )
    for pattern in patterns:
        match = re.search(pattern, combined, flags=re.I)
        if match:
            phrase = _clean_phrase(match.group(1) if match.lastindex else match.group(0))
            if len(_tokens(phrase)) >= 1:
                return phrase

    segments = re.split(r"\s+(?:-|–|—|\|)\s+|:\s+", title)
    ranked: List[Tuple[int, str]] = []
    for raw in segments:
        phrase = _clean_phrase(raw)
        tokens = _tokens(phrase)
        if not tokens or len(phrase) < 5:
            continue
        generic_hits = sum(1 for word in GENERIC_WORDS if word in phrase.lower())
        entity_bonus = 4 if any(term in phrase.lower() for term in BUSINESS_TERMS) else 0
        score = len(tokens) * 3 + entity_bonus - generic_hits * 2
        ranked.append((score, phrase))
    ranked.sort(key=lambda x: (x[0], len(x[1])), reverse=True)
    return ranked[0][1] if ranked else ""


def _query(signal: Dict[str, Any], phrase: str) -> str:
    category = " ".join(str(signal.get("category") or "").split())
    phrase = phrase.replace('"', "")
    return f'"{phrase}" "{category}" Argentina sitio oficial -licitaya -facebook -instagram -linkedin -mercadolibre'


def _score_result(signal: Dict[str, Any], phrase: str, item: Dict[str, str]) -> Dict[str, Any]:
    url = str(item.get("url") or "")
    title = str(item.get("title") or "")
    snippet = str(item.get("snippet") or "")
    host = _host(url)
    text = f"{title} {snippet} {url}".lower()

    if not host or host in PORTAL_HOSTS or host in LOW_VALUE_HOSTS:
        return {"score": 0, "host": host, "identity_hits": 0}

    identity_tokens = _tokens(phrase)
    category_tokens = _tokens(str(signal.get("category") or ""))
    identity_hits = sum(1 for token in identity_tokens if token in text)
    category_hits = sum(1 for token in category_tokens if token in text)
    identity_ratio = identity_hits / max(1, len(identity_tokens))
    category_ratio = category_hits / max(1, len(category_tokens)) if category_tokens else 0

    score = round(identity_ratio * 50)
    score += round(category_ratio * 12)
    if host.endswith((".gob.ar", ".gov.ar", ".edu.ar", ".org.ar", ".com.ar", ".ar")):
        score += 12
    if any(term in text for term in BUSINESS_TERMS):
        score += 12
    if url.lower().endswith(".pdf") or ".pdf?" in url.lower():
        score -= 10
    if any(term in text for term in DIRECTORY_TERMS):
        score -= 20

    if identity_tokens and identity_hits == 0:
        score = min(score, 35)
    if len(identity_tokens) >= 2 and identity_hits < 2 and not host.endswith((".gob.ar", ".gov.ar")):
        score = min(score, 60)

    return {
        "score": max(0, min(100, int(score))),
        "host": host,
        "domain": _canonical_domain(host),
        "identity_hits": identity_hits,
        "category_hits": category_hits,
    }


def _known_signal_urls(state: Dict[str, Any]) -> set[str]:
    return {
        str(x.get("demand_evidence_url") or "")
        for x in state.get("research_leads", []) or []
        if x.get("demand_evidence_url")
    }


def _upsert_lead(state: Dict[str, Any], signal: Dict[str, Any], item: Dict[str, str], scoring: Dict[str, Any], phrase: str) -> Dict[str, Any]:
    leads = state.setdefault("research_leads", [])
    domain = str(scoring.get("domain") or "")
    category = str(signal.get("category") or "")

    for lead in leads:
        if lead.get("type") != "buyer":
            continue
        if str(lead.get("domain") or "").lower() == domain.lower() and str(lead.get("category") or "").lower() == category.lower():
            lead["public_demand_hint"] = True
            lead["demand_score"] = max(int(lead.get("demand_score") or 0), int(signal.get("score") or 0))
            lead["demand_evidence_url"] = signal.get("url")
            lead["buyer_identity_resolved"] = True
            lead["identity_resolution_score"] = max(int(lead.get("identity_resolution_score") or 0), int(scoring.get("score") or 0))
            return lead

    lead = {
        "id": f"LEAD-{len(leads)+1:05d}",
        "type": "buyer",
        "category": category,
        "title": str(item.get("title") or phrase)[:300],
        "url": str(item.get("url") or ""),
        "snippet": str(item.get("snippet") or "")[:700],
        "market": "Argentina",
        "status": "research_required",
        "confidence": round(min(0.92, 0.48 + int(scoring.get("score") or 0) / 220.0), 2),
        "verified_company": False,
        "verified_contact": False,
        "public_demand_hint": True,
        "demand_score": int(signal.get("score") or 0),
        "demand_source_kind": "buyer_identity_resolved_from_public_procurement_signal",
        "demand_evidence_url": signal.get("url"),
        "demand_source_title": signal.get("title"),
        "demand_source_host": signal.get("host"),
        "buyer_identity_resolved": True,
        "identity_phrase": phrase,
        "identity_resolution_score": int(scoring.get("score") or 0),
        "identity_resolution_domain": domain,
        "created_at": utcnow(),
    }
    leads.append(lead)
    return lead


def resolver_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    stats = {
        "version": VERSION,
        "eligible": 0,
        "attempted": 0,
        "resolved": 0,
        "leads_created_or_enriched": 0,
        "deferred_budget": 0,
        "unresolved": 0,
        "errors": 0,
    }
    now = datetime.now(timezone.utc)
    known_signal_urls = _known_signal_urls(state)
    queue: List[Dict[str, Any]] = []

    for signal in state.get("unlinked_demand_signals", []) or []:
        if str(signal.get("status") or "") not in {"buyer_identity_research_required", "identity_retry_required"}:
            continue
        if str(signal.get("url") or "") in known_signal_urls:
            signal["status"] = "identity_already_linked"
            continue
        attempts = int(signal.get("identity_attempts") or 0)
        if attempts >= MAX_ATTEMPTS:
            signal["status"] = "identity_unresolved_max_attempts"
            continue
        retry_at = _parse_utc(signal.get("identity_retry_at"))
        if retry_at and retry_at > now:
            continue
        queue.append(signal)

    queue.sort(key=lambda x: int(x.get("score") or 0), reverse=True)
    stats["eligible"] = len(queue)

    for signal in queue[:MAX_PER_CYCLE]:
        if int(search_budget_governor.demand_budget(state).get("queries_remaining") or 0) <= 0:
            stats["deferred_budget"] += 1
            break

        phrase = _candidate_phrase(signal)
        if not phrase:
            signal["identity_attempts"] = int(signal.get("identity_attempts") or 0) + 1
            signal["identity_last_attempt"] = utcnow()
            signal["identity_retry_at"] = (now + timedelta(hours=RETRY_HOURS)).strftime("%Y-%m-%d %H:%M:%S UTC")
            signal["status"] = "identity_retry_required"
            signal["identity_last_reason"] = "buyer_name_not_extractable"
            stats["unresolved"] += 1
            continue

        if search_budget_governor.reserve_demand_search(state, 1) != 1:
            stats["deferred_budget"] += 1
            break

        signal["identity_attempts"] = int(signal.get("identity_attempts") or 0) + 1
        signal["identity_last_attempt"] = utcnow()
        signal["identity_phrase"] = phrase
        stats["attempted"] += 1

        try:
            results = scout_connector.search(_query(signal, phrase))
            ranked = sorted(
                [(_score_result(signal, phrase, item), item) for item in results],
                key=lambda pair: pair[0]["score"],
                reverse=True,
            )
            best_scoring, best_item = ranked[0] if ranked else ({"score": 0}, {})
            best_score = int(best_scoring.get("score") or 0)

            if best_score >= MIN_RESOLUTION_SCORE and best_scoring.get("domain"):
                lead = _upsert_lead(state, signal, best_item, best_scoring, phrase)
                signal.update({
                    "status": "identity_resolved_lead_created",
                    "resolved_domain": best_scoring.get("domain"),
                    "resolved_url": best_item.get("url"),
                    "resolution_score": best_score,
                    "resolved_lead_id": lead.get("id"),
                    "resolved_at": utcnow(),
                })
                stats["resolved"] += 1
                stats["leads_created_or_enriched"] += 1
            else:
                signal["status"] = "identity_retry_required"
                signal["identity_retry_at"] = (now + timedelta(hours=RETRY_HOURS)).strftime("%Y-%m-%d %H:%M:%S UTC")
                signal["identity_last_reason"] = f"no_official_domain_above_{MIN_RESOLUTION_SCORE}"
                signal["identity_best_score"] = best_score
                stats["unresolved"] += 1
        except Exception as exc:
            signal["status"] = "identity_retry_required"
            signal["identity_retry_at"] = (now + timedelta(hours=RETRY_HOURS)).strftime("%Y-%m-%d %H:%M:%S UTC")
            signal["identity_last_reason"] = str(exc)[:160]
            stats["errors"] += 1

    state["buyer_identity_resolver"] = {
        **stats,
        "demand_budget_remaining": search_budget_governor.demand_budget(state).get("queries_remaining"),
        "policy": "public_evidence_only_no_contact_inference_no_outreach_bypass",
        "updated_at": utcnow(),
    }
    return stats
