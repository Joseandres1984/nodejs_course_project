from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from autonomy_governor import record_decision

MIN_OPPORTUNITY_SCORE = 75
MAX_NEW_PER_TICK = 5
COLLECTION_FOCUS = os.getenv("LUMEN_COLLECTION_FOCUS", "").strip().lower()


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _log(state: Dict[str, Any], msg: str) -> None:
    state.setdefault("activity", []).insert(0, {"ts": utcnow(), "msg": msg})
    state["activity"] = state["activity"][:100]


def _category(value: Any) -> str:
    return " ".join(str(value or "").lower().strip().split())


def _mercadopago_focus() -> bool:
    return COLLECTION_FOCUS == "mercadopago_ars"


def _is_argentina_account(account: Dict[str, Any]) -> bool:
    values = [account.get("country"), account.get("market"), account.get("growth_market")]
    text = " ".join(str(x or "").strip().lower() for x in values if str(x or "").strip())
    return bool(text) and ("argentina" in text or text in {"ar", "arg", "republica argentina", "república argentina"})


def _collection_eligible(buyer: Dict[str, Any]) -> bool:
    if not _mercadopago_focus():
        return True
    return _is_argentina_account(buyer)


def _score(buyer: Dict[str, Any], supplier: Dict[str, Any]) -> int:
    buyer_ver = float(buyer.get("verification_score") or 0)
    demand = float(buyer.get("demand_score") or 0)
    supplier_ver = float(supplier.get("verification_score") or 0)
    buyer_lead = float(buyer.get("lead_score") or 0)
    supplier_lead = float(supplier.get("lead_score") or 0)
    score = buyer_ver * 0.20 + demand * 0.35 + supplier_ver * 0.25 + buyer_lead * 0.10 + supplier_lead * 0.10
    return max(0, min(100, round(score)))


def _learning_profile(state: Dict[str, Any], category: Any) -> Dict[str, float]:
    target = _category(category)
    for item in state.get("profit_learning", {}).get("category_rankings", []) or []:
        if _category(item.get("category")) == target:
            return {
                "score": float(item.get("learned_score") or 50.0),
                "confidence": float(item.get("confidence") or 0.0),
            }
    return {"score": 50.0, "confidence": 0.0}


def _portfolio_priority(state: Dict[str, Any], buyer: Dict[str, Any], supplier: Dict[str, Any]) -> float:
    evidence = float(_score(buyer, supplier))
    profile = _learning_profile(state, buyer.get("category"))
    adjustment = (profile["score"] - 50.0) * 0.30 * profile["confidence"]
    collection_bonus = 5.0 if _mercadopago_focus() and _collection_eligible(buyer) else 0.0
    return round(max(0.0, min(110.0, evidence + adjustment + collection_bonus)), 2)


def _buyer_priority(state: Dict[str, Any], buyer: Dict[str, Any]) -> float:
    profile = _learning_profile(state, buyer.get("category"))
    evidence = (
        float(buyer.get("demand_score") or 0) * 0.45
        + float(buyer.get("verification_score") or 0) * 0.35
        + float(buyer.get("lead_score") or 0) * 0.20
    )
    adjustment = (profile["score"] - 50.0) * 0.25 * profile["confidence"]
    collection_bonus = 5.0 if _mercadopago_focus() and _collection_eligible(buyer) else 0.0
    return evidence + adjustment + collection_bonus


def _key(buyer: Dict[str, Any], supplier: Dict[str, Any], category: str) -> str:
    return f"{buyer.get('id')}|{supplier.get('id')}|{category}"


def _risk_flags(buyer: Dict[str, Any], supplier: Dict[str, Any], requirement_confirmed: bool = False) -> List[str]:
    flags: List[str] = []
    if not requirement_confirmed:
        flags.append("requirement_not_confirmed")
    flags.extend(["commercial_terms_unknown", "deal_value_unknown"])
    if not buyer.get("commercial_channel_verified"):
        flags.append("buyer_channel_unverified")
    elif not buyer.get("verified_contact"):
        flags.append("buyer_email_unverified")
    if not supplier.get("commercial_channel_verified"):
        flags.append("supplier_channel_unverified")
    elif not supplier.get("verified_contact"):
        flags.append("supplier_email_unverified")
    if _mercadopago_focus() and not _collection_eligible(buyer):
        flags.append("collection_focus_not_mercadopago_compatible")
    return flags


def _evidence(buyer: Dict[str, Any], supplier: Dict[str, Any]) -> List[str]:
    return list(dict.fromkeys([
        str(buyer.get("official_url") or ""),
        *[str(x) for x in buyer.get("demand_evidence_urls", [])[:3]],
        *[str(x) for x in buyer.get("commercial_contact_evidence", [])[:2]],
        str(supplier.get("official_url") or ""),
        *[str(x) for x in supplier.get("commercial_contact_evidence", [])[:2]],
    ]))[:8]


