from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List

from autonomy_governor import record_decision
from preclose_gate import preclose_tick

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
    "return_request": ("solicito devolución", "solicitamos devolución", "quiero devolver", "return request", "request a return"),
    "defect_claim": ("producto defectuoso", "equipo defectuoso", "presenta una falla", "no funciona", "defective", "faulty", "not working"),
    "damage_claim": ("llegó dañado", "llego danado", "mercadería dañada", "mercaderia danada", "arrived damaged", "damaged goods"),
    "delay_claim": ("entrega demorada", "entrega retrasada", "incumplimiento de plazo", "late delivery", "delivery delayed"),
    "missing_goods": ("mercadería faltante", "mercaderia faltante", "faltan unidades", "missing item", "short shipment"),
    "warranty_claim": ("reclamo de garantía", "reclamo de garantia", "hacer uso de la garantía", "hacer uso de la garantia", "warranty claim"),
    "cancellation_request": ("solicito cancelar", "solicitamos cancelar", "cancelar el pedido", "cancel order", "cancellation request"),
    "refund_request": ("solicito reembolso", "solicito reintegro", "request a refund", "refund request"),
    "legal_threat": ("carta documento", "iniciaremos acciones", "acciones legales", "demanda judicial", "legal action", "lawsuit", "attorney"),
}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _norm(v: Any) -> str:
    return " ".join(str(v or "").lower().strip().split())


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _known(v: Any) -> bool:
    return v not in (None, "", [], {}, "unknown", "por validar", "n/a")


def _accounts(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(x.get("id")): x for x in state.get("candidate_accounts", []) if x.get("id")}


