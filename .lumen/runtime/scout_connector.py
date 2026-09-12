from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

PROVIDER = os.getenv("LUMEN_SCOUT_PROVIDER", "").strip().lower()
API_KEY = os.getenv("LUMEN_SCOUT_API_KEY", "").strip()
CUSTOM_ENDPOINT = os.getenv("LUMEN_SCOUT_ENDPOINT", "").strip()
MARKET = os.getenv("LUMEN_SCOUT_MARKET", "Argentina").strip() or "Argentina"
COUNTRY_CODE = os.getenv("LUMEN_SCOUT_GL", "ar").strip().lower() or "ar"
LANGUAGE = os.getenv("LUMEN_SCOUT_HL", "es").strip().lower() or "es"
MAX_QUERIES_PER_TICK = max(1, min(5, int(os.getenv("LUMEN_SCOUT_MAX_QUERIES", "2"))))
DAILY_QUERY_BUDGET = max(2, min(500, int(os.getenv("LUMEN_SCOUT_DAILY_BUDGET", "24"))))
MAX_NEW_LEADS_PER_QUERY = max(1, min(8, int(os.getenv("LUMEN_SCOUT_MAX_NEW_LEADS", "4"))))

STRONG_DEMAND_TERMS = (
    "licitación", "licitacion", "cotización", "cotizacion", "convocatoria", "compras",
    "proveedores", "pliego", "abastecimiento", "concurso de precios", "solicitud de oferta",
    "rfq", "tender", "procurement",
)
STOPWORDS = {"para", "con", "una", "uno", "del", "las", "los", "por", "que", "and", "the", "argentina", "empresa"}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def utcdate() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def status() -> Dict[str, Any]:
    return {
        "provider": PROVIDER or None,
        "configured": bool(PROVIDER and API_KEY),
        "market": MARKET,
        "country_code": COUNTRY_CODE,
        "language": LANGUAGE,
        "max_queries_per_tick": MAX_QUERIES_PER_TICK,
        "daily_query_budget": DAILY_QUERY_BUDGET,
        "max_new_leads_per_query": MAX_NEW_LEADS_PER_QUERY,
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
        if created >= MAX_NEW_LEADS_PER_QUERY:
            break
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


def _unique_strings(values: List[Any]) -> List[str]:
    out: List[str] = []
    for value in values:
        text = " ".join(str(value or "").strip().split())
        if text and text not in out:
            out.append(text)
    return out


def _verified_accounts(state: Dict[str, Any], account_type: str) -> List[Dict[str, Any]]:
    return [x for x in state.get("candidate_accounts", []) if x.get("type") == account_type and x.get("verified_company")]


def _supplier_categories(state: Dict[str, Any]) -> List[str]:
    real = [x.get("category") for x in _verified_accounts(state, "supplier")]
    fallback = [x.get("category") for x in sorted(state.get("suppliers", []), key=lambda x: x.get("source") == "demo")]
    return _unique_strings(real + fallback)


def _buyer_need_categories(state: Dict[str, Any]) -> List[str]:
    real = [x.get("category") for x in _verified_accounts(state, "buyer")]
    human = [x.get("need") for x in sorted(state.get("buyers", []), key=lambda x: x.get("source") == "demo")]
    return _unique_strings(real + human)


def _supplier_queries(state: Dict[str, Any]) -> List[tuple[str, str, str]]:
    needs = _buyer_need_categories(state)
    return [(f'"{need}" fabricante distribuidor proveedor {MARKET}', "supplier", need) for need in needs[:4]]


def _buyer_queries(state: Dict[str, Any]) -> List[tuple[str, str, str]]:
    cats = _supplier_categories(state)
    return [(f'empresa industria planta mantenimiento "{cat}" {MARKET} -proveedor -distribuidor', "buyer", cat) for cat in cats[:4]]


def _interleave(a: List[tuple[str, str, str]], b: List[tuple[str, str, str]]) -> List[tuple[str, str, str]]:
    out: List[tuple[str, str, str]] = []
    for i in range(max(len(a), len(b))):
        if i < len(a): out.append(a[i])
        if i < len(b): out.append(b[i])
    return out


def _generic_search_plan(state: Dict[str, Any]) -> tuple[str, List[tuple[str, str, str]]]:
    verified_suppliers = _verified_accounts(state, "supplier")
    verified_buyers = _verified_accounts(state, "buyer")
    supplier_q = _supplier_queries(state)
    buyer_q = _buyer_queries(state)

    if verified_suppliers and not verified_buyers:
        return "buyer_gap", buyer_q + supplier_q
    if verified_buyers and not verified_suppliers:
        return "supplier_gap", supplier_q + buyer_q

    buyer_categories = {_norm_category(x.get("category")) for x in verified_buyers if x.get("category")}
    supplier_categories = {_norm_category(x.get("category")) for x in verified_suppliers if x.get("category")}
    missing_buyers = bool(supplier_categories - buyer_categories)
    missing_suppliers = bool(buyer_categories - supplier_categories)
    if missing_buyers and not missing_suppliers:
        return "buyer_category_gap", buyer_q + supplier_q
    if missing_suppliers and not missing_buyers:
        return "supplier_category_gap", supplier_q + buyer_q
    return "balanced", _interleave(buyer_q, supplier_q)


def _norm_category(value: Any) -> str:
    return " ".join(str(value or "").lower().strip().split())


def _budget(state: Dict[str, Any]) -> Dict[str, Any]:
    today = utcdate()
    budget = state.setdefault("scout_budget", {"date": today, "queries_used": 0, "daily_budget": DAILY_QUERY_BUDGET})
    if budget.get("date") != today:
        budget.clear(); budget.update({"date": today, "queries_used": 0, "daily_budget": DAILY_QUERY_BUDGET})
    budget["daily_budget"] = DAILY_QUERY_BUDGET
    budget["queries_used"] = int(budget.get("queries_used", 0))
    budget["queries_remaining"] = max(0, DAILY_QUERY_BUDGET - budget["queries_used"])
    return budget


def _tokens(text: str) -> List[str]:
    return [x.lower() for x in re.findall(r"[A-Za-zÁÉÍÓÚáéíóúÑñ0-9]+", text or "") if len(x) >= 4 and x.lower() not in STOPWORDS]


def _domain(url: str) -> str:
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _demand_candidates(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    today = utcdate()
    out = []
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
    return sorted(out, key=lambda x: float(x.get("verification_score") or 0), reverse=True)


def _demand_query(account: Dict[str, Any]) -> str:
    domain = str(account.get("domain") or "")
    category = str(account.get("category") or "")
    return f'site:{domain} "{category}" (compras OR licitación OR licitacion OR cotización OR cotizacion OR proveedores OR pliego OR abastecimiento)'


def _score_demand(account: Dict[str, Any], item: Dict[str, str]) -> int:
    text = f"{item.get('title','')} {item.get('snippet','')} {item.get('url','')}".lower()
    url_domain = _domain(item.get("url", ""))
    account_domain = str(account.get("domain") or "").lower()
    official = bool(url_domain and (url_domain == account_domain or url_domain.endswith("." + account_domain)))
    strong_hits = sum(1 for term in STRONG_DEMAND_TERMS if term in text)
    cat_tokens = list(dict.fromkeys(_tokens(str(account.get("category") or ""))))
    cat_hits = sum(1 for token in cat_tokens if token in text)
    cat_score = round(30 * cat_hits / max(1, len(cat_tokens))) if cat_tokens else 0
    return max(0, min(100, (35 if official else 0) + min(35, strong_hits * 18) + cat_score))


def _store_demand_signal(state: Dict[str, Any], account: Dict[str, Any], query: str, results: List[Dict[str, str]]) -> bool:
    signals = state.setdefault("demand_signals", [])
    known = {x.get("url") for x in signals if x.get("url")}
    scored = []
    for item in results:
        score = _score_demand(account, item)
        if score <= 0:
            continue
        scored.append((score, item))
    scored.sort(key=lambda x: x[0], reverse=True)
    best_score = scored[0][0] if scored else 0
    evidence_urls: List[str] = []
    for score, item in scored[:3]:
        url = str(item.get("url") or "")
        evidence_urls.append(url)
        if url and url not in known:
            signals.append({
                "id": f"SIG-{len(signals)+1:05d}", "account_id": account.get("id"), "category": account.get("category"),
                "url": url, "title": str(item.get("title") or "")[:300], "snippet": str(item.get("snippet") or "")[:700],
                "score": score, "source": "public_search", "created_at": utcnow(),
            })
            known.add(url)

    verified = best_score >= 75
    account["demand_score"] = best_score
    account["demand_last_checked"] = utcnow()
    account["demand_evidence_urls"] = evidence_urls[:3]
    account["demand_signal"] = verified
    if verified:
        account["demand_status"] = "public_signal_verified"
        account["status"] = "demand_verified"
        account["next_action"] = "Construir tesis de oportunidad y validar requerimiento/contacto comercial"
    else:
        account["demand_status"] = "no_strong_public_signal"
        account["demand_next_check"] = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d")
        account["next_action"] = "Revisar nuevamente señal de demanda más adelante; no contactar por ahora"
    return verified


def scout_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    state.setdefault("research_leads", [])
    budget = _budget(state)
    strategy, generic_queue = _generic_search_plan(state)
    stats = {
        "configured": bool(PROVIDER and API_KEY), "queries": 0, "new_leads": 0, "errors": 0,
        "demand_queries": 0, "demand_signals_verified": 0,
        "buyer_discovery_queries": 0, "supplier_discovery_queries": 0,
        "strategy": strategy,
        "budget_used_today": budget["queries_used"], "budget_remaining": budget["queries_remaining"], "budget_exhausted": False,
    }
    if not stats["configured"]:
        return stats
    if budget["queries_remaining"] <= 0:
        stats["budget_exhausted"] = True
        _log(state, "Scout pausó búsquedas: presupuesto diario agotado; prioriza calificación y seguimiento de evidencia existente.")
        return stats

    allowed = min(MAX_QUERIES_PER_TICK, budget["queries_remaining"])
    used_this_tick = 0

    for account in _demand_candidates(state):
        if used_this_tick >= allowed:
            break
        query = _demand_query(account)
        try:
            budget["queries_used"] += 1; used_this_tick += 1; stats["queries"] += 1; stats["demand_queries"] += 1
            results = search(query)
            if _store_demand_signal(state, account, query, results):
                stats["demand_signals_verified"] += 1
                _log(state, f"Demand Signal verificó evidencia pública de intención para {account.get('id')} ({account.get('category')}).")
            else:
                _log(state, f"Demand Signal no encontró señal pública fuerte para {account.get('id')}; no se habilita contacto.")
        except Exception as exc:
            stats["errors"] += 1
            _log(state, f"Demand Signal falló para {account.get('id')}: {str(exc)[:140]}")

    for query, lead_type, category in generic_queue:
        if used_this_tick >= allowed:
            break
        try:
            budget["queries_used"] += 1; used_this_tick += 1; stats["queries"] += 1
            if lead_type == "buyer": stats["buyer_discovery_queries"] += 1
            else: stats["supplier_discovery_queries"] += 1
            results = search(query)
            created = _store_results(state, query, lead_type, category, results)
            stats["new_leads"] += created
            _log(state, f"Scout [{strategy}] investigó {lead_type} para {category}: {created} leads nuevos con evidencia web.")
        except Exception as exc:
            stats["errors"] += 1
            _log(state, f"Scout falló al investigar {category}: {str(exc)[:140]}")

    budget["queries_remaining"] = max(0, DAILY_QUERY_BUDGET - budget["queries_used"])
    budget["updated_at"] = utcnow()
    budget["last_strategy"] = strategy
    stats["budget_used_today"] = budget["queries_used"]
    stats["budget_remaining"] = budget["queries_remaining"]
    stats["budget_exhausted"] = budget["queries_remaining"] <= 0
    return stats
