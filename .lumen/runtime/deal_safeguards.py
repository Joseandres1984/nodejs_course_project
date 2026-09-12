from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from autonomy_governor import record_decision

MAX_CASES = 100
MAX_INCIDENTS = 100
MAX_OUTBOUND_PER_TICK = 1

HIGH_RISK_CLAUSES = {
    "unlimited_liability": ("responsabilidad ilimitada", "unlimited liability"),
    "indemnity": ("indemnizar", "indemnización", "indemnizacion", "indemnity", "hold harmless"),
    "penalty": ("penalidad", "penalty", "liquidated damages", "daños liquidados", "danos liquidados"),
    "consequential_damages": ("lucro cesante", "consequential damages", "indirect damages", "daños indirectos", "danos indirectos"),
    "exclusive_jurisdiction": ("jurisdicción exclusiva", "jurisdiccion exclusiva", "exclusive jurisdiction"),
    "governing_law": ("ley aplicable", "governing law", "applicable law"),
    "auto_renewal": ("renovación automática", "renovacion automatica", "automatic renewal"),
    "exclusivity": ("exclusividad", "exclusive supplier", "exclusive distributor"),
}

CLAUSE_SIGNALS = {
    "returns": ("devolución", "devolucion", "returns", "return policy", "rma"),
    "cancellation": ("cancelación", "cancelacion", "cancellation", "non-cancellable", "non cancelable"),
    "warranty": ("garantía", "garantia", "warranty"),
    "acceptance": ("aceptación", "aceptacion", "acceptance", "inspection", "inspección", "inspeccion"),
    "refund": ("reembolso", "refund", "reintegro"),
    "risk_transfer": ("transferencia de riesgo", "risk of loss", "transfer of risk", "title passes", "título", "titulo"),
}

INCIDENT_SIGNALS = {
    "return_request": ("devolución", "devolucion", "quiero devolver", "return request", "return the"),
    "defect_claim": ("defectuoso", "defecto", "falla", "no funciona", "defective", "faulty", "not working"),
    "damage_claim": ("dañado", "danado", "rotura", "golpeado", "damaged", "broken"),
    "delay_claim": ("demora", "retraso", "atraso", "late delivery", "delayed"),
    "missing_goods": ("faltante", "faltan", "missing item", "short shipment"),
    "warranty_claim": ("garantía", "garantia", "warranty claim"),
    "cancellation_request": ("cancelar", "cancelación", "cancelacion", "cancel order", "cancellation"),
    "refund_request": ("reembolso", "reintegro", "refund"),
    "legal_threat": ("abogado", "carta documento", "demanda", "judicial", "legal action", "lawsuit", "attorney"),
}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().strip().split())


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _known(value: Any) -> bool:
    return value not in (None, "", [], {}, "unknown", "por validar", "n/a")


def _accounts(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(x.get("id")): x for x in state.get("candidate_accounts", []) if x.get("id")}


