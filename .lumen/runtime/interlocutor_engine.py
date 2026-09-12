from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from autonomy_governor import record_decision


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


REQUIRED_REQUIREMENT_FIELDS = [
    "technical_scope",
    "quantity",
    "delivery_target",
    "delivery_location",
    "commercial_terms",
]

OPTIONAL_REQUIREMENT_FIELDS = [
    "accepted_alternatives",
    "required_documentation",
    "warranty_requirement",
    "budget_reference",
    "currency",
]

SERVICE_MODEL = {
    "role": "interlocutor comercial B2B y facilitador de abastecimiento",
    "buyer_value": "reducir tiempo, incertidumbre y carga operativa para localizar, validar y comparar alternativas de suministro",
    "supplier_value": "traducir necesidades en requerimientos claros y facilitar una oportunidad comercial bien calificada",
    "principles": [
        "separar hechos confirmados de supuestos",
        "no inventar cantidades, presupuesto, precio, plazo ni especificaciones",
        "compartir con cada parte solamente la información necesaria para avanzar",
        "mantener trazabilidad de requerimientos, ofertas y cambios",
        "proteger margen sin deteriorar innecesariamente la relación comercial",
        "escalar compromisos contractuales o financieros para aprobación",
    ],
}


def _log(state: Dict[str, Any], message: str) -> None:
    state.setdefault("activity", []).insert(0, {"ts": utcnow(), "msg": message})
    state["activity"] = state["activity"][:100]


def _case_key(opportunity: Dict[str, Any]) -> str:
    return str(opportunity.get("id") or opportunity.get("opportunity_key") or "")


def _default_requirement(opportunity: Dict[str, Any]) -> Dict[str, Any]:
    category = opportunity.get("category")
    return {
        "category": category,
        "technical_scope": None,
        "quantity": None,
        "unit": None,
        "delivery_target": None,
        "delivery_location": None,
        "commercial_terms": None,
        "accepted_alternatives": None,
        "required_documentation": None,
        "warranty_requirement": None,
        "budget_reference": None,
        "currency": None,
        "source": "buyer_confirmation_required",
        "confirmed_by_buyer": False,
    }


def _missing(requirement: Dict[str, Any]) -> List[str]:
    return [field for field in REQUIRED_REQUIREMENT_FIELDS if requirement.get(field) in (None, "", [], {})]


def _completeness(requirement: Dict[str, Any]) -> int:
    required_done = sum(1 for f in REQUIRED_REQUIREMENT_FIELDS if requirement.get(f) not in (None, "", [], {}))
    optional_done = sum(1 for f in OPTIONAL_REQUIREMENT_FIELDS if requirement.get(f) not in (None, "", [], {}))
    score = (required_done / len(REQUIRED_REQUIREMENT_FIELDS)) * 85
    score += (optional_done / len(OPTIONAL_REQUIREMENT_FIELDS)) * 15
    return round(min(100, score))


def _questions(missing: List[str]) -> List[str]:
    mapping = {
        "technical_scope": "¿Podrían indicarnos la especificación, modelo, norma, prestación o alcance técnico requerido?",
        "quantity": "¿Qué cantidad estimada necesitan y en qué unidad de medida?",
        "delivery_target": "¿Cuál es el plazo o fecha objetivo de entrega?",
        "delivery_location": "¿En qué localidad o sitio debería realizarse la entrega o prestación?",
        "commercial_terms": "¿Hay condiciones comerciales relevantes que debamos contemplar (forma de pago, vigencia, moneda u otras)?",
    }
    return [mapping[x] for x in missing if x in mapping]


def _build_case(opportunity: Dict[str, Any], number: int) -> Dict[str, Any]:
    requirement = _default_requirement(opportunity)
    missing = _missing(requirement)
    return {
        "id": f"CASE-{number:05d}",
        "opportunity_id": opportunity.get("id"),
        "case_key": _case_key(opportunity),
        "buyer_account_id": opportunity.get("buyer_account_id"),
        "supplier_account_id": opportunity.get("supplier_account_id"),
        "category": opportunity.get("category"),
        "role": SERVICE_MODEL["role"],
        "status": "requirement_discovery",
        "requirement": requirement,
        "requirement_completeness": _completeness(requirement),
        "missing_required_fields": missing,
        "buyer_questions": _questions(missing),
        "supplier_rfq_ready": False,
        "proposal_ready": False,
        "economic_value": None,
        "currency": None,
        "confidentiality": {
            "buyer_private_data_to_supplier": "minimum_necessary",
            "supplier_private_data_to_buyer": "minimum_necessary",
            "commercial_margin_internal": True,
        },
        "next_action": "Confirmar el requerimiento concreto con el comprador antes de solicitar una oferta comparable",
        "created_at": utcnow(),
        "updated_at": utcnow(),
    }


def _refresh_case(case: Dict[str, Any], opportunity: Dict[str, Any]) -> None:
    requirement = case.setdefault("requirement", _default_requirement(opportunity))
    missing = _missing(requirement)
    completeness = _completeness(requirement)
    case["missing_required_fields"] = missing
    case["requirement_completeness"] = completeness
    case["buyer_questions"] = _questions(missing)
    confirmed = bool(requirement.get("confirmed_by_buyer"))
    rfq_ready = confirmed and completeness >= 85 and not missing
    case["supplier_rfq_ready"] = rfq_ready
    opportunity["requirement_confirmed"] = rfq_ready
    if rfq_ready:
        case["status"] = "ready_for_supplier_rfq"
        case["next_action"] = "Solicitar ofertas comparables a proveedores validados"
    else:
        case["status"] = "requirement_discovery"
        case["next_action"] = "Completar y confirmar el requerimiento con el comprador"
    case["updated_at"] = utcnow()


def interlocutor_tick(state: Dict[str, Any]) -> Dict[str, int]:
    opportunities = state.setdefault("market_opportunities", [])
    cases = state.setdefault("interlocution_cases", [])
    known = {str(x.get("case_key")): x for x in cases if x.get("case_key")}
    stats = {"created": 0, "refreshed": 0, "requirement_ready": 0, "awaiting_details": 0}

    for opportunity in opportunities:
        if opportunity.get("source") != "public_evidence":
            continue
        key = _case_key(opportunity)
        if not key:
            continue
        case = known.get(key)
        if case is None:
            case = _build_case(opportunity, len(cases) + 1)
            cases.append(case)
            known[key] = case
            stats["created"] += 1
            record_decision(
                state,
                engine="Interlocutor Engine",
                object_type="interlocution_case",
                object_id=case["id"],
                decision="case_opened",
                reason="Existe una oportunidad respaldada por evidencia, pero el requerimiento debe confirmarse antes de pedir una oferta seria.",
                action="normalize_requirement",
                confidence=float(opportunity.get("score") or 0) / 100.0,
                evidence_refs=list(opportunity.get("evidence_refs") or [])[:6],
            )
        _refresh_case(case, opportunity)
        stats["refreshed"] += 1
        if case.get("supplier_rfq_ready"):
            stats["requirement_ready"] += 1
        else:
            stats["awaiting_details"] += 1

    state["service_model"] = {**SERVICE_MODEL, "updated_at": utcnow()}
    state["interlocutor_stats"] = {**stats, "total_cases": len(cases), "updated_at": utcnow()}
    if stats["created"]:
        _log(state, f"Interlocutor Engine abrió {stats['created']} casos y separó requerimientos confirmados de datos todavía pendientes.")
    return stats
