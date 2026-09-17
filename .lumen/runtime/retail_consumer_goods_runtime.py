from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Dict, List

import retail_market_expansion as expansion
import retail_velocity_radar as radar


VERSION = "1.0"
BUSINESS_UNIT = "consumer_goods"

# Keep the existing consumer-electronics lanes while putting high-rotation everyday goods first.
# Discovery is public-search only and still consumes the protected retail search quota.
DISCOVERY_LANES = (
    (
        "beverages_non_alcoholic",
        'site:mercadolibre.com.ar ("MÁS VENDIDO" OR "mas vendido") (agua mineral OR gaseosa OR jugo OR bebida isotónica OR bebida energetica) -cerveza -vino -fernet -whisky -vodka Argentina',
    ),
    (
        "pantry_snacks",
        'site:mercadolibre.com.ar ("MÁS VENDIDO" OR "mas vendido") (yerba mate OR café OR galletitas OR snacks OR fideos OR arroz OR conservas) Argentina',
    ),
    (
        "cleaning_home",
        'site:mercadolibre.com.ar ("MÁS VENDIDO" OR "mas vendido") (detergente OR lavandina OR limpiador OR jabón para ropa OR suavizante OR esponjas) Argentina',
    ),
    (
        "personal_care",
        'site:mercadolibre.com.ar ("MÁS VENDIDO" OR "mas vendido") (shampoo OR acondicionador OR desodorante OR jabón tocador OR pasta dental OR cuidado personal) Argentina',
    ),
    (
        "household_consumables",
        'site:mercadolibre.com.ar ("MÁS VENDIDO" OR "mas vendido") (papel higiénico OR rollo cocina OR bolsas residuos OR servilletas OR film OR aluminio) Argentina',
    ),
    (
        "pet_care",
        'site:mercadolibre.com.ar ("MÁS VENDIDO" OR "mas vendido") (alimento perro OR alimento gato OR arena sanitaria OR snacks mascotas) Argentina',
    ),
    ("smartphones", 'site:mercadolibre.com.ar "MÁS VENDIDO" celular smartphone Samsung Motorola Xiaomi Argentina'),
    ("wearables", 'site:mercadolibre.com.ar "MÁS VENDIDO" smartwatch smart band Samsung Xiaomi Garmin Argentina'),
    ("audio", 'site:mercadolibre.com.ar "MÁS VENDIDO" auriculares bluetooth Redmi Sony Samsung Argentina'),
    ("charging", 'site:mercadolibre.com.ar "MÁS VENDIDO" cargador power bank USB-C Xiaomi Samsung Apple Argentina'),
)

FAMILY_LABELS = {
    "beverages_non_alcoholic": "bebidas_sin_alcohol",
    "pantry_snacks": "alimentos_secos_snacks",
    "cleaning_home": "limpieza_hogar",
    "personal_care": "higiene_cuidado_personal",
    "household_consumables": "consumibles_hogar",
    "pet_care": "mascotas",
    "smartphones": "electronica_consumo",
    "wearables": "electronica_consumo",
    "audio": "electronica_consumo",
    "charging": "electronica_consumo",
}

# Fail closed for categories that should not enter this commercial lane.
RESTRICTED_TERMS = (
    "cerveza", "vino ", "whisky", "vodka", "fernet", "licor", "champagne", "espumante",
    "tabaco", "cigarrillo", "cigarro", "vape", "vaper", "nicotina",
    "cannabis", "marihuana", "thc", "cbd", "esteroide", "hormona",
    "medicamento recetado", "venta bajo receta", "sildenafil",
    "réplica", "replica", "imitación", "imitacion", "clon", "fake", "trucho", "copia aaa",
)

