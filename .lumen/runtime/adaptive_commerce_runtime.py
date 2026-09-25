from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from statistics import median
from typing import Any, Dict, List, Tuple

import retail_velocity_radar as radar

VERSION = "1.0-adaptive-commerce"
MAX_CANDIDATES = max(20, min(120, int(os.getenv("LUMEN_COMMERCE_MAX_CANDIDATES", "60"))))
MAX_DRAFTS = max(5, min(80, int(os.getenv("LUMEN_COMMERCE_MAX_DRAFTS", "30"))))
MIN_PRETAX_MARGIN_PCT = max(8.0, min(60.0, float(os.getenv("LUMEN_COMMERCE_MIN_MARGIN_PCT", "18"))))
MIN_MARKET_SOURCES = max(2, min(6, int(os.getenv("LUMEN_COMMERCE_MIN_MARKET_SOURCES", "2"))))
PRICE_DISCOUNT_PCT = max(0.0, min(12.0, float(os.getenv("LUMEN_COMMERCE_MARKET_DISCOUNT_PCT", "2"))))
CONSERVATIVE_PAYMENT_FEE_PCT = max(0.0, min(20.0, float(os.getenv("LUMEN_COMMERCE_CONSERVATIVE_PAYMENT_FEE_PCT", "10"))))
CONSERVATIVE_RETURN_RESERVE_PCT = max(0.0, min(20.0, float(os.getenv("LUMEN_COMMERCE_CONSERVATIVE_RETURN_RESERVE_PCT", "4"))))

PRICE_RE = re.compile(r"(?:AR\$|\$)\s*([0-9][0-9\.\s]*(?:,[0-9]{1,2})?)", re.I)
AVAILABLE_TERMS = {"available", "in stock", "instock", "disponible", "en stock", "stock", "ready"}
DROPSHIP_TERMS = {"dropship", "dropshipping", "drop shipping", "direct_to_customer", "direct-to-customer", "supplier_to_customer", "supplier-to-customer", "envio directo", "envío directo"}
INCLUDED_TERMS = {"included", "incluido", "incluida", "free", "gratis", "sin cargo", "0"}
RESTRICTED_TERMS = (
    "cerveza", "vino ", "whisky", "vodka", "fernet", "licor", "tabaco", "cigarrillo", "vape",
    "nicotina", "cannabis", "marihuana", "thc", "cbd", "esteroide", "hormona", "sildenafil",
    "réplica", "replica", "imitación", "imitacion", "clon", "fake", "trucho", "copia aaa",
)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().strip().split())


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _norm(value) in {"1", "true", "yes", "si", "sí", "verified", "confirmed", "approved", "allowed"}


def _same_product(a: Any, b: Any) -> bool:
    aa, bb = _norm(a), _norm(b)
    if not aa or not bb:
        return False
    if aa == bb or aa in bb or bb in aa:
        return True
    aw = {x for x in re.split(r"[^a-z0-9áéíóúñ]+", aa) if len(x) >= 4}
    bw = {x for x in re.split(r"[^a-z0-9áéíóúñ]+", bb) if len(x) >= 4}
    return len(aw & bw) >= 2


def _restricted(text: Any) -> bool:
    low = _norm(text)
    return any(term in low for term in RESTRICTED_TERMS)


def _parse_ars_price(value: Any) -> float | None:
    text = str(value or "")
    match = PRICE_RE.search(text)
    if not match:
        return None
    raw = match.group(1).replace(" ", "")
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    else:
        raw = raw.replace(".", "")
    try:
        amount = float(raw)
    except ValueError:
        return None
    return amount if amount > 0 else None


