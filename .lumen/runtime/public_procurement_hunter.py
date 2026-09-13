from __future__ import annotations

import os
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import scout_connector
import search_budget_governor


VERSION = "1.0-public-procurement-first"
MAX_QUERIES_PER_TICK = max(0, min(3, int(os.getenv("LUMEN_PUBLIC_PROCUREMENT_MAX_QUERIES", "2"))))
DAILY_CAP = max(1, min(24, int(os.getenv("LUMEN_PUBLIC_PROCUREMENT_DAILY_CAP", "10"))))
MIN_SIGNAL_SCORE = max(45, min(95, int(os.getenv("LUMEN_PUBLIC_PROCUREMENT_MIN_SCORE", "60"))))

CATEGORIES = (
    "materiales eléctricos",
    "instrumentación industrial",
    "válvulas bombas y repuestos industriales",
    "ferretería industrial",
    "mantenimiento mecánico industrial",
    "motores grupos electrógenos y repuestos",
)

DEMAND_TERMS = (
    "licitación", "licitacion", "contratación directa", "contratacion directa",
    "solicitud de cotización", "solicitud de cotizacion", "compra directa",
    "adquisición", "adquisicion", "presentación de ofertas", "presentacion de ofertas",
    "apertura", "pliego", "compr.ar",
)

TRUSTED_PORTALS = {
    "comprar.gob.ar",
    "boletinoficial.gob.ar",
    "nuevaweb.boletinoficial.gob.ar",
    "argentina.gob.ar",
    "dposs.gob.ar",
}

LOW_VALUE_HOSTS = {
    "facebook.com", "instagram.com", "linkedin.com", "youtube.com",
    "mercadolibre.com.ar", "mercadolibre.com", "amazon.com", "reddit.com",
}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _host(url: str) -> str:
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _log(state: Dict[str, Any], message: str) -> None:
    state.setdefault("activity", []).insert(0, {"ts": utcnow(), "msg": message})
    state["activity"] = state["activity"][:100]


def _budget(state: Dict[str, Any]) -> Dict[str, Any]:
    today = search_budget_governor.local_day()
    budget = state.setdefault("public_procurement_budget", {})
    if str(budget.get("date") or "") != today:
        budget.clear()
        budget.update({"date": today, "queries_used": 0, "daily_cap": DAILY_CAP})
    budget["daily_cap"] = DAILY_CAP
    budget["queries_used"] = max(0, int(budget.get("queries_used") or 0))
    budget["queries_remaining"] = max(0, DAILY_CAP - budget["queries_used"])
    return budget


def _query(category: str) -> str:
    year = datetime.now(timezone.utc).year
    return (
        f'"{category}" Argentina {year} '
        '("licitación" OR "licitacion" OR "contratación directa" OR "contratacion directa" '
        'OR "solicitud de cotización" OR "solicitud de cotizacion" OR "adquisición" OR "adquisicion") '
        '(site:comprar.gob.ar OR site:boletinoficial.gob.ar OR site:argentina.gob.ar OR site:gob.ar)'
    )


def _tokens(text: str) -> List[str]:
    stop = {"para", "industrial", "industriales", "materiales", "servicio", "servicios", "repuestos"}
    return [
        x.lower() for x in re.findall(r"[A-Za-zÁÉÍÓÚáéíóúÑñ0-9]+", text or "")
        if len(x) >= 4 and x.lower() not in stop
    ]


def _score(category: str, item: Dict[str, str]) -> Dict[str, Any]:
    title = str(item.get("title") or "")
    snippet = str(item.get("snippet") or "")
    url = str(item.get("url") or "")
    text = f"{title} {snippet} {url}".lower()
    host = _host(url)
    demand_hits = sum(1 for term in DEMAND_TERMS if term in text)
    category_tokens = list(dict.fromkeys(_tokens(category)))
    category_hits = sum(1 for token in category_tokens if token in text)
    portal = host in TRUSTED_PORTALS or host.endswith(".gob.ar")
    current_year = str(datetime.now(timezone.utc).year) in text
    argentina = "argentina" in text or host.endswith(".ar")
    penalty = 40 if host in LOW_VALUE_HOSTS else 0
    score = (
        (30 if portal else 0)
        + min(35, demand_hits * 12)
        + min(25, category_hits * 10)
        + (5 if current_year else 0)
        + (5 if argentina else 0)
        - penalty
    )
    return {
        "score": max(0, min(100, int(score))),
        "host": host,
        "portal": portal,
        "demand_hits": demand_hits,
        "category_hits": category_hits,
    }


