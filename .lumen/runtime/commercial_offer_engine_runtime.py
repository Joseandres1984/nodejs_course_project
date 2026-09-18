from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


VERSION = "1.0-launch-pricing-offer-engine"
PRICING_MODE = "launch_validation"
REVIEW_AFTER_PAID_WINS_PER_SERVICE = 3
CANONICAL_CURRENCY = "USD"

# Deliberately low-friction launch pricing. These are bounded service packages, not unlimited
# consulting retainers. Lower price must mean lower scope; LUMEN is not authorized to invent
# discounts, binding terms or automatic payment commitments.
PRICEBOOK: Dict[str, Dict[str, Any]] = {
    "SRV-QUOTECHECK": {
        "name": "LUMEN QuoteCheck Global",
        "billing": "one_time",
        "public_from_usd": 59,
        "tiers": [
            {"id": "quick", "label": "Quick Check", "price_usd": 59, "scope": ["1 cotización", "1 proveedor", "1 moneda", "revisión documental y referencias públicas disponibles"]},
            {"id": "compare", "label": "Compare", "price_usd": 99, "scope": ["hasta 3 cotizaciones o alternativas", "comparación estructurada", "observaciones y palancas de negociación"]},
            {"id": "global", "label": "Global", "price_usd": 149, "scope": ["caso internacional o técnicamente complejo", "múltiples referencias", "riesgos, supuestos y próximos pasos"]},
        ],
    },
    "SRV-SUPPLIERCHECK": {
        "name": "LUMEN SupplierCheck",
        "billing": "one_time",
        "public_from_usd": 79,
        "tiers": [
            {"id": "identity", "label": "Identity", "price_usd": 79, "scope": ["1 proveedor", "identidad y canales oficiales", "señales públicas y datos faltantes"]},
            {"id": "risk", "label": "Risk Review", "price_usd": 129, "scope": ["1 proveedor", "revisión ampliada de señales", "banderas de riesgo y checklist de verificación"]},
            {"id": "extended", "label": "Extended", "price_usd": 199, "scope": ["proveedor internacional o caso sensible", "evidencia ampliada", "recomendaciones de due diligence"]},
        ],
    },
    "SRV-SOURCING-EXPRESS": {
        "name": "LUMEN Sourcing Express",
        "billing": "one_time",
        "public_from_usd": 149,
        "tiers": [
            {"id": "express", "label": "Express", "price_usd": 149, "scope": ["1 necesidad concreta", "hasta 5 proveedores investigados", "1 mercado", "shortlist y próximos pasos"]},
            {"id": "standard", "label": "Standard", "price_usd": 249, "scope": ["hasta 10 proveedores", "comparación ampliada", "canales corporativos verificables", "recomendación priorizada"]},
            {"id": "technical", "label": "Technical / Global", "price_usd": 399, "scope": ["requerimiento técnico o internacional", "múltiples mercados o restricciones", "matriz de evidencia y riesgos"]},
        ],
    },
    "SRV-B2B-PROSPECTING": {
        "name": "LUMEN Prospección B2B",
        "billing": "pilot_or_monthly",
        "public_from_usd": 199,
        "tiers": [
            {"id": "pilot", "label": "Pilot", "price_usd": 199, "scope": ["1 oferta o rubro", "lista priorizada inicial", "señales públicas y canales corporativos", "sin envío masivo"]},
            {"id": "growth", "label": "Growth", "price_usd": 399, "scope": ["prospección mensual acotada", "priorización continua", "aprendizaje sobre respuestas y señales"]},
            {"id": "scale", "label": "Scale", "price_usd": 699, "scope": ["múltiples segmentos o mercados", "mayor cobertura", "seguimiento y optimización comercial"]},
        ],
    },
    "SRV-EXPORT-SCOUT": {
        "name": "LUMEN Export Scout",
        "billing": "one_time",
        "public_from_usd": 249,
        "tiers": [
            {"id": "single_market", "label": "Single Market", "price_usd": 249, "scope": ["1 producto", "1 país o mercado", "compradores/importadores/distribuidores priorizados"]},
            {"id": "multi_market", "label": "Multi Market", "price_usd": 399, "scope": ["hasta 3 mercados", "comparación de encaje", "shortlist internacional y canales corporativos"]},
            {"id": "expansion", "label": "Expansion", "price_usd": 649, "scope": ["múltiples mercados o categorías", "priorización ampliada", "plan de prospección internacional"]},
        ],
    },
    "SRV-TENDER-HUNTER": {
        "name": "LUMEN Tender Hunter Global",
        "billing": "fixed_or_monthly",
        "public_from_usd": 99,
        "tiers": [
            {"id": "radar", "label": "Radar", "price_usd": 99, "scope": ["1 búsqueda puntual", "1 rubro", "oportunidades públicas encontradas y priorizadas"]},
            {"id": "watch", "label": "Watch", "price_usd": 149, "scope": ["vigilancia mensual de 1 rubro/mercado", "deduplicación", "fuente, fechas y requisitos observables"]},
            {"id": "multi_market", "label": "Multi Market Watch", "price_usd": 249, "scope": ["hasta 3 mercados o familias", "vigilancia y priorización ampliada", "resumen de compatibilidad"]},
        ],
    },
}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _clean(value: Any, limit: int = 1600) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _norm(value: Any) -> str:
    return _clean(value, 2000).lower()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        text = str(value or "").replace(" ", "").replace(",", ".")
        return float(re.sub(r"[^0-9.\-]", "", text) or default)
    except (TypeError, ValueError):
        return default