def _market_prices(state: Dict[str, Any], signal: Dict[str, Any]) -> Tuple[List[float], List[str]]:
    product = str(signal.get("product") or "")
    values: List[float] = []
    sources: List[str] = []
    for text in (signal.get("source_title"), signal.get("source_snippet")):
        price = _parse_ars_price(text)
        if price:
            values.append(price)
            source = str(signal.get("source_domain") or "mercadolibre.com.ar")
            if source and source not in sources:
                sources.append(source)
    for row in state.get("retail_market_evidence", []) or []:
        if not _same_product(row.get("product"), product):
            continue
        parsed = [p for p in (_parse_ars_price(x) for x in list(row.get("price_mentions", []) or [])) if p]
        if not parsed:
            continue
        values.extend(parsed)
        source = str(row.get("source_domain") or "").strip().lower()
        if source and source not in sources:
            sources.append(source)
    values = sorted({round(x, 2) for x in values if x > 0})
    return values[:20], sources[:12]


def _offer_category(state: Dict[str, Any], offer: Dict[str, Any]) -> str:
    for key in ("product", "title", "category", "need", "technical_scope"):
        value = str(offer.get(key) or "").strip()
        if value:
            return value
    deal_id = str(offer.get("deal_id") or "")
    if deal_id:
        deal = next((x for x in state.get("deals", []) or [] if str(x.get("id") or "") == deal_id), None)
        if deal:
            return str(deal.get("need") or deal.get("category") or deal.get("product") or "")
    return ""


def _supplier_account(state: Dict[str, Any], offer: Dict[str, Any]) -> Dict[str, Any]:
    supplier_id = str(offer.get("supplier_account_id") or "")
    supplier_name = _norm(offer.get("supplier"))
    for account in state.get("candidate_accounts", []) or []:
        if account.get("type") != "supplier":
            continue
        if supplier_id and str(account.get("id") or "") == supplier_id:
            return account
        names = {_norm(account.get("company_name")), _norm(account.get("name_hint")), _norm(account.get("site_title")), _norm(account.get("domain"))}
        if supplier_name and supplier_name in names:
            return account
    return {}


def _supplier_verified(account: Dict[str, Any]) -> bool:
    if not account or not bool(account.get("verified_company")):
        return False
    return str((account.get("supplier_network_profile") or {}).get("tier") or "").lower() != "blocked"


def _dropship_allowed(offer: Dict[str, Any]) -> bool:
    for key in ("dropship_allowed", "dropshipping_allowed", "direct_to_customer", "direct_fulfillment", "supplier_delivers_to_customer"):
        if _truthy(offer.get(key)):
            return True
    low = _norm(" ".join(str(offer.get(k) or "") for k in ("fulfillment_mode", "delivery_mode", "shipping_terms", "delivery_terms")))
    return any(term in low for term in DROPSHIP_TERMS)


def _stock_ready(offer: Dict[str, Any]) -> bool:
    for key in ("stock", "stock_count", "available_units", "inventory", "inventory_count"):
        if offer.get(key) not in (None, ""):
            return _f(offer.get(key), -1) > 0
    return _norm(offer.get("availability") or offer.get("stock_status") or offer.get("inventory_status")) in AVAILABLE_TERMS


def _returns_known(offer: Dict[str, Any]) -> bool:
    return any(offer.get(key) not in (None, "", "unknown", "por validar") for key in ("return_policy", "returns_policy", "return_terms", "returns_days", "warranty_returns"))


def _traceable(offer: Dict[str, Any]) -> bool:
    if _truthy(offer.get("source_traceable")):
        return True
    return any(str(offer.get(key) or "").startswith("http") for key in ("source_url", "quote_url", "evidence_url"))


def _trade_landed_cost(state: Dict[str, Any], offer: Dict[str, Any]) -> Tuple[float | None, str | None]:
    offer_id = str(offer.get("id") or "")
    for case in state.get("trade_cases", []) or []:
        if offer_id and str(case.get("offer_id") or "") != offer_id:
            continue
        if case.get("decision_ready") is not True:
            continue
        cost = _f(case.get("landed_cost"), 0.0)
        if cost > 0:
            return cost, "verified_trade_case_landed_cost"
    return None, None


