from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

MAX_LEDGER = 600

LOW_RISK_ACTIONS = {"research_public", "classify_lead", "verify_company", "score_opportunity", "prepare_draft"}
MEDIUM_RISK_ACTIONS = {"prepare_outreach", "request_quote", "negotiate_nonbinding", "send_email"}
HIGH_RISK_ACTIONS = {"contract", "financial_commitment", "place_order", "accept_binding_terms", "payment"}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def ensure_governance_state(state: Dict[str, Any]) -> None:
    state.setdefault("decision_ledger", [])
    state.setdefault("governor_incidents", [])
    state.setdefault("governor_policy", {
        "require_verified_contact_for_email": True,
        "require_human_approval_for_contract": True,
        "require_human_approval_for_financial_commitment": True,
        "never_claim_unverified_evidence": True,
        "public_web_research_only": True,
    })


def risk_level(action: str) -> str:
    if action in HIGH_RISK_ACTIONS:
        return "high"
    if action in MEDIUM_RISK_ACTIONS:
        return "medium"
    return "low"


def record_decision(
    state: Dict[str, Any], *, engine: str, object_type: str, object_id: str,
    decision: str, reason: str, action: str = "classify_lead", confidence: float | None = None,
    evidence_refs: Iterable[str] | None = None, allowed: bool = True, requires_approval: bool = False,
) -> Dict[str, Any]:
    ensure_governance_state(state)
    ledger: List[Dict[str, Any]] = state["decision_ledger"]
    entry = {
        "id": f"DEC-{len(ledger)+1:06d}",
        "ts": utcnow(),
        "engine": engine,
        "object_type": object_type,
        "object_id": object_id,
        "decision": decision,
        "reason": reason[:600],
        "action": action,
        "risk": risk_level(action),
        "confidence": round(float(confidence), 2) if confidence is not None else None,
        "evidence_refs": [str(x)[:500] for x in (evidence_refs or [])][:8],
        "allowed": bool(allowed),
        "requires_approval": bool(requires_approval),
    }
    ledger.append(entry)
    if len(ledger) > MAX_LEDGER:
        del ledger[:-MAX_LEDGER]
    return entry


def authorize(state: Dict[str, Any], action: str, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
    ensure_governance_state(state)
    context = context or {}
    policy = state["governor_policy"]
    result = {"allowed": True, "requires_approval": False, "reason": "Dentro de política", "risk": risk_level(action)}

    if action in LOW_RISK_ACTIONS:
        return result

    if action == "send_email":
        if not context.get("live_outbound"):
            return {**result, "allowed": False, "reason": "Salida real deshabilitada"}
        if policy.get("require_verified_contact_for_email", True) and not context.get("contact_verified"):
            return {**result, "allowed": False, "reason": "Contacto no verificado"}
        if context.get("opt_out"):
            return {**result, "allowed": False, "reason": "Contraparte opt-out"}
        return result

    if action in {"contract", "accept_binding_terms"} and policy.get("require_human_approval_for_contract", True):
        return {**result, "allowed": False, "requires_approval": True, "reason": "Requiere aprobación humana contractual"}

    if action in {"financial_commitment", "place_order", "payment"} and policy.get("require_human_approval_for_financial_commitment", True):
        return {**result, "allowed": False, "requires_approval": True, "reason": "Requiere aprobación humana financiera"}

    return result


def register_incident(state: Dict[str, Any], engine: str, kind: str, detail: str) -> None:
    ensure_governance_state(state)
    incidents: List[Dict[str, Any]] = state["governor_incidents"]
    incidents.append({"ts": utcnow(), "engine": engine, "kind": kind, "detail": detail[:500]})
    if len(incidents) > 200:
        del incidents[:-200]