def _deal_documents(state: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    inbox_to_deal = {str(x.get("id")): str(x.get("deal_id") or "") for x in state.get("inbox", []) if x.get("id")}
    offer_doc_to_deal = {
        str(x.get("document_id")): str(x.get("deal_id") or "")
        for x in state.get("offers", []) if x.get("document_id") and x.get("deal_id")
    }
    rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for doc in state.get("document_registry", []) or []:
        deal_ids = set()
        if str(doc.get("id") or "") in offer_doc_to_deal:
            deal_ids.add(offer_doc_to_deal[str(doc.get("id"))])
        for msg_id in doc.get("source_messages", []) or []:
            if inbox_to_deal.get(str(msg_id)):
                deal_ids.add(inbox_to_deal[str(msg_id)])
        for deal_id in deal_ids:
            rows[deal_id].append(doc)
    return rows


def _sender_role(state: Dict[str, Any], sender: Any) -> str:
    target = _norm(sender)
    if not target:
        return "unknown"
    for account in state.get("candidate_accounts", []) or []:
        email = _norm(account.get("commercial_email"))
        if email and email == target:
            return str(account.get("type") or "unknown")
    return "unknown"


def _scan_text(text: str) -> Dict[str, Any]:
    low = _norm(text)
    high: List[str] = []
    signals: List[str] = []
    for code, phrases in HIGH_RISK_CLAUSES.items():
        if any(p in low for p in phrases):
            high.append(code)
    for code, phrases in CLAUSE_SIGNALS.items():
        if any(p in low for p in phrases):
            signals.append(code)
    return {"high_risk": high, "signals": signals}


def _document_clause_context(state: Dict[str, Any], deal_id: str, docs: List[Dict[str, Any]]) -> Dict[str, Any]:
    out = {"buyer": {"high_risk": [], "signals": [], "documents": []}, "supplier": {"high_risk": [], "signals": [], "documents": []}, "unknown": {"high_risk": [], "signals": [], "documents": []}}
    for doc in docs:
        text = str(doc.get("text_excerpt") or "")
        if not text:
            continue
        role = _sender_role(state, doc.get("sender"))
        if role not in out:
            role = "unknown"
        scan = _scan_text(text)
        out[role]["high_risk"].extend(scan["high_risk"])
        out[role]["signals"].extend(scan["signals"])
        out[role]["documents"].append(doc.get("id"))
    for role in out:
        out[role]["high_risk"] = list(dict.fromkeys(out[role]["high_risk"]))
        out[role]["signals"] = list(dict.fromkeys(out[role]["signals"]))
    return out


def _offer_terms(offers: List[Dict[str, Any]]) -> Dict[str, Any]:
    warranty = [x.get("warranty") for x in offers if _known(x.get("warranty"))]
    returns = [x.get("return_terms") or x.get("returns_policy") for x in offers if _known(x.get("return_terms") or x.get("returns_policy"))]
    cancellation = [x.get("cancellation_terms") for x in offers if _known(x.get("cancellation_terms"))]
    payment = [x.get("payment_terms") for x in offers if _known(x.get("payment_terms"))]
    delivery = [x.get("freight_terms") or x.get("delivery_terms") for x in offers if _known(x.get("freight_terms") or x.get("delivery_terms"))]
    compliance = [x.get("technical_compliance") for x in offers if _known(x.get("technical_compliance"))]
    return {
        "warranty_known": bool(warranty),
        "returns_known": bool(returns),
        "cancellation_known": bool(cancellation),
        "payment_known": bool(payment),
        "delivery_known": bool(delivery),
        "technical_compliance_known": bool(compliance),
        "warranty_samples": warranty[:4],
        "return_samples": returns[:4],
        "cancellation_samples": cancellation[:4],
    }


def _buyer_expectations(deal: Dict[str, Any], clauses: Dict[str, Any]) -> Dict[str, bool]:
    requirement = deal.get("requirement", {}) or {}
    text = _norm(" ".join(str(x) for x in [
        deal.get("buyer_terms"), deal.get("commercial_terms"), deal.get("acceptance_terms"),
        deal.get("return_terms"), deal.get("warranty_terms"), requirement.get("commercial_terms"),
        requirement.get("warranty_requirement"), requirement.get("acceptance_criteria"), requirement.get("return_requirements"),
    ] if x))
    return {
        "returns_expected": "returns" in clauses.get("buyer", {}).get("signals", []) or any(x in text for x in ("devol", "return", "rma")),
        "cancellation_expected": "cancellation" in clauses.get("buyer", {}).get("signals", []) or "cancel" in text,
        "warranty_expected": "warranty" in clauses.get("buyer", {}).get("signals", []) or any(x in text for x in ("garant", "warranty")),
        "acceptance_expected": "acceptance" in clauses.get("buyer", {}).get("signals", []) or any(x in text for x in ("acept", "inspection", "inspecc")),
    }


def _payment_exposure(deal: Dict[str, Any], offers: List[Dict[str, Any]]) -> Dict[str, Any]:
    buyer_terms = _norm(deal.get("buyer_payment_terms") or deal.get("commercial_terms") or "")
    supplier_terms = " | ".join(_norm(x.get("payment_terms")) for x in offers if _known(x.get("payment_terms")))
    supplier_advance = any(x in supplier_terms for x in ("anticipo", "advance", "prepayment", "100%", "50% adelant"))
    buyer_deferred = any(x in buyer_terms for x in ("30 días", "30 dias", "45 días", "45 dias", "60 días", "60 dias", "90 días", "90 dias", "net 30", "net 45", "net 60", "net 90"))
    return {"supplier_advance_detected": supplier_advance, "buyer_deferred_detected": buyer_deferred, "cash_gap_risk": supplier_advance and buyer_deferred}


def _structure(case: Dict[str, Any]) -> Dict[str, Any]:
    severe = bool(case.get("mandatory_legal_review"))
    gaps = set(case.get("critical_gaps") or [])
    if severe:
        return {"code": "legal_review_before_commitment", "title": "Revisión legal antes de aceptar términos", "autonomous": False, "reason": "Se detectaron cláusulas de exposición elevada o amenaza legal que requieren criterio profesional humano."}
    if {"returns_mismatch", "cancellation_mismatch", "warranty_mismatch"} & gaps:
        return {"code": "back_to_back_terms_first", "title": "Alinear términos comprador↔proveedor antes de cerrar", "autonomous": True, "reason": "No conviene prometer al comprador una protección que el proveedor no respalda."}
    if "cash_gap_risk" in gaps:
        return {"code": "buyer_commitment_before_supplier_commitment", "title": "Evitar financiar el riesgo del negocio", "autonomous": True, "reason": "El proveedor exige desembolso antes de que el comprador pague; negociar hitos/condiciones antes de comprometer capital."}
    if "acceptance_criteria_missing" in gaps:
        return {"code": "define_acceptance_before_close", "title": "Definir aceptación e inspección antes del cierre", "autonomous": True, "reason": "La aceptación objetiva reduce disputas sobre conformidad y devoluciones posteriores."}
    if gaps:
        return {"code": "complete_protective_terms", "title": "Completar condiciones protectivas", "autonomous": True, "reason": "Faltan condiciones comerciales/documentales necesarias para un cierre seguro."}
    return {"code": "matched_terms_close", "title": "Cerrar con términos alineados y trazables", "autonomous": True, "reason": "No se detectan asimetrías materiales entre lo ofrecido, lo exigido y lo documentado."}


def _case_for(state: Dict[str, Any], deal: Dict[str, Any], docs: List[Dict[str, Any]]) -> Dict[str, Any]:
    deal_id = str(deal.get("id") or "")
    offers = [x for x in state.get("offers", []) if str(x.get("deal_id") or "") == deal_id and x.get("source") != "demo/simulación"]
    clauses = _document_clause_context(state, deal_id, docs)
    supplier_terms = _offer_terms(offers)
    buyer = _buyer_expectations(deal, clauses)
    payment = _payment_exposure(deal, offers)
    trade_cases = [x for x in state.get("trade_cases", []) if str(x.get("deal_id") or "") == deal_id]

    gaps: List[str] = []
    warnings: List[str] = []
    high_risk = list(dict.fromkeys(clauses.get("buyer", {}).get("high_risk", []) + clauses.get("supplier", {}).get("high_risk", []) + clauses.get("unknown", {}).get("high_risk", [])))
    mandatory_legal_review = bool(high_risk)

    if buyer["returns_expected"] and not supplier_terms["returns_known"]:
        gaps.append("returns_mismatch")
    if buyer["cancellation_expected"] and not supplier_terms["cancellation_known"]:
        gaps.append("cancellation_mismatch")
    if buyer["warranty_expected"] and not supplier_terms["warranty_known"]:
        gaps.append("warranty_mismatch")
    if buyer["acceptance_expected"] and not _known(deal.get("acceptance_criteria")):
        gaps.append("acceptance_criteria_missing")
    if not supplier_terms["technical_compliance_known"]:
        gaps.append("technical_compliance_not_confirmed")
    if not supplier_terms["warranty_known"]:
        warnings.append("supplier_warranty_not_explicit")
    if payment["cash_gap_risk"]:
        gaps.append("cash_gap_risk")
    if any(x.get("cross_border") is True and not x.get("decision_ready") for x in trade_cases):
        gaps.append("cross_border_terms_incomplete")
    if not deal.get("buyer_legal_identity_verified"):
        gaps.append("buyer_legal_identity_unconfirmed")
    if not deal.get("supplier_legal_identity_verified"):
        gaps.append("supplier_legal_identity_unconfirmed")

    severe_codes = {"unlimited_liability", "indemnity", "penalty", "consequential_damages", "exclusive_jurisdiction", "governing_law", "exclusivity", "auto_renewal"}
    if any(x in severe_codes for x in high_risk):
        mandatory_legal_review = True

    severity_weight = {
        "returns_mismatch": 15, "cancellation_mismatch": 15, "warranty_mismatch": 13,
        "acceptance_criteria_missing": 10, "technical_compliance_not_confirmed": 12,
        "cash_gap_risk": 14, "cross_border_terms_incomplete": 12,
        "buyer_legal_identity_unconfirmed": 16, "supplier_legal_identity_unconfirmed": 16,
    }
    exposure = min(100, sum(severity_weight.get(x, 8) for x in set(gaps)) + len(high_risk) * 20)
    safe_close_score = max(0, 100 - exposure)
    cleared = not mandatory_legal_review and not any(x in set(gaps) for x in {
        "returns_mismatch", "cancellation_mismatch", "warranty_mismatch", "acceptance_criteria_missing",
        "technical_compliance_not_confirmed", "cash_gap_risk", "cross_border_terms_incomplete",
        "buyer_legal_identity_unconfirmed", "supplier_legal_identity_unconfirmed",
    })

    case = {
        "deal_id": deal_id,
        "updated_at": utcnow(),
        "safe_close_score": safe_close_score,
        "exposure_score": exposure,
        "cleared": cleared,
        "mandatory_legal_review": mandatory_legal_review,
        "high_risk_clause_signals": high_risk,
        "critical_gaps": list(dict.fromkeys(gaps)),
        "warnings": list(dict.fromkeys(warnings)),
        "buyer_expectations": buyer,
        "supplier_terms": supplier_terms,
        "payment_exposure": payment,
        "document_clause_context": clauses,
        "recommended_structure": None,
        "proposal_allowed": not mandatory_legal_review and "technical_compliance_not_confirmed" not in gaps,
        "governance": {
            "legal_interpretation": "signal_detection_only_not_legal_advice",
            "binding_terms": "never_accepted_autonomously",
            "refunds_returns_concessions": "never_promised_autonomously",
            "evidence_rule": "only explicit traceable terms are treated as confirmed",
        },
    }
    case["recommended_structure"] = _structure(case)
    return case


def _existing_keys(state: Dict[str, Any]) -> set[str]:
    return {str(x.get("execution_key")) for x in state.get("outbox", []) if x.get("execution_key")}


def _account(state: Dict[str, Any], account_id: Any) -> Dict[str, Any]:
    return _accounts(state).get(str(account_id or ""), {})


def _prepare_clarification(state: Dict[str, Any], deal: Dict[str, Any], case: Dict[str, Any], budget: List[int]) -> int:
    if budget[0] <= 0 or case.get("mandatory_legal_review"):
        return 0
    gaps = set(case.get("critical_gaps") or [])
    target_supplier_gaps = [x for x in ("returns_mismatch", "cancellation_mismatch", "warranty_mismatch", "technical_compliance_not_confirmed") if x in gaps]
    if not target_supplier_gaps:
        return 0
    supplier = _account(state, deal.get("supplier_account_id"))
    contact = str(supplier.get("commercial_email") or "").strip().lower()
    if not contact or not supplier.get("verified_contact"):
        return 0
    key = f"deal_safeguards|supplier_terms|{deal.get('id')}|{'-'.join(target_supplier_gaps)}"
    if key in _existing_keys(state):
        return 0
    ask_map = {
        "returns_mismatch": "política aplicable ante devolución/no conformidad y procedimiento RMA, si corresponde",
        "cancellation_mismatch": "condiciones de cancelación o modificación una vez emitido el pedido",
        "warranty_mismatch": "alcance, plazo y exclusiones de garantía",
        "technical_compliance_not_confirmed": "confirmación expresa de cumplimiento con la especificación/requerimiento indicado",
    }
    asks = "\n".join(f"- {ask_map[x]}" for x in target_supplier_gaps)
    body = (
        "Para cerrar el análisis comercial sin asumir condiciones que no hayan sido confirmadas, agradeceremos precisar:\n\n"
        f"{asks}\n\n"
        "La consulta es exploratoria y no implica aceptación de términos, orden de compra ni compromiso financiero."
    )
    state.setdefault("outbox", []).append({
        "id": f"MSG-{len(state.get('outbox', []))+1:04d}",
        "deal_id": deal.get("id"),
        "kind": "terms_clarification",
        "purpose": "deal_safeguards",
        "counterparty": supplier.get("company_name") or supplier.get("name_hint") or deal.get("supplier"),
        "channel": "email",
        "contact": contact,
        "contact_verified": True,
        "subject": f"Aclaración de condiciones — {deal.get('need') or 'operación B2B'}",
        "body": body,
        "status": "ready",
        "execution_key": key,
        "created_at": utcnow(),
    })
    budget[0] -= 1
    return 1


def _incident_kind(body: str) -> List[str]:
    low = _norm(body)
    return [code for code, phrases in INCIDENT_SIGNALS.items() if any(p in low for p in phrases)]


def _incidents(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    existing = {str(x.get("source_message_id")): x for x in state.setdefault("commercial_incidents", []) if x.get("source_message_id")}
    deals = {str(x.get("id")): x for x in state.get("deals", []) if x.get("id")}
    for msg in state.get("inbox", []) or []:
        deal_id = str(msg.get("deal_id") or "")
        if not deal_id or deal_id not in deals or not msg.get("id"):
            continue
        signals = _incident_kind(str(msg.get("body") or ""))
        if not signals:
            continue
        key = str(msg.get("id"))
        if key in existing:
            continue
        severity = "critical" if "legal_threat" in signals else "high" if any(x in signals for x in ("refund_request", "return_request", "cancellation_request", "defect_claim", "damage_claim")) else "medium"
        incident = {
            "id": f"INC-{len(existing)+1:05d}",
            "deal_id": deal_id,
            "source_message_id": key,
            "signals": signals,
            "severity": severity,
            "status": "evidence_review",
            "liability_admission_allowed": False,
            "refund_or_return_commitment_allowed": False,
            "recommended_action": "preserve_evidence_and_compare_promised_vs_supplier_backing",
            "created_at": utcnow(),
        }
        existing[key] = incident
        deals[deal_id]["commercial_incident_open"] = True
        deals[deal_id]["incident_hold"] = True
        record_decision(
            state,
            engine="Deal Safeguards / Dispute Prevention",
            object_type="deal",
            object_id=deal_id,
            decision="commercial_incident_opened",
            reason=f"Se detectaron señales de reclamo/incidente: {', '.join(signals)}. Se congela cualquier concesión o admisión automática hasta revisar evidencia.",
            action="prepare_draft",
            confidence=0.9,
            evidence_refs=[key],
            requires_approval=severity in {"high", "critical"},
        )
    state["commercial_incidents"] = list(existing.values())[-MAX_INCIDENTS:]
    return state["commercial_incidents"]


def deal_safeguards_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    docs_by_deal = _deal_documents(state)
    cases: List[Dict[str, Any]] = []
    budget = [MAX_OUTBOUND_PER_TICK]
    clarification_messages = 0

    for deal in state.get("deals", []) or []:
        if not deal.get("id") or deal.get("source") == "demo" or str(deal.get("stage") or "") in {"cerrado (simulación)", "closed_simulated"}:
            continue
        case = _case_for(state, deal, docs_by_deal.get(str(deal.get("id")), []))
        cases.append(case)
        deal["deal_safeguards"] = {
            "safe_close_score": case["safe_close_score"],
            "exposure_score": case["exposure_score"],
            "cleared": case["cleared"],
            "mandatory_legal_review": case["mandatory_legal_review"],
            "critical_gaps": case["critical_gaps"],
            "recommended_structure": case["recommended_structure"],
            "proposal_allowed": case["proposal_allowed"],
            "updated_at": case["updated_at"],
        }
        deal["deal_safeguards_cleared"] = bool(case["cleared"])
        deal["legal_review_required"] = bool(case["mandatory_legal_review"])
        deal["safe_close_score"] = case["safe_close_score"]
        if deal.get("incident_hold"):
            deal["deal_safeguards_cleared"] = False
        clarification_messages += _prepare_clarification(state, deal, case, budget)

    cases.sort(key=lambda x: (not x.get("cleared"), _f(x.get("exposure_score"))), reverse=True)
    cases = cases[:MAX_CASES]
    state["deal_safeguard_cases"] = cases
    state["deal_safeguard_index"] = {str(x.get("deal_id")): x for x in cases}

    incidents = _incidents(state)
    open_incidents = [x for x in incidents if x.get("status") not in {"resolved", "closed"}]
    blocked = [x for x in cases if not x.get("cleared")]
    legal = [x for x in cases if x.get("mandatory_legal_review")]
    primary = cases[0] if cases else None
    directive = {
        "deal_id": (primary or {}).get("deal_id"),
        "safe_close_score": (primary or {}).get("safe_close_score"),
        "exposure_score": (primary or {}).get("exposure_score"),
        "recommended_structure": (primary or {}).get("recommended_structure"),
        "critical_gaps": (primary or {}).get("critical_gaps", []),
        "mandatory_legal_review": bool((primary or {}).get("mandatory_legal_review")),
    } if primary else {}

    report = {
        "updated_at": utcnow(),
        "mode": "deal_safeguards_and_dispute_prevention",
        "deals_reviewed": len(cases),
        "cleared": sum(1 for x in cases if x.get("cleared")),
        "blocked": len(blocked),
        "mandatory_legal_review": len(legal),
        "clarification_messages_created": clarification_messages,
        "open_incidents": len(open_incidents),
        "primary_directive": directive,
        "governance": {
            "objective": "maximize safe risk-adjusted close probability, not raw closes",
            "legal_boundary": "high-risk legal clauses are detected and escalated; LUMEN does not provide jurisdiction-specific legal conclusions",
            "claims_boundary": "no autonomous admission of liability, refund, return acceptance, penalty acceptance or indemnity",
            "back_to_back_rule": "do not promise buyer protections that are not backed by supplier terms or explicit company policy",
            "binding_rule": "contracts, purchase orders, binding terms and payments remain human-gated",
        },
    }
    state["deal_safeguards_report"] = report

    if primary:
        record_decision(
            state,
            engine="Deal Safeguards / Dispute Prevention",
            object_type="deal",
            object_id=str(primary.get("deal_id") or ""),
            decision="safe_close_assessment",
            reason=f"Safe close {primary.get('safe_close_score')}%; exposure {primary.get('exposure_score')}%; gaps: {', '.join(primary.get('critical_gaps', [])[:6]) or 'none'}.",
            action="prepare_draft",
            confidence=0.94,
            evidence_refs=[],
            requires_approval=bool(primary.get("mandatory_legal_review")),
        )
    return report