def _stable(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(x or "") for x in parts)
    return prefix + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12].upper()


def pricebook_entry(service_id: str) -> Dict[str, Any]:
    return dict(PRICEBOOK.get(str(service_id or ""), {}) or {})


def public_from_usd(service_id: str) -> Optional[float]:
    item = PRICEBOOK.get(str(service_id or ""))
    if not item:
        return None
    return float(item.get("public_from_usd") or 0.0)


def public_price_label(service_id: str) -> str:
    value = public_from_usd(service_id)
    return f"Desde USD {int(value)}" if value else "Precio según alcance"


def _paid_wins(state: Dict[str, Any], service_id: str) -> int:
    count = 0
    for row in state.get("service_revenue_transactions", []) or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("service_id") or "") != service_id:
            continue
        if str(row.get("status") or "").lower() in {"paid", "settled", "completed"}:
            count += 1
    return count


def _context_text(context: Dict[str, Any]) -> str:
    values = [
        context.get("need"), context.get("stated_need"), context.get("product"), context.get("country"),
        context.get("quantity"), context.get("supplier_name"), context.get("company_name"),
    ]
    payload = context.get("intelligence_payload") if isinstance(context.get("intelligence_payload"), dict) else {}
    values.extend([payload.get("country"), payload.get("product"), payload.get("quantity"), payload.get("supplier_name")])
    return _norm(" | ".join(str(x or "") for x in values))


