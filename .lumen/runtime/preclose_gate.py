from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from autonomy_governor import record_decision


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# These controls must be complete BEFORE the human is asked to approve a binding close.
# Human approval itself is a separate final authority step, not a prerequisite to become approvable.
REQUIRED_BEFORE_APPROVAL_FIELDS = [
    "buyer_legal_identity_verified",
    "supplier_legal_identity_verified",
    "requirement_confirmed",
    "commercial_terms_confirmed",
    "delivery_terms_confirmed",
    "invoice_tax_treatment_confirmed",
    "payment_instructions_verified",
    "revenue_model_confirmed",
    "commission_terms_secured",
    "payment_route_ready",
    "deal_safeguards_cleared",
]


def _checklist(deal: Dict[str, Any]) -> Dict[str, bool]:
    approval = bool(deal.get("close_approval_status") == "approved" or deal.get("human_close_approval"))
    safeguards = bool(
        deal.get("deal_safeguards_cleared")
        and not deal.get("legal_review_required")
        and not deal.get("incident_hold")
        and not deal.get("red_team_hold")
    )
    return {
        "buyer_legal_identity_verified": bool(deal.get("buyer_legal_identity_verified")),
        "supplier_legal_identity_verified": bool(deal.get("supplier_legal_identity_verified")),
        "requirement_confirmed": bool(deal.get("requirement_confirmed")),
        "commercial_terms_confirmed": bool(deal.get("commercial_terms_confirmed")),
        "delivery_terms_confirmed": bool(deal.get("delivery_terms_confirmed")),
        "invoice_tax_treatment_confirmed": bool(deal.get("invoice_tax_treatment_confirmed")),
        "payment_instructions_verified": bool(deal.get("payment_instructions_verified")),
        "revenue_model_confirmed": bool(deal.get("revenue_model_confirmed")),
        "commission_terms_secured": bool(deal.get("commission_terms_secured")),
        "payment_route_ready": bool(deal.get("payment_route_ready")),
        "deal_safeguards_cleared": safeguards,
        "human_close_approval": approval,
    }


def preclose_tick(state: Dict[str, Any]) -> Dict[str, int]:
    stats = {"reviewed": 0, "ready_for_approval": 0, "approved_ready": 0, "blocked": 0, "safeguard_blocked": 0}
    for deal in state.get("deals", []):
        if deal.get("source") == "demo":
            continue
        if deal.get("stage") not in {"listo para cerrar", "autorizado para cierre", "preclose_validation", "listo para cierre aprobado"}:
            continue
        stats["reviewed"] += 1
        checklist = _checklist(deal)
        missing: List[str] = [key for key in REQUIRED_BEFORE_APPROVAL_FIELDS if not checklist.get(key)]
        deal["preclose_checklist"] = checklist
        deal["preclose_missing"] = missing
        deal["preclose_reviewed_at"] = utcnow()
        deal["preclose_ready_for_human_approval"] = not missing

        if missing:
            deal["stage"] = "preclose_validation"
            deal["next_action"] = "Completar controles previos a la aprobación vinculante: " + ", ".join(missing[:6])
            deal["close_gate"] = "blocked"
            stats["blocked"] += 1
            if "deal_safeguards_cleared" in missing:
                stats["safeguard_blocked"] += 1
            record_decision(
                state,
                engine="Pre-Close Gate",
                object_type="deal",
                object_id=str(deal.get("id") or ""),
                decision="close_blocked",
                reason="Faltan controles contractuales, fiscales, de identidad, entrega, pago, modelo de ingresos, comisión, ruta de cobro o Deal Safeguards.",
                action="block_contractual_commitment",
                confidence=1.0,
                evidence_refs=[],
            )
            continue

        if checklist.get("human_close_approval"):
            deal["close_gate"] = "ready"
            deal["stage"] = "listo para cierre aprobado"
            deal["next_action"] = "Ejecutar el cierre exactamente dentro de la aprobación y los términos validados"
            stats["approved_ready"] += 1
            record_decision(
                state,
                engine="Pre-Close Gate",
                object_type="deal",
                object_id=str(deal.get("id") or ""),
                decision="close_ready_after_human_approval",
                reason="Controles completos y aprobación humana registrada.",
                action="permit_close_execution",
                confidence=1.0,
                evidence_refs=[],
            )
        else:
            deal["close_gate"] = "awaiting_human_approval"
            deal["stage"] = "listo para cerrar"
            deal["next_action"] = "Solicitar la aprobación humana final del paquete de cierre"
            stats["ready_for_approval"] += 1
            record_decision(
                state,
                engine="Pre-Close Gate",
                object_type="deal",
                object_id=str(deal.get("id") or ""),
                decision="ready_for_human_close_approval",
                reason="Todos los controles previos al compromiso están completos; solo falta la autorización humana vinculante.",
                action="request_human_close_approval",
                confidence=1.0,
                evidence_refs=[],
                requires_approval=True,
            )

    state["preclose_gate_stats"] = {**stats, "updated_at": utcnow()}
    return stats
