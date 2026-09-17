from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

import commercial_execution

VERSION = "1.1-supplier-rfq-standard"
RFQ_STANDARD = "LUMEN-RFQ-1.0"
RFQ_REQUIRED_RESPONSE_FIELDS = (
    "unit_price",
    "total_price",
    "currency",
    "availability",
    "delivery_lead_time",
    "quote_validity",
    "payment_terms",
    "brand_model",
    "technical_sheet_when_applicable",
)
_ORIGINAL_ENSURE = commercial_execution._ensure_revops_cases
_ORIGINAL_MESSAGE = commercial_execution._message


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().strip().split())


def _supplier_rfq_body_standard(requirement: Dict[str, Any]) -> str:
    summary = commercial_execution._requirement_summary(requirement)
    return (
        "Estamos evaluando un requerimiento B2B confirmado y agradeceremos contar con una cotización formal y comparable.\n\n"
        f"Requerimiento:\n{summary}\n\n"
        "Por favor indicar, cuando corresponda:\n"
        "- precio unitario y precio total;\n"
        "- moneda;\n"
        "- disponibilidad/stock;\n"
        "- plazo de entrega;\n"
        "- vigencia de la cotización;\n"
        "- forma y condiciones de pago;\n"
        "- marca, fabricante y modelo ofrecido;\n"
        "- ficha técnica o documentación técnica aplicable;\n"
        "- garantía, origen, flete, impuestos y cualquier condición o exclusión relevante.\n\n"
        "Si la alternativa ofrecida presenta algún desvío respecto del requerimiento, agradeceremos identificarlo expresamente. "
        "Para suministros internacionales, por favor indicar también Incoterm y lugar convenido.\n\n"
        "Esta solicitud es exploratoria y no vinculante. No implica orden de compra, aceptación contractual, compromiso de pago ni aceptación automática de condiciones comerciales; cualquier decisión posterior queda sujeta a revisión final."
    )


def _message_with_rfq_standard(
    state: Dict[str, Any], *, execution_key: str, kind: str, counterparty: str,
    contact: str, contact_verified: bool, subject: str, body: str,
    deal_id: str | None = None, revops_case_id: str | None = None,
    interlocution_case_id: str | None = None, opportunity_id: str | None = None,
    counterparty_account_id: str | None = None, purpose: str | None = None,
) -> bool:
    if kind == "supplier_rfq":
        supplier_name = str(counterparty or "equipo comercial").strip()
        topic = str(subject or "requerimiento B2B").strip()
        if "—" in topic:
            topic = topic.split("—", 1)[1].strip() or "requerimiento B2B"
        body = (
            f"Estimado equipo de {supplier_name},\n\n"
            f"Nos comunicamos específicamente por {topic}.\n\n"
            f"{body}"
        )
        purpose = purpose or "supplier_rfq_standard_v1"
    return _ORIGINAL_MESSAGE(
        state,
        execution_key=execution_key,
        kind=kind,
        counterparty=counterparty,
        contact=contact,
        contact_verified=contact_verified,
        subject=subject,
        body=body,
        deal_id=deal_id,
        revops_case_id=revops_case_id,
        interlocution_case_id=interlocution_case_id,
        opportunity_id=opportunity_id,
        counterparty_account_id=counterparty_account_id,
        purpose=purpose,
    )


def _priority(state: Dict[str, Any], case: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
    interlocution = next((x for x in state.get("interlocution_cases", []) or [] if str(x.get("id") or "") == str(case.get("interlocution_case_id") or "")), {})
    deal_id = str(case.get("deal_id") or "")
    if not deal_id and interlocution.get("opportunity_id"):
        deal = next((x for x in state.get("deals", []) or [] if str(x.get("opportunity_id") or "") == str(interlocution.get("opportunity_id") or "")), {})
        deal_id = str(deal.get("id") or "")
    offers = [x for x in state.get("offers", []) or [] if deal_id and str(x.get("deal_id") or "") == deal_id and str(x.get("source") or "") != "demo/simulación"]
    comparable = [x for x in offers if x.get("comparable")]
    incomplete = [x for x in offers if x.get("normalization_status") == "clarification_required"]
    status = _norm(case.get("status"))

    if status in {"nonbinding_negotiation", "quote_clarification"}:
        score = 120
        reason = "Negociación/aclaración ya activa; proteger continuidad comercial."
    elif interlocution.get("supplier_rfq_ready") and len(comparable) == 0 and len(offers) == 0:
        score = 115
        reason = "Requerimiento listo para RFQ y todavía no hay cotización real."
    elif interlocution.get("supplier_rfq_ready") and len(comparable) < 2:
        score = 108
        reason = "Faltan cotizaciones comparables para poder decidir proveedor y economía."
    elif incomplete:
        score = 104
        reason = "Hay cotización real pero faltan términos para compararla."
    elif len(comparable) >= 2:
        score = 98
        reason = "Hay comparación suficiente; acelerar preparación de propuesta al comprador."
    elif status == "requirement_discovery":
        score = 82
        reason = "Todavía falta cerrar requerimiento antes de solicitar precio."
    else:
        score = 70
        reason = "Caso comercial activo sin urgencia de cotización superior."
    return score, {
        "case_id": case.get("id"), "deal_id": deal_id or None,
        "interlocution_case_id": case.get("interlocution_case_id"),
        "supplier_rfq_ready": bool(interlocution.get("supplier_rfq_ready")),
        "real_offers": len(offers), "comparable_offers": len(comparable),
        "incomplete_offers": len(incomplete), "priority": score, "reason": reason,
    }


def _ensure_prioritized(state: Dict[str, Any], memory: Dict[str, Any]) -> List[Dict[str, Any]]:
    cases = list(_ORIGINAL_ENSURE(state, memory) or [])
    scored = []
    telemetry = []
    for case in cases:
        score, info = _priority(state, case)
        scored.append((score, case))
        telemetry.append(info)
    scored.sort(key=lambda x: x[0], reverse=True)
    ordered = [x[1] for x in scored]
    telemetry.sort(key=lambda x: x["priority"], reverse=True)
    state["quote_accelerator"] = {
        "version": VERSION,
        "status": "active",
        "updated_at": utcnow(),
        "cases_total": len(cases),
        "quote_priority_cases": sum(1 for x in telemetry if x["priority"] >= 98),
        "top_cases": telemetry[:8],
        "message_cap_unchanged": True,
        "max_new_messages_per_tick": commercial_execution.MAX_NEW_MESSAGES_PER_TICK,
        "rule": "use_existing_nonbinding_message_cap_on_the_cases_closest_to_comparable_quotes_and_buyer_proposal",
        "rfq_standard": {
            "name": RFQ_STANDARD,
            "mandatory": True,
            "professional_courteous": True,
            "supplier_personalization": True,
            "required_response_fields": list(RFQ_REQUIRED_RESPONSE_FIELDS),
            "nonbinding_only": True,
            "autonomous_contract_acceptance": False,
            "autonomous_purchase": False,
            "autonomous_payment": False,
        },
    }
    return ordered


commercial_execution._supplier_rfq_body = _supplier_rfq_body_standard
commercial_execution._message = _message_with_rfq_standard
commercial_execution._ensure_revops_cases = _ensure_prioritized
print({
    "quote_accelerator_runtime": {
        "version": VERSION,
        "status": "active",
        "message_cap_unchanged": True,
        "rfq_standard": RFQ_STANDARD,
        "supplier_personalization": True,
        "nonbinding_only": True,
    }
}, flush=True)
