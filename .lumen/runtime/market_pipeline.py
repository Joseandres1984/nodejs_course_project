from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from autonomy_governor import record_decision

MIN_OPPORTUNITY_SCORE = 75
MAX_NEW_PER_TICK = 5


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _log(state: Dict[str, Any], msg: str) -> None:
    state.setdefault("activity", []).insert(0, {"ts": utcnow(), "msg": msg})
    state["activity"] = state["activity"][:100]


def _category(value: Any) -> str:
    return " ".join(str(value or "").lower().strip().split())


def _score(buyer: Dict[str, Any], supplier: Dict[str, Any]) -> int:
    buyer_ver = float(buyer.get("verification_score") or 0)
    demand = float(buyer.get("demand_score") or 0)
    supplier_ver = float(supplier.get("verification_score") or 0)
    buyer_lead = float(buyer.get("lead_score") or 0)
    supplier_lead = float(supplier.get("lead_score") or 0)
    score = buyer_ver * 0.20 + demand * 0.35 + supplier_ver * 0.25 + buyer_lead * 0.10 + supplier_lead * 0.10
    return max(0, min(100, round(score)))


def _key(buyer: Dict[str, Any], supplier: Dict[str, Any], category: str) -> str:
    return f"{buyer.get('id')}|{supplier.get('id')}|{category}"


def _risk_flags(buyer: Dict[str, Any], supplier: Dict[str, Any]) -> List[str]:
    flags = ["requirement_not_confirmed", "commercial_terms_unknown", "deal_value_unknown"]
    if not buyer.get("verified_contact"):
        flags.append("buyer_contact_unverified")
    if not supplier.get("verified_contact"):
        flags.append("supplier_contact_unverified")
    return flags


def build_market_pipeline(state: Dict[str, Any]) -> Dict[str, int]:
    accounts = state.setdefault("candidate_accounts", [])
    opportunities = state.setdefault("market_opportunities", [])
    known = {str(x.get("opportunity_key")) for x in opportunities if x.get("opportunity_key")}
    buyers = [x for x in accounts if x.get("type") == "buyer" and x.get("verified_company") and x.get("demand_signal")]
    suppliers = [x for x in accounts if x.get("type") == "supplier" and x.get("verified_company")]
    stats = {"buyer_accounts": len(buyers), "supplier_accounts": len(suppliers), "pairs_evaluated": 0, "created": 0, "below_threshold": 0}

    for buyer in buyers:
        category = _category(buyer.get("category"))
        if not category:
            continue
        matches = [s for s in suppliers if _category(s.get("category")) == category]
        matches.sort(key=lambda x: float(x.get("verification_score") or 0), reverse=True)
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
            flags = _risk_flags(buyer, supplier)
            opp = {
                "id": f"MKT-{len(opportunities)+1:05d}",
                "opportunity_key": key,
                "buyer_account_id": buyer.get("id"),
                "supplier_account_id": supplier.get("id"),
                "category": buyer.get("category"),
                "score": score,
                "status": "evidence_backed",
                "source": "public_evidence",
                "buyer_company_verified": True,
                "buyer_demand_verified": True,
                "supplier_company_verified": True,
                "buyer_contact_verified": bool(buyer.get("verified_contact")),
                "supplier_contact_verified": bool(supplier.get("verified_contact")),
                "requirement_confirmed": False,
                "economic_value": None,
                "currency": None,
                "risk_flags": flags,
                "evidence_refs": list(dict.fromkeys([
                    str(buyer.get("official_url") or ""),
                    *[str(x) for x in buyer.get("demand_evidence_urls", [])[:3]],
                    str(supplier.get("official_url") or ""),
                ]))[:6],
                "next_action": "Validar requerimiento concreto y canales comerciales antes de cualquier outreach",
                "ready_for_deal": False,
                "created_at": utcnow(),
            }
            opportunities.append(opp)
            known.add(key)
            stats["created"] += 1
            record_decision(
                state, engine="Market Opportunity Builder", object_type="market_opportunity", object_id=opp["id"],
                decision="evidence_backed_opportunity_created",
                reason="Comprador verificado + señal pública de demanda + proveedor verificado en misma categoría; valor económico aún desconocido",
                action="score_opportunity", confidence=score / 100.0, evidence_refs=opp["evidence_refs"],
            )

    state["market_pipeline_stats"] = {**stats, "updated_at": utcnow(), "total": len(opportunities)}
    if stats["created"]:
        _log(state, f"Market Opportunity Builder creó {stats['created']} oportunidades respaldadas por evidencia, sin inventar valores económicos.")
    return stats