def _supplier_cost(state: Dict[str, Any], offer: Dict[str, Any]) -> Tuple[float | None, str | None, bool]:
    landed, source = _trade_landed_cost(state, offer)
    if landed:
        return landed, source, True
    for key in ("customer_delivered_cost", "dropship_delivered_cost", "local_delivered_cost", "delivered_total_cost", "all_in_total", "landed_cost"):
        amount = _f(offer.get(key), 0.0)
        if amount > 0:
            return amount, key, True
    amount = _f(offer.get("amount"), 0.0)
    if amount > 0 and _norm(offer.get("amount_scope")) in {"customer_delivered", "delivered_total", "all_in", "landed_total", "puesto_en_destino", "total_entregado"}:
        return amount, "amount_with_delivered_scope", True
    return None, None, False


def _shipping_cost(offer: Dict[str, Any], cost_includes_shipping: bool) -> Tuple[float | None, str | None]:
    if cost_includes_shipping:
        return 0.0, "included_in_supplier_cost"
    for key in ("dropship_shipping_cost", "customer_shipping_cost", "last_mile_cost", "local_delivery_cost", "shipping_cost"):
        if offer.get(key) not in (None, ""):
            amount = _f(offer.get(key), -1.0)
            if amount >= 0:
                return amount, key
    status = _norm(offer.get("shipping_status") or offer.get("local_delivery_status") or offer.get("freight_status"))
    if status in INCLUDED_TERMS:
        return 0.0, "shipping_explicitly_included"
    return None, None


def _fee_pct(offer: Dict[str, Any], keys: Tuple[str, ...], conservative: float) -> Tuple[float, str, bool]:
    for key in keys:
        if offer.get(key) not in (None, ""):
            pct = _f(offer.get(key), -1.0)
            if pct >= 0:
                return min(50.0, pct), key, True
    return conservative, "conservative_policy_ceiling", False


def _tax_pct(offer: Dict[str, Any]) -> Tuple[float, str, bool]:
    for key in ("sales_tax_cost_pct", "commerce_tax_cost_pct", "tax_cost_pct"):
        if offer.get(key) not in (None, ""):
            pct = _f(offer.get(key), -1.0)
            if pct >= 0:
                return min(50.0, pct), key, bool(offer.get("tax_treatment_verified") or _truthy(offer.get("tax_verified")))
    if _truthy(offer.get("tax_treatment_verified")) and _norm(offer.get("tax_terms")) in {"included", "incluido", "included_in_price"}:
        return 0.0, "verified_tax_included", True
    return 0.0, "tax_treatment_missing", False


def _market_reference(prices: List[float]) -> float | None:
    return round(float(median(prices)), 2) if prices else None


def _suggested_price(reference: float) -> float:
    raw = reference * (1.0 - PRICE_DISCOUNT_PCT / 100.0)
    if raw >= 100000:
        return round(raw / 1000.0) * 1000.0
    if raw >= 10000:
        return round(raw / 100.0) * 100.0
    return round(raw / 10.0) * 10.0


