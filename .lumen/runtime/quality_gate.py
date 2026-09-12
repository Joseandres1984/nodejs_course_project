from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from autonomy_governor import record_decision


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


RISKY_COMMITMENT_PHRASES = (
    "confirmamos la compra",
    "aceptamos el contrato",
    "orden de compra emitida",
    "pago realizado",
    "transferencia realizada",
    "garantizamos stock",
    "garantizamos la entrega",
    "comprometemos el pago",
    "aceptamos sus condiciones",
    "queda adjudicado",
    "aceptamos la devolución",
    "aceptamos devolución",
    "reembolso garantizado",
    "reintegro garantizado",
    "asumimos responsabilidad",
    "nos hacemos responsables",
    "indemnizaremos",
    "aceptamos penalidad",
    "aceptamos la penalidad",
    "responsabilidad ilimitada",
    "aceptamos jurisdicción",
    "aceptamos jurisdiccion",
    "aceptamos la ley aplicable",
    "aceptamos cancelación sin cargo",
    "aceptamos cancelacion sin cargo",
)

REVOPS_MULTITURN_KINDS = {
    "quote_clarification",
    "supplier_negotiation",
    "buyer_information_response",
    "terms_clarification",
}

RED_TEAM_SENSITIVE_KINDS = {
    "buyer_proposal",
    "supplier_negotiation",
    "buyer_information_response",
    "payment_status_reminder",
    "commission_payment_request",
    "customer_success_checkin",
}


def _log(state: Dict[str, Any], message: str) -> None:
    state.setdefault("activity", []).insert(0, {"ts": utcnow(), "msg": message})
    state["activity"] = state["activity"][:100]


def _relationship_for(state: Dict[str, Any], contact: str, counterparty: str) -> Dict[str, Any] | None:
    contact = (contact or "").strip().lower()
    counterparty = (counterparty or "").strip().lower()
    for relation in state.get("commercial_relationships", []):
        if contact and str(relation.get("commercial_email") or "").strip().lower() == contact:
            return relation
        if counterparty and str(relation.get("counterparty") or "").strip().lower() == counterparty:
            return relation
    return None


def _duplicate_sent(state: Dict[str, Any], item: Dict[str, Any]) -> bool:
    kind = str(item.get("kind") or "")
    execution_key = str(item.get("execution_key") or "")
    for other in state.get("outbox", []):
        if other is item or other.get("status") != "sent":
            continue
        same_conversation_slot = (
            other.get("deal_id") == item.get("deal_id")
            and other.get("kind") == item.get("kind")
            and str(other.get("contact") or "").lower() == str(item.get("contact") or "").lower()
        )
        if not same_conversation_slot:
            continue
        if kind in REVOPS_MULTITURN_KINDS and execution_key:
            other_key = str(other.get("execution_key") or "")
            if other_key and other_key != execution_key:
                continue
        return True
    return False


def _deal(state: Dict[str, Any], deal_id: Any) -> Dict[str, Any] | None:
    return next((x for x in state.get("deals", []) if x.get("id") == deal_id), None)


def _counterparty_risk(state: Dict[str, Any], account_id: Any) -> Dict[str, Any]:
    return dict((state.get("counterparty_risk_index", {}) or {}).get(str(account_id or ""), {}) or {})


def _settlement_case(state: Dict[str, Any], transaction_id: Any) -> Dict[str, Any]:
    return next((x for x in state.get("commission_settlement_cases", []) or [] if str(x.get("transaction_id") or "") == str(transaction_id or "")), {})