SUPERMARKET_DOMAINS = {
    "carrefour.com.ar", "coto.com.ar", "jumbo.com.ar", "disco.com.ar", "vea.com.ar",
    "diaonline.supermercadosdia.com.ar", "changomas.com.ar",
}
PERSONAL_CARE_DOMAINS = {"farmacity.com", "simplicity.com.ar"}
MAJOR_RETAIL_DOMAINS = set(expansion.MAJOR_RETAIL_DOMAINS) | SUPERMARKET_DOMAINS | PERSONAL_CARE_DOMAINS


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().strip().split())


def _restricted(text: str) -> bool:
    low = _norm(text)
    return any(term in low for term in RESTRICTED_TERMS)


def _family_from_lane(lane: str) -> str:
    return FAMILY_LABELS.get(str(lane or ""), "otros_consumo")


def _commercial_priority(signal: Dict[str, Any]) -> float:
    velocity = float(signal.get("velocity_score") or 0)
    breadth = float(signal.get("market_breadth_score") or 0)
    sales = max(0, int(signal.get("reported_sales") or 0))
    recurring_bonus = 8.0 if str(signal.get("lane") or "") in {
        "beverages_non_alcoholic", "pantry_snacks", "cleaning_home", "personal_care",
        "household_consumables", "pet_care",
    } else 3.0
    sales_bonus = min(10.0, 2.5 * math.log10(max(1, sales))) if sales else 0.0
    return round(min(100.0, velocity * 0.72 + breadth * 0.10 + recurring_bonus + sales_bonus), 1)


_ORIGINAL_UPSERT = radar._upsert_product_signal


def _consumer_goods_upsert(state: Dict[str, Any], lane: str, item: Dict[str, str]) -> bool:
    raw = f"{item.get('title', '')} {item.get('snippet', '')}"
    if _restricted(raw):
        return False
    changed = bool(_ORIGINAL_UPSERT(state, lane, item))
    product = radar._safe_title(str(item.get("title") or ""))
    key = radar._signal_key(product) if product else ""
    row = next((x for x in state.get("retail_product_signals", []) or [] if x.get("key") == key), None)
    if row:
        row.update({
            "business_unit": BUSINESS_UNIT,
            "consumer_family": _family_from_lane(lane),
            "business_model": "commission_or_success_fee",
            "inventory_policy": "no_owned_inventory",
            "purchase_policy": "no_autonomous_purchases_or_advances",
            "paid_media_policy": "no_paid_ads_without_human_approval",
            "buyer_payment_policy": "buyer_pays_supplier_directly",
            "binding_terms_policy": "human_approval_required",
            "commercial_priority_score": _commercial_priority(row),
        })
    return changed


def _expanded_family(url: str, title: str = "", snippet: str = "") -> str:
    host = expansion._host(url)
    text = f"{title} {snippet}".lower()
    if host.endswith("mercadolibre.com.ar"):
        return "mercadolibre"
    if host.endswith("mitiendanube.com") or "tiendanube" in text:
        return "tiendanube"
    if any(host == d or host.endswith("." + d) for d in SUPERMARKET_DOMAINS):
        return "supermarket_chain"
    if any(host == d or host.endswith("." + d) for d in PERSONAL_CARE_DOMAINS):
        return "personal_care_chain"
    if any(word in text for word in ("mayorista", "distribuidor", "importador", "distribución", "distribucion")):
        return "wholesaler_distributor"
    if any(host == d or host.endswith("." + d) for d in MAJOR_RETAIL_DOMAINS):
        if any(x in host for x in ("samsung", "motorola", "xiaomi", "sony")):
            return "brand_store"
        return "major_retail"
    return "independent_store"


def _consumer_corroboration_query(product: str) -> str:
    return (
        f'"{product}" Argentina '
        '(site:mitiendanube.com OR site:carrefour.com.ar OR site:coto.com.ar OR site:jumbo.com.ar '
        'OR site:disco.com.ar OR site:vea.com.ar OR site:diaonline.supermercadosdia.com.ar '
        'OR site:changomas.com.ar OR site:farmacity.com OR "distribuidor mayorista" OR "comprar online") '
        '-site:mercadolibre.com.ar'
    )