def _offer_score(state: Dict[str, Any], signal: Dict[str, Any], offer: Dict[str, Any]) -> Dict[str, Any]:
    account = _supplier_account(state, offer)
    prices, market_sources = _market_prices(state, signal)
    market_reference = _market_reference(prices)
    sale_price = _suggested_price(market_reference) if market_reference else None
    supplier_cost, cost_source, cost_includes_shipping = _supplier_cost(state, offer)
    shipping, shipping_source = _shipping_cost(offer, cost_includes_shipping)
    payment_fee_pct, payment_fee_source, fee_verified = _fee_pct(offer, ("payment_fee_pct", "payment_processing_fee_pct", "checkout_fee_pct"), CONSERVATIVE_PAYMENT_FEE_PCT)
    return_reserve_pct, return_reserve_source, return_reserve_verified = _fee_pct(offer, ("return_reserve_pct", "returns_reserve_pct"), CONSERVATIVE_RETURN_RESERVE_PCT)
    tax_pct, tax_source, tax_verified = _tax_pct(offer)
    checks = {
        "product_not_restricted": not _restricted(signal.get("product")),
        "supplier_verified": _supplier_verified(account),
        "source_traceable": _traceable(offer),
        "dropship_allowed": _dropship_allowed(offer),
        "stock_confirmed": _stock_ready(offer),
        "returns_policy_known": _returns_known(offer),
        "market_price_multisource": bool(market_reference and len(market_sources) >= MIN_MARKET_SOURCES),
        "supplier_cost_known": supplier_cost is not None,
        "shipping_cost_known": shipping is not None,
        "payment_fee_verified": fee_verified,
        "return_reserve_verified": return_reserve_verified,
        "tax_treatment_verified": tax_verified,
    }
    economics: Dict[str, Any] = {
        "currency": "ARS", "market_prices": prices, "market_sources": market_sources,
        "market_reference_price": market_reference, "suggested_sale_price": sale_price,
        "supplier_cost": supplier_cost, "supplier_cost_source": cost_source,
        "shipping_cost": shipping, "shipping_cost_source": shipping_source,
        "payment_fee_pct": round(payment_fee_pct, 3), "payment_fee_source": payment_fee_source,
        "return_reserve_pct": round(return_reserve_pct, 3), "return_reserve_source": return_reserve_source,
        "tax_cost_pct": round(tax_pct, 3), "tax_cost_source": tax_source,
        "market_discount_pct": PRICE_DISCOUNT_PCT, "minimum_margin_pct": MIN_PRETAX_MARGIN_PCT,
    }
    contribution = None
    margin_pct = None
    if sale_price and supplier_cost is not None and shipping is not None:
        payment_fee = sale_price * payment_fee_pct / 100.0
        return_reserve = sale_price * return_reserve_pct / 100.0
        tax_cost = sale_price * tax_pct / 100.0
        contribution = sale_price - supplier_cost - shipping - payment_fee - return_reserve - tax_cost
        margin_pct = contribution / sale_price * 100.0 if sale_price > 0 else None
        economics.update({"payment_fee_amount": round(payment_fee, 2), "return_reserve_amount": round(return_reserve, 2), "tax_cost_amount": round(tax_cost, 2), "contribution_amount": round(contribution, 2), "contribution_margin_pct": round(margin_pct, 2) if margin_pct is not None else None})
    checks["margin_floor_passed"] = bool(margin_pct is not None and margin_pct >= MIN_PRETAX_MARGIN_PCT and contribution and contribution > 0)
    draft_checks = ["product_not_restricted", "supplier_verified", "source_traceable", "dropship_allowed", "stock_confirmed", "returns_policy_known", "market_price_multisource", "supplier_cost_known", "shipping_cost_known", "margin_floor_passed"]
    publication_checks = draft_checks + ["payment_fee_verified", "return_reserve_verified", "tax_treatment_verified"]
    draft_ready = all(checks[name] for name in draft_checks)
    sale_ready = all(checks[name] for name in publication_checks)
    missing = [name for name, passed in checks.items() if not passed]
    status = "SALE_READY_HUMAN_FULFILLMENT_GATE" if sale_ready else "DRAFT_READY_ECONOMICS_CONSERVATIVE" if draft_ready else "RESEARCH_REQUIRED"
    offer_id = str(offer.get("id") or hashlib.sha1(repr(sorted(offer.items())).encode("utf-8", errors="ignore")).hexdigest()[:12])
    supplier_label = str(account.get("company_name") or account.get("name_hint") or offer.get("supplier") or "Proveedor")
    return {
        "product_key": signal.get("key"), "product": signal.get("product"), "consumer_family": signal.get("consumer_family"),
        "offer_id": offer_id, "supplier_account_id": account.get("id"), "supplier": supplier_label,
        "status": status, "draft_ready": draft_ready, "sale_ready": sale_ready, "checks": checks,
        "missing_requirements": missing, "economics": economics,
        "fulfillment": {"mode": "supplier_direct_to_customer", "supplier_purchase_automatic": False, "supplier_purchase_requires_human_approval": True, "customer_funds_do_not_authorize_outgoing_spend": True, "stock_must_be_rechecked_before_order": True},
        "evidence": {"signal_url": signal.get("source_url"), "supplier_source": offer.get("source_url") or offer.get("quote_url") or offer.get("evidence_url"), "market_sources": market_sources},
    }


