from __future__ import annotations

import hashlib
import os
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import agent_fleet
import scout_connector


MAX_STORES = max(20, min(500, int(os.getenv("LUMEN_PARTNER_MAX_STORES", "180"))))
MAX_STORES_PER_CYCLE = max(1, min(12, int(os.getenv("LUMEN_PARTNER_STORES_PER_CYCLE", "4"))))
MAX_SEARCHES_PER_CYCLE = max(0, min(10, int(os.getenv("LUMEN_PARTNER_SEARCHES_PER_CYCLE", "3"))))
DAILY_SEARCH_CAP = max(0, min(60, int(os.getenv("LUMEN_PARTNER_DAILY_SEARCH_CAP", "8"))))
MAX_PRODUCTS_PER_STORE = max(5, min(100, int(os.getenv("LUMEN_PARTNER_MAX_PRODUCTS_PER_STORE", "35"))))
MAX_ACTIVE_OFFERS = max(10, min(500, int(os.getenv("LUMEN_PARTNER_MAX_ACTIVE_OFFERS", "120"))))

LOW_VALUE_HOSTS = {
    "facebook.com", "instagram.com", "linkedin.com", "youtube.com", "reddit.com",
    "mercadolibre.com.ar", "mercadolibre.com", "amazon.com", "pinterest.com",
    "google.com", "bing.com", "yahoo.com",
}
AFFILIATE_TERMS = (
    "afiliado", "afiliados", "affiliate", "partners", "partner", "referidos", "referidos",
    "revendedor", "revendedores", "programa de afiliados", "programa de partners",
)
CONTACT_TERMS = ("contacto", "ventas", "comercial", "whatsapp", "email", "correo")
PRICE_RE = re.compile(r"(?:AR\$|\$)\s?\d{1,3}(?:[\.\s]\d{3})+(?:,\d{2})?", re.I)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _clean(value: Any, limit: int = 500) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _host(url: str) -> str:
    try:
        return (urllib.parse.urlparse(str(url or "")).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _allowed_host(host: str) -> bool:
    return bool(host) and not any(host == x or host.endswith("." + x) for x in LOW_VALUE_HOSTS)


def _store_key(domain: str) -> str:
    return hashlib.sha1(domain.lower().encode("utf-8")).hexdigest()[:14]


def _partner_id(domain: str) -> str:
    return "PST-" + _store_key(domain).upper()


def _product_key(domain: str, url: str, title: str) -> str:
    return hashlib.sha1(f"{domain}|{url}|{title}".encode("utf-8")).hexdigest()[:18]


def _price_mentions(text: str) -> List[str]:
    out: List[str] = []
    for value in PRICE_RE.findall(text or ""):
        value = " ".join(value.split())
        if value not in out:
            out.append(value)
    return out[:5]


def _budget(state: Dict[str, Any]) -> Dict[str, Any]:
    today = agent_fleet.local_day()
    row = state.setdefault("partner_network_budget", {})
    if row.get("date") != today:
        row.clear()
        row.update({"date": today, "searches_used": 0, "daily_cap": DAILY_SEARCH_CAP, "reset_at": utcnow()})
    row["daily_cap"] = DAILY_SEARCH_CAP
    row["searches_used"] = max(0, int(row.get("searches_used") or 0))
    row["searches_remaining"] = max(0, DAILY_SEARCH_CAP - row["searches_used"])
    return row


def _consume_search(state: Dict[str, Any], cycle: Dict[str, int]) -> bool:
    if cycle["used"] >= MAX_SEARCHES_PER_CYCLE:
        return False
    local = _budget(state)
    global_budget = agent_fleet._budget(state)
    if int(local.get("searches_remaining") or 0) <= 0:
        return False
    if int(global_budget.get("general_queries_remaining") or 0) <= 0:
        return False
    local["searches_used"] = int(local.get("searches_used") or 0) + 1
    global_budget["queries_used"] = int(global_budget.get("queries_used") or 0) + 1
    cycle["used"] += 1
    _budget(state)
    agent_fleet._budget(state)
    return True


def _ensure_store(stores: List[Dict[str, Any]], by_domain: Dict[str, Dict[str, Any]], domain: str, *, name: str = "", source: str = "", url: str = "", category: str = "", family: str = "") -> Optional[Dict[str, Any]]:
    domain = domain.lower().removeprefix("www.")
    if not _allowed_host(domain):
        return None
    store = by_domain.get(domain)
    if not store:
        store = {
            "id": _partner_id(domain),
            "domain": domain,
            "name": _clean(name, 180) or domain,
            "commercial_status": "prospect",
            "agreement_required": True,
            "commission_authorized": False,
            "commission_model": None,
            "commission_rate": None,
            "source_families": [],
            "source_urls": [],
            "categories": [],
            "catalog_products": [],
            "catalog_searches": 0,
            "catalog_last_checked_at": None,
            "affiliate_program_hint": False,
            "affiliate_evidence": [],
            "contact_hints": [],
            "created_at": utcnow(),
            "updated_at": utcnow(),
            "next_action": "Investigar catálogo y vía comercial antes de proponer partnership",
        }
        stores.append(store)
        by_domain[domain] = store
    if name and (store.get("name") in {None, "", domain}):
        store["name"] = _clean(name, 180)
    if family and family not in store["source_families"]:
        store["source_families"].append(family)
    if source and source not in store["source_families"]:
        store["source_families"].append(source)
    if url and url not in store["source_urls"]:
        store["source_urls"].append(url)
        store["source_urls"] = store["source_urls"][-20:]
    if category and category not in store["categories"]:
        store["categories"].append(category)
        store["categories"] = store["categories"][-20:]
    store["updated_at"] = utcnow()
    return store


def _add_product(store: Dict[str, Any], *, title: str, url: str, snippet: str = "", category: str = "", source: str = "search_index") -> bool:
    title = _clean(title, 260)
    url = _clean(url, 900)
    if not title or not url:
        return False
    host = _host(url)
    if host and not (host == store.get("domain") or host.endswith("." + str(store.get("domain") or ""))):
        return False
    path = urllib.parse.urlparse(url).path.strip("/")
    if not path or path.lower() in {"contacto", "contact", "nosotros", "about", "blog", "ayuda"}:
        return False
    key = _product_key(str(store.get("domain") or ""), url, title)
    products = store.setdefault("catalog_products", [])
    existing = next((x for x in products if x.get("key") == key or x.get("url") == url), None)
    row = {
        "key": key,
        "title": title,
        "url": url,
        "snippet": _clean(snippet, 700),
        "category": _clean(category, 160),
        "price_mentions": _price_mentions(f"{title} {snippet}"),
        "source": source,
        "observed_at": utcnow(),
        "eligible_for_publication": False,
        "publication_reason": "partner_agreement_required",
    }
    if existing:
        existing.update({k: v for k, v in row.items() if v not in {None, "", []}})
        return False
    products.append(row)
    store["catalog_products"] = products[-MAX_PRODUCTS_PER_STORE:]
    return True


def _sync_existing_evidence(state: Dict[str, Any]) -> int:
    stores = state.setdefault("partner_stores", [])
    by_domain = {str(x.get("domain") or "").lower(): x for x in stores if x.get("domain")}
    before = len(stores)

    for ev in state.get("retail_market_evidence", []) or []:
        url = _clean(ev.get("source_url"), 900)
        domain = _clean(ev.get("source_domain"), 220) or _host(url)
        family = _clean(ev.get("source_family"), 80)
        if family == "mercadolibre":
            continue
        store = _ensure_store(
            stores, by_domain, domain,
            name=_clean(ev.get("source_title"), 180), source="retail_market_evidence", url=url,
            category=_clean(ev.get("product"), 160), family=family,
        )
        if store and url:
            _add_product(
                store,
                title=_clean(ev.get("product") or ev.get("source_title"), 260),
                url=url,
                snippet=_clean(ev.get("source_snippet"), 700),
                category=_clean(ev.get("product"), 160),
                source="retail_market_evidence",
            )

    for account in state.get("candidate_accounts", []) or []:
        if account.get("type") != "supplier":
            continue
        domain = _clean(account.get("domain"), 220)
        url = _clean(account.get("source_url"), 900)
        _ensure_store(
            stores, by_domain, domain or _host(url),
            name=_clean(account.get("name_hint"), 180), source="supplier_account", url=url,
            category=_clean(account.get("category"), 160), family="b2b_supplier",
        )

    for lead in state.get("research_leads", []) or []:
        if lead.get("type") != "supplier":
            continue
        url = _clean(lead.get("url"), 900)
        _ensure_store(
            stores, by_domain, _clean(lead.get("domain"), 220) or _host(url),
            name=_clean(lead.get("title"), 180), source="supplier_research", url=url,
            category=_clean(lead.get("category"), 160), family="supplier_research",
        )

    state["partner_stores"] = stores[-MAX_STORES:]
    return max(0, len(state["partner_stores"]) - before)


def _apply_agreements(state: Dict[str, Any]) -> int:
    agreements = list(state.get("partner_agreements", []) or [])
    by_domain = {str(x.get("domain") or "").lower().removeprefix("www."): x for x in agreements if x.get("domain")}
    activated = 0
    for store in state.get("partner_stores", []) or []:
        domain = str(store.get("domain") or "").lower()
        agreement = by_domain.get(domain)
        active = False
        if agreement:
            status = str(agreement.get("status") or "").lower()
            rate = agreement.get("commission_pct") or agreement.get("commission_rate")
            fixed = agreement.get("fixed_fee") or agreement.get("fixed_fee_usd")
            affiliate_url = agreement.get("affiliate_url_template") or agreement.get("affiliate_base_url")
            active = status in {"active", "approved", "executed", "enrolled"} and bool(rate or fixed or affiliate_url)
        previous = bool(store.get("commission_authorized"))
        store["commission_authorized"] = active
        store["agreement_required"] = not active
        if active:
            store["commercial_status"] = "active_partner"
            store["commission_model"] = agreement.get("commission_model") or ("percentage" if agreement.get("commission_pct") or agreement.get("commission_rate") else "fixed_or_affiliate")
            store["commission_rate"] = agreement.get("commission_pct") or agreement.get("commission_rate")
            store["agreement_id"] = agreement.get("id")
            store["affiliate_url_template"] = agreement.get("affiliate_url_template") or agreement.get("affiliate_base_url")
            store["append_ref_param"] = bool(agreement.get("append_ref_param"))
            store["next_action"] = "Publicar únicamente productos elegibles y medir atribución/conversión"
            if not previous:
                activated += 1
        elif store.get("affiliate_program_hint"):
            store["commercial_status"] = "affiliate_program_detected"
            store["next_action"] = "Evaluar/enrolarse en el programa; la aceptación de términos requiere autorización humana"
        else:
            store["commercial_status"] = "prospect"
            store["next_action"] = "Contactar al comercio y proponer comisión/success fee antes de publicar como partner"
    return activated


def _search_store(state: Dict[str, Any], store: Dict[str, Any], cycle: Dict[str, int]) -> Dict[str, int]:
    if not _consume_search(state, cycle):
        return {"products": 0, "affiliate": 0, "contact": 0}
    domain = str(store.get("domain") or "")
    category = str((store.get("categories") or [""])[0] or "")
    query = f'site:{domain} ({"\"" + category + "\" " if category else ""})(comprar OR producto OR tienda OR catálogo OR catalogo OR stock)'
    try:
        results = list(scout_connector.search(query) or [])[:10]
    except Exception as exc:
        store.setdefault("history", []).append({"ts": utcnow(), "event": "catalog_search_error", "detail": f"{type(exc).__name__}: {str(exc)[:180]}"})
        return {"products": 0, "affiliate": 0, "contact": 0}

    products = 0
    affiliate = 0
    contact = 0
    for item in results:
        url = _clean(item.get("url"), 900)
        title = _clean(item.get("title"), 260)
        snippet = _clean(item.get("snippet"), 700)
        text = f"{title} {snippet}".lower()
        if any(term in text for term in AFFILIATE_TERMS):
            store["affiliate_program_hint"] = True
            ev = {"url": url, "title": title, "snippet": snippet, "observed_at": utcnow()}
            if url and not any(x.get("url") == url for x in store.setdefault("affiliate_evidence", [])):
                store["affiliate_evidence"].append(ev)
                store["affiliate_evidence"] = store["affiliate_evidence"][-10:]
                affiliate += 1
        if any(term in text for term in CONTACT_TERMS):
            if url and url not in store.setdefault("contact_hints", []):
                store["contact_hints"].append(url)
                store["contact_hints"] = store["contact_hints"][-10:]
                contact += 1
        if _add_product(store, title=title, url=url, snippet=snippet, category=category, source="public_search_index"):
            products += 1

    store["catalog_searches"] = int(store.get("catalog_searches") or 0) + 1
    store["catalog_last_checked_at"] = utcnow()
    store["updated_at"] = utcnow()
    return {"products": products, "affiliate": affiliate, "contact": contact}


def _offer_token(partner_id: str, product_key: str) -> str:
    return hashlib.sha256(f"LUMEN|{partner_id}|{product_key}".encode("utf-8")).hexdigest()[:16].upper()


def _sync_referral_offers(state: Dict[str, Any]) -> int:
    offers = state.setdefault("partner_referral_offers", [])
    known = {str(x.get("offer_key") or ""): x for x in offers if x.get("offer_key")}
    created = 0
    for store in state.get("partner_stores", []) or []:
        active = bool(store.get("commission_authorized")) and store.get("commercial_status") == "active_partner"
        for product in store.get("catalog_products", []) or []:
            product["eligible_for_publication"] = active
            product["publication_reason"] = "authorized_partner" if active else "partner_agreement_required"
            if not active:
                continue
            offer_key = f"{store.get('id')}|{product.get('key')}"
            row = known.get(offer_key)
            if not row:
                token = _offer_token(str(store.get("id")), str(product.get("key")))
                row = {
                    "id": f"PROF-{len(offers)+1:05d}",
                    "offer_key": offer_key,
                    "token": token,
                    "partner_id": store.get("id"),
                    "partner_domain": store.get("domain"),
                    "partner_name": store.get("name"),
                    "product_key": product.get("key"),
                    "title": product.get("title"),
                    "category": product.get("category"),
                    "source_url": product.get("url"),
                    "price_mentions": product.get("price_mentions", []),
                    "commission_model": store.get("commission_model"),
                    "commission_rate": store.get("commission_rate"),
                    "agreement_id": store.get("agreement_id"),
                    "status": "active",
                    "lumen_referral_path": f"/go/{token}",
                    "created_at": utcnow(),
                    "updated_at": utcnow(),
                }
                offers.append(row)
                known[offer_key] = row
                created += 1
            else:
                row.update({
                    "title": product.get("title"), "source_url": product.get("url"),
                    "price_mentions": product.get("price_mentions", []), "status": "active",
                    "commission_model": store.get("commission_model"), "commission_rate": store.get("commission_rate"),
                    "agreement_id": store.get("agreement_id"), "updated_at": utcnow(),
                })
    state["partner_referral_offers"] = offers[-MAX_ACTIVE_OFFERS:]
    return created


def partner_network_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    """Discover stores, inspect indexed catalog evidence and prepare commission-attributed referrals.

    Discovery and catalog research may use public search results. LUMEN never represents a store as a
    commercial partner merely because it was found online. Referral offers become active only when an
    explicit partner_agreement in state proves commission/affiliate authorization. This keeps the buyer
    paying the original merchant and the merchant fulfilling the order while LUMEN earns only its agreed fee.
    """
    created_stores = _sync_existing_evidence(state)
    activated = _apply_agreements(state)
    cycle = {"used": 0}
    searched = 0
    products_added = 0
    affiliate_hints = 0
    contacts = 0

    stores = list(state.get("partner_stores", []) or [])
    prospects = sorted(
        stores,
        key=lambda x: (
            0 if x.get("commission_authorized") else 1,
            int(x.get("catalog_searches") or 0),
            -len(x.get("source_urls", []) or []),
            str(x.get("domain") or ""),
        ),
    )
    for store in prospects[:MAX_STORES_PER_CYCLE]:
        if cycle["used"] >= MAX_SEARCHES_PER_CYCLE:
            break
        if int(_budget(state).get("searches_remaining") or 0) <= 0:
            break
        if int(agent_fleet._budget(state).get("general_queries_remaining") or 0) <= 0:
            break
        result = _search_store(state, store, cycle)
        searched += 1
        products_added += result["products"]
        affiliate_hints += result["affiliate"]
        contacts += result["contact"]

    # Re-evaluate statuses after fresh affiliate evidence, then create referral links only for authorized partners.
    _apply_agreements(state)
    offers_created = _sync_referral_offers(state)

    report = {
        "version": "1.0",
        "updated_at": utcnow(),
        "status": "healthy",
        "stores_total": len(state.get("partner_stores", []) or []),
        "stores_created": created_stores,
        "stores_searched": searched,
        "products_added": products_added,
        "affiliate_hints_added": affiliate_hints,
        "contact_hints_added": contacts,
        "active_partners": sum(1 for x in state.get("partner_stores", []) or [] if x.get("commercial_status") == "active_partner"),
        "agreement_required": sum(1 for x in state.get("partner_stores", []) or [] if x.get("agreement_required")),
        "partners_activated": activated,
        "referral_offers_active": sum(1 for x in state.get("partner_referral_offers", []) or [] if x.get("status") == "active"),
        "referral_offers_created": offers_created,
        "searches_used": cycle["used"],
        "partner_search_budget_remaining": int(_budget(state).get("searches_remaining") or 0),
        "global_general_search_remaining": int(agent_fleet._budget(state).get("general_queries_remaining") or 0),
        "commercial_rule": "buyer_pays_store_store_fulfills_lumen_receives_only_agreed_commission",
        "publication_gate": "active_referral_requires_explicit_partner_agreement",
    }
    state["partner_network"] = report
    state.setdefault("activity", []).insert(0, {
        "ts": utcnow(),
        "msg": (
            f"Partner Network: {report['stores_total']} tiendas mapeadas, {report['active_partners']} partners activos, "
            f"{report['referral_offers_active']} ofertas atribuibles; {cycle['used']} búsquedas de catálogo este ciclo."
        ),
    })
    state["activity"] = state["activity"][:100]
    return report