def _refresh_existing(state: Dict[str, Any], opportunity: Dict[str, Any], buyer: Dict[str, Any], supplier: Dict[str, Any]) -> None:
    requirement_confirmed = bool(opportunity.get("requirement_confirmed"))
    eligible = _collection_eligible(buyer)
    opportunity["score"] = _score(buyer, supplier)
    profile = _learning_profile(state, opportunity.get("category"))
    opportunity["learned_category_score"] = round(profile["score"], 2)
    opportunity["learned_category_confidence"] = round(profile["confidence"], 2)
    opportunity["portfolio_priority_score"] = _portfolio_priority(state, buyer, supplier)
    opportunity["buyer_company_verified"] = bool(buyer.get("verified_company"))
    opportunity["buyer_demand_verified"] = bool(buyer.get("demand_signal"))
    opportunity["supplier_company_verified"] = bool(supplier.get("verified_company"))
    opportunity["buyer_contact_verified"] = bool(buyer.get("verified_contact"))
    opportunity["supplier_contact_verified"] = bool(supplier.get("verified_contact"))
    opportunity["buyer_channel_verified"] = bool(buyer.get("commercial_channel_verified"))
    opportunity["supplier_channel_verified"] = bool(supplier.get("commercial_channel_verified"))
    opportunity["buyer_contact_channel"] = buyer.get("contact_channel")
    opportunity["supplier_contact_channel"] = supplier.get("contact_channel")
    opportunity["collection_focus"] = "mercadopago_ars" if _mercadopago_focus() else None
    opportunity["collection_focus_eligible"] = eligible
    opportunity["collection_focus_reason"] = (
        "Comprador verificado en Argentina; candidato a comisión ARS por Mercado Pago, sujeto a confirmar términos de cobro."
        if eligible and _mercadopago_focus()
        else "Fuera del foco Mercado Pago ARS mientras el riel internacional no esté listo."
        if _mercadopago_focus()
        else None
    )
    opportunity["risk_flags"] = _risk_flags(buyer, supplier, requirement_confirmed=requirement_confirmed)
    opportunity["evidence_refs"] = _evidence(buyer, supplier)
    opportunity["updated_at"] = utcnow()
    if _mercadopago_focus() and not eligible:
        opportunity["status"] = "parked_collection_focus"
        opportunity["portfolio_priority_score"] = min(float(opportunity.get("portfolio_priority_score") or 0), 20.0)
        opportunity["next_action"] = "Pausada mientras LUMEN prioriza compradores argentinos cobrables por Mercado Pago en ARS"
    elif requirement_confirmed and opportunity["buyer_channel_verified"] and opportunity["supplier_channel_verified"]:
        if opportunity.get("status") == "parked_collection_focus":
            opportunity["status"] = "evidence_backed"
        opportunity["next_action"] = "Solicitar/normalizar ofertas comparables y completar economía real"
    elif not requirement_confirmed:
        if opportunity.get("status") == "parked_collection_focus":
            opportunity["status"] = "evidence_backed"
        opportunity["next_action"] = "Confirmar el requerimiento concreto con el comprador"
    else:
        if opportunity.get("status") == "parked_collection_focus":
            opportunity["status"] = "evidence_backed"
        opportunity["next_action"] = "Validar los canales comerciales faltantes antes de outreach"