def _complexity(service_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
    text = _context_text(context)
    score = 0
    factors: List[str] = []

    need = _clean(context.get("need") or context.get("stated_need"), 1800)
    if len(need) > 450:
        score += 1; factors.append("brief_detallado")
    if len(need) > 900:
        score += 1; factors.append("brief_extenso")

    if any(k in text for k in ("varios", "multiples", "múltiples", "diversos", "mas de un", "más de un")):
        score += 2; factors.append("multiples_objetos")
    if any(k in text for k in ("urgente", "esta semana", "24 horas", "48 horas", "inmediato")):
        score += 1; factors.append("urgencia")
    if any(k in text for k in ("internacional", "export", "import", "global", "otro pais", "otro país")):
        score += 1; factors.append("cross_border")
    if any(k in text for k in ("iso ", "certific", "norma ", "homolog", "especificacion", "especificación", "tecnico", "técnico")):
        score += 1; factors.append("complejidad_tecnica")

    quantity = _f(context.get("quantity") or (context.get("intelligence_payload") or {}).get("quantity"))
    if quantity >= 100:
        score += 1; factors.append("volumen_relevante")
    quote_amount = _f(context.get("quote_amount") or (context.get("intelligence_payload") or {}).get("quote_amount"))
    if quote_amount >= 10000:
        score += 1; factors.append("importe_relevante")

    if service_id == "SRV-B2B-PROSPECTING" and any(k in text for k in ("mensual", "campaña", "campana", "outreach", "seguimiento")):
        score += 3; factors.append("programa_recurrente")
    if service_id == "SRV-TENDER-HUNTER" and any(k in text for k in ("mensual", "monitore", "vigilar", "continu", "alerta")):
        score += 3; factors.append("vigilancia_recurrente")
    if service_id == "SRV-EXPORT-SCOUT" and any(k in text for k in ("paises", "países", "latam", "america", "europa", "asia")):
        score += 2; factors.append("multi_market")
    if service_id == "SRV-QUOTECHECK" and any(k in text for k in ("tres cot", "3 cot", "comparar cot", "varias cot")):
        score += 2; factors.append("comparacion_multiple")

    return {"score": score, "factors": factors}


def recommend_offer(service_id: str, context: Optional[Dict[str, Any]] = None, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    sid = str(service_id or "")
    context = dict(context or {})
    item = PRICEBOOK.get(sid)
    if not item:
        return {}

    complexity = _complexity(sid, context)
    score = int(complexity.get("score") or 0)
    tier_index = 0 if score <= 2 else 1 if score <= 5 else 2
    tiers = list(item.get("tiers") or [])

    # Product-specific recurring intent should not be squeezed into a one-off starter package.
    text = _context_text(context)
    if sid == "SRV-B2B-PROSPECTING" and any(k in text for k in ("mensual", "campaña", "campana", "outreach", "seguimiento")):
        tier_index = max(tier_index, 1)
    if sid == "SRV-TENDER-HUNTER" and any(k in text for k in ("mensual", "monitore", "vigilar", "continu", "alerta")):
        tier_index = max(tier_index, 1)
    tier_index = min(tier_index, max(0, len(tiers) - 1))
    tier = dict(tiers[tier_index] if tiers else {})

    paid_wins = _paid_wins(state or {}, sid) if state is not None else 0
    review_due = paid_wins >= REVIEW_AFTER_PAID_WINS_PER_SERVICE
    price = float(tier.get("price_usd") or item.get("public_from_usd") or 0.0)

    seed = context.get("id") or context.get("source_id") or context.get("account_id") or context.get("email") or context.get("company_name") or utcnow()
    return {
        "id": _stable("OFFER-", sid, seed, tier.get("id")),
        "engine_version": VERSION,
        "pricing_mode": PRICING_MODE,
        "service_id": sid,
        "service_name": item.get("name"),
        "tier_id": tier.get("id"),
        "tier_label": tier.get("label"),
        "recommended_price_usd": price,
        "public_from_usd": float(item.get("public_from_usd") or 0.0),
        "canonical_currency": CANONICAL_CURRENCY,
        "billing": item.get("billing"),
        "scope": list(tier.get("scope") or []),
        "complexity_score": score,
        "complexity_factors": list(complexity.get("factors") or []),
        "paid_wins_for_service": paid_wins,
        "pricing_review_due": review_due,
        "review_after_paid_wins": REVIEW_AFTER_PAID_WINS_PER_SERVICE,
        "discount_policy": "reduce_scope_before_price; no_autonomous_discount",
        "local_currency_policy": "convert_only_with_verified_fx_source_and_human_confirmation",
        "final_price_human_confirmation_required": True,
        "binding_terms_human_required": True,
        "autonomous_discount_allowed": False,
        "payment_created": False,
        "binding": False,
        "updated_at": utcnow(),
    }


def _linked_inquiries(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        str(x.get("id") or ""): x
        for x in state.get("service_inquiries", []) or []
        if isinstance(x, dict) and x.get("id")
    }


def offer_engine_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    inquiries = _linked_inquiries(state)
    offers_recommended = 0
    by_service: Dict[str, int] = {sid: 0 for sid in PRICEBOOK}
    review_due_services: List[str] = []

    # Inbound inquiries receive an immediate non-binding recommendation in state. Nothing is charged.
    for row in state.get("service_inquiries", []) or []:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("service_id") or "")
        if sid not in PRICEBOOK:
            continue
        offer = recommend_offer(sid, row, state)
        if offer:
            row["recommended_offer"] = offer
            row["price_status"] = "recommended_nonbinding_human_confirmation_required"
            offers_recommended += 1
            by_service[sid] = by_service.get(sid, 0) + 1

    # CRM pipeline gets the same deterministic offer truth so outbound, diagnosis and proposals share one price source.
    for row in state.get("service_sales_pipeline", []) or []:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("service_id") or "")
        if sid not in PRICEBOOK or str(row.get("stage") or "") in {"won", "lost"}:
            continue
        context = dict(row)
        source = inquiries.get(str(row.get("source_id") or ""))
        if source:
            context.update({k: v for k, v in source.items() if v not in (None, "", [], {})})
        offer = recommend_offer(sid, context, state)
        if offer:
            row["recommended_offer"] = offer
            row["price_status"] = "recommended_nonbinding_human_confirmation_required"

    # Intelligence work cases expose the package chosen for the actual submitted case.
    for row in state.get("intelligence_cases", []) or []:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("service_id") or "")
        if sid not in PRICEBOOK:
            continue
        offer = recommend_offer(sid, row, state)
        if offer:
            row["recommended_offer"] = offer
            row["price_status"] = "recommended_nonbinding_human_confirmation_required"

    for sid in PRICEBOOK:
        if _paid_wins(state, sid) >= REVIEW_AFTER_PAID_WINS_PER_SERVICE:
            review_due_services.append(sid)

    report = {
        "version": VERSION,
        "status": "active",
        "pricing_mode": PRICING_MODE,
        "active_pricebook_services": len(PRICEBOOK),
        "offers_recommended_for_inquiries": offers_recommended,
        "by_service": by_service,
        "public_starting_prices_usd": {sid: float(item.get("public_from_usd") or 0.0) for sid, item in PRICEBOOK.items()},
        "pricing_review_due_services": review_due_services,
        "review_after_paid_wins_per_service": REVIEW_AFTER_PAID_WINS_PER_SERVICE,
        "autonomous_discount_allowed": False,
        "payment_created": False,
        "binding_authority_changed": False,
        "paid_spend": False,
        "updated_at": utcnow(),
    }
    state["commercial_offer_engine"] = report
    return report


print({
    "commercial_offer_engine_runtime": {
        "version": VERSION,
        "status": "active",
        "pricing_mode": PRICING_MODE,
        "services": len(PRICEBOOK),
        "public_starting_prices_usd": {sid: item.get("public_from_usd") for sid, item in PRICEBOOK.items()},
        "autonomous_discount": False,
        "payment_created": False,
        "binding_authority_changed": False,
    }
}, flush=True)
