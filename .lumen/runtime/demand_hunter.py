from __future__ import annotations

import os
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from scout_connector import DAILY_QUERY_BUDGET, MARKET, search, utcnow

MAX_QUERIES_PER_TICK = max(0, min(2, int(os.getenv("LUMEN_DEMAND_HUNTER_MAX_QUERIES", "1"))))
MAX_NEW_LEADS_PER_TICK = max(1, min(5, int(os.getenv("LUMEN_DEMAND_HUNTER_MAX_NEW_LEADS", "3"))))
COLLECTION_FOCUS = os.getenv("LUMEN_COLLECTION_FOCUS", "").strip().lower()

DEMAND_TERMS = (
    "licitación", "licitacion", "cotización", "cotizacion", "solicitud de cotización",
    "solicitud de cotizacion", "concurso de precios", "compra", "adquisición", "adquisicion",
    "pliego", "rfq", "pedido de cotización", "pedido de cotizacion",
)
NEGATIVE_VENDOR_TERMS = (
    "venta online", "tienda", "distribuidor", "distribuidora", "fabricante", "somos proveedores",
    "catálogo", "catalogo", "mercadolibre", "e-commerce", "ecommerce",
)
CENTRAL_PORTALS = {
    "comprar.gob.ar", "argentinacompra.gov.ar", "boletinoficial.gob.ar",
    "licitaya.com.ar", "contrataciones.gov.ar",
}
LOW_VALUE_HOSTS = {
    "facebook.com", "instagram.com", "linkedin.com", "youtube.com", "mercadolibre.com.ar",
    "mercadolibre.com", "amazon.com", "reddit.com", "pinterest.com",
}


def _log(state: Dict[str, Any], msg: str) -> None:
    state.setdefault("activity", []).insert(0, {"ts": utcnow(), "msg": msg})
    state["activity"] = state["activity"][:100]


def _host(url: str) -> str:
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().strip().split())


def _is_argentina(account: Dict[str, Any]) -> bool:
    values = [account.get("country"), account.get("market"), account.get("growth_market")]
    text = " ".join(_norm(x) for x in values if str(x or "").strip())
    if not text:
        return _norm(MARKET) == "argentina"
    return "argentina" in text or text in {"ar", "arg", "republica argentina", "república argentina"}


def _verified_accounts(state: Dict[str, Any], kind: str) -> List[Dict[str, Any]]:
    return [
        x for x in state.get("candidate_accounts", [])
        if x.get("type") == kind and x.get("verified_company")
    ]


def _categories(state: Dict[str, Any]) -> List[str]:
    values: List[str] = []
    for account in _verified_accounts(state, "supplier"):
        category = " ".join(str(account.get("category") or "").split())
        if category and category not in values:
            values.append(category)
    return values


def _aliases(category: str) -> List[str]:
    low = _norm(category)
    if "presi" in low or "manometr" in low:
        return [
            "manómetro", "manometro", "transmisor de presión", "transmisor de presion",
            "presostato", "regulador de presión", "regulador de presion",
            "manovacuómetro", "manovacuometro", "instrumentación de presión",
        ]
    if "temper" in low:
        return ["termómetro", "termometro", "sensor de temperatura", "transmisor de temperatura"]
    if "caudal" in low:
        return ["caudalímetro", "caudalimetro", "medidor de caudal", "flowmeter"]

    words = [x for x in re.findall(r"[A-Za-zÁÉÍÓÚáéíóúÑñ0-9]+", category) if len(x) >= 4]
    aliases = [category]
    aliases.extend(words[:4])
    out: List[str] = []
    for value in aliases:
        value = " ".join(str(value).split())
        if value and value not in out:
            out.append(value)
    return out[:8]


def _query(category: str) -> str:
    aliases = _aliases(category)[:5]
    alias_expr = " OR ".join(f'"{x}"' for x in aliases)
    year = datetime.now(timezone.utc).year
    return (
        f'({alias_expr}) '
        '("licitación" OR "licitacion" OR "solicitud de cotización" OR "solicitud de cotizacion" '
        'OR "concurso de precios" OR "adquisición" OR "adquisicion" OR "compra") '
        f'{MARKET} {year} -venta -proveedor -distribuidor -fabricante'
    )


