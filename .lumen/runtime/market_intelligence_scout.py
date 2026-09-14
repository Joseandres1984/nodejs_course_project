from __future__ import annotations

import hashlib
import json
import os
import re
import statistics
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

MAX_OBSERVATIONS = max(100, min(3000, int(os.getenv("LUMEN_MARKET_INTELLIGENCE_MAX_OBSERVATIONS", "900"))))
MAX_CANDIDATES = max(20, min(500, int(os.getenv("LUMEN_MARKET_INTELLIGENCE_MAX_CANDIDATES", "160"))))
MIN_SPREAD_PCT = max(5.0, min(300.0, float(os.getenv("LUMEN_MARKET_INTELLIGENCE_MIN_SPREAD_PCT", "22"))))
MIN_SELLERS = max(2, min(8, int(os.getenv("LUMEN_MARKET_INTELLIGENCE_MIN_SELLERS", "2"))))


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _clean(value: Any, limit: int = 500) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _slug(value: Any) -> str:
    text = _clean(value, 300).lower()
    text = re.sub(r"[^a-z0-9áéíóúüñ]+", "-", text)
    return text.strip("-")[:180]


def _price(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        price = float(str(value).strip().replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None
    if price <= 0 or price > 1_000_000_000_000:
        return None
    return round(price, 6)


def _identity(row: Dict[str, Any]) -> tuple[str, float, str]:
    for key in ("gtin14", "gtin13", "gtin12", "gtin8", "gtin"):
        value = re.sub(r"\D+", "", _clean(row.get(key), 64))
        if len(value) >= 8:
            return f"gtin:{value}", 0.99, "gtin"

    brand = _slug(row.get("brand"))
    mpn = _slug(row.get("mpn"))
    model = _slug(row.get("model"))
    if brand and mpn:
        return f"mpn:{brand}:{mpn}", 0.96, "brand_mpn"
    if brand and model:
        return f"model:{brand}:{model}", 0.92, "brand_model"

    # Fallback is deliberately conservative: exact normalized public product title only.
    title = _slug(row.get("product"))
    if len(title) >= 12:
        return f"title:{title}", 0.72, "exact_normalized_title"
    return "", 0.0, "insufficient_identity"


def _observation_key(row: Dict[str, Any]) -> str:
    basis = "|".join(
        [
            _clean(row.get("source_domain"), 220).lower(),
            _clean(row.get("source_url"), 900),
            _clean(row.get("product"), 260),
            str(row.get("price") or ""),
            _clean(row.get("currency"), 16).upper(),
            _clean(row.get("sku"), 100),
            _clean(row.get("mpn"), 100),
            _clean(row.get("model"), 100),
        ]
    )
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:24]


def _type_is_product(value: Any) -> bool:
    types = value if isinstance(value, list) else [value]
    return any(str(x or "").strip().lower() == "product" for x in types)


def _brand(value: Any) -> str:
    if isinstance(value, dict):
        return _clean(value.get("name"), 120)
    return _clean(value, 120)


def _availability_name(value: Any) -> str:
    text = _clean(value, 160)
    if not text:
        return ""
    return text.rsplit("/", 1)[-1]


def extract_jsonld_products(blocks: Iterable[str], source_url: str) -> List[Dict[str, Any]]:
    """Extract structured Product/Offer facts without inventing missing values."""
    rows: List[Dict[str, Any]] = []

    def emit_product(product: Dict[str, Any]) -> None:
        name = _clean(product.get("name"), 260)
        if not name:
            return
        product_url = _clean(product.get("url") or source_url, 900)
        base = {
            "title": name,
            "url": product_url,
            "source": "jsonld_product",
            "brand": _brand(product.get("brand")),
            "model": _clean(product.get("model"), 160),
            "sku": _clean(product.get("sku"), 120),
            "mpn": _clean(product.get("mpn"), 120),
            "gtin": _clean(product.get("gtin"), 64),
            "gtin8": _clean(product.get("gtin8"), 64),
            "gtin12": _clean(product.get("gtin12"), 64),
            "gtin13": _clean(product.get("gtin13"), 64),
            "gtin14": _clean(product.get("gtin14"), 64),
            "color": _clean(product.get("color"), 100),
            "size": _clean(product.get("size"), 100),
        }
        offers = product.get("offers")
        offers_list = offers if isinstance(offers, list) else [offers] if isinstance(offers, dict) else []
        emitted_offer = False
        for offer in offers_list:
            if not isinstance(offer, dict):
                continue
            offer_type = _clean(offer.get("@type"), 80).lower()
            price = offer.get("price")
            if price in (None, "") and "aggregateoffer" in offer_type:
                price = offer.get("lowPrice")
            currency = offer.get("priceCurrency")
            row = dict(base)
            row.update({
                "source": "jsonld_product_offer",
                "url": _clean(offer.get("url") or product_url, 900),
                "price": _price(price),
                "price_currency": _clean(currency, 16).upper(),
                "availability": _availability_name(offer.get("availability")),
            })
            rows.append(row)
            emitted_offer = True
        if not emitted_offer:
            rows.append(base)

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if _type_is_product(value.get("@type")):
                emit_product(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    for block in blocks:
        try:
            walk(json.loads(block))
        except Exception:
            continue

    dedup: List[Dict[str, Any]] = []
    seen = set()
    for row in rows:
        key = (
            row.get("url"), row.get("title"), row.get("price"), row.get("price_currency"),
            row.get("gtin14") or row.get("gtin13") or row.get("mpn") or row.get("model"),
        )
        if key in seen:
            continue
        seen.add(key)
        dedup.append(row)
    return dedup


def capture_catalog_observation(
    state: Dict[str, Any],
    *,
    store: Dict[str, Any],
    product: Dict[str, Any],
) -> bool:
    """Persist one read-only market observation from public catalog evidence.

    This function owns only market-intelligence state. It never creates prospects, messages,
    deals, approvals, orders or financial actions.
    """
    domain = _clean(store.get("domain"), 220).lower().removeprefix("www.")
    source_url = _clean(product.get("url"), 900)
    name = _clean(product.get("title") or product.get("product"), 260)
    if not domain or not source_url or not name:
        return False

    row: Dict[str, Any] = {
        "product": name,
        "source_domain": domain,
        "source_url": source_url,
        "source_type": _clean(product.get("source") or "public_catalog", 80),
        "brand": _clean(product.get("brand"), 120),
        "model": _clean(product.get("model"), 160),
        "sku": _clean(product.get("sku"), 120),
        "mpn": _clean(product.get("mpn"), 120),
        "gtin": _clean(product.get("gtin"), 64),
        "gtin8": _clean(product.get("gtin8"), 64),
        "gtin12": _clean(product.get("gtin12"), 64),
        "gtin13": _clean(product.get("gtin13"), 64),
        "gtin14": _clean(product.get("gtin14"), 64),
        "color": _clean(product.get("color"), 100),
        "size": _clean(product.get("size"), 100),
        "availability": _clean(product.get("availability"), 120),
        "price": _price(product.get("price")),
        "currency": _clean(product.get("price_currency") or product.get("currency"), 16).upper(),
        "observed_at": utcnow(),
        "evidence_policy": "public_get_only_source_url_retained",
        "shadow_only": True,
        "action_authority": "none",
    }
    identity_key, identity_confidence, identity_basis = _identity(row)
    row["identity_key"] = identity_key
    row["identity_confidence"] = identity_confidence
    row["identity_basis"] = identity_basis
    row["key"] = _observation_key(row)

    rows: List[Dict[str, Any]] = state.setdefault("market_intelligence_observations", [])
    existing = next((x for x in rows if x.get("key") == row["key"]), None)
    if existing:
        first_seen = existing.get("first_seen_at") or existing.get("observed_at") or row["observed_at"]
        existing.update(row)
        existing["first_seen_at"] = first_seen
        return False

    row["first_seen_at"] = row["observed_at"]
    rows.append(row)
    state["market_intelligence_observations"] = rows[-MAX_OBSERVATIONS:]
    return True


def _latest_per_domain(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    latest: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        domain = _clean(row.get("source_domain"), 220).lower()
        if not domain:
            continue
        previous = latest.get(domain)
        if previous is None or str(row.get("observed_at") or "") >= str(previous.get("observed_at") or ""):
            latest[domain] = row
    return list(latest.values())


def detect_opportunities(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Create deterministic shadow candidates from same-product, same-currency price spreads."""
    groups: Dict[tuple[str, str], List[Dict[str, Any]]] = {}
    for row in state.get("market_intelligence_observations", []) or []:
        identity = _clean(row.get("identity_key"), 260)
        currency = _clean(row.get("currency"), 16).upper()
        price = _price(row.get("price"))
        if not identity or not currency or price is None:
            continue
        groups.setdefault((identity, currency), []).append(row)

    candidates: List[Dict[str, Any]] = []
    for (identity, currency), observations in groups.items():
        sellers = _latest_per_domain(observations)
        priced = [x for x in sellers if _price(x.get("price")) is not None]
        if len(priced) < MIN_SELLERS:
            continue
        priced.sort(key=lambda x: float(x.get("price") or 0))
        low, high = priced[0], priced[-1]
        low_price = float(low.get("price") or 0)
        high_price = float(high.get("price") or 0)
        if low_price <= 0 or high_price <= low_price:
            continue
        spread_pct = round(((high_price - low_price) / low_price) * 100.0, 2)
        if spread_pct < MIN_SPREAD_PCT:
            continue

        prices = [float(x.get("price") or 0) for x in priced]
        confidence = round(min(float(x.get("identity_confidence") or 0) for x in priced), 2)
        candidate_id = "MIO-" + hashlib.sha1(f"{identity}|{currency}".encode("utf-8")).hexdigest()[:16].upper()
        candidates.append(
            {
                "id": candidate_id,
                "type": "public_market_price_asymmetry",
                "identity_key": identity,
                "identity_basis": low.get("identity_basis"),
                "product": low.get("product") or high.get("product"),
                "currency": currency,
                "min_price": round(low_price, 6),
                "median_price": round(statistics.median(prices), 6),
                "max_price": round(high_price, 6),
                "spread_pct": spread_pct,
                "seller_count": len(priced),
                "confidence": confidence,
                "low_source": {"domain": low.get("source_domain"), "url": low.get("source_url")},
                "high_source": {"domain": high.get("source_domain"), "url": high.get("source_url")},
                "evidence_urls": [x.get("source_url") for x in priced[:8] if x.get("source_url")],
                "status": "shadow_only",
                "shadow_only": True,
                "execution_allowed": False,
                "outreach_allowed": False,
                "financial_commitment_allowed": False,
                "action_authority": "none",
                "next_step": "research_only_requires_governed_promotion_before_any_external_action",
                "updated_at": utcnow(),
            }
        )

    candidates.sort(key=lambda x: (float(x.get("spread_pct") or 0), float(x.get("confidence") or 0)), reverse=True)
    state["market_intelligence_opportunity_candidates"] = candidates[:MAX_CANDIDATES]
    return state["market_intelligence_opportunity_candidates"]


def market_intelligence_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    candidates = detect_opportunities(state)
    observations = list(state.get("market_intelligence_observations", []) or [])
    priced = [x for x in observations if _price(x.get("price")) is not None and x.get("currency")]
    report = {
        "status": "shadow",
        "mode": "public_market_intelligence",
        "observations_total": len(observations),
        "priced_observations": len(priced),
        "opportunity_candidates": len(candidates),
        "top_candidate": candidates[0] if candidates else None,
        "source_policy": "public_get_only_robots_respected_existing_catalog_pipeline",
        "authority": "research_only_no_outreach_no_purchase_no_deal_mutation",
        "promotion_policy": "candidate_must_pass_decision_kernel_governor_and_existing_execution_gates",
        "updated_at": utcnow(),
    }
    state["market_intelligence_scout"] = report
    return report
