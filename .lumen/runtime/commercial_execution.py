from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from autonomy_governor import record_decision

MAX_NEW_MESSAGES_PER_TICK = 3
MAX_CASES = 80
MAX_CASE_HISTORY = 40
MAX_RFQ_SUPPLIERS = 4


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().strip().split())


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _ensure(state: Dict[str, Any]) -> Dict[str, Any]:
    memory = state.setdefault("commercial_execution_memory", {})
    memory.setdefault("cycles", 0)
    memory.setdefault("cases", [])
    memory.setdefault("history", [])
    state.setdefault("outbox", [])
    state.setdefault("inbox", [])
    return memory


def _accounts(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(x.get("id")): x for x in state.get("candidate_accounts", []) if x.get("id")}


def _opportunities(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    rows = list(state.get("market_opportunities", [])) + list(state.get("opportunities", []))
    return {str(x.get("id")): x for x in rows if x.get("id")}


def _deals(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(x.get("id")): x for x in state.get("deals", []) if x.get("id")}


def _deal_for_opportunity(state: Dict[str, Any], opportunity_id: Any) -> Dict[str, Any]:
    target = str(opportunity_id or "")
    return next((x for x in state.get("deals", []) if str(x.get("opportunity_id") or "") == target), {})


def _account_contact(account: Dict[str, Any]) -> Tuple[str | None, bool, str | None]:
    email = str(account.get("commercial_email") or "").strip().lower()
    if email and account.get("verified_contact"):
        return email, True, "email"
    if account.get("commercial_form_url") and account.get("commercial_channel_verified"):
        return str(account.get("commercial_form_url")), True, "web_form"
    return None, False, None


def _counterparty_name(account: Dict[str, Any]) -> str:
    return str(account.get("company_name") or account.get("name_hint") or account.get("site_title") or account.get("domain") or "Contraparte")


def _existing_execution_keys(state: Dict[str, Any]) -> set[str]:
    return {str(x.get("execution_key")) for x in state.get("outbox", []) if x.get("execution_key")}


def _case_history(case: Dict[str, Any], event: str, detail: str, **extra: Any) -> None:
    history = case.setdefault("history", [])
    history.append({"ts": utcnow(), "event": event, "detail": detail[:500], **extra})
    if len(history) > MAX_CASE_HISTORY:
        del history[:-MAX_CASE_HISTORY]


def _message(
    state: Dict[str, Any], *, execution_key: str, kind: str, counterparty: str,
    contact: str, contact_verified: bool, subject: str, body: str,
    deal_id: str | None = None, revops_case_id: str | None = None,
    interlocution_case_id: str | None = None, opportunity_id: str | None = None,
    purpose: str | None = None,
) -> bool:
    if not contact or "@" not in contact or not contact_verified:
        return False
    if execution_key in _existing_execution_keys(state):
        return False
    state.setdefault("outbox", []).append({
        "id": f"MSG-{len(state['outbox'])+1:04d}",
        "deal_id": deal_id,
        "revops_case_id": revops_case_id,
        "interlocution_case_id": interlocution_case_id,
        "opportunity_id": opportunity_id,
        "kind": kind,
        "purpose": purpose,
        "counterparty": counterparty,
        "channel": "email",
        "contact": contact,
        "contact_verified": True,
        "subject": subject[:180],
        "body": body[:5600],
        "status": "ready",
        "execution_key": execution_key,
        "created_at": utcnow(),
    })
    return True


def _buyer_requirement_body(case: Dict[str, Any]) -> str:
    questions = list(case.get("buyer_questions") or [])
    intro = (
        "Para preparar una alternativa concreta y evitar hacerles perder tiempo con una propuesta incompleta, "
        "nos gustaría confirmar algunos puntos del requerimiento."
    )
    lines = [intro, ""]
    for question in questions[:5]:
        lines.append(f"- {question}")
    lines.extend([
        "",
        "Con esa información podemos comparar proveedores y condiciones sobre una base homogénea, sin asumir datos que ustedes no hayan confirmado.",
    ])
    return "\n".join(lines)


def _requirement_summary(requirement: Dict[str, Any]) -> str:
    mapping = [
        ("technical_scope", "Alcance técnico"),
        ("quantity", "Cantidad"),
        ("unit", "Unidad"),
        ("delivery_target", "Entrega objetivo"),
        ("delivery_location", "Lugar de entrega"),
        ("commercial_terms", "Condiciones comerciales"),
        ("required_documentation", "Documentación requerida"),
        ("warranty_requirement", "Garantía"),
    ]
    lines: List[str] = []
    for key, label in mapping:
        value = requirement.get(key)
        if value not in (None, "", [], {}):
            lines.append(f"- {label}: {value}")
    return "\n".join(lines)


def _supplier_rfq_body(requirement: Dict[str, Any]) -> str:
    summary = _requirement_summary(requirement)
    return (
        "Estamos evaluando un requerimiento B2B confirmado y nos gustaría contar con una cotización comparable.\n\n"
        f"Requerimiento:\n{summary}\n\n"
        "Agradeceremos indicar, cuando corresponda: precio total y moneda, validez, plazo de entrega, forma de pago, "
        "garantía, origen, flete/impuestos, documentación técnica y cualquier condición o exclusión relevante. "
        "Si se trata de suministro internacional, por favor incluir Incoterm y lugar convenido.\n\n"
        "La solicitud es exploratoria/no vinculante y cualquier decisión comercial posterior queda sujeta a revisión final."
    )


def _quote_clarification_body(offer: Dict[str, Any]) -> str:
    labels = {
        "amount": "precio/importe total",
        "currency": "moneda",
        "lead_days": "plazo de entrega",
        "payment_terms": "condiciones de pago",
        "validity_days": "vigencia de la oferta",
        "warranty": "garantía",
        "freight_terms": "condiciones de flete/entrega",
        "tax_terms": "tratamiento de impuestos",
        "technical_compliance": "confirmación de cumplimiento técnico",
    }
    missing = [labels.get(x, x) for x in list(offer.get("missing_commercial_fields") or [])]
    bullets = "\n".join(f"- {x}" for x in missing[:8])
    return (
        "Muchas gracias por la propuesta. Para poder compararla de manera homogénea con otras alternativas y evitar interpretar condiciones que no estén confirmadas, "
        "¿podrían ayudarnos a completar los siguientes puntos?\n\n"
        f"{bullets}\n\n"
        "No hace falta reformular toda la cotización; con confirmar esos datos es suficiente."
    )


def _supplier_negotiation_body(deal: Dict[str, Any], offer: Dict[str, Any] | None = None) -> str:
    current = ""
    if offer and offer.get("amount") and offer.get("currency"):
        current = f" La referencia actualmente recibida es {offer.get('currency')} {offer.get('amount')}."
    return (
        "Estamos revisando la viabilidad económica de esta oportunidad y queremos preservar una alternativa competitiva sin deteriorar especificación ni condiciones de cumplimiento."
        f"{current} ¿Existe posibilidad de revisar precio total, plazo, forma de pago o alguna condición comercial que permita mejorar la propuesta? "
        "Nos sirve conocer su mejor condición real; no estamos solicitando aceptar ningún compromiso vinculante en esta instancia."
    )


def _buyer_delivery_body(lead_days: Any) -> str:
    return (
        f"El plazo actualmente informado por el proveedor es de aproximadamente {lead_days} días. "
        "Lo compartimos como referencia comercial vigente a hoy y sujeto a confirmación final de disponibilidad, condiciones y fecha de orden. "
        "Si tienen una fecha objetivo distinta, podemos usarla para volver a validar alternativas."
    )


def _find_account_by_email(state: Dict[str, Any], email: str) -> Dict[str, Any]:
    target = str(email or "").strip().lower()
    return next((
        x for x in state.get("candidate_accounts", [])
        if str(x.get("commercial_email") or "").strip().lower() == target and x.get("verified_contact")
    ), {})


def _latest_outbound_to(state: Dict[str, Any], email: str) -> Dict[str, Any]:
    target = str(email or "").strip().lower()
    rows = [x for x in state.get("outbox", []) if str(x.get("contact") or "").strip().lower() == target]
    return rows[-1] if rows else {}


def _extract_requirement_evidence(body: str) -> Dict[str, Any]:
    text = " ".join(str(body or "").split())
    low = text.lower()
    found: Dict[str, Any] = {}

    quantity = re.search(r"\b(\d+(?:[\.,]\d+)?)\s*(unidades?|uds?\.?|u\.?|piezas?|metros?|m\b|kg\b|kilos?|litros?|l\b)\b", low, re.I)
    if quantity:
        raw = quantity.group(1).replace(",", ".")
        try:
            number = float(raw)
            found["quantity"] = int(number) if number.is_integer() else number
            found["unit"] = quantity.group(2)
        except ValueError:
            pass

    date = re.search(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b", text)
    relative = re.search(r"\b(?:en|dentro de)\s+(\d+)\s+(d[ií]as?|semanas?)\b", low)
    if date:
        found["delivery_target"] = date.group(1)
    elif relative:
        found["delivery_target"] = f"{relative.group(1)} {relative.group(2)}"

    location = re.search(r"(?:entrega(?:r)?\s+en|destino\s*:?|ubicaci[oó]n\s*:?|sitio\s*:?)[\s-]+([^.;\n]{3,90})", text, re.I)
    if location:
        found["delivery_location"] = location.group(1).strip()

    if any(token in low for token in ("pago", "transferencia", "30 días", "30 dias", "45 días", "45 dias", "60 días", "60 dias", "anticipo")):
        snippets = re.findall(r"[^.;]*(?:pago|transferencia|30 d[ií]as|45 d[ií]as|60 d[ií]as|anticipo)[^.;]*", text, re.I)
        if snippets:
            found["commercial_terms"] = snippets[0].strip()[:300]

    technical = re.search(r"[^.;]*(?:modelo|c[oó]digo|part number|p/n|norma|especificaci[oó]n|presi[oó]n|tensi[oó]n|potencia|di[aá]metro|material)[^.;]*", text, re.I)
    if technical:
        found["technical_scope"] = technical.group(0).strip()[:700]

    currency = re.search(r"\b(USD|U\$S|US\$|ARS|EUR|BRL)\b", text, re.I)
    if currency:
        found["currency"] = currency.group(1).upper()
    return found


def _apply_buyer_reply_to_requirement(state: Dict[str, Any], incoming: Dict[str, Any], source: Dict[str, Any]) -> Dict[str, Any]:
    case_id = str(source.get("interlocution_case_id") or "")
    if not case_id:
        return {"applied": False}
    case = next((x for x in state.get("interlocution_cases", []) if str(x.get("id")) == case_id), None)
    if not case:
        return {"applied": False}
    requirement = case.setdefault("requirement", {})
    evidence = _extract_requirement_evidence(str(incoming.get("body") or ""))
    changed: List[str] = []
    for key, value in evidence.items():
        if requirement.get(key) in (None, "", [], {}):
            requirement[key] = value
            changed.append(key)
    if changed:
        requirement["source"] = "buyer_email_evidence"
        requirement["last_buyer_evidence_at"] = incoming.get("received_at") or utcnow()
        requirement.setdefault("evidence_message_ids", []).append(incoming.get("id"))
    # Explicit email evidence can fill fields, but full confirmation is only asserted when every required field exists.
    required = ["technical_scope", "quantity", "delivery_target", "delivery_location", "commercial_terms"]
    if all(requirement.get(x) not in (None, "", [], {}) for x in required):
        requirement["confirmed_by_buyer"] = True
        requirement["confirmed_at"] = incoming.get("received_at") or utcnow()
    _case_history(case, "buyer_reply_evidence", f"Buyer reply aportó campos: {', '.join(changed) or 'sin campos estructurados suficientes'}", inbox_id=incoming.get("id"))
    return {"applied": bool(changed), "changed": changed, "case_id": case_id}


def _process_new_inbound(state: Dict[str, Any]) -> Dict[str, int]:
    stats = {"reviewed": 0, "requirement_updates": 0, "commercial_signals": 0}
    for incoming in state.get("inbox", []):
        if incoming.get("revops_processed"):
            continue
        sender = str(incoming.get("from") or "").lower()
        source = _latest_outbound_to(state, sender)
        if not source or not source.get("revops_case_id"):
            incoming["revops_processed"] = True
            incoming["revops_note"] = "no_revops_conversation_link"
            continue
        stats["reviewed"] += 1
        kind = str((incoming.get("classification") or {}).get("kind") or "general")
        incoming["revops_case_id"] = source.get("revops_case_id")
        if source.get("kind") in {"buyer_requirement_request", "buyer_intro"}:
            result = _apply_buyer_reply_to_requirement(state, incoming, source)
            if result.get("applied"):
                stats["requirement_updates"] += 1
        if kind in {"commercial_offer", "buyer_interest", "price_objection", "delivery_question"}:
            stats["commercial_signals"] += 1
        incoming["revops_processed"] = True
        incoming["revops_source_message_id"] = source.get("id")
    return stats


def _supplier_accounts_for_case(state: Dict[str, Any], interlocution: Dict[str, Any]) -> List[Dict[str, Any]]:
    account_map = _accounts(state)
    ids: List[str] = []
    primary = str(interlocution.get("supplier_account_id") or "")
    if primary:
        ids.append(primary)
    opportunity_id = str(interlocution.get("opportunity_id") or "")
    for deep in state.get("deep_dive_cases", []):
        if str(deep.get("opportunity_id") or "") != opportunity_id:
            continue
        for row in deep.get("supplier_alternatives", []) or []:
            supplier_id = str(row.get("id") or "")
            if supplier_id and supplier_id not in ids:
                ids.append(supplier_id)
    suppliers = [account_map[x] for x in ids if x in account_map]
    suppliers = [x for x in suppliers if x.get("verified_company")]
    suppliers.sort(key=lambda x: (bool(x.get("verified_contact")), _f(x.get("verification_score")), _f(x.get("lead_score"))), reverse=True)
    return suppliers[:MAX_RFQ_SUPPLIERS]


def _ensure_revops_cases(state: Dict[str, Any], memory: Dict[str, Any]) -> List[Dict[str, Any]]:
    existing = {str(x.get("interlocution_case_id")): x for x in memory.get("cases", []) if x.get("interlocution_case_id")}
    accounts = _accounts(state)
    opportunities = _opportunities(state)
    for interlocution in state.get("interlocution_cases", []):
        case_id = str(interlocution.get("id") or "")
        if not case_id:
            continue
        revops = existing.get(case_id)
        if revops is None:
            opportunity = opportunities.get(str(interlocution.get("opportunity_id") or ""), {})
            buyer = accounts.get(str(interlocution.get("buyer_account_id") or ""), {})
            revops = {
                "id": f"REVOPS-{len(memory['cases'])+1:05d}",
                "interlocution_case_id": case_id,
                "opportunity_id": interlocution.get("opportunity_id"),
                "deal_id": (_deal_for_opportunity(state, interlocution.get("opportunity_id")) or {}).get("id"),
                "buyer_account_id": interlocution.get("buyer_account_id"),
                "supplier_account_id": interlocution.get("supplier_account_id"),
                "category": interlocution.get("category") or opportunity.get("category"),
                "status": "requirement_discovery",
                "turns": 0,
                "created_at": utcnow(),
                "updated_at": utcnow(),
                "history": [],
                "buyer": _counterparty_name(buyer) if buyer else opportunity.get("buyer_name"),
            }
            memory["cases"].append(revops)
            existing[case_id] = revops
            _case_history(revops, "case_opened", "RevOps tomó control del caso comercial.")
        revops["deal_id"] = revops.get("deal_id") or (_deal_for_opportunity(state, interlocution.get("opportunity_id")) or {}).get("id")
        revops["updated_at"] = utcnow()
    if len(memory["cases"]) > MAX_CASES:
        memory["cases"] = memory["cases"][-MAX_CASES:]
    return memory["cases"]


def _latest_real_offer_for_deal(state: Dict[str, Any], deal_id: Any) -> Dict[str, Any] | None:
    rows = [x for x in state.get("offers", []) if str(x.get("deal_id") or "") == str(deal_id or "") and x.get("source") != "demo/simulación"]
    return rows[-1] if rows else None


def _buyer_account_for_case(state: Dict[str, Any], interlocution: Dict[str, Any]) -> Dict[str, Any]:
    return _accounts(state).get(str(interlocution.get("buyer_account_id") or ""), {})


def _supplier_account_by_name(state: Dict[str, Any], supplier: Any) -> Dict[str, Any]:
    target = _norm(supplier)
    for account in state.get("candidate_accounts", []):
        if account.get("type") != "supplier" or not account.get("verified_company"):
            continue
        names = {_norm(account.get("company_name")), _norm(account.get("name_hint")), _norm(account.get("site_title"))}
        if target and any(name and (name == target or target in name or name in target) for name in names):
            return account
    return {}


def _last_inbound_for_case(state: Dict[str, Any], revops_id: str) -> Dict[str, Any] | None:
    rows = [x for x in state.get("inbox", []) if str(x.get("revops_case_id") or "") == str(revops_id)]
    return rows[-1] if rows else None


def _drive_case(state: Dict[str, Any], revops: Dict[str, Any], message_budget: List[int]) -> Dict[str, Any]:
    interlocution = next((x for x in state.get("interlocution_cases", []) if str(x.get("id")) == str(revops.get("interlocution_case_id"))), {})
    if not interlocution:
        revops["status"] = "orphaned"
        revops["next_action"] = "repair_case_link"
        return {"action": "orphaned", "created": 0}

    opportunity_id = str(interlocution.get("opportunity_id") or "")
    deal = _deal_for_opportunity(state, opportunity_id)
    deal_id = str(deal.get("id") or revops.get("deal_id") or "") or None
    revops["deal_id"] = deal_id
    requirement = interlocution.setdefault("requirement", {})
    buyer = _buyer_account_for_case(state, interlocution)
    created = 0

    # Phase 1: requirement discovery with the buyer.
    if not interlocution.get("supplier_rfq_ready"):
        revops["status"] = "requirement_discovery"
        revops["next_action"] = "obtain_buyer_requirement"
        contact, verified, channel = _account_contact(buyer)
        if channel == "email" and message_budget[0] > 0:
            key = f"buyer_requirement|{revops['id']}|v1"
            if _message(
                state,
                execution_key=key,
                kind="buyer_requirement_request",
                counterparty=_counterparty_name(buyer),
                contact=str(contact),
                contact_verified=verified,
                subject=f"Consulta para precisar requerimiento de {interlocution.get('category') or 'suministro'}",
                body=_buyer_requirement_body(interlocution),
                deal_id=deal_id,
                revops_case_id=revops["id"],
                interlocution_case_id=interlocution.get("id"),
                opportunity_id=opportunity_id,
                purpose="requirement_discovery",
            ):
                message_budget[0] -= 1; created += 1
                _case_history(revops, "buyer_requirement_requested", "Se preparó solicitud estructurada de requerimiento al comprador.")
        elif channel == "web_form":
            revops["next_action"] = "buyer_web_form_requires_supported_execution_channel"
        return {"action": revops["next_action"], "created": created}

    # Phase 2: RFQ to multiple verified suppliers.
    suppliers = _supplier_accounts_for_case(state, interlocution)
    offers_for_deal = [x for x in state.get("offers", []) if deal_id and str(x.get("deal_id") or "") == deal_id and x.get("source") != "demo/simulación"]
    supplier_names_with_offer = {_norm(x.get("supplier")) for x in offers_for_deal}
    rfq_targets = []
    for supplier in suppliers:
        name = _counterparty_name(supplier)
        if _norm(name) not in supplier_names_with_offer:
            rfq_targets.append(supplier)

    if rfq_targets:
        revops["status"] = "rfq_execution"
        revops["next_action"] = "obtain_comparable_supplier_quotes"
        for supplier in rfq_targets:
            if message_budget[0] <= 0:
                break
            contact, verified, channel = _account_contact(supplier)
            if channel != "email":
                continue
            key = f"supplier_rfq|{revops['id']}|{supplier.get('id')}|v1"
            if _message(
                state,
                execution_key=key,
                kind="supplier_rfq",
                counterparty=_counterparty_name(supplier),
                contact=str(contact),
                contact_verified=verified,
                subject=f"Solicitud de cotización — {interlocution.get('category') or 'requerimiento B2B'}",
                body=_supplier_rfq_body(requirement),
                deal_id=deal_id,
                revops_case_id=revops["id"],
                interlocution_case_id=interlocution.get("id"),
                opportunity_id=opportunity_id,
                purpose="supplier_quote_collection",
            ):
                message_budget[0] -= 1; created += 1
                _case_history(revops, "supplier_rfq_prepared", f"RFQ preparada para {_counterparty_name(supplier)}.", supplier_account_id=supplier.get("id"))
        return {"action": revops["next_action"], "created": created}

    # Phase 3: clarify incomplete quotes before comparison.
    incomplete = [x for x in offers_for_deal if x.get("normalization_status") == "clarification_required"]
    for offer in incomplete:
        if message_budget[0] <= 0:
            break
        supplier = _supplier_account_by_name(state, offer.get("supplier"))
        contact, verified, channel = _account_contact(supplier)
        if channel != "email":
            continue
        missing_signature = "-".join(sorted(str(x) for x in (offer.get("missing_commercial_fields") or [])))[:160]
        key = f"quote_clarification|{revops['id']}|{offer.get('id')}|{missing_signature}"
        if _message(
            state,
            execution_key=key,
            kind="quote_clarification",
            counterparty=_counterparty_name(supplier),
            contact=str(contact),
            contact_verified=verified,
            subject="Aclaración de condiciones de cotización",
            body=_quote_clarification_body(offer),
            deal_id=deal_id,
            revops_case_id=revops["id"],
            interlocution_case_id=interlocution.get("id"),
            opportunity_id=opportunity_id,
            purpose="quote_normalization",
        ):
            message_budget[0] -= 1; created += 1
            _case_history(revops, "quote_clarification_prepared", f"Se solicitaron campos faltantes de {offer.get('id')}.")
    if incomplete:
        revops["status"] = "quote_clarification"
        revops["next_action"] = "complete_quote_terms"
        return {"action": revops["next_action"], "created": created}

    # Phase 4: respond to buyer objections by improving supplier economics first.
    inbound = _last_inbound_for_case(state, revops["id"])
    inbound_kind = str((inbound.get("classification") or {}).get("kind") or "") if inbound else ""
    if inbound_kind == "price_objection" and deal:
        offer = _latest_real_offer_for_deal(state, deal_id)
        supplier = _supplier_account_by_name(state, deal.get("supplier") or (offer or {}).get("supplier"))
        contact, verified, channel = _account_contact(supplier)
        key = f"supplier_negotiation|{revops['id']}|{inbound.get('id')}"
        if channel == "email" and message_budget[0] > 0 and _message(
            state,
            execution_key=key,
            kind="supplier_negotiation",
            counterparty=_counterparty_name(supplier),
            contact=str(contact),
            contact_verified=verified,
            subject="Revisión de condiciones comerciales",
            body=_supplier_negotiation_body(deal, offer),
            deal_id=deal_id,
            revops_case_id=revops["id"],
            interlocution_case_id=interlocution.get("id"),
            opportunity_id=opportunity_id,
            purpose="nonbinding_supplier_negotiation",
        ):
            message_budget[0] -= 1; created += 1
            _case_history(revops, "supplier_negotiation_prepared", "Objeción de precio del comprador derivó en revisión no vinculante de costo proveedor.")
        revops["status"] = "nonbinding_negotiation"
        revops["next_action"] = "improve_supplier_economics_before_discounting_buyer"
        return {"action": revops["next_action"], "created": created}

    # Phase 5: answer factual delivery questions when a traceable offer contains lead time.
    if inbound_kind == "delivery_question" and deal:
        offer = _latest_real_offer_for_deal(state, deal_id)
        if offer and offer.get("lead_days") is not None and inbound:
            buyer_account = _find_account_by_email(state, str(inbound.get("from") or ""))
            contact, verified, channel = _account_contact(buyer_account)
            key = f"buyer_delivery_response|{revops['id']}|{inbound.get('id')}"
            if channel == "email" and message_budget[0] > 0 and _message(
                state,
                execution_key=key,
                kind="buyer_information_response",
                counterparty=_counterparty_name(buyer_account),
                contact=str(contact),
                contact_verified=verified,
                subject="Referencia de plazo de entrega",
                body=_buyer_delivery_body(offer.get("lead_days")),
                deal_id=deal_id,
                revops_case_id=revops["id"],
                interlocution_case_id=interlocution.get("id"),
                opportunity_id=opportunity_id,
                purpose="answer_verified_delivery_question",
            ):
                message_budget[0] -= 1; created += 1
                _case_history(revops, "buyer_delivery_response_prepared", "Se respondió usando plazo informado en oferta trazable, sujeto a confirmación final.")
                revops["status"] = "buyer_question_answered"
                revops["next_action"] = "await_buyer_response"
                return {"action": revops["next_action"], "created": created}

    comparable = [x for x in offers_for_deal if x.get("comparable")]
    if len(comparable) >= 2:
        revops["status"] = "commercial_comparison_ready"
        revops["next_action"] = "optimize_and_prepare_buyer_proposal"
    elif len(comparable) == 1:
        revops["status"] = "single_quote_ready"
        revops["next_action"] = "obtain_second_comparable_quote_or_justify_single_source"
    else:
        revops["status"] = "awaiting_supplier_response"
        revops["next_action"] = "wait_or_follow_up_under_relationship_policy"
    return {"action": revops["next_action"], "created": created}


def commercial_execution_tick(state: Dict[str, Any]) -> Dict[str, Any]:
    memory = _ensure(state)
    memory["cycles"] = int(memory.get("cycles") or 0) + 1
    inbound_stats = _process_new_inbound(state)
    cases = _ensure_revops_cases(state, memory)
    message_budget = [MAX_NEW_MESSAGES_PER_TICK]
    driven = 0
    created = 0
    status_counts: Dict[str, int] = {}

    for revops in cases:
        if revops.get("status") in {"closed", "lost", "do_not_contact"}:
            continue
        result = _drive_case(state, revops, message_budget)
        driven += 1
        created += int(result.get("created") or 0)
        revops["turns"] = int(revops.get("turns") or 0) + 1
        revops["updated_at"] = utcnow()
        status = str(revops.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    active = [x for x in cases if x.get("status") not in {"closed", "lost", "do_not_contact"}]
    primary = None
    priority_order = {
        "nonbinding_negotiation": 100,
        "quote_clarification": 95,
        "commercial_comparison_ready": 92,
        "rfq_execution": 88,
        "requirement_discovery": 85,
        "single_quote_ready": 82,
        "awaiting_supplier_response": 65,
        "buyer_question_answered": 60,
    }
    if active:
        primary = sorted(active, key=lambda x: priority_order.get(str(x.get("status")), 50), reverse=True)[0]

    directive = {
        "updated_at": utcnow(),
        "primary_case_id": primary.get("id") if primary else None,
        "primary_status": primary.get("status") if primary else None,
        "primary_next_action": primary.get("next_action") if primary else None,
        "active_cases": len(active),
        "messages_created_this_cycle": created,
        "message_budget_remaining": message_budget[0],
    }
    state["commercial_execution_directive"] = directive

    report = {
        "updated_at": utcnow(),
        "mode": "autonomous_commercial_execution_revops",
        "cycle": memory["cycles"],
        "cases_total": len(cases),
        "active_cases": len(active),
        "cases_driven": driven,
        "status_counts": status_counts,
        "inbound": inbound_stats,
        "messages_created": created,
        "primary_case": primary,
        "directive": directive,
        "governance": {
            "max_new_messages_per_tick": MAX_NEW_MESSAGES_PER_TICK,
            "max_rfq_suppliers": MAX_RFQ_SUPPLIERS,
            "contact_rule": "solo email corporativo público verificado; formularios quedan como acción pendiente si no existe ejecutor compatible",
            "evidence_rule": "no inventar requerimientos, precios, cantidades, plazos ni condiciones; usar respuestas y ofertas trazables",
            "negotiation_rule": "negociación autónoma solo no vinculante; no fabricar cotizaciones rivales ni presión falsa",
            "margin_rule": "ante objeción de precio, intentar mejorar costo/condiciones proveedor antes de sacrificar margen comprador",
            "binding_rule": "aceptar términos, emitir orden, contratar, pagar o asumir obligación requiere aprobación humana",
        },
    }
    state["commercial_execution"] = report

    if primary:
        record_decision(
            state,
            engine="Commercial Execution Brain / RevOps",
            object_type="commercial_case",
            object_id=str(primary.get("id")),
            decision=str(primary.get("status") or "active"),
            reason=f"Próxima acción comercial: {primary.get('next_action')}",
            action="negotiate_nonbinding" if primary.get("status") == "nonbinding_negotiation" else "prepare_outreach",
            confidence=0.90,
            evidence_refs=[],
            requires_approval=False,
        )
    return report