def _matching_offers(state: Dict[str, Any], signal: Dict[str, Any]) -> List[Dict[str, Any]]:
    product = str(signal.get("product") or "")
    return [offer for offer in state.get("offers", []) or [] if offer.get("source") != "demo/simulación" and not _restricted(_offer_category(state, offer)) and _same_product(_offer_category(state, offer), product)]


def _candidate_rank(row: Dict[str, Any]) -> Tuple[int, float, float]:
    status_rank = {"SALE_READY_HUMAN_FULFILLMENT_GATE": 3, "DRAFT_READY_ECONOMICS_CONSERVATIVE": 2, "RESEARCH_REQUIRED": 1}.get(str(row.get("status")), 0)
    econ = row.get("economics") or {}
    return status_rank, _f(econ.get("contribution_margin_pct"), -999.0), _f(econ.get("contribution_amount"), -999.0)


def _listing_copy(candidate: Dict[str, Any]) -> Dict[str, Any]:
    product = str(candidate.get("product") or "Producto").strip()
    return {
        "title": product[:150],
        "subtitle": "Despacho directo desde proveedor verificado; disponibilidad sujeta a reconfirmación.",
        "description": (f"{product}. Oferta preparada por LUMEN a partir de especificaciones y evidencia pública factual; el texto no copia descripciones ni imágenes de publicaciones de terceros. Stock, plazo, costo de envío y condiciones se reconfirman antes de aceptar una operación vinculante.")[:1800],
        "suggested_price_ars": (candidate.get("economics") or {}).get("suggested_sale_price"),
        "price_is_binding": False, "source_copy_reused": False, "source_images_reused": False,
    }


