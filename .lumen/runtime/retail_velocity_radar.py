from __future__ import annotations

import math
import os
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict

import scout_connector

MARKET = os.getenv("LUMEN_SCOUT_MARKET", "Argentina").strip() or "Argentina"
DAILY_RETAIL_BUDGET = max(1, min(12, int(os.getenv("LUMEN_RETAIL_DAILY_BUDGET", "4"))))
MIN_VELOCITY_SCORE = max(50, min(95, int(os.getenv("LUMEN_RETAIL_MIN_VELOCITY_SCORE", "68"))))
MAX_SIGNALS = max(20, min(240, int(os.getenv("LUMEN_RETAIL_MAX_SIGNALS", "120"))))

DISCOVERY_LANES = (
    ("smartphones", 'site:mercadolibre.com.ar "MÁS VENDIDO" celular smartphone Samsung Motorola Xiaomi Argentina'),
    ("wearables", 'site:mercadolibre.com.ar "MÁS VENDIDO" smartwatch smart band Samsung Xiaomi Garmin Argentina'),
    ("audio", 'site:mercadolibre.com.ar "MÁS VENDIDO" auriculares bluetooth Redmi Sony Samsung Argentina'),
    ("charging", 'site:mercadolibre.com.ar "MÁS VENDIDO" cargador power bank USB-C Xiaomi Samsung Apple Argentina'),
)