def build_market_pipeline(state: Dict[str, Any]) -> Dict[str, int]:
    accounts = state.setdefault("candidate_accounts", [])
    opportunities = state.setdefault("market_opportunities", [])
    account_by_id = {str(x.get("id")): x for x in accounts if x.get("id")}
    known = {str(x.get("opportunity_key")) for x in opportunities if x.get("opportunity_key")}
    all_buyers = [x for x in accounts if x.get("type") == "buyer" and x.get("verified_company") and x.get("demand_signal")]
    filtered_non_mercadopago = sum(1 for x in all_buyers if _mercadopago_focus() and not _collection_eligible(x))
    buyers = [x for x in all_buyers if _collection_eligible(x)]
    suppliers = [x for x in accounts if x.get("type") == "supplier" and x.get("verified_company")]
    buyers.sort(key=lambda x: _buyer_priority(state, x), reverse=True)
    stats = {
        "buyer_accounts": len(buyers),
        "supplier_accounts": len(suppliers),
        "pairs_evaluated": 0,
        "created": 0,
        "refreshed": 0,
        "below_threshold": 0,
        "collection_focus": "mercadopago_ars" if _mercadopago_focus() else None,
        "filtered_non_mercadopago_buyers": filtered_non_mercadopago,
    }

    # Reconcile old opportunities first so no case keeps stale contact, verification or learned-priority flags.
    for opportunity in opportunities:
        buyer = account_by_id.get(str(opportunity.get("buyer_account_id") or ""))
        supplier = account_by_id.get(str(opportunity.get("supplier_account_id") or ""))
        if buyer and supplier:
            _refresh_existing(state, opportunity, buyer, supplier)
            stats["refreshed"] += 1

    for buyer in buyers:
        category = _category(buyer.get("category"))
        if not category:
            continue
        matches = [s for s in suppliers if _category(s.get("category")) == category]
        matches.sort(key=lambda x: _portfolio_priority(state, buyer, x), reverse=True)
        for supplier in matches[:3]:
            if stats["created"] >= MAX_NEW_PER_TICK:
                break
            stats["pairs_evaluated"] += 1
            key = _key(buyer, supplier, category)
            if key in known:
                continue
            score = _score(buyer, supplier)
            if score < MIN_OPPORTUNITY_SCORE:
                stats["below_threshold"] += 1
                continue
            flags = _risk_flags(buyer, supplier, requirement_confirmed=False)
            profile = _learning_profile(state, buyer.get("category"))
            opp = {
                "id": f"MKT-{len(opportunities)+1:05d}",
                "opportunity_key": key,
                "buyer_account_id": buyer.get("id"),
                "supplier_account_id": supplier.get("id"),
                "category": buyer.get("category"),
                "score": score,
                "learned_category_score": round(profile["score"], 2),
                "learned_category_confidence": round(profile["confidence"], 2),
                "portfolio_priority_score": _portfolio_priority(state, buyer, supplier),
                "status": "evidence_backed",
                "source": "public_evidence",
                "buyer_company_verified": True,
                "buyer_demand_verified": True,
                "supplier_company_verified": True,
                "buyer_contact_verified": bool(buyer.get("verified_contact")),
                "supplier_contact_verified": bool(supplier.get("verified_contact")),
                "buyer_channel_verified": bool(buyer.get("commercial_channel_verified")),
                "supplier_channel_verified": bool(supplier.get("commercial_channel_verified")),
                "buyer_contact_channel": buyer.get("contact_channel"),
                "supplier_contact_channel": supplier.get("contact_channel"),
                "requirement_confirmed": False,
                "economic_value": None,
                "currency": None,
                "collection_focus": "mercadopago_ars" if _mercadopago_focus() else None,
                "collection_focus_eligible": True,
                "collection_focus_reason": (
                    "Comprador verificado en Argentina; candidato a comisión ARS por Mercado Pago, sujeto a confirmar términos de cobro."
                    if _mercadopago_focus() else None
                ),
                "risk_flags": flags,
                "evidence_refs": _evidence(buyer, supplier),
                "next_action": "Validar requerimiento concreto y canales comerciales antes de cualquier outreach",
                "ready_for_deal": False,
                "created_at": utcnow(),
                "updated_at": utcnow(),
            }
            opportunities.append(opp)
            known.add(key)
            stats["created"] += 1
            record_decision(
                state, engine="Market Opportunity Builder", object_type="market_opportunity", object_id=opp["id"],
                decision="evidence_backed_opportunity_created",
                reason=(
                    "Comprador verificado + señal pública de demanda + proveedor verificado en misma categoría; "
                    f"prioridad de portfolio {opp['portfolio_priority_score']:.1f}; valor económico aún desconocido; "
                    + ("foco de cobro Mercado Pago ARS activo" if _mercadopago_focus() else "foco de cobro estándar")
                ),
                action="score_opportunity", confidence=score / 100.0, evidence_refs=opp["evidence_refs"],
            )

    # Keep the portfolio naturally ordered for downstream engines and dashboard consumers.
    opportunities.sort(key=lambda x: float(x.get("portfolio_priority_score") or x.get("score") or 0), reverse=True)
    state["market_pipeline_stats"] = {**stats, "updated_at": utcnow(), "total": len(opportunities)}
    state["collection_focus"] = {
        "mode": "mercadopago_ars" if _mercadopago_focus() else "standard",
        "buyer_market": "Argentina" if _mercadopago_focus() else None,
        "commission_currency_target": "ARS" if _mercadopago_focus() else None,
        "rule": "El foco comercial prioriza compradores argentinos y comisión cobrable en ARS; la moneda final debe quedar documentada antes del cierre y nunca se convierte por suposición.",
        "updated_at": utcnow(),
    }
    if stats["created"]:
        _log(state, f"Market Opportunity Builder creó {stats['created']} oportunidades priorizadas por evidencia + aprendizaje económico, sin bajar el umbral de verificación.")
    if _mercadopago_focus() and filtered_non_mercadopago:
        _log(state, f"Foco Mercado Pago pausó {filtered_non_mercadopago} comprador(es) fuera de Argentina para no gastar ejecución comercial en rieles de cobro todavía no listos.")
    return stats