def _matches_product(value: Any, product: str) -> bool:
    a, b = _norm(value), _norm(product)
    if not a or not b:
        return False
    return a == b or a in b or b in a


def _supplier_leads(state: Dict[str, Any], product: str) -> List[Dict[str, Any]]:
    return [
        x for x in state.get("research_leads", []) or []
        if x.get("type") == "supplier" and _matches_product(x.get("category"), product)
    ]


def _partner_stores(state: Dict[str, Any], product: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for store in state.get("partner_stores", []) or []:
        categories = list(store.get("categories", []) or [])
        products = list(store.get("catalog_products", []) or [])
        if any(_matches_product(x, product) for x in categories) or any(
            _matches_product(x.get("category") or x.get("title"), product) for x in products
        ):
            out.append(store)
    return out


def _active_referral_offers(state: Dict[str, Any], product: str) -> List[Dict[str, Any]]:
    return [
        x for x in state.get("partner_referral_offers", []) or []
        if str(x.get("status") or "").lower() == "active"
        and _matches_product(x.get("title") or x.get("category"), product)
    ]


def _stage(signal: Dict[str, Any], suppliers: List[Dict[str, Any]], stores: List[Dict[str, Any]], offers: List[Dict[str, Any]]) -> tuple[str, str, bool]:
    if offers:
        return "referral_offer_active", "Medir clics, consultas, conversión y comisión realizada", False
    authorized = [x for x in stores if bool(x.get("commission_authorized")) and x.get("commercial_status") == "active_partner"]
    if authorized:
        return "partner_ready_offer_preparation", "Preparar oferta de referido con trazabilidad y atribución", False
    if stores:
        return "partner_agreement_required", "Proponer comisión/success fee; cualquier aceptación vinculante requiere aprobación humana", True
    if suppliers:
        return "supplier_verification", "Verificar empresa, contacto, disponibilidad y condiciones no vinculantes", False
    if signal.get("supplier_search_done"):
        return "supplier_research_retry", "Reintentar investigación de proveedor cuando haya presupuesto disponible", False
    return "supplier_research", "Buscar proveedor/distribuidor sin comprar stock ni comprometer fondos", False


def _build_unit_state(state: Dict[str, Any], report: Dict[str, Any]) -> Dict[str, Any]:
    signals = list(state.get("retail_product_signals", []) or [])
    # Migrate previously discovered rows into the formal unit without fabricating new market evidence.
    for row in signals:
        lane = str(row.get("lane") or "")
        if lane in FAMILY_LABELS:
            row.setdefault("business_unit", BUSINESS_UNIT)
            row.setdefault("consumer_family", _family_from_lane(lane))
            row.setdefault("business_model", "commission_or_success_fee")
            row.setdefault("inventory_policy", "no_owned_inventory")
            row.setdefault("purchase_policy", "no_autonomous_purchases_or_advances")
            row.setdefault("paid_media_policy", "no_paid_ads_without_human_approval")
            row.setdefault("buyer_payment_policy", "buyer_pays_supplier_directly")
            row.setdefault("binding_terms_policy", "human_approval_required")
            row["commercial_priority_score"] = _commercial_priority(row)

    eligible = [x for x in signals if x.get("business_unit") == BUSINESS_UNIT and not _restricted(str(x.get("product") or ""))]
    eligible.sort(key=lambda x: float(x.get("commercial_priority_score") or x.get("velocity_score") or 0), reverse=True)

    pipeline: List[Dict[str, Any]] = []
    supplier_domains = set()
    relevant_store_ids = set()
    active_offer_ids = set()
    for signal in eligible[:60]:
        product = str(signal.get("product") or "")
        suppliers = _supplier_leads(state, product)
        stores = _partner_stores(state, product)
        offers = _active_referral_offers(state, product)
        for lead in suppliers:
            if lead.get("url"):
                supplier_domains.add(expansion._host(str(lead.get("url"))))
        relevant_store_ids.update(str(x.get("id") or x.get("domain") or "") for x in stores)
        active_offer_ids.update(str(x.get("id") or x.get("offer_key") or "") for x in offers)
        stage, next_action, human_required = _stage(signal, suppliers, stores, offers)
        score = min(
            100.0,
            float(signal.get("commercial_priority_score") or signal.get("velocity_score") or 0)
            + min(8.0, len(suppliers) * 2.0)
            + min(8.0, len(stores) * 2.0)
            + (12.0 if offers else 0.0),
        )
        pipeline.append({
            "product_key": signal.get("key"),
            "product": product,
            "family": signal.get("consumer_family"),
            "stage": stage,
            "commercial_score": round(score, 1),
            "velocity_score": signal.get("velocity_score"),
            "market_breadth_score": signal.get("market_breadth_score"),
            "supplier_leads": len(suppliers),
            "partner_stores": len(stores),
            "active_referral_offers": len(offers),
            "next_action": next_action,
            "human_approval_required": human_required,
            "autonomous_spend_allowed": False,
            "autonomous_binding_commitment_allowed": False,
        })

    pipeline.sort(key=lambda x: float(x.get("commercial_score") or 0), reverse=True)
    families = Counter(str(x.get("consumer_family") or "otros_consumo") for x in eligible)
    stages = Counter(str(x.get("stage") or "unknown") for x in pipeline)
    high_priority = sum(1 for x in pipeline if float(x.get("commercial_score") or 0) >= 75)

    unit = {
        "version": VERSION,
        "status": "active",
        "mode": "parallel_consumer_goods_commission_only",
        "objective": "scale_high_rotation_demand_without_owned_inventory_or_autonomous_spend",
        "policies": {
            "owned_inventory": False,
            "autonomous_purchase_or_advance": False,
            "paid_ad_spend": False,
            "buyer_pays_supplier_directly": True,
            "binding_partner_terms_require_human_approval": True,
            "public_research_only": True,
            "industrial_lane_preserved": True,
        },
        "metrics": {
            "products_total": len(eligible),
            "high_priority_products": high_priority,
            "supplier_domains": len([x for x in supplier_domains if x]),
            "partner_stores": len([x for x in relevant_store_ids if x]),
            "active_referral_offers": len([x for x in active_offer_ids if x]),
            "families": dict(families),
            "stages": dict(stages),
        },
        "pipeline": pipeline[:50],
        "top_priorities": pipeline[:8],
        "search": {
            "retail_budget_remaining": report.get("retail_budget_remaining"),
            "global_search_budget_remaining": report.get("global_search_budget_remaining"),
            "latest_action": report.get("action"),
            "latest_target": report.get("target_product") or report.get("lane"),
        },
        "updated_at": radar.utcnow(),
    }
    state["consumer_goods_unit"] = unit
    return unit


# Install reversible runtime patches. The underlying industrial scout and its quotas remain unchanged.
radar.DISCOVERY_LANES = DISCOVERY_LANES
radar._upsert_product_signal = _consumer_goods_upsert
expansion.MAJOR_RETAIL_DOMAINS = MAJOR_RETAIL_DOMAINS
expansion._family = _expanded_family
expansion._corroboration_query = _consumer_corroboration_query

_ORIGINAL_TICK = radar.retail_velocity_tick


def _consumer_goods_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    report = dict(_ORIGINAL_TICK(state) or {})
    unit = _build_unit_state(state, report)
    report["business_unit"] = BUSINESS_UNIT
    report["consumer_goods_unit"] = {
        "version": unit.get("version"),
        "status": unit.get("status"),
        "mode": unit.get("mode"),
        "metrics": unit.get("metrics"),
        "top_priorities": unit.get("top_priorities"),
    }
    state["retail_velocity_radar"] = report
    return report


radar.retail_velocity_tick = _consumer_goods_tick
