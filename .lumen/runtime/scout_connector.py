from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List

PROVIDER = os.getenv("LUMEN_SCOUT_PROVIDER", "").strip().lower()
API_KEY = os.getenv("LUMEN_SCOUT_API_KEY", "").strip()
CUSTOM_ENDPOINT = os.getenv("LUMEN_SCOUT_ENDPOINT", "").strip()
MARKET = os.getenv("LUMEN_SCOUT_MARKET", "Argentina").strip() or "Argentina"
COUNTRY_CODE = os.getenv("LUMEN_SCOUT_GL", "ar").strip().lower() or "ar"
LANGUAGE = os.getenv("LUMEN_SCOUT_HL", "es").strip().lower() or "es"
MAX_QUERIES_PER_TICK = max(1, min(5, int(os.getenv("LUMEN_SCOUT_MAX_QUERIES", "2"))))


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def status() -> Dict[str, Any]:
    return {
        "provider": PROVIDER or None,
        "configured": bool(PROVIDER and API_KEY),
        "market": MARKET,
        "country_code": COUNTRY_CODE,
        "language": LANGUAGE,
        "max_queries_per_tick": MAX_QUERIES_PER_TICK,
    }


def _log(state: Dict[str, Any], msg: str) -> None:
    state.setdefault("activity", []).insert(0, {"ts": utcnow(), "msg": msg})
    state["activity"] = state["activity"][:100]


def _http_json(req: urllib.request.Request) -> Dict[str, Any]:
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _search_serper(query: str) -> List[Dict[str, str]]:
    body = json.dumps({"q": query, "num": 8, "gl": COUNTRY_CODE, "hl": LANGUAGE}).encode("utf-8")
    req = urllib.request.Request(
        "https://google.serper.dev/search",
        data=body,
        headers={"X-API-KEY": API_KEY, "Content-Type": "application/json"},
        method="POST",
    )
    data = _http_json(req)
    return [{"title": x.get("title", ""), "url": x.get("link", ""), "snippet": x.get("snippet", "")} for x in data.get("organic", [])[:8]]


def _search_brave(query: str) -> List[Dict[str, str]]:
    url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode({"q": query, "count": 8, "country": COUNTRY_CODE, "search_lang": LANGUAGE})
    req = urllib.request.Request(url, headers={"Accept": "application/json", "X-Subscription-Token": API_KEY})
    data = _http_json(req)
    return [{"title": x.get("title", ""), "url": x.get("url", ""), "snippet": x.get("description", "")} for x in data.get("web", {}).get("results", [])[:8]]


def _search_custom(query: str) -> List[Dict[str, str]]:
    if not CUSTOM_ENDPOINT:
        return []
    url = CUSTOM_ENDPOINT + ("&" if "?" in CUSTOM_ENDPOINT else "?") + urllib.parse.urlencode({"q": query})
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {API_KEY}", "Accept": "application/json"})
    data = _http_json(req)
    raw = data.get("results", data.get("items", []))
    results = []
    for x in raw[:8]:
        results.append({
            "title": x.get("title", x.get("name", "")),
            "url": x.get("url", x.get("link", "")),
            "snippet": x.get("snippet", x.get("description", "")),
        })
    return results


def search(query: str) -> List[Dict[str, str]]:
    if not PROVIDER or not API_KEY:
        return []
    if PROVIDER == "serper":
        return _search_serper(query)
    if PROVIDER == "brave":
        return _search_brave(query)
    if PROVIDER == "custom":
        return _search_custom(query)
    raise ValueError(f"Proveedor Scout no soportado: {PROVIDER}")


def _lead_id(state: Dict[str, Any]) -> str:
    return f"LEAD-{len(state.setdefault('research_leads', []))+1:05d}"


def _known_urls(state: Dict[str, Any]) -> set[str]:
    return {x.get("url", "") for x in state.setdefault("research_leads", []) if x.get("url")}


def _store_results(state: Dict[str, Any], query: str, lead_type: str, category: str, results: List[Dict[str, str]]) -> int:
    known = _known_urls(state)
    created = 0
    for item in results:
        url = (item.get("url") or "").strip()
        title = (item.get("title") or "").strip()
        if not url or url in known:
            continue
        lead = {
            "id": _lead_id(state),
            "type": lead_type,
            "category": category,
            "title": title,
            "url": url,
            "snippet": (item.get("snippet") or "")[:700],
            "query": query,
            "market": MARKET,
            "status": "research_required",
            "confidence": 0.45,
            "verified_company": False,
            "verified_contact": False,
            "created_at": utcnow(),
        }
        state["research_leads"].append(lead)
        known.add(url)
        created += 1
    return created


def _unique_values(items: List[Dict[str, Any]], field: str) -> List[str]:
    ordered = sorted(items, key=lambda x: x.get("source") == "demo")
    values: List[str] = []
    for item in ordered:
        value = (item.get(field) or "").strip()
        if value and value not in values:
            values.append(value)
    return values


def _supplier_queries(state: Dict[str, Any]) -> List[tuple[str, str, str]]:
    needs = _unique_values(state.get("buyers", []), "need")
    return [(f'"{need}" fabricante distribuidor proveedor {MARKET}', "supplier", need) for need in needs[:2]]


def _buyer_queries(state: Dict[str, Any]) -> List[tuple[str, str, str]]:
    cats = _unique_values(state.get("suppliers", []), "category")
    return [(f'empresa industria mantenimiento compras "{cat}" {MARKET}', "buyer", cat) for cat in cats[:2]]


def scout_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    state.setdefault("research_leads", [])
    stats = {"configured": bool(PROVIDER and API_KEY), "queries": 0, "new_leads": 0, "errors": 0}
    if not stats["configured"]:
        return stats
    queue = _supplier_queries(state) + _buyer_queries(state)
    for query, lead_type, category in queue[:MAX_QUERIES_PER_TICK]:
        try:
            results = search(query)
            created = _store_results(state, query, lead_type, category, results)
            stats["queries"] += 1
            stats["new_leads"] += created
            _log(state, f"Scout investigó {lead_type} para {category}: {created} leads nuevos con evidencia web.")
        except Exception as exc:
            stats["errors"] += 1
            _log(state, f"Scout falló al investigar {category}: {str(exc)[:140]}")
    return stats
