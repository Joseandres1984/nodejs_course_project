from __future__ import annotations

import hashlib
import re
import urllib.parse
from typing import Any, Dict, List

import retail_velocity_radar as radar
import scout_connector


_ORIGINAL_TICK = radar.retail_velocity_tick

MAJOR_RETAIL_DOMAINS = {
    "fravega.com", "musimundo.com", "megatone.net", "oncity.com", "cetrogar.com.ar",
    "personal.com.ar", "movistar.com.ar", "claro.com.ar", "samsung.com", "motorola.com.ar",
    "xiaomistore.com.ar", "sony.com.ar",
}

PRICE_RE = re.compile(r"(?:AR\$|\$)\s?\d{1,3}(?:[\.\s]\d{3})+(?:,\d{2})?", re.I)


def _host(url: str) -> str:
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _family(url: str, title: str = "", snippet: str = "") -> str:
    host = _host(url)
    text = f"{title} {snippet}".lower()
    if host.endswith("mercadolibre.com.ar"):
        return "mercadolibre"
    if host.endswith("mitiendanube.com") or "tiendanube" in text:
        return "tiendanube"
    if any(host == d or host.endswith("." + d) for d in MAJOR_RETAIL_DOMAINS):
        if any(x in host for x in ("samsung", "motorola", "xiaomi", "sony")):
            return "brand_store"
        return "major_retail"
    if any(word in text for word in ("mayorista", "distribuidor", "importador", "distribución", "distribucion")):
        return "wholesaler_distributor"
    return "independent_store"


def _price_mentions(title: str, snippet: str) -> List[str]:
    out: List[str] = []
    for value in PRICE_RE.findall(f"{title} {snippet}"):
        value = " ".join(value.split())
        if value not in out:
            out.append(value)
    return out[:4]


def _evidence_key(product: str, url: str) -> str:
    return hashlib.sha1(f"{product}|{url}".encode("utf-8")).hexdigest()[:20]


def _corroboration_query(product: str) -> str:
    # One broad public-web search intentionally mixes Tiendanube, chains, brands and independent stores.
    # Mercado Libre is excluded here because it already supplies the primary velocity signal.
    return (
        f'"{product}" Argentina '
        '(site:mitiendanube.com OR site:fravega.com OR site:musimundo.com OR site:megatone.net '
        'OR site:oncity.com OR site:cetrogar.com.ar OR site:personal.com.ar OR site:movistar.com.ar '
        'OR site:claro.com.ar OR site:samsung.com OR site:motorola.com.ar OR "comprar online") '
        '-site:mercadolibre.com.ar'
    )


def _target_for_corroboration(state: Dict[str, Any]) -> Dict[str, Any] | None:
    rows = list(state.get("retail_product_signals", []) or [])
    rows.sort(key=lambda x: float(x.get("velocity_score") or 0), reverse=True)
    for row in rows:
        if float(row.get("velocity_score") or 0) < float(radar.MIN_VELOCITY_SCORE):
            continue
        if row.get("market_corroboration_done"):
            continue
        if int(row.get("market_corroboration_attempts") or 0) >= 2:
            continue
        return row
    return None


def _store_corroboration(state: Dict[str, Any], product: str, results: List[Dict[str, str]]) -> Dict[str, Any]:
    evidence = state.setdefault("retail_market_evidence", [])
    existing_keys = {str(x.get("key") or "") for x in evidence}
    added = 0
    families = set()
    hosts = set()
    price_mentions: List[str] = []

    for item in results[:8]:
        url = str(item.get("url") or "").strip()
        title = str(item.get("title") or "").strip()
        snippet = str(item.get("snippet") or "").strip()
        if not url:
            continue
        family = _family(url, title, snippet)
        if family == "mercadolibre":
            continue
        host = _host(url)
        key = _evidence_key(product, url)
        families.add(family)
        if host:
            hosts.add(host)
        prices = _price_mentions(title, snippet)
        for value in prices:
            if value not in price_mentions:
                price_mentions.append(value)
        if key in existing_keys:
            continue
        evidence.append({
            "key": key,
            "product": product,
            "source_url": url,
            "source_domain": host,
            "source_family": family,
            "source_title": title[:240],
            "source_snippet": snippet[:700],
            "price_mentions": prices,
            "source_type": "public_retail_corroboration",
            "market": radar.MARKET,
            "observed_at": radar.utcnow(),
        })
        existing_keys.add(key)
        added += 1

    state["retail_market_evidence"] = evidence[-500:]
    return {
        "added": added,
        "families": sorted(families),
        "hosts": sorted(hosts),
        "price_mentions": price_mentions[:10],
    }


def _update_target(target: Dict[str, Any], summary: Dict[str, Any], result_count: int) -> None:
    attempts = int(target.get("market_corroboration_attempts") or 0) + 1
    target["market_corroboration_attempts"] = attempts
    target["market_corroboration_at"] = radar.utcnow()
    target["market_channel_families"] = summary.get("families", [])
    target["market_corroboration_sources"] = len(summary.get("hosts", []) or [])
    target["market_price_mentions"] = summary.get("price_mentions", [])
    families = len(summary.get("families", []) or [])
    hosts = len(summary.get("hosts", []) or [])
    target["market_breadth_score"] = round(min(100.0, 35.0 + families * 15.0 + min(25.0, hosts * 5.0)), 1)
    # Require at least two distinct non-ML sources/families before treating corroboration as complete.
    done = hosts >= 2 and families >= 2
    target["market_corroboration_done"] = done
    target["market_corroboration_status"] = "multi_source_confirmed" if done else "retry_required" if result_count else "no_public_corroboration_yet"


def _expanded_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    report = dict(_ORIGINAL_TICK(state) or {})
    target = _target_for_corroboration(state)
    expansion = {
        "active": bool(scout_connector.status().get("configured")),
        "mode": "argentina_multi_source_retail_corroboration",
        "query_used": 0,
        "product": None,
        "sources_added": 0,
        "families": [],
        "policy": "public_search_only_no_direct_scraping_no_verbatim_copy",
    }

    if not target or not expansion["active"]:
        expansion["reason"] = "no_high_velocity_target_or_search_unavailable"
        report["market_expansion"] = expansion
        state["retail_market_expansion"] = expansion
        return report

    # Respect the same protected retail/global budget policy already installed by worker_with_demand.
    if not radar._consume_search_budget(state):
        expansion["reason"] = "retail_or_global_budget_unavailable"
        report["market_expansion"] = expansion
        state["retail_market_expansion"] = expansion
        return report

    product = str(target.get("product") or "").strip()
    expansion["product"] = product
    try:
        results = scout_connector.search(_corroboration_query(product))
        summary = _store_corroboration(state, product, results)
        _update_target(target, summary, len(results))
        expansion.update({
            "query_used": 1,
            "sources_added": int(summary.get("added") or 0),
            "families": summary.get("families", []),
            "source_domains": summary.get("hosts", []),
            "price_mentions": summary.get("price_mentions", []),
            "market_breadth_score": target.get("market_breadth_score"),
            "corroboration_status": target.get("market_corroboration_status"),
        })
    except Exception as exc:
        expansion["error"] = f"{type(exc).__name__}: {str(exc)[:220]}"

    report["market_expansion"] = expansion
    state["retail_market_expansion"] = expansion
    state["retail_velocity_radar"] = report
    return report


radar.retail_velocity_tick = _expanded_tick
