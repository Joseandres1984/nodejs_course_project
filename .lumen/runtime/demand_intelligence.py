from __future__ import annotations

import os
import re
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

from scout_connector import DAILY_QUERY_BUDGET, search, utcnow

MAX_QUERIES_PER_TICK = max(0, min(2, int(os.getenv("LUMEN_DEMAND_MAX_QUERIES", "1"))))

STRONG_DEMAND_TERMS = (
    "licitación", "licitacion", "cotización", "cotizacion", "convocatoria", "compras",
    "proveedores", "pliego", "abastecimiento", "concurso de precios", "solicitud de oferta",
    "rfq", "tender", "procurement",
)
STOPWORDS = {
    "para", "con", "una", "uno", "del", "las", "los", "por", "que", "and", "the",
    "argentina", "empresa", "inicio", "home", "sitio", "oficial", "grupo", "company",
    "industria", "industrial", "soluciones", "servicios",
}


def _log(state: Dict[str, Any], msg: str) -> None:
    state.setdefault("activity", []).insert(0, {"ts": utcnow(), "msg": msg})
    state["activity"] = state["activity"][:100]


def _tokens(text: str) -> List[str]:
    return [
        x.lower()
        for x in re.findall(r"[A-Za-zÁÉÍÓÚáéíóúÑñ0-9]+", text or "")
        if len(x) >= 4 and x.lower() not in STOPWORDS
    ]


def _domain(url: str) -> str:
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _identity_tokens(account: Dict[str, Any]) -> List[str]:
    domain = str(account.get("domain") or "").lower()
    brand = (domain.split(".")[0] if domain else "").replace("-", " ")
    category_tokens = set(_tokens(str(account.get("category") or "")))
    candidates = _tokens(brand) + _tokens(str(account.get("name_hint") or ""))
    out: List[str] = []
    for token in candidates:
        if token in category_tokens or token in out:
            continue
        out.append(token)
    return out[:6]


def _query(account: Dict[str, Any]) -> str:
    domain = str(account.get("domain") or "")
    category = str(account.get("category") or "")
    identity = _identity_tokens(account)
    identity_expr = " OR ".join(f'"{token}"' for token in identity[:2])
    official_expr = f"site:{domain}" if domain else ""
    if official_expr and identity_expr:
        anchor = f"({official_expr} OR {identity_expr})"
    else:
        anchor = official_expr or identity_expr or f'"{domain}"'
    return (
        f'{anchor} "{category}" '
        "(compras OR licitación OR licitacion OR cotización OR cotizacion OR "
        "proveedores OR pliego OR abastecimiento OR RFQ OR procurement)"
    )


def _score(account: Dict[str, Any], item: Dict[str, str]) -> Dict[str, Any]:
    text = f"{item.get('title', '')} {item.get('snippet', '')} {item.get('url', '')}".lower()
    account_domain = str(account.get("domain") or "").lower()
    result_domain = _domain(str(item.get("url") or ""))
    official = bool(
        result_domain
        and account_domain
        and (result_domain == account_domain or result_domain.endswith("." + account_domain))
    )

    strong_hits = sum(1 for term in STRONG_DEMAND_TERMS if term in text)

    category_tokens = list(dict.fromkeys(_tokens(str(account.get("category") or ""))))
    category_hits = sum(1 for token in category_tokens if token in text)
    category_score = round(30 * category_hits / max(1, len(category_tokens))) if category_tokens else 0

    identity_tokens = _identity_tokens(account)
    identity_hits = sum(1 for token in identity_tokens if token in text)
    identity_denominator = max(1, min(3, len(identity_tokens)))
    identity_score = round(25 * identity_hits / identity_denominator) if identity_tokens else 0

    score = (35 if official else 0) + min(35, strong_hits * 18) + category_score + identity_score

    # A product page is not a buying signal. Demand language must be present.
    if strong_hits == 0:
        score = min(score, 60)

    # External portals are accepted only when the buyer identity is actually present.
    if not official and identity_score < 15:
        score = min(score, 65)

    return {
        "score": max(0, min(100, int(score))),
        "official": official,
        "strong_hits": strong_hits,
        "category_score": category_score,
        "identity_score": identity_score,
    }