def commerce_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    signals = [x for x in state.get("retail_product_signals", []) or [] if not _restricted(x.get("product")) and float(x.get("velocity_score") or 0) >= float(radar.MIN_VELOCITY_SCORE)]
    signals.sort(key=lambda x: float(x.get("commercial_priority_score") or x.get("velocity_score") or 0), reverse=True)
    candidates: List[Dict[str, Any]] = []
    requirements: List[Dict[str, Any]] = []
    for signal in signals[:MAX_CANDIDATES]:
        offers = _matching_offers(state, signal)
        if not offers:
            prices, sources = _market_prices(state, signal)
            requirements.append({
                "product_key": signal.get("key"), "product": signal.get("product"), "priority": signal.get("commercial_priority_score") or signal.get("velocity_score"),
                "status": "SUPPLIER_OFFER_REQUIRED", "market_price_points": len(prices), "market_sources": sources,
                "requirements": ["verified_supplier", "traceable_quote", "dropship_permission", "stock", "returns_policy", "customer_delivered_cost", "shipping_cost_or_included_status", "payment_fee_pct", "return_reserve_pct", "tax_treatment_verified"],
                "outbound_message_created": False, "search_budget_increased": False,
            })
            continue
        scored = [_offer_score(state, signal, offer) for offer in offers]
        scored.sort(key=_candidate_rank, reverse=True)
        candidates.append(scored[0])
    candidates.sort(key=_candidate_rank, reverse=True)
    drafts: List[Dict[str, Any]] = []
    for candidate in candidates:
        if not candidate.get("draft_ready"):
            continue
        key = f"{candidate.get('product_key')}|{candidate.get('offer_id')}"
        draft_id = f"COM-{hashlib.sha1(key.encode('utf-8')).hexdigest()[:14].upper()}"
        drafts.append({
            "id": draft_id,
            "status": "ready_for_human_publication_review" if candidate.get("sale_ready") else "economics_draft_requires_fee_tax_validation",
            "product_key": candidate.get("product_key"), "product": candidate.get("product"), "supplier_account_id": candidate.get("supplier_account_id"), "supplier": candidate.get("supplier"), "offer_id": candidate.get("offer_id"),
            "copy": _listing_copy(candidate), "economics": candidate.get("economics"), "checks": candidate.get("checks"),
            "publication": {"owned_channel_first": True, "external_marketplace_autopublish": False, "human_approval_required": True, "publish_allowed": bool(candidate.get("sale_ready"))},
            "fulfillment": candidate.get("fulfillment"), "created_or_refreshed_at": utcnow(),
        })
        if len(drafts) >= MAX_DRAFTS:
            break
    state["commerce_listing_drafts"] = drafts
    state["commerce_supplier_requirements"] = requirements[:MAX_CANDIDATES]
    report = {
        "version": VERSION, "status": "active", "mode": "evidence_gated_dropship_candidate_engine",
        "objective": "turn_public_demand_plus_verified_supplier_fulfillment_into_profitable_listing_drafts_without_inventory",
        "metrics": {"signals_considered": len(signals[:MAX_CANDIDATES]), "candidates_with_supplier_offer": len(candidates), "supplier_offer_required": len(requirements), "draft_ready": sum(1 for x in candidates if x.get("draft_ready")), "sale_ready": sum(1 for x in candidates if x.get("sale_ready")), "listing_drafts": len(drafts)},
        "top_candidates": candidates[:12], "top_requirements": requirements[:12],
        "guardrails": {"copies_third_party_listing_text": False, "copies_third_party_images": False, "restricted_products_allowed": False, "autonomous_supplier_purchase": False, "autonomous_outgoing_spend_usd": 0, "autonomous_contract_acceptance": False, "external_marketplace_autopublish": False, "human_approval_required_for_binding_sale_and_fulfillment": True, "stock_recheck_required_before_fulfillment": True, "revenue_must_be_verified_from_real_payment": True},
        "economics_policy": {"min_margin_pct": MIN_PRETAX_MARGIN_PCT, "min_market_sources": MIN_MARKET_SOURCES, "market_discount_pct": PRICE_DISCOUNT_PCT, "conservative_payment_fee_pct_when_unverified": CONSERVATIVE_PAYMENT_FEE_PCT, "conservative_return_reserve_pct_when_unverified": CONSERVATIVE_RETURN_RESERVE_PCT, "unverified_fee_or_tax_blocks_sale_ready": True},
        "updated_at": utcnow(),
    }
    state["adaptive_commerce"] = report
    return report


_ORIGINAL_RETAIL_TICK = radar.retail_velocity_tick


def _retail_tick_with_commerce(state: Dict[str, Any]) -> Dict[str, Any]:
    report = dict(_ORIGINAL_RETAIL_TICK(state) or {})
    try:
        commerce = commerce_tick(state)
        report["adaptive_commerce"] = {"version": commerce.get("version"), "status": commerce.get("status"), "metrics": commerce.get("metrics"), "guardrails": commerce.get("guardrails")}
    except Exception as exc:
        degraded = {"version": VERSION, "status": "degraded_fail_open", "error": f"{type(exc).__name__}: {str(exc)[:240]}", "guardrails_preserved": True, "updated_at": utcnow()}
        state["adaptive_commerce"] = degraded
        report["adaptive_commerce"] = degraded
    state["retail_velocity_radar"] = report
    return report


radar.retail_velocity_tick = _retail_tick_with_commerce