def _deal_documents(state: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    inbox_to_deal = {str(x.get("id")): str(x.get("deal_id") or "") for x in state.get("inbox", []) if x.get("id")}
    offer_doc_to_deal = {str(x.get("document_id")): str(x.get("deal_id") or "") for x in state.get("offers", []) if x.get("document_id") and x.get("deal_id")}
    rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for doc in state.get("document_registry", []) or []:
        ids = set()
        if str(doc.get("id") or "") in offer_doc_to_deal:
            ids.add(offer_doc_to_deal[str(doc.get("id"))])
        for msg_id in doc.get("source_messages", []) or []:
            if inbox_to_deal.get(str(msg_id)):
                ids.add(inbox_to_deal[str(msg_id)])
        for deal_id in ids:
            rows[deal_id].append(doc)
    return rows


def _sender_role(state: Dict[str, Any], sender: Any) -> str:
    target = _norm(sender)
    for account in state.get("candidate_accounts", []) or []:
        if target and _norm(account.get("commercial_email")) == target:
            return str(account.get("type") or "unknown")
    return "unknown"


def _scan(text: str) -> Dict[str, List[str]]:
    low = _norm(text)
    return {
        "high_risk": [code for code, phrases in HIGH_RISK_CLAUSES.items() if any(p in low for p in phrases)],
        "signals": [code for code, phrases in CLAUSE_SIGNALS.items() if any(p in low for p in phrases)],
    }


def _clauses(state: Dict[str, Any], docs: List[Dict[str, Any]]) -> Dict[str, Any]:
    out = {role: {"high_risk": [], "signals": [], "documents": []} for role in ("buyer", "supplier", "unknown")}
    for doc in docs:
        text = str(doc.get("text_excerpt") or "")
        if not text:
            continue
        role = _sender_role(state, doc.get("sender"))
        role = role if role in out else "unknown"
        scan = _scan(text)
        out[role]["high_risk"].extend(scan["high_risk"])
        out[role]["signals"].extend(scan["signals"])
        out[role]["documents"].append(doc.get("id"))
    for role in out:
        out[role]["high_risk"] = list(dict.fromkeys(out[role]["high_risk"]))
        out[role]["signals"] = list(dict.fromkeys(out[role]["signals"]))
    return out


def _offer_terms(offers: List[Dict[str, Any]], supplier_signals: List[str]) -> Dict[str, Any]:
    warranty = [x.get("warranty") for x in offers if _known(x.get("warranty"))]
    returns = [x.get("return_terms") or x.get("returns_policy") for x in offers if _known(x.get("return_terms") or x.get("returns_policy"))]
    cancellation = [x.get("cancellation_terms") for x in offers if _known(x.get("cancellation_terms"))]
    return {
        "warranty_known": bool(warranty) or "warranty" in supplier_signals,
        "returns_known": bool(returns) or "returns" in supplier_signals,
        "cancellation_known": bool(cancellation) or "cancellation" in supplier_signals,
        "payment_known": any(_known(x.get("payment_terms")) for x in offers),
        "delivery_known": any(_known(x.get("freight_terms") or x.get("delivery_terms")) for x in offers),
        "technical_compliance_known": any(_known(x.get("technical_compliance")) for x in offers),
        "warranty_samples": warranty[:4], "return_samples": returns[:4], "cancellation_samples": cancellation[:4],
        "document_signals": supplier_signals,
    }


def _buyer_expectations(deal: Dict[str, Any], clauses: Dict[str, Any]) -> Dict[str, bool]:
    requirement = deal.get("requirement", {}) or {}
    text = _norm(" ".join(str(x) for x in [deal.get("buyer_terms"), deal.get("commercial_terms"), deal.get("acceptance_terms"), deal.get("return_terms"), deal.get("warranty_terms"), requirement.get("commercial_terms"), requirement.get("warranty_requirement"), requirement.get("acceptance_criteria"), requirement.get("return_requirements")] if x))
    signals = clauses.get("buyer", {}).get("signals", [])
    return {
        "returns_expected": "returns" in signals or any(x in text for x in ("devol", "return", "rma")),
        "cancellation_expected": "cancellation" in signals or "cancel" in text,
        "warranty_expected": "warranty" in signals or any(x in text for x in ("garant", "warranty")),
        "acceptance_expected": "acceptance" in signals or any(x in text for x in ("acept", "inspection", "inspecc")),
    }


def _payment_exposure(deal: Dict[str, Any], offers: List[Dict[str, Any]]) -> Dict[str, Any]:
    buyer_terms = _norm(deal.get("buyer_payment_terms") or deal.get("commercial_terms") or "")
    supplier_terms = " | ".join(_norm(x.get("payment_terms")) for x in offers if _known(x.get("payment_terms")))
    supplier_advance = any(x in supplier_terms for x in ("anticipo", "advance", "prepayment", "100%", "50% adelant"))
    buyer_deferred = any(x in buyer_terms for x in ("30 días", "30 dias", "45 días", "45 dias", "60 días", "60 dias", "90 días", "90 dias", "net 30", "net 45", "net 60", "net 90"))
    return {"supplier_advance_detected": supplier_advance, "buyer_deferred_detected": buyer_deferred, "cash_gap_risk": supplier_advance and buyer_deferred}


def _structure(case: Dict[str, Any]) -> Dict[str, Any]:
    gaps = set(case.get("critical_gaps") or [])
    if case.get("mandatory_legal_review"):
        return {"code": "legal_review_before_commitment", "title": "Revisión legal antes de aceptar términos", "autonomous": False, "reason": "Hay cláusulas de exposición elevada que requieren criterio profesional humano."}
    if gaps & {"returns_mismatch", "cancellation_mismatch", "warranty_mismatch"}:
        return {"code": "back_to_back_terms_first", "title": "Alinear términos comprador↔proveedor antes de cerrar", "autonomous": True, "reason": "No prometer al comprador una protección que el proveedor no respalda."}
    if "cash_gap_risk" in gaps:
        return {"code": "buyer_commitment_before_supplier_commitment", "title": "Evitar financiar el riesgo del negocio", "autonomous": True, "reason": "Negociar hitos/condiciones antes de comprometer capital."}
    if "acceptance_criteria_missing" in gaps:
        return {"code": "define_acceptance_before_close", "title": "Definir aceptación e inspección antes del cierre", "autonomous": True, "reason": "Criterios objetivos reducen disputas y devoluciones."}
    if gaps:
        return {"code": "complete_protective_terms", "title": "Completar condiciones protectivas", "autonomous": True, "reason": "Faltan condiciones/documentos para un cierre seguro."}
    return {"code": "matched_terms_close", "title": "Cerrar con términos alineados y trazables", "autonomous": True, "reason": "No se detectan asimetrías materiales conocidas."}


def _case_for(state: Dict[str, Any], deal: Dict[str, Any], docs: List[Dict[str, Any]]) -> Dict[str, Any]:
    deal_id = str(deal.get("id") or "")
    offers = [x for x in state.get("offers", []) if str(x.get("deal_id") or "") == deal_id and x.get("source") != "demo/simulación"]
    clauses = _clauses(state, docs)
    supplier_terms = _offer_terms(offers, clauses.get("supplier", {}).get("signals", []))
    buyer = _buyer_expectations(deal, clauses)
    payment = _payment_exposure(deal, offers)
    trade_cases = [x for x in state.get("trade_cases", []) if str(x.get("deal_id") or "") == deal_id]
    gaps: List[str] = []
    warnings: List[str] = []
    high_risk = list(dict.fromkeys(clauses.get("buyer", {}).get("high_risk", []) + clauses.get("supplier", {}).get("high_risk", []) + clauses.get("unknown", {}).get("high_risk", [])))

    if buyer["returns_expected"] and not supplier_terms["returns_known"]: gaps.append("returns_mismatch")
    if buyer["cancellation_expected"] and not supplier_terms["cancellation_known"]: gaps.append("cancellation_mismatch")
    if buyer["warranty_expected"] and not supplier_terms["warranty_known"]: gaps.append("warranty_mismatch")
    if buyer["acceptance_expected"] and not _known(deal.get("acceptance_criteria")): gaps.append("acceptance_criteria_missing")
    if not supplier_terms["technical_compliance_known"]: gaps.append("technical_compliance_not_confirmed")
    if not supplier_terms["warranty_known"]: warnings.append("supplier_warranty_not_explicit")
    if payment["cash_gap_risk"]: gaps.append("cash_gap_risk")
    if any(x.get("cross_border") is True and not x.get("decision_ready") for x in trade_cases): gaps.append("cross_border_terms_incomplete")
    if not deal.get("buyer_legal_identity_verified"): gaps.append("buyer_legal_identity_unconfirmed")
    if not deal.get("supplier_legal_identity_verified"): gaps.append("supplier_legal_identity_unconfirmed")

    weight = {"returns_mismatch":15,"cancellation_mismatch":15,"warranty_mismatch":13,"acceptance_criteria_missing":10,"technical_compliance_not_confirmed":12,"cash_gap_risk":14,"cross_border_terms_incomplete":12,"buyer_legal_identity_unconfirmed":16,"supplier_legal_identity_unconfirmed":16}
    exposure = min(100, sum(weight.get(x, 8) for x in set(gaps)) + len(high_risk) * 20)
    blocking = set(weight)
    mandatory = bool(high_risk)
    case = {
        "deal_id": deal_id, "updated_at": utcnow(), "safe_close_score": max(0, 100-exposure), "exposure_score": exposure,
        "cleared": not mandatory and not bool(set(gaps) & blocking), "mandatory_legal_review": mandatory,
        "high_risk_clause_signals": high_risk, "critical_gaps": list(dict.fromkeys(gaps)), "warnings": list(dict.fromkeys(warnings)),
        "buyer_expectations": buyer, "supplier_terms": supplier_terms, "payment_exposure": payment, "document_clause_context": clauses,
        "proposal_allowed": not mandatory and "technical_compliance_not_confirmed" not in gaps,
        "governance": {"legal_interpretation":"signal_detection_only_not_legal_advice","binding_terms":"never_accepted_autonomously","refunds_returns_concessions":"never_promised_autonomously","evidence_rule":"only explicit traceable terms are treated as confirmed"},
    }
    case["recommended_structure"] = _structure(case)
    return case


def _existing_keys(state: Dict[str, Any]) -> set[str]:
    return {str(x.get("execution_key")) for x in state.get("outbox", []) if x.get("execution_key")}


def _prepare_clarification(state: Dict[str, Any], deal: Dict[str, Any], case: Dict[str, Any], budget: List[int]) -> int:
    if budget[0] <= 0 or case.get("mandatory_legal_review"):
        return 0
    gaps = set(case.get("critical_gaps") or [])
    targets = [x for x in ("returns_mismatch","cancellation_mismatch","warranty_mismatch","technical_compliance_not_confirmed") if x in gaps]
    if not targets:
        return 0
    supplier = _accounts(state).get(str(deal.get("supplier_account_id") or ""), {})
    contact = str(supplier.get("commercial_email") or "").strip().lower()
    if not contact or not supplier.get("verified_contact"):
        return 0
    key = f"deal_safeguards|supplier_terms|{deal.get('id')}|{'-'.join(targets)}"
    if key in _existing_keys(state):
        return 0
    asks = {"returns_mismatch":"política ante devolución/no conformidad y procedimiento RMA, si corresponde","cancellation_mismatch":"condiciones de cancelación o modificación una vez emitido el pedido","warranty_mismatch":"alcance, plazo y exclusiones de garantía","technical_compliance_not_confirmed":"confirmación expresa de cumplimiento con la especificación indicada"}
    body = "Para cerrar el análisis sin asumir condiciones no confirmadas, agradeceremos precisar:\n\n" + "\n".join(f"- {asks[x]}" for x in targets) + "\n\nLa consulta es exploratoria y no implica aceptación de términos, orden de compra ni compromiso financiero."
    state.setdefault("outbox", []).append({"id":f"MSG-{len(state.get('outbox', []))+1:04d}","deal_id":deal.get("id"),"kind":"terms_clarification","purpose":"deal_safeguards","counterparty":supplier.get("company_name") or supplier.get("name_hint") or deal.get("supplier"),"channel":"email","contact":contact,"contact_verified":True,"subject":f"Aclaración de condiciones — {deal.get('need') or 'operación B2B'}","body":body,"status":"ready","execution_key":key,"created_at":utcnow()})
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
        if not signals or str(msg.get("id")) in existing:
            continue
        severity = "critical" if "legal_threat" in signals else "high" if any(x in signals for x in ("refund_request","return_request","cancellation_request","defect_claim","damage_claim")) else "medium"
        incident = {"id":f"INC-{len(existing)+1:05d}","deal_id":deal_id,"source_message_id":str(msg.get("id")),"signals":signals,"severity":severity,"status":"evidence_review","liability_admission_allowed":False,"refund_or_return_commitment_allowed":False,"recommended_action":"preserve_evidence_and_compare_promised_vs_supplier_backing","created_at":utcnow()}
        existing[str(msg.get("id"))] = incident
        deals[deal_id]["commercial_incident_open"] = True
        deals[deal_id]["incident_hold"] = True
        record_decision(state, engine="Deal Safeguards / Dispute Prevention", object_type="deal", object_id=deal_id, decision="commercial_incident_opened", reason=f"Se detectaron señales de reclamo/incidente: {', '.join(signals)}. Se congelan concesiones/admisiones automáticas hasta revisar evidencia.", action="prepare_draft", confidence=0.9, evidence_refs=[str(msg.get("id"))], requires_approval=severity in {"high","critical"})
    state["commercial_incidents"] = list(existing.values())[-MAX_INCIDENTS:]
    return state["commercial_incidents"]


def deal_safeguards_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    docs_by_deal = _deal_documents(state)
    cases: List[Dict[str, Any]] = []
    budget = [MAX_OUTBOUND_PER_TICK]
    clarifications = 0
    for deal in state.get("deals", []) or []:
        if not deal.get("id") or deal.get("source") == "demo" or str(deal.get("stage") or "") in {"cerrado (simulación)","closed_simulated"}:
            continue
        case = _case_for(state, deal, docs_by_deal.get(str(deal.get("id")), []))
        cases.append(case)
        deal["deal_safeguards"] = {k: case.get(k) for k in ("safe_close_score","exposure_score","cleared","mandatory_legal_review","critical_gaps","recommended_structure","proposal_allowed","updated_at")}
        deal["deal_safeguards_cleared"] = bool(case["cleared"])
        deal["legal_review_required"] = bool(case["mandatory_legal_review"])
        deal["safe_close_score"] = case["safe_close_score"]
        clarifications += _prepare_clarification(state, deal, case, budget)

    incidents = _incidents(state)
    for deal in state.get("deals", []) or []:
        if deal.get("incident_hold"):
            deal["deal_safeguards_cleared"] = False
    preclose_refresh = preclose_tick(state)
    cases.sort(key=lambda x: (not x.get("cleared"), _f(x.get("exposure_score"))), reverse=True)
    cases = cases[:MAX_CASES]
    state["deal_safeguard_cases"] = cases
    state["deal_safeguard_index"] = {str(x.get("deal_id")): x for x in cases}
    open_incidents = [x for x in incidents if x.get("status") not in {"resolved","closed"}]
    primary = cases[0] if cases else None
    directive = {"deal_id":(primary or {}).get("deal_id"),"safe_close_score":(primary or {}).get("safe_close_score"),"exposure_score":(primary or {}).get("exposure_score"),"recommended_structure":(primary or {}).get("recommended_structure"),"critical_gaps":(primary or {}).get("critical_gaps", []),"mandatory_legal_review":bool((primary or {}).get("mandatory_legal_review"))} if primary else {}
    report = {"updated_at":utcnow(),"mode":"deal_safeguards_and_dispute_prevention","deals_reviewed":len(cases),"cleared":sum(1 for x in cases if x.get("cleared")),"blocked":sum(1 for x in cases if not x.get("cleared")),"mandatory_legal_review":sum(1 for x in cases if x.get("mandatory_legal_review")),"clarification_messages_created":clarifications,"open_incidents":len(open_incidents),"preclose_refresh":preclose_refresh,"primary_directive":directive,"governance":{"objective":"maximize safe risk-adjusted close probability, not raw closes","legal_boundary":"high-risk legal clauses are detected and escalated; no jurisdiction-specific legal conclusion","claims_boundary":"no autonomous admission of liability, refund, return acceptance, penalty acceptance or indemnity","back_to_back_rule":"do not promise buyer protections not backed by supplier terms or explicit company policy","binding_rule":"contracts, purchase orders, binding terms and payments remain human-gated"}}
    state["deal_safeguards_report"] = report
    if primary:
        record_decision(state, engine="Deal Safeguards / Dispute Prevention", object_type="deal", object_id=str(primary.get("deal_id") or ""), decision="safe_close_assessment", reason=f"Safe close {primary.get('safe_close_score')}%; exposure {primary.get('exposure_score')}%; gaps: {', '.join(primary.get('critical_gaps', [])[:6]) or 'none'}.", action="prepare_draft", confidence=0.94, evidence_refs=[], requires_approval=bool(primary.get("mandatory_legal_review")))
    return report