def _budget(state: Dict[str, Any]) -> Dict[str, Any]:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    budget = state.setdefault(
        "scout_budget",
        {"date": today, "queries_used": 0, "daily_budget": DAILY_QUERY_BUDGET},
    )
    if budget.get("date") != today:
        budget.clear()
        budget.update({"date": today, "queries_used": 0, "daily_budget": DAILY_QUERY_BUDGET})
    budget["daily_budget"] = DAILY_QUERY_BUDGET
    budget["queries_used"] = int(budget.get("queries_used", 0))
    budget["queries_remaining"] = max(0, DAILY_QUERY_BUDGET - budget["queries_used"])
    return budget


def _candidates(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out: List[Dict[str, Any]] = []
    for account in state.get("candidate_accounts", []):
        if account.get("type") != "buyer" or not account.get("verified_company"):
            continue
        if account.get("demand_signal"):
            continue
        next_check = str(account.get("demand_next_check") or "")
        if next_check and next_check > today:
            continue
        if account.get("domain") and account.get("category"):
            out.append(account)
    return sorted(
        out,
        key=lambda x: (
            float(x.get("verification_score") or 0),
            float(x.get("lead_score") or 0),
        ),
        reverse=True,
    )


def demand_intelligence_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    budget = _budget(state)
    stats: Dict[str, Any] = {
        "queries": 0,
        "verified": 0,
        "no_signal": 0,
        "errors": 0,
        "budget_remaining": budget["queries_remaining"],
    }
    if MAX_QUERIES_PER_TICK <= 0 or budget["queries_remaining"] <= 0:
        return stats

    signals = state.setdefault("demand_signals", [])
    known_urls = {str(x.get("url") or "") for x in signals if x.get("url")}

    for account in _candidates(state)[:MAX_QUERIES_PER_TICK]:
        if budget["queries_remaining"] <= 0:
            break

        query = _query(account)
        budget["queries_used"] += 1
        budget["queries_remaining"] = max(0, DAILY_QUERY_BUDGET - budget["queries_used"])
        stats["queries"] += 1

        try:
            results = search(query)
            scored = sorted(
                [(_score(account, item), item) for item in results],
                key=lambda pair: pair[0]["score"],
                reverse=True,
            )
            best = scored[0][0]["score"] if scored else 0
            evidence_urls: List[str] = []

            for scoring, item in scored[:3]:
                url = str(item.get("url") or "")
                if url:
                    evidence_urls.append(url)
                if not url or url in known_urls or scoring["score"] <= 0:
                    continue
                signals.append(
                    {
                        "id": f"SIG-{len(signals)+1:05d}",
                        "account_id": account.get("id"),
                        "category": account.get("category"),
                        "url": url,
                        "title": str(item.get("title") or "")[:300],
                        "snippet": str(item.get("snippet") or "")[:700],
                        "score": scoring["score"],
                        "source": "official_site" if scoring["official"] else "external_public_source",
                        "identity_score": scoring["identity_score"],
                        "category_score": scoring["category_score"],
                        "strong_demand_hits": scoring["strong_hits"],
                        "created_at": utcnow(),
                    }
                )
                known_urls.add(url)

            account["demand_score"] = best
            account["demand_last_checked"] = utcnow()
            account["demand_evidence_urls"] = evidence_urls[:3]

            if best >= 75:
                account["demand_signal"] = True
                account["demand_status"] = "public_signal_verified"
                account["status"] = "demand_verified"
                account["next_action"] = "Construir tesis de oportunidad y validar requerimiento/contacto comercial"
                stats["verified"] += 1
                _log(
                    state,
                    f"Demand Intelligence verificó intención pública para {account.get('id')} "
                    f"({account.get('category')}) con score {best}.",
                )
            else:
                account["demand_signal"] = False
                account["demand_status"] = "no_strong_public_signal"
                account["demand_next_check"] = (
                    datetime.now(timezone.utc) + timedelta(days=7)
                ).strftime("%Y-%m-%d")
                account["next_action"] = (
                    "Revisar nuevamente señal de demanda más adelante; no contactar por ahora"
                )
                stats["no_signal"] += 1
                _log(
                    state,
                    f"Demand Intelligence no encontró evidencia suficiente para {account.get('id')} "
                    f"(mejor score {best}); no habilita contacto.",
                )
        except Exception as exc:
            stats["errors"] += 1
            _log(state, f"Demand Intelligence falló para {account.get('id')}: {str(exc)[:140]}")

    budget["updated_at"] = utcnow()
    stats["budget_remaining"] = budget["queries_remaining"]
    return stats