def _score(category: str, item: Dict[str, str]) -> Dict[str, Any]:
    title = str(item.get("title") or "")
    snippet = str(item.get("snippet") or "")
    url = str(item.get("url") or "")
    text = f"{title} {snippet} {url}".lower()
    host = _host(url)

    aliases = _aliases(category)
    category_hits = sum(1 for alias in aliases if alias.lower() in text)
    demand_hits = sum(1 for term in DEMAND_TERMS if term in text)
    negative_hits = sum(1 for term in NEGATIVE_VENDOR_TERMS if term in text)

    category_score = min(35, category_hits * 15)
    demand_score = min(40, demand_hits * 15)
    local_score = 10 if ("argentina" in text or host.endswith(".ar")) else 0
    year_score = 10 if str(datetime.now(timezone.utc).year) in text else 0
    source_score = 5 if host and host not in LOW_VALUE_HOSTS else 0
    penalty = min(35, negative_hits * 15)

    total = max(0, min(100, category_score + demand_score + local_score + year_score + source_score - penalty))
    return {
        "score": int(total),
        "host": host,
        "category_hits": category_hits,
        "demand_hits": demand_hits,
        "negative_hits": negative_hits,
        "central_portal": host in CENTRAL_PORTALS,
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


def _needs_hunt(state: Dict[str, Any]) -> bool:
    suppliers = _verified_accounts(state, "supplier")
    buyers = _verified_accounts(state, "buyer")
    demand_buyers = [x for x in buyers if x.get("demand_signal")]
    if not suppliers or demand_buyers:
        return False
    if COLLECTION_FOCUS == "mercadopago_ars" and not any(_is_argentina(x) for x in suppliers):
        return False
    return True


def _known_urls(state: Dict[str, Any]) -> set[str]:
    urls = {str(x.get("url") or "") for x in state.get("research_leads", []) if x.get("url")}
    urls.update(str(x.get("url") or "") for x in state.get("unlinked_demand_signals", []) if x.get("url"))
    return urls


def _record_signal(state: Dict[str, Any], category: str, query: str, item: Dict[str, str], scoring: Dict[str, Any]) -> None:
    signals = state.setdefault("unlinked_demand_signals", [])
    signals.append({
        "id": f"UDS-{len(signals)+1:05d}",
        "category": category,
        "url": str(item.get("url") or ""),
        "title": str(item.get("title") or "")[:300],
        "snippet": str(item.get("snippet") or "")[:700],
        "query": query,
        "score": scoring["score"],
        "host": scoring["host"],
        "central_portal": bool(scoring["central_portal"]),
        "status": "buyer_identity_research_required",
        "collection_focus": COLLECTION_FOCUS or "standard",
        "created_at": utcnow(),
    })
    state["unlinked_demand_signals"] = signals[-200:]


def _record_lead(state: Dict[str, Any], category: str, query: str, item: Dict[str, str], scoring: Dict[str, Any]) -> bool:
    url = str(item.get("url") or "").strip()
    if not url or scoring["central_portal"] or scoring["host"] in LOW_VALUE_HOSTS:
        return False
    leads = state.setdefault("research_leads", [])
    leads.append({
        "id": f"LEAD-{len(leads)+1:05d}",
        "type": "buyer",
        "category": category,
        "title": str(item.get("title") or "")[:300],
        "url": url,
        "snippet": str(item.get("snippet") or "")[:700],
        "query": query,
        "market": MARKET,
        "status": "research_required",
        "confidence": round(min(0.88, 0.45 + scoring["score"] / 250.0), 2),
        "verified_company": False,
        "verified_contact": False,
        "public_demand_hint": True,
        "demand_score": scoring["score"],
        "demand_source_kind": "demand_first_public_search",
        "created_at": utcnow(),
    })
    return True


def demand_hunter_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    budget = _budget(state)
    stats: Dict[str, Any] = {
        "active": False,
        "mode": "demand_first",
        "queries": 0,
        "signals_found": 0,
        "buyer_leads_created": 0,
        "errors": 0,
        "budget_remaining": budget["queries_remaining"],
        "collection_focus": COLLECTION_FOCUS or "standard",
        "reason": None,
    }

    if not _needs_hunt(state):
        stats["reason"] = "no_demand_gap"
        return stats
    if MAX_QUERIES_PER_TICK <= 0:
        stats["reason"] = "disabled"
        return stats
    if budget["queries_remaining"] <= 0:
        stats["reason"] = "daily_budget_exhausted"
        return stats

    categories = _categories(state)
    if not categories:
        stats["reason"] = "no_verified_supplier_category"
        return stats

    stats["active"] = True
    stats["reason"] = "verified_suppliers_without_verified_buyer_demand"
    cursor = int(state.get("demand_hunter_cursor") or 0)
    known_urls = _known_urls(state)
    used = 0

    for offset in range(len(categories)):
        if used >= MAX_QUERIES_PER_TICK or budget["queries_remaining"] <= 0:
            break
        category = categories[(cursor + offset) % len(categories)]
        query = _query(category)
        budget["queries_used"] += 1
        budget["queries_remaining"] = max(0, DAILY_QUERY_BUDGET - budget["queries_used"])
        used += 1
        stats["queries"] += 1

        try:
            results = search(query)
            scored: List[Tuple[Dict[str, Any], Dict[str, str]]] = sorted(
                [(_score(category, item), item) for item in results],
                key=lambda pair: pair[0]["score"],
                reverse=True,
            )
            leads_created = 0
            for scoring, item in scored:
                url = str(item.get("url") or "").strip()
                if not url or url in known_urls or scoring["score"] < 55:
                    continue
                _record_signal(state, category, query, item, scoring)
                known_urls.add(url)
                stats["signals_found"] += 1

                if (
                    scoring["score"] >= 65
                    and scoring["demand_hits"] > 0
                    and scoring["category_hits"] > 0
                    and leads_created < MAX_NEW_LEADS_PER_TICK
                ):
                    if _record_lead(state, category, query, item, scoring):
                        leads_created += 1
                        stats["buyer_leads_created"] += 1

            _log(
                state,
                f"Demand Hunter investigó demanda activa para {category}: "
                f"{stats['signals_found']} señales acumuladas en el ciclo y {leads_created} leads compradores nuevos.",
            )
        except Exception as exc:
            stats["errors"] += 1
            _log(state, f"Demand Hunter falló para {category}: {str(exc)[:140]}")

    state["demand_hunter_cursor"] = (cursor + max(1, used)) % max(1, len(categories))
    budget["updated_at"] = utcnow()
    stats["budget_remaining"] = budget["queries_remaining"]
    state["demand_hunter"] = {**stats, "updated_at": utcnow()}
    return stats
