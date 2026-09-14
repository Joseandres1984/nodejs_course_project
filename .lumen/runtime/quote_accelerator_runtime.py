from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

import commercial_execution

VERSION = "1.0-supplier-quote-accelerator"
_ORIGINAL_ENSURE = commercial_execution._ensure_revops_cases


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().strip().split())


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
    }
    return ordered


commercial_execution._ensure_revops_cases = _ensure_prioritized
print({"quote_accelerator_runtime": {"version": VERSION, "status": "active", "message_cap_unchanged": True}}, flush=True)
