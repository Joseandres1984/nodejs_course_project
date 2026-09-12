from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from autonomy_governor import record_decision

REQUIRED_FIELDS = ["amount", "currency", "lead_days", "payment_terms"]
IMPORTANT_FIELDS = ["validity_days", "warranty", "freight_terms", "tax_terms", "technical_compliance"]


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _missing(offer: Dict[str, Any]) -> List[str]:
    return [x for x in REQUIRED_FIELDS + IMPORTANT_FIELDS if offer.get(x) in (None, "", "por validar", "unknown")]


def _completeness(offer: Dict[str, Any]) -> int:
    req = sum(1 for x in REQUIRED_FIELDS if offer.get(x) not in (None, "", "por validar", "unknown"))
    imp = sum(1 for x in IMPORTANT_FIELDS if offer.get(x) not in (None, "", "por validar", "unknown"))
    return round((req / len(REQUIRED_FIELDS)) * 75 + (imp / len(IMPORTANT_FIELDS)) * 25)


def _normalize_offer(offer: Dict[str, Any]) -> None:
    offer.setdefault("validity_days", None)
    offer.setdefault("warranty", None)
    offer.setdefault("freight_terms", None)
    offer.setdefault("tax_terms", None)
    offer.setdefault("technical_compliance", None)
    offer["missing_commercial_fields"] = _missing(offer)
    offer["quote_completeness"] = _completeness(offer)
    offer["source_traceable"] = offer.get("source") in {"email real", "manual verified", "formal quote"}
    offer["comparable"] = bool(
        offer.get("amount")
        and offer.get("currency")
        and offer.get("lead_days") is not None
        and offer.get("payment_terms") not in (None, "", "por validar")
        and offer["quote_completeness"] >= 70
        and offer["source_traceable"]
    )
    offer["normalization_status"] = "comparable" if offer["comparable"] else "clarification_required"
    offer["normalized_at"] = utcnow()


def _comparison_for(deal_id: str, offers: List[Dict[str, Any]]) -> Dict[str, Any]:
    comparable = [x for x in offers if x.get("comparable")]
    currencies = sorted({str(x.get("currency")) for x in comparable if x.get("currency")})
    result: Dict[str, Any] = {
        "deal_id": deal_id,
        "offers_total": len(offers),
        "comparable_offers": len(comparable),
        "currencies": currencies,
        "status": "insufficient_comparable_quotes",
        "ranking": [],
        "best_offer_id": None,
        "comparison_note": "No se convierten monedas ni se completan términos faltantes por inferencia.",
        "updated_at": utcnow(),
    }
    if len(comparable) < 2:
        return result
    if len(currencies) != 1:
        result["status"] = "currency_normalization_required"
        return result

    min_amount = min(float(x["amount"]) for x in comparable)
    ranked = []
    for offer in comparable:
        amount = float(offer["amount"])
        price_score = 50.0 * (min_amount / amount) if amount > 0 else 0.0
        completeness_score = float(offer.get("quote_completeness") or 0) * 0.20
        lead = float(offer.get("lead_days") or 9999)
        lead_score = max(0.0, 15.0 - min(15.0, lead / 10.0))
        traceability_score = 15.0 if offer.get("source_traceable") else 0.0
        total = round(min(100.0, price_score + completeness_score + lead_score + traceability_score), 1)
        ranked.append({
            "offer_id": offer.get("id"),
            "supplier": offer.get("supplier"),
            "amount": amount,
            "currency": offer.get("currency"),
            "lead_days": offer.get("lead_days"),
            "payment_terms": offer.get("payment_terms"),
            "score": total,
        })
    ranked.sort(key=lambda x: x["score"], reverse=True)
    result["status"] = "comparable"
    result["ranking"] = ranked
    result["best_offer_id"] = ranked[0]["offer_id"] if ranked else None
    return result


def quote_tick(state: Dict[str, Any]) -> Dict[str, int]:
    offers = state.setdefault("offers", [])
    real_offers = [x for x in offers if x.get("source") != "demo/simulación"]
    stats = {"normalized": 0, "comparable": 0, "clarification_required": 0, "comparisons_ready": 0}

    for offer in real_offers:
        _normalize_offer(offer)
        stats["normalized"] += 1
        if offer.get("comparable"):
            stats["comparable"] += 1
        else:
            stats["clarification_required"] += 1

    by_deal: Dict[str, List[Dict[str, Any]]] = {}
    for offer in real_offers:
        deal_id = str(offer.get("deal_id") or "")
        if deal_id:
            by_deal.setdefault(deal_id, []).append(offer)

    comparisons = []
    for deal_id, deal_offers in by_deal.items():
        comparison = _comparison_for(deal_id, deal_offers)
        comparisons.append(comparison)
        if comparison["status"] == "comparable":
            stats["comparisons_ready"] += 1
            record_decision(
                state,
                engine="Quote Engine",
                object_type="deal",
                object_id=deal_id,
                decision="comparable_quotes_available",
                reason="Existen al menos dos ofertas reales con moneda y términos comerciales suficientemente normalizados.",
                action="compare_supplier_quotes",
                confidence=0.95,
                evidence_refs=[],
            )

    state["quote_comparisons"] = comparisons
    state["quote_engine_stats"] = {**stats, "updated_at": utcnow()}
    return stats
