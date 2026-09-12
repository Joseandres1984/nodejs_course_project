from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from autonomy_governor import record_decision

MAX_AUTO_RESPONSES_PER_TICK = 2
MAX_ESCALATIONS = 120


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().strip().split())


def _accounts(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(x.get("id")): x for x in state.get("candidate_accounts", []) or [] if x.get("id")}


def _outbox_index(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(x.get("id")): x for x in state.get("outbox", []) or [] if x.get("id")}


def _deal(state: Dict[str, Any], deal_id: Any) -> Dict[str, Any]:
    return next((x for x in state.get("deals", []) or [] if str(x.get("id")) == str(deal_id or "")), {})


def _latest_real_offer(state: Dict[str, Any], deal_id: Any) -> Dict[str, Any]:
    rows = [x for x in state.get("offers", []) or [] if str(x.get("deal_id") or "") == str(deal_id or "") and x.get("source") != "demo/simulación"]
    rows.sort(key=lambda x: str(x.get("created_at") or ""))
    return rows[-1] if rows else {}


def _source_message(state: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    index = _outbox_index(state)
    for key in ("revops_source_message_id", "related_message_id"):
        value = str(incoming.get(key) or "")
        if value and value in index:
            return index[value]
    sender = str(incoming.get("from") or "").strip().lower()
    rows = [x for x in state.get("outbox", []) or [] if str(x.get("contact") or "").strip().lower() == sender]
    rows.sort(key=lambda x: str(x.get("sent_at") or x.get("created_at") or ""))
    return rows[-1] if rows else {}


def _source_lane_id(state: Dict[str, Any], source: Dict[str, Any]) -> str:
    opportunity_id = str(source.get("opportunity_id") or "")
    if not opportunity_id and source.get("deal_id"):
        opportunity_id = str(_deal(state, source.get("deal_id")).get("opportunity_id") or "")
    return f"opportunity:{opportunity_id}" if opportunity_id else ""


def _intent(incoming: Dict[str, Any]) -> str:
    classified = str((incoming.get("classification") or {}).get("kind") or "").lower()
    text = _norm(f"{incoming.get('subject', '')} {incoming.get('body', '')}")
    if classified == "opt_out" or any(x in text for x in ("no contactar", "no me interesa", "unsubscribe", "quitarme")):
        return "opt_out"
    if any(x in text for x in ("reclamo", "devolución", "devolucion", "reembolso", "daño", "danio", "falló", "fallo", "incumplimiento", "penalidad")):
        return "incident"
    if any(x in text for x in ("contrato", "jurisdicción", "jurisdiccion", "indemn", "responsabilidad", "ley aplicable", "cláusula", "clausula")):
        return "legal"
    if classified == "price_objection" or any(x in text for x in ("muy caro", "precio alto", "descuento", "mejor precio", "fuera de presupuesto")):
        return "price"
    if classified == "delivery_question" or any(x in text for x in ("plazo de entrega", "fecha de entrega", "cuándo entreg", "cuando entreg", "lead time")):
        return "delivery"
    if any(x in text for x in ("garantía", "garantia")):
        return "warranty"
    if any(x in text for x in ("forma de pago", "condiciones de pago", "anticipo", "transferencia", "30 días", "30 dias", "45 días", "45 dias", "60 días", "60 dias")):
        return "payment_terms"
    if any(x in text for x in ("vigencia", "validez de la oferta", "hasta cuándo", "hasta cuando")):
        return "validity"
    if any(x in text for x in ("flete", "impuesto", "iva", "incluye iva", "entrega incluida", "costo de envío", "costo de envio")):
        return "freight_tax"
    if any(x in text for x in ("stock", "disponibilidad", "disponible", "hay unidades")):
        return "availability"
    if any(x in text for x in ("ficha técnica", "ficha tecnica", "datasheet", "certificado", "documentación técnica", "documentacion tecnica", "manual")):
        return "documentation"
    if any(x in text for x in ("modelo", "código", "codigo", "part number", "compatibilidad", "especificación", "especificacion", "norma", "material", "presión", "presion", "tensión", "tension", "potencia", "diámetro", "diametro")):
        return "technical"
    if any(x in text for x in ("factura", "facturación", "facturacion", "retención", "retencion", "percepción", "percepcion")):
        return "tax_invoice"
    if any(x in text for x in ("quiénes son", "quienes son", "qué es lumen", "que es lumen", "cómo trabajan", "como trabajan", "sitio web")):
        return "about_lumen"
    if any(x in text for x in ("tengo que consultar", "debemos consultar", "aprobación interna", "aprobacion interna", "gerencia", "mi jefe", "compras debe aprobar")):
        return "internal_approval"
    if any(x in text for x in ("otro proveedor", "ya tenemos proveedor", "otra oferta", "otra cotización", "otra cotizacion", "competidor")):
        return "competitor"
    if classified == "buyer_interest" or any(x in text for x in ("avancemos", "sigamos", "nos interesa", "me interesa")):
        return "interest"
    if "?" in str(incoming.get("body") or "") or any(x in text for x in ("podrían", "podrian", "pueden", "quisiera saber", "necesito saber")):
        return "general_question"
    return classified or "general"


def _field_evidence(offer: Dict[str, Any], deal: Dict[str, Any], intent: str) -> tuple[str | None, str | None]:
    mapping = {
        "delivery": ("lead_days", "plazo de entrega"),
        "warranty": ("warranty", "garantía"),
        "payment_terms": ("payment_terms", "condiciones de pago"),
        "validity": ("validity_days", "vigencia de oferta"),
        "availability": ("availability", "disponibilidad"),
        "technical": ("technical_compliance", "cumplimiento técnico"),
        "documentation": ("technical_documentation", "documentación técnica"),
    }
    if intent in mapping:
        key, label = mapping[intent]
        value = offer.get(key)
        if value not in (None, "", [], {}):
            if intent == "delivery":
                return f"El proveedor informa un plazo aproximado de {value} días.", label
            if intent == "validity":
                return f"La oferta informa una vigencia de {value} días.", label
            return f"La información actualmente documentada indica: {value}.", label
    if intent == "freight_tax":
        parts = []
        if offer.get("freight_terms") not in (None, "", [], {}):
            parts.append(f"flete/entrega: {offer.get('freight_terms')}")
        if offer.get("tax_terms") not in (None, "", [], {}):
            parts.append(f"impuestos: {offer.get('tax_terms')}")
        if parts:
            return "La oferta documenta " + "; ".join(parts) + ".", "flete/impuestos"
    if intent == "tax_invoice" and deal.get("invoice_tax_treatment_confirmed") and deal.get("invoice_tax_treatment"):
        return f"El tratamiento fiscal confirmado para esta operación es: {deal.get('invoice_tax_treatment')}.", "tratamiento fiscal"
    return None, None


def _buyer_answer_body(evidence: str) -> str:
    return f"Gracias por la consulta. {evidence} Lo compartimos únicamente sobre la base de la información comercial actualmente documentada y queda sujeto a confirmación final antes de cualquier compromiso."


def _about_lumen_body() -> str:
    return "LUMEN B2B trabaja en investigación comercial, sourcing y coordinación de oportunidades entre empresas compradoras y proveedores. Nuestro objetivo es ordenar requerimientos, comparar alternativas y facilitar la conversación comercial con información trazable. Las gestiones iniciales son no vinculantes y cualquier condición final queda sujeta a validación antes de asumir compromisos."


def _internal_approval_body() -> str:
    return "Perfecto. Si les resulta útil para la revisión interna, podemos ordenar en un resumen breve los puntos confirmados: alcance, alternativa propuesta, precio, plazo, garantía y condiciones comerciales, usando únicamente información documentada. Quedamos a disposición para facilitar esa evaluación sin generar presión ni asumir una decisión de su parte."


def _competitor_body() -> str:
    return "Entendido. Si están comparando alternativas, podemos mantener la evaluación sobre variables objetivas y verificables —precio total, cumplimiento técnico, plazo, garantía y condiciones comerciales— sin descalificar ni hacer afirmaciones sobre otros proveedores que no podamos acreditar."


def _clarification_question(intent: str) -> str:
    return {
        "delivery": "¿Podrían confirmar el plazo de entrega actualmente válido y desde qué hito comienza a computarse?",
        "warranty": "¿Podrían confirmar la garantía aplicable, alcance y plazo?",
        "payment_terms": "¿Podrían confirmar las condiciones y forma de pago actualmente ofrecidas?",
        "validity": "¿Podrían confirmar hasta cuándo se mantiene vigente la oferta?",
        "freight_tax": "¿Podrían confirmar qué incluye el precio respecto de flete, entrega e impuestos?",
        "availability": "¿Podrían confirmar disponibilidad/stock real y cualquier condición asociada?",
        "technical": "¿Podrían confirmar específicamente el cumplimiento técnico solicitado y señalar la documentación que lo respalda?",
        "documentation": "¿Podrían indicar qué ficha técnica, certificado, manual o documentación de respaldo pueden aportar?",
        "tax_invoice": "¿Podrían confirmar el tratamiento de facturación/impuestos aplicable a la oferta?",
        "general_question": "Recibimos una consulta del comprador que requiere precisión adicional. ¿Podrían ayudarnos a confirmar el punto pendiente sobre su propuesta?",
    }.get(intent, "¿Podrían ayudarnos a confirmar este punto de la propuesta para responder con precisión al comprador?")


def _supplier_for_deal(state: Dict[str, Any], deal: Dict[str, Any], offer: Dict[str, Any]) -> Dict[str, Any]:
    accounts = _accounts(state)
    account = accounts.get(str(deal.get("supplier_account_id") or ""), {})
    if account:
        return account
    name = _norm(offer.get("supplier") or deal.get("supplier"))
    for row in accounts.values():
        if row.get("type") != "supplier" or not row.get("verified_company"):
            continue
        names = {_norm(row.get("company_name")), _norm(row.get("name_hint")), _norm(row.get("site_title"))}
        if name and any(x and (x == name or x in name or name in x) for x in names):
            return row
    return {}


def _append_message(state: Dict[str, Any], *, key: str, kind: str, purpose: str, account: Dict[str, Any], source: Dict[str, Any], subject: str, body: str) -> bool:
    if any(str(x.get("execution_key") or "") == key for x in state.get("outbox", []) or []):
        return False
    lane_id = _source_lane_id(state, source)
    active_ids = {str(x) for x in state.get("closer_active_lane_ids", []) or []}
    if not lane_id or lane_id not in active_ids:
        return False
    contact = str(account.get("commercial_email") or "").strip().lower()
    if not contact or not account.get("verified_contact"):
        return False
    state.setdefault("outbox", []).append({
        "id": f"MSG-{len(state.get('outbox', []))+1:04d}",
        "deal_id": source.get("deal_id"),
        "revops_case_id": source.get("revops_case_id"),
        "interlocution_case_id": source.get("interlocution_case_id"),
        "opportunity_id": source.get("opportunity_id"),
        "counterparty_account_id": account.get("id"),
        "kind": kind,
        "purpose": purpose,
        "counterparty": account.get("company_name") or account.get("name_hint") or account.get("domain"),
        "channel": "email",
        "contact": contact,
        "contact_verified": True,
        "subject": subject[:180],
        "body": body[:5600],
        "status": "ready",
        "execution_key": key,
        "created_at": utcnow(),
        "nonbinding": True,
        "response_intelligence_generated": True,
        "closer_lane_id": lane_id,
        "closer_governed": True,
        "closer_allowed": True,
    })
    return True


def _escalate(state: Dict[str, Any], incoming: Dict[str, Any], source: Dict[str, Any], intent: str, reason: str, severity: str = "medium") -> None:
    rows = state.setdefault("response_escalations", [])
    key = f"{incoming.get('id')}|{intent}"
    if any(str(x.get("key") or "") == key for x in rows):
        return
    rows.append({"key": key, "inbox_id": incoming.get("id"), "deal_id": source.get("deal_id"), "opportunity_id": source.get("opportunity_id"), "intent": intent, "severity": severity, "reason": reason, "status": "open", "created_at": utcnow()})
    state["response_escalations"] = rows[-MAX_ESCALATIONS:]


def _resolve_escalation(state: Dict[str, Any], incoming: Dict[str, Any], intent: str) -> None:
    key = f"{incoming.get('id')}|{intent}"
    for row in state.get("response_escalations", []) or []:
        if str(row.get("key") or "") == key and row.get("status") == "open":
            row["status"] = "resolved"
            row["resolved_at"] = utcnow()


def response_intelligence_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    stats = {"reviewed": 0, "answered": 0, "supplier_clarifications": 0, "escalated": 0, "ignored": 0, "deferred_by_closer": 0, "waiting_evidence": 0}
    remaining = MAX_AUTO_RESPONSES_PER_TICK
    accounts = _accounts(state)
    active_ids = {str(x) for x in state.get("closer_active_lane_ids", []) or []}

    for incoming in state.get("inbox", []) or []:
        if incoming.get("response_intelligence_processed"):
            continue
        source = _source_message(state, incoming)
        if not source:
            incoming["response_intelligence_processed"] = True
            incoming["response_intelligence_note"] = "no_traceable_outbound_source"
            stats["ignored"] += 1
            continue
        lane_id = _source_lane_id(state, source)
        if not lane_id or lane_id not in active_ids:
            incoming["response_intelligence_note"] = "deferred_by_closer_lane_gate"
            stats["deferred_by_closer"] += 1
            continue

        stats["reviewed"] += 1
        intent = _intent(incoming)
        incoming["response_intent"] = intent
        deal = _deal(state, source.get("deal_id"))
        offer = _latest_real_offer(state, source.get("deal_id"))
        sender_account = accounts.get(str(source.get("counterparty_account_id") or ""), {})
        sender_role = str(sender_account.get("type") or "")

        if intent == "opt_out":
            incoming["response_intelligence_processed"] = True
            incoming["response_intelligence_note"] = "opt_out_respected"
            continue
        if intent in {"legal", "incident"}:
            if deal:
                if intent == "legal": deal["legal_review_required"] = True
                if intent == "incident": deal["incident_hold"] = True
            _escalate(state, incoming, source, intent, "La consulta puede crear exposición legal, contractual, de devolución/reclamo o responsabilidad; no se responde de forma autónoma.", "high")
            incoming["response_intelligence_processed"] = True
            stats["escalated"] += 1
            continue
        if intent == "price":
            incoming["response_intelligence_processed"] = True
            incoming["response_intelligence_note"] = "delegated_to_revops_price_negotiation"
            continue
        if sender_role != "buyer":
            incoming["response_intelligence_processed"] = True
            incoming["response_intelligence_note"] = "supplier_or_nonbuyer_reply_left_to_quote_revops"
            continue
        if remaining <= 0:
            incoming["response_intelligence_note"] = "deferred_response_budget"
            continue

        static_body = None
        static_subject = None
        static_purpose = None
        if intent == "about_lumen":
            static_body, static_subject, static_purpose = _about_lumen_body(), "Sobre LUMEN B2B", "answer_about_lumen"
        elif intent == "internal_approval":
            static_body, static_subject, static_purpose = _internal_approval_body(), "Información para revisión interna", "support_internal_approval"
        elif intent == "competitor":
            static_body, static_subject, static_purpose = _competitor_body(), "Comparación de alternativas", "objective_competitor_comparison"
        elif intent == "interest":
            incoming["response_intelligence_processed"] = True
            incoming["response_intelligence_note"] = "interest_advances_case_without_redundant_acknowledgement"
            continue
        if static_body:
            if _append_message(state, key=f"response|{incoming.get('id')}|{intent}", kind="buyer_information_response", purpose=str(static_purpose), account=sender_account, source=source, subject=str(static_subject), body=str(static_body)):
                remaining -= 1; stats["answered"] += 1; incoming["response_intelligence_processed"] = True; _resolve_escalation(state, incoming, intent)
            continue

        evidence, label = _field_evidence(offer, deal, intent)
        if evidence:
            duplicate_delivery = intent == "delivery" and any(x.get("purpose") == "answer_verified_delivery_question" and str(x.get("revops_case_id") or "") == str(source.get("revops_case_id") or "") for x in state.get("outbox", []) or [])
            if duplicate_delivery:
                incoming["response_intelligence_processed"] = True
                _resolve_escalation(state, incoming, intent)
                continue
            if _append_message(state, key=f"response|{incoming.get('id')}|{intent}", kind="buyer_information_response", purpose=f"answer_verified_{intent}", account=sender_account, source=source, subject=f"Respuesta sobre {label or 'la consulta'}", body=_buyer_answer_body(evidence)):
                remaining -= 1; stats["answered"] += 1; incoming["response_intelligence_processed"] = True; _resolve_escalation(state, incoming, intent)
            continue

        supplier = _supplier_for_deal(state, deal, offer)
        supported = {"delivery", "warranty", "payment_terms", "validity", "freight_tax", "availability", "technical", "documentation", "tax_invoice", "general_question"}
        if supplier and supplier.get("verified_contact") and intent in supported:
            key = f"evidence_clarification|{incoming.get('id')}|{intent}"
            existing = any(str(x.get("execution_key") or "") == key for x in state.get("outbox", []) or [])
            body = "Para responder con precisión una consulta del comprador necesitamos validar un punto de su propuesta.\n\n" + _clarification_question(intent) + "\n\nPreferimos confirmar el dato con ustedes antes que asumir una condición no documentada. La consulta es no vinculante."
            created = _append_message(state, key=key, kind="terms_clarification", purpose=f"buyer_question_evidence_clarification:{intent}", account=supplier, source=source, subject="Confirmación de información para el comprador", body=body)
            if created:
                remaining -= 1; stats["supplier_clarifications"] += 1
                _escalate(state, incoming, source, intent, "Respuesta al comprador en espera de evidencia del proveedor.", "low")
            if created or existing:
                incoming["response_waiting_supplier"] = True
                incoming["response_intelligence_note"] = "waiting_for_supplier_evidence"
                stats["waiting_evidence"] += 1
                continue
            incoming["response_intelligence_processed"] = True
            _escalate(state, incoming, source, intent, "No existe canal de proveedor verificado para confirmar el dato solicitado.", "medium")
            stats["escalated"] += 1
            continue

        incoming["response_intelligence_processed"] = True
        _escalate(state, incoming, source, intent, "No existe evidencia suficiente para responder automáticamente sin riesgo de inventar datos.", "medium")
        stats["escalated"] += 1

    open_escalations = [x for x in state.get("response_escalations", []) or [] if x.get("status") == "open"]
    report = {
        "updated_at": utcnow(), "mode": "evidence_first_response_intelligence", "stats": stats,
        "open_escalations": len(open_escalations),
        "principle": "Responder automáticamente cuando existe evidencia trazable; pedir confirmación al proveedor cuando falta un dato; escalar legal/reclamos/ambigüedad en vez de improvisar; toda respuesta respeta el carril activo del Closer.",
        "supported_intents": ["delivery", "warranty", "payment_terms", "validity", "freight_tax", "availability", "technical", "documentation", "tax_invoice", "about_lumen", "internal_approval", "competitor", "interest", "price", "legal", "incident", "general_question"],
    }
    state["response_intelligence"] = report
    if stats["answered"] or stats["supplier_clarifications"] or stats["escalated"]:
        record_decision(state, engine="Response Intelligence", object_type="system", object_id="conversation_response", decision="evidence_first_conversation_routing", reason=f"Respondidas {stats['answered']}; aclaraciones a proveedor {stats['supplier_clarifications']}; escaladas {stats['escalated']}.", action="respond_or_escalate_without_hallucination", confidence=0.96, evidence_refs=[])
    return report
