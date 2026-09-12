from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from autonomy_governor import record_decision

MAX_FINDINGS = 120
MAX_MESSAGE_REVIEWS = 60
MAX_DEAL_REVIEWS = 80


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _risk_profile(state: Dict[str, Any], account_id: Any) -> Dict[str, Any]:
    return dict((state.get("counterparty_risk_index", {}) or {}).get(str(account_id or ""), {}) or {})


def _finding(*, severity: str, kind: str, object_type: str, object_id: str, title: str,
             reason: str, recommendation: str, blocking: bool = False, evidence: List[str] | None = None) -> Dict[str, Any]:
    return {
        "severity": severity,
        "kind": kind,
        "object_type": object_type,
        "object_id": object_id,
        "title": title,
        "reason": reason,
        "recommendation": recommendation,
        "blocking": bool(blocking),
        "evidence": list(evidence or [])[:8],
        "created_at": utcnow(),
    }


def _deal_findings(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    risk_index = state.get("counterparty_risk_index", {}) or {}
    offers = {str(x.get("id")): x for x in state.get("offers", []) or [] if x.get("id")}
    proposals_by_deal: Dict[str, List[Dict[str, Any]]] = {}
    for proposal in state.get("proposals", []) or []:
        proposals_by_deal.setdefault(str(proposal.get("deal_id") or ""), []).append(proposal)

    for deal in list(state.get("deals", []) or [])[:MAX_DEAL_REVIEWS]:
        if deal.get("source") == "demo" or str(deal.get("stage") or "") in {"closed_simulated", "cerrado (simulación)"}:
            continue
        deal_id = str(deal.get("id") or "")
        buyer_risk = risk_index.get(str(deal.get("buyer_account_id") or ""), {}) or {}
        supplier_risk = risk_index.get(str(deal.get("supplier_account_id") or ""), {}) or {}
        blocked_parties = [x for x in (buyer_risk, supplier_risk) if x.get("risk_tier") == "BLOCKED"]

        if blocked_parties:
            findings.append(_finding(
                severity="critical", kind="blocked_counterparty", object_type="deal", object_id=deal_id,
                title="Contraparte bloqueada dentro de una operación activa",
                reason="El deal contiene al menos una contraparte clasificada BLOCKED por identidad, opt-out, incidente o posible coincidencia oficial que exige verificación.",
                recommendation="Detener progresión comercial y verificar la contraparte antes de cualquier propuesta, negociación o cierre.",
                blocking=True,
                evidence=[str(x.get("account_id")) for x in blocked_parties if x.get("account_id")],
            ))

        safeguards = deal.get("deal_safeguards", {}) or {}
        safe_score = _f(safeguards.get("safe_close_score"), 100.0)
        capital_action = str(deal.get("capital_action") or "")
        if capital_action == "ACCELERATE" and (safe_score < 70 or deal.get("incident_hold") or deal.get("legal_review_required")):
            findings.append(_finding(
                severity="high", kind="strategy_risk_contradiction", object_type="deal", object_id=deal_id,
                title="Aceleración contradice el estado de riesgo",
                reason=f"Capital Intelligence marca ACCELERATE pero Safe Close={safe_score:.0f}, incident_hold={bool(deal.get('incident_hold'))}, legal_review={bool(deal.get('legal_review_required'))}.",
                recommendation="Suspender aceleración y reparar términos/riesgo antes de volver a priorizar el deal.",
                blocking=bool(deal.get("incident_hold") or deal.get("legal_review_required") or safe_score < 55),
            ))

        if deal.get("deal_safeguards_cleared") and (deal.get("incident_hold") or deal.get("legal_review_required")):
            findings.append(_finding(
                severity="critical", kind="safeguard_state_contradiction", object_type="deal", object_id=deal_id,
                title="Estado de Safeguards inconsistente",
                reason="El deal figura cleared y simultáneamente mantiene incidente o revisión legal obligatoria.",
                recommendation="Tratar el cierre como bloqueado y regenerar Safeguards/Pre-Close antes de cualquier aprobación.",
                blocking=True,
            ))

        close_stage = str(deal.get("stage") or "") in {"listo para cerrar", "autorizado para cierre", "listo para cierre aprobado", "preclose_validation"}
        missing = list(deal.get("preclose_missing") or [])
        if close_stage and missing:
            findings.append(_finding(
                severity="high", kind="preclose_contradiction", object_type="deal", object_id=deal_id,
                title="Deal cercano al cierre con controles pendientes",
                reason="La etapa sugiere cierre pero Pre-Close todavía informa faltantes: " + ", ".join(str(x) for x in missing[:6]),
                recommendation="No cerrar; completar controles y volver a evaluar.",
                blocking=True,
            ))

        for proposal in proposals_by_deal.get(deal_id, []):
            source_offer_id = str(proposal.get("source_offer_id") or "")
            source_offer = offers.get(source_offer_id)
            if not source_offer or source_offer.get("source") == "demo/simulación":
                findings.append(_finding(
                    severity="critical", kind="proposal_traceability_gap", object_type="proposal", object_id=str(proposal.get("id") or ""),
                    title="Propuesta sin oferta real trazable",
                    reason=f"La propuesta del deal {deal_id} no tiene una oferta fuente real y disponible.",
                    recommendation="Bloquear presentación al comprador hasta reconstruir la trazabilidad económica.",
                    blocking=True,
                    evidence=[source_offer_id] if source_offer_id else [],
                ))

        negotiation = (state.get("negotiation_plan_index", {}) or {}).get(deal_id, {}) or {}
        if negotiation.get("autonomous") and supplier_risk.get("risk_tier") == "BLOCKED":
            findings.append(_finding(
                severity="critical", kind="negotiation_risk_contradiction", object_type="deal", object_id=deal_id,
                title="Negociación autónoma contra contraparte bloqueada",
                reason="Negotiation Intelligence habilita una táctica autónoma mientras Counterparty Risk bloquea al proveedor.",
                recommendation="Cancelar presión comercial y verificar contraparte.",
                blocking=True,
            ))

    return findings


def _message_findings_and_blocks(state: Dict[str, Any]) -> tuple[List[Dict[str, Any]], int]:
    findings: List[Dict[str, Any]] = []
    blocked = 0
    sensitive_kinds = {"buyer_proposal", "supplier_negotiation", "buyer_information_response", "payment_status_reminder", "customer_success_checkin"}
    for item in list(state.get("outbox", []) or [])[:MAX_MESSAGE_REVIEWS]:
        if item.get("status") != "ready":
            continue
        reasons: List[str] = []
        deal = next((x for x in state.get("deals", []) or [] if str(x.get("id") or "") == str(item.get("deal_id") or "")), {})
        risk = _risk_profile(state, item.get("counterparty_account_id"))
        kind = str(item.get("kind") or "")

        if risk.get("risk_tier") == "BLOCKED":
            reasons.append("counterparty_risk_blocked")
        if deal and deal.get("incident_hold") and kind not in {"terms_clarification"}:
            reasons.append("commercial_incident_hold")
        if deal and deal.get("legal_review_required") and kind in sensitive_kinds:
            reasons.append("mandatory_legal_review")
        if kind == "buyer_proposal":
            safeguards = deal.get("deal_safeguards", {}) or {}
            if not safeguards.get("proposal_allowed", False):
                reasons.append("proposal_not_allowed_by_safeguards")
            if not deal.get("economics") or not deal.get("economics", {}).get("viable"):
                reasons.append("proposal_without_viable_economics")
        if kind == "supplier_negotiation" and deal:
            plan = (state.get("negotiation_plan_index", {}) or {}).get(str(deal.get("id") or ""), {}) or {}
            if plan.get("strategy") in {"HOLD", "WALK_AWAY_FROM_FURTHER_PRESSURE"}:
                reasons.append("negotiation_strategy_says_stop")

        if reasons:
            item["red_team_gate"] = "blocked"
            item["red_team_reasons"] = reasons[:8]
            item["red_team_reviewed_at"] = utcnow()
            item["status"] = "blocked_red_team"
            blocked += 1
            findings.append(_finding(
                severity="critical", kind="outbound_blocked_by_red_team", object_type="message", object_id=str(item.get("id") or ""),
                title="Mensaje bloqueado por Auditor Interno",
                reason="; ".join(reasons),
                recommendation="Resolver la contradicción y regenerar el mensaje con evidencia/estado actualizado.",
                blocking=True,
                evidence=[str(item.get("deal_id") or ""), str(item.get("counterparty_account_id") or "")],
            ))
        else:
            item["red_team_gate"] = "passed"
            item["red_team_reviewed_at"] = utcnow()
    return findings, blocked


def _decision_findings(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    # High-confidence decisions with no explicit evidence are challenged, not blocked: many engines summarize
    # state-derived evidence instead of carrying source URLs directly.
    for decision in list(state.get("decision_ledger", []) or [])[:80]:
        confidence = _f(decision.get("confidence"))
        evidence = list(decision.get("evidence_refs") or [])
        if confidence >= 0.95 and not evidence:
            findings.append(_finding(
                severity="medium", kind="high_confidence_without_explicit_refs", object_type=str(decision.get("object_type") or "decision"),
                object_id=str(decision.get("object_id") or ""),
                title="Confianza alta sin referencias explícitas",
                reason=f"{decision.get('engine') or 'Motor'} registró confianza {confidence:.2f} sin evidence_refs explícitos.",
                recommendation="Mantener como advertencia; exigir fuente explícita antes de convertir esa conclusión en compromiso vinculante.",
                blocking=False,
            ))
        if len(findings) >= 30:
            break
    return findings


def _apply_deal_holds(state: Dict[str, Any], findings: List[Dict[str, Any]]) -> int:
    blocking_deals = {str(x.get("object_id") or "") for x in findings if x.get("blocking") and x.get("object_type") == "deal"}
    changed = 0
    for deal in state.get("deals", []) or []:
        deal_id = str(deal.get("id") or "")
        active = deal_id in blocking_deals
        if bool(deal.get("red_team_hold")) != active:
            changed += 1
        deal["red_team_hold"] = active
        if active:
            deal["red_team_hold_at"] = utcnow()
    return changed


def red_team_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    deal_findings = _deal_findings(state)
    message_findings, messages_blocked = _message_findings_and_blocks(state)
    decision_findings = _decision_findings(state)
    findings = (deal_findings + message_findings + decision_findings)[:MAX_FINDINGS]
    holds_changed = _apply_deal_holds(state, findings)

    critical = sum(1 for x in findings if x.get("severity") == "critical")
    high = sum(1 for x in findings if x.get("severity") == "high")
    blocking = sum(1 for x in findings if x.get("blocking"))
    penalty = critical * 18 + high * 10 + max(0, len(findings) - critical - high) * 2
    audit_score = round(max(0.0, 100.0 - min(100.0, penalty)), 1)
    verdict = "BLOCK" if blocking else "CHALLENGE" if findings else "PASS"
    primary = next((x for x in findings if x.get("blocking")), findings[0] if findings else None)

    report = {
        "updated_at": utcnow(),
        "mode": "autonomous_internal_red_team",
        "verdict": verdict,
        "audit_score": audit_score,
        "findings": findings,
        "findings_total": len(findings),
        "critical": critical,
        "high": high,
        "blocking": blocking,
        "messages_blocked": messages_blocked,
        "deal_holds_changed": holds_changed,
        "primary_finding": primary,
        "governance": {
            "block_rule": "Automatic block only for strong contradictions or traceability/risk failures; weaker doubts remain challenges.",
            "truth_rule": "The Red Team cannot invent missing evidence; unknown stays unknown.",
            "authority_rule": "May block reversible execution or demand re-analysis; cannot approve contracts, payments or legal conclusions.",
            "learning_rule": "Findings are auditable and should feed future engine improvements; they do not prove causality or wrongdoing.",
        },
    }
    state["red_team_audit"] = report
    state["red_team_findings"] = findings

    if primary:
        record_decision(
            state,
            engine="Internal Red Team",
            object_type=str(primary.get("object_type") or "system"),
            object_id=str(primary.get("object_id") or "LUMEN"),
            decision=f"red_team:{verdict.lower()}",
            reason=str(primary.get("reason") or "Auditoría interna detectó una contradicción."),
            action="block_outbound" if primary.get("blocking") else "score_opportunity",
            confidence=0.97 if primary.get("blocking") else 0.78,
            evidence_refs=list(primary.get("evidence") or []),
            allowed=not bool(primary.get("blocking")),
            requires_approval=False,
        )
    return report