def _known_urls(state: Dict[str, Any]) -> set[str]:
    urls = {str(x.get("url") or "") for x in state.get("unlinked_demand_signals", []) if x.get("url")}
    urls.update(str(x.get("url") or "") for x in state.get("research_leads", []) if x.get("url"))
    return urls


def _record_signal(state: Dict[str, Any], category: str, query: str, item: Dict[str, str], scoring: Dict[str, Any]) -> bool:
    url = str(item.get("url") or "").strip()
    if not url:
        return False
    signals = state.setdefault("unlinked_demand_signals", [])
    signals.append({
        "id": f"UDS-{len(signals)+1:05d}",
        "category": category,
        "url": url,
        "title": str(item.get("title") or "")[:300],
        "snippet": str(item.get("snippet") or "")[:900],
        "query": query,
        "score": scoring["score"],
        "host": scoring["host"],
        "central_portal": bool(scoring["portal"]),
        "status": "buyer_identity_research_required",
        "collection_focus": "industrial_procurement_ar",
        "demand_source_kind": "public_procurement_first",
        "created_at": utcnow(),
    })
    state["unlinked_demand_signals"] = signals[-300:]
    return True


def public_procurement_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    local_budget = _budget(state)
    demand_budget = search_budget_governor.demand_budget(state)
    stats: Dict[str, Any] = {
        "version": VERSION,
        "active": False,
        "mode": "public_procurement_first",
        "queries": 0,
        "signals_found": 0,
        "errors": 0,
        "daily_remaining": local_budget["queries_remaining"],
        "demand_budget_remaining": int(demand_budget.get("queries_remaining") or 0),
        "collection_focus": "industrial_procurement_ar",
    }
    if MAX_QUERIES_PER_TICK <= 0 or local_budget["queries_remaining"] <= 0 or stats["demand_budget_remaining"] <= 0:
        state["public_procurement_hunter"] = {**stats, "updated_at": utcnow()}
        return stats

    stats["active"] = True
    known = _known_urls(state)
    cursor = int(state.get("public_procurement_cursor") or 0)
    used = 0

    for offset in range(len(CATEGORIES)):
        if used >= MAX_QUERIES_PER_TICK or local_budget["queries_remaining"] <= 0:
            break
        if search_budget_governor.reserve_demand_search(state, 1) != 1:
            break
        category = CATEGORIES[(cursor + offset) % len(CATEGORIES)]
        query = _query(category)
        local_budget["queries_used"] += 1
        local_budget["queries_remaining"] = max(0, DAILY_CAP - local_budget["queries_used"])
        used += 1
        stats["queries"] += 1
        try:
            results = scout_connector.search(query)
            ranked: List[Tuple[Dict[str, Any], Dict[str, str]]] = sorted(
                [(_score(category, item), item) for item in results],
                key=lambda pair: pair[0]["score"],
                reverse=True,
            )
            for scoring, item in ranked[:8]:
                url = str(item.get("url") or "").strip()
                if not url or url in known or scoring["score"] < MIN_SIGNAL_SCORE:
                    continue
                if scoring["demand_hits"] <= 0 or scoring["category_hits"] <= 0:
                    continue
                if _record_signal(state, category, query, item, scoring):
                    known.add(url)
                    stats["signals_found"] += 1
        except Exception as exc:
            stats["errors"] += 1
            _log(state, f"Public Procurement Hunter falló para {category}: {type(exc).__name__}: {str(exc)[:160]}")

    state["public_procurement_cursor"] = (cursor + max(1, used)) % len(CATEGORIES)
    local_budget["updated_at"] = utcnow()
    stats["daily_remaining"] = local_budget["queries_remaining"]
    stats["demand_budget_remaining"] = int(search_budget_governor.demand_budget(state).get("queries_remaining") or 0)
    state["public_procurement_hunter"] = {**stats, "updated_at": utcnow()}
    if stats["signals_found"]:
        _log(state, f"Public Procurement Hunter detectó {stats['signals_found']} señales nuevas de demanda pública verificable.")
    return stats