UNSAFE_COPY_TERMS = ("réplica", "replica", "imitación", "imitacion", "clon", "fake", "trucho", "copia aaa")
GENERIC_TITLES = (
    "más vendidos", "mas vendidos", "mercadolibre argentina", "celulares y teléfonos", "celulares y telefonos",
    "smartwatches y accesorios", "los más vendidos", "los mas vendidos",
)
SALES_RE = re.compile(r"\+?\s*(\d+(?:[\.,]\d+)?)\s*(mil|k)?\s+(?:productos?\s+)?vendid", re.I)
RANK_RE = re.compile(r"\b([1-9]|10)[º°]?\s*(?:más|mas)\s+vendido", re.I)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def utcdate() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _host(url: str) -> str:
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _safe_title(raw: str) -> str:
    text = _norm(raw)
    low = text.lower()
    for sep in (" | mercadolibre", " - mercado libre", " | mercado libre"):
        idx = low.find(sep)
        if idx >= 0:
            text = text[:idx]
            break
    text = re.sub(r"\b\d+[º°]?\s*(?:MÁS|MAS)\s+VENDIDO\b", "", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip(" -|·")[:150]


def _sales_count(text: str) -> int:
    match = SALES_RE.search(text or "")
    if not match:
        return 0
    value = float(match.group(1).replace(",", "."))
    if (match.group(2) or "").lower() in {"mil", "k"}:
        value *= 1000
    return int(value)


def _copy_risk(text: str) -> bool:
    low = (text or "").lower()
    return any(term in low for term in UNSAFE_COPY_TERMS)


def _is_generic_title(title: str) -> bool:
    low = title.lower().strip()
    return any(low == x or low.startswith(x + " |") for x in GENERIC_TITLES)


def _velocity_score(item: Dict[str, str]) -> float:
    title = str(item.get("title") or "")
    snippet = str(item.get("snippet") or "")
    url = str(item.get("url") or "")
    text = f"{title} {snippet}"
    score = 28.0
    if "más vendido" in text.lower() or "mas vendido" in text.lower():
        score += 18.0
    rank = RANK_RE.search(text)
    if rank:
        position = int(rank.group(1))
        score += max(4.0, 18.0 - position)
    sales = _sales_count(text)
    if sales:
        score += min(34.0, 7.0 * math.log10(max(10, sales)))
    if _host(url).endswith("mercadolibre.com.ar"):
        score += 8.0
    return round(min(100.0, score), 1)


def _retail_budget(state: Dict[str, Any]) -> Dict[str, Any]:
    today = utcdate()
    row = state.setdefault("retail_velocity_budget", {"date": today, "queries_used": 0})
    if row.get("date") != today:
        row.clear(); row.update({"date": today, "queries_used": 0})
    row["daily_budget"] = DAILY_RETAIL_BUDGET
    row["queries_used"] = int(row.get("queries_used", 0))
    row["queries_remaining"] = max(0, DAILY_RETAIL_BUDGET - row["queries_used"])
    return row


def _consume_search_budget(state: Dict[str, Any]) -> bool:
    global_budget = scout_connector._budget(state)
    own = _retail_budget(state)
    if int(global_budget.get("queries_remaining") or 0) <= 1 or int(own.get("queries_remaining") or 0) <= 0:
        return False
    global_budget["queries_used"] = int(global_budget.get("queries_used") or 0) + 1
    global_budget["queries_remaining"] = max(0, int(global_budget.get("daily_budget") or 0) - global_budget["queries_used"])
    own["queries_used"] += 1
    own["queries_remaining"] = max(0, DAILY_RETAIL_BUDGET - own["queries_used"])
    return True


def _signal_key(product: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", product.lower())[:90].strip("-")


def _upsert_product_signal(state: Dict[str, Any], lane: str, item: Dict[str, str]) -> bool:
    raw_title = str(item.get("title") or "")
    snippet = str(item.get("snippet") or "")
    url = str(item.get("url") or "")
    product = _safe_title(raw_title)
    if not product or len(product) < 8 or _is_generic_title(product) or _copy_risk(f"{product} {snippet}"):
        return False
    score = _velocity_score(item)
    if score < MIN_VELOCITY_SCORE:
        return False

    rows = state.setdefault("retail_product_signals", [])
    key = _signal_key(product)
    existing = next((x for x in rows if x.get("key") == key), None)
    payload = {
        "key": key,
        "product": product,
        "lane": lane,
        "market": MARKET,
        "velocity_score": score,
        "reported_sales": _sales_count(f"{raw_title} {snippet}"),
        "source_url": url,
        "source_domain": _host(url),
        "source_title": raw_title[:240],
        "source_snippet": snippet[:700],
        "source_type": "public_market_velocity_evidence",
        "status": "supplier_research_required",
        "supplier_search_done": bool((existing or {}).get("supplier_search_done")),
        "commission_path_status": "must_be_agreed_before_close",
        "listing_policy": "original_lumen_copy_from_facts_only_no_source_images_or_verbatim_description",
        "authenticity_policy": "do_not_claim_authorized_reseller_or_originality_without_verification",
        "money_policy": "buyer_pays_supplier_directly_lumen_only_success_fee_or_commission",
        "updated_at": utcnow(),
        "first_seen_at": (existing or {}).get("first_seen_at") or utcnow(),
    }
    if existing:
        existing.update(payload)
    else:
        rows.append(payload)
    rows.sort(key=lambda x: float(x.get("velocity_score") or 0), reverse=True)
    state["retail_product_signals"] = rows[:MAX_SIGNALS]

    signals = state.setdefault("unlinked_demand_signals", [])
    signal_id = f"RETAIL-{key}"
    demand = next((x for x in signals if str(x.get("id") or "") == signal_id), None)
    demand_payload = {
        "id": signal_id,
        "category": product,
        "score": score,
        "source": "retail_velocity_public",
        "source_url": url,
        "public_demand_hint": True,
        "verified_buyer": False,
        "buyer_commitment": False,
        "created_at": (demand or {}).get("created_at") or utcnow(),
        "updated_at": utcnow(),
    }
    if demand:
        demand.update(demand_payload)
    else:
        signals.append(demand_payload)
    state["unlinked_demand_signals"] = signals[-500:]
    return True


def _next_supplier_target(state: Dict[str, Any]):
    rows = [x for x in state.get("retail_product_signals", []) or [] if not x.get("supplier_search_done")]
    rows.sort(key=lambda x: float(x.get("velocity_score") or 0), reverse=True)
    return rows[0] if rows else None


def retail_velocity_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    own = _retail_budget(state)
    global_budget = scout_connector._budget(state)
    report = {
        "active": bool(scout_connector.status().get("configured")),
        "mode": "high_velocity_consumer_radar",
        "queries": 0,
        "products_added_or_refreshed": 0,
        "supplier_leads_created": 0,
        "retail_budget_remaining": int(own.get("queries_remaining") or 0),
        "global_search_budget_remaining": int(global_budget.get("queries_remaining") or 0),
        "copy_policy": "original_lumen_copy_only",
        "money_policy": "commission_or_success_fee_only_no_inventory_no_gross_funds",
    }
    if not report["active"] or not _consume_search_budget(state):
        report["reason"] = "search_not_configured_or_budget_reserved"
        state["retail_velocity_radar"] = report
        return report

    target = _next_supplier_target(state)
    try:
        if target:
            product = str(target.get("product") or "")
            query = f'"{product}" distribuidor mayorista proveedor {MARKET} -mercadolibre'
            results = scout_connector.search(query)
            created = scout_connector._store_results(state, query, "supplier", product, results)
            target["supplier_search_done"] = True
            target["supplier_search_at"] = utcnow()
            target["supplier_leads_created"] = created
            target["status"] = "supplier_verification_in_progress" if created else "supplier_research_retry_later"
            report["supplier_leads_created"] = created
            report["action"] = "supplier_discovery"
            report["target_product"] = product
        else:
            cursor = int(state.get("retail_velocity_cursor") or 0) % len(DISCOVERY_LANES)
            lane, query = DISCOVERY_LANES[cursor]
            results = scout_connector.search(query)
            added = sum(1 for item in results if _upsert_product_signal(state, lane, item))
            state["retail_velocity_cursor"] = (cursor + 1) % len(DISCOVERY_LANES)
            report["products_added_or_refreshed"] = added
            report["action"] = "product_velocity_discovery"
            report["lane"] = lane
        report["queries"] = 1
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {str(exc)[:220]}"

    own = _retail_budget(state)
    global_budget = scout_connector._budget(state)
    report["retail_budget_remaining"] = int(own.get("queries_remaining") or 0)
    report["global_search_budget_remaining"] = int(global_budget.get("queries_remaining") or 0)
    rows = state.get("retail_product_signals", []) or []
    report["signals_total"] = len(rows)
    report["primary_product"] = rows[0] if rows else None
    report["updated_at"] = utcnow()
    state["retail_velocity_radar"] = report
    return report