def _review(state: Dict[str, Any], item: Dict[str, Any]) -> tuple[bool, List[str]]:
    reasons: List[str] = []
    target = str(item.get("contact") or "").strip().lower()
    subject = str(item.get("subject") or "").strip()
    body = str(item.get("body") or "").strip()
    kind = str(item.get("kind") or "")

    if not target or "@" not in target:
        reasons.append("No existe un email corporativo utilizable")
    if not item.get("contact_verified"):
        reasons.append("El contacto no está verificado")
    if not item.get("communication_reviewed"):
        reasons.append("El mensaje no pasó Communication Director")
    if len(subject) < 5 or len(subject) > 180:
        reasons.append("Asunto fuera de estándar")
    if len(body) < 80 or len(body) > 6000:
        reasons.append("Cuerpo fuera de estándar")
    if target and target in {str(x).lower() for x in state.get("opt_out", [])}:
        reasons.append("La dirección solicitó no ser contactada")
    if _duplicate_sent(state, item) and item.get("kind") != "follow_up":
        reasons.append("Mensaje comercial equivalente ya enviado")

    low = body.lower()
    if any(phrase in low for phrase in RISKY_COMMITMENT_PHRASES):
        reasons.append("El texto contiene un compromiso financiero/contractual/de responsabilidad no permitido")

    relation = _relationship_for(state, target, str(item.get("counterparty") or ""))
    if relation:
        if relation.get("opted_out") or relation.get("relationship_state") == "do_not_contact":
            reasons.append("Relationship Memory bloquea contacto")
        if item.get("kind") == "follow_up" and int(relation.get("follow_up_count") or 0) >= 2:
            reasons.append("Se alcanzó el máximo de seguimientos sin respuesta")
        if relation.get("relationship_state") == "cooldown":
            reasons.append("La relación está en período de cooldown")

    risk = _counterparty_risk(state, item.get("counterparty_account_id"))
    if risk.get("risk_tier") == "BLOCKED" or risk.get("can_outreach") is False:
        reasons.append("Counterparty Risk bloquea esta contraparte")

    deal = _deal(state, item.get("deal_id"))
    if deal and deal.get("red_team_hold") and kind in RED_TEAM_SENSITIVE_KINDS:
        reasons.append("El Auditor Interno mantiene el deal en hold para comunicaciones comerciales sensibles")
    if deal and deal.get("incident_hold") and item.get("kind") not in {"terms_clarification"}:
        reasons.append("El deal tiene un incidente/reclamo abierto; se congelan comunicaciones comerciales que puedan ampliar exposición")

    if item.get("kind") == "buyer_proposal":
        if not deal or not deal.get("economics"):
            reasons.append("La propuesta no tiene economía calculada")
        elif not bool(deal.get("economics", {}).get("viable")):
            reasons.append("La economía del negocio no cumple el margen mínimo")
        safeguards = (deal or {}).get("deal_safeguards", {}) or {}
        if deal and safeguards and not safeguards.get("proposal_allowed", False):
            reasons.append("Deal Safeguards no autoriza todavía presentar esta propuesta")
        if deal and deal.get("legal_review_required"):
            reasons.append("El deal requiere revisión legal humana antes de presentar términos comerciales")

    if item.get("kind") == "supplier_rfq":
        if deal and not deal.get("need"):
            reasons.append("RFQ sin necesidad/requerimiento identificable")
        if not deal and not item.get("interlocution_case_id"):
            reasons.append("RFQ sin deal ni caso de requerimiento trazable")

    if kind == "commission_payment_request":
        setup = (state.get("commission_settlement", {}) or {}).get("settlement_setup", {}) or {}
        case = _settlement_case(state, item.get("transaction_id"))
        if not setup.get("instructions_verified"):
            reasons.append("Los datos de cobro de LUMEN no están marcados como verificados")
        if item.get("financial_instruction_source") != "verified_runtime_configuration":
            reasons.append("El mensaje de cobro no proviene de la configuración financiera verificada")
        if not case:
            reasons.append("No existe caso de liquidación de comisión trazable")
        elif case.get("status") not in {"AWAITING_PAYMENT", "OVERDUE", "PARTIAL_RECEIVED"}:
            reasons.append("El estado de la comisión no autoriza solicitar liquidación")

    if item.get("kind") in REVOPS_MULTITURN_KINDS and not item.get("execution_key"):
        reasons.append("Turno comercial multivuelta sin clave idempotente")

    return len(reasons) == 0, reasons


def quality_tick(state: Dict[str, Any]) -> Dict[str, int]:
    stats = {"reviewed": 0, "passed": 0, "blocked": 0}
    for item in state.setdefault("outbox", []):
        if item.get("quality_reviewed"):
            continue
        if item.get("status") not in {"ready", "needs_verified_contact"}:
            continue
        stats["reviewed"] += 1

        if item.get("status") == "needs_verified_contact":
            item["quality_gate"] = "pending_contact"
            item["quality_reviewed"] = True
            item["quality_reviewed_at"] = utcnow()
            continue

        passed, reasons = _review(state, item)
        item["quality_reviewed"] = True
        item["quality_reviewed_at"] = utcnow()
        item["quality_gate"] = "passed" if passed else "blocked"
        item["quality_reasons"] = reasons[:8]

        if passed:
            stats["passed"] += 1
            record_decision(
                state,
                engine="Quality Gate",
                object_type="message",
                object_id=str(item.get("id") or ""),
                decision="outbound_quality_passed",
                reason="Contacto, tono, relación, Counterparty Risk, Red Team, trazabilidad, Deal Safeguards y autoridad cumplen las reglas de salida.",
                action="authorize_message_for_mail_connector",
                confidence=0.99,
                evidence_refs=[],
            )
        else:
            item["status"] = "blocked_quality"
            stats["blocked"] += 1
            record_decision(
                state,
                engine="Quality Gate",
                object_type="message",
                object_id=str(item.get("id") or ""),
                decision="outbound_blocked",
                reason="; ".join(reasons[:5]) or "Control de calidad no superado",
                action="block_outbound",
                confidence=0.99,
                evidence_refs=[],
            )

    state["quality_gate_stats"] = {**stats, "updated_at": utcnow()}
    if stats["reviewed"]:
        _log(state, f"Quality Gate revisó {stats['reviewed']} mensajes: {stats['passed']} autorizados y {stats['blocked']} bloqueados.")
    return stats
