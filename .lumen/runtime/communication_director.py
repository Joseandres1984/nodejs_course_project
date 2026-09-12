from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from autonomy_governor import record_decision


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


PROFILE = {
    "tone": "amable, profesional, claro, breve, humano y contextual",
    "principles": [
        "ser respetuoso sin sonar distante",
        "pedir en lugar de exigir",
        "explicar brevemente el contexto real de la conversación",
        "personalizar con empresa, categoría y evidencia pública cuando exista",
        "hacer un pedido concreto",
        "agradecer el tiempo de la contraparte",
        "evitar presión artificial, manipulación o urgencias inventadas",
        "no prometer condiciones, stock, plazos ni compromisos no verificados",
        "no revelar información innecesaria del comprador a proveedores",
        "respetar inmediatamente bajas y pedidos de no contacto",
    ],
}


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _context(state: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Any]:
    account_id = str(item.get("counterparty_account_id") or "")
    account = next((x for x in state.get("candidate_accounts", []) or [] if str(x.get("id") or "") == account_id), {})
    opportunity_id = str(item.get("opportunity_id") or "")
    opportunity = next((x for x in state.get("market_opportunities", []) or [] if str(x.get("id") or "") == opportunity_id), {})
    deal_id = str(item.get("deal_id") or "")
    deal = next((x for x in state.get("deals", []) or [] if str(x.get("id") or "") == deal_id), {})
    interlocution_id = str(item.get("interlocution_case_id") or "")
    interlocution = next((x for x in state.get("interlocution_cases", []) or [] if str(x.get("id") or "") == interlocution_id), {})
    requirement = interlocution.get("requirement", {}) or {}
    category = _norm(item.get("category") or interlocution.get("category") or opportunity.get("category") or deal.get("need"))

    signal = None
    if account.get("type") == "buyer":
        candidates = [
            x for x in state.get("demand_signals", []) or []
            if str(x.get("account_id") or "") == account_id and float(x.get("score") or 0) >= 75
        ]
        candidates.sort(key=lambda x: float(x.get("score") or 0), reverse=True)
        signal = candidates[0] if candidates else None

    return {
        "company": _norm(account.get("company_name") or account.get("name_hint") or item.get("counterparty")),
        "role": account.get("type"),
        "category": category,
        "demand_title": _norm((signal or {}).get("title"))[:160],
        "delivery_location": _norm(requirement.get("delivery_location"))[:160],
        "quantity": requirement.get("quantity"),
        "unit": _norm(requirement.get("unit")),
    }


def _context_prefix(kind: str, ctx: Dict[str, Any]) -> str:
    category = ctx.get("category") or "este requerimiento"
    demand_title = ctx.get("demand_title")
    location = ctx.get("delivery_location")
    quantity = ctx.get("quantity")
    unit = ctx.get("unit")

    if kind == "buyer_requirement_request":
        if demand_title:
            return (
                f"Tomamos como punto de partida una referencia pública asociada a su organización y vinculada a {category}: “{demand_title}”. "
                "Antes de preparar cualquier alternativa preferimos confirmar con ustedes los datos vigentes y no asumir detalles a partir de una publicación."
            )
        return f"Estamos revisando una necesidad vinculada a {category} y queremos validar con ustedes los datos vigentes antes de preparar alternativas."
    if kind == "supplier_rfq":
        details = []
        if quantity:
            details.append(f"{quantity} {unit}".strip())
        if location:
            details.append(f"entrega en {location}")
        suffix = f" ({'; '.join(details)})" if details else ""
        return f"Estamos trabajando sobre un requerimiento B2B confirmado de {category}{suffix} y buscamos una alternativa técnicamente adecuada y comercialmente comparable."
    if kind == "quote_clarification":
        return f"Estamos normalizando las condiciones de la cotización vinculada a {category} para compararla sin interpretar datos faltantes."
    if kind == "supplier_negotiation":
        return f"Estamos optimizando una oportunidad real de {category} y queremos revisar condiciones sin alterar el alcance técnico confirmado."
    if kind in {"buyer_information_response", "terms_clarification"}:
        return f"Seguimos el caso de {category} y preferimos responder cada punto únicamente con información trazable."
    if kind == "follow_up":
        return f"Retomamos brevemente el caso de {category}, manteniendo como referencia únicamente la información ya conversada."
    return ""


def _friendly_body(kind: str, original: str, counterparty: str, ctx: Dict[str, Any]) -> str:
    original = (original or "").strip()
    name = (counterparty or "").strip()
    greeting = f"Hola, buen día{(' equipo de ' + name) if name else ''}."
    prefix = _context_prefix(kind, ctx)

    if kind == "buyer_intro":
        core = original or "Estamos evaluando una alternativa de abastecimiento que podría resultarles útil. Nos gustaría comprender mejor su necesidad, especificación, volumen, plazo objetivo y condiciones comerciales para preparar una propuesta concreta y relevante."
    elif kind == "supplier_rfq":
        core = original or "Nos gustaría contar con su mejor propuesta comercial. Si es posible, agradeceremos precio, validez, plazo de entrega, condiciones de pago, garantía, origen y documentación técnica disponible."
    elif kind == "buyer_proposal":
        core = original or "Preparamos una propuesta comercial en función de la información confirmada. Quedamos a disposición para revisar cualquier aspecto técnico o comercial que necesiten ajustar."
    elif kind == "follow_up":
        core = original or "Queríamos consultar, cuando tengan un momento, si pudieron revisar nuestro mensaje anterior y si podemos aportar alguna información adicional para facilitar la evaluación."
    else:
        core = original

    low = core.lower()
    replacements = {
        "solicitamos cotización": "nos gustaría solicitar una cotización",
        "agradecemos precio": "si es posible, agradeceremos precio",
        "necesitamos": "nos sería útil contar con",
        "debe": "sería importante que",
        "urgente": "prioritario",
    }
    for old, new in replacements.items():
        if old in low:
            idx = low.find(old)
            core = core[:idx] + new + core[idx + len(old):]
            low = core.lower()

    paragraphs = [greeting]
    if prefix and prefix.lower() not in core.lower():
        paragraphs.append(prefix)
    if core:
        paragraphs.append(core.strip())
    paragraphs.append("Muchas gracias por su tiempo. Quedamos atentos y a disposición.\n\nSaludos cordiales,\nLUMEN B2B")
    return "\n\n".join(paragraphs)


def review_outbox(state: Dict[str, Any]) -> Dict[str, int]:
    outbox = state.setdefault("outbox", [])
    opt_out = {str(x).lower() for x in state.setdefault("opt_out", [])}
    stats = {"reviewed": 0, "polished": 0, "personalized": 0, "blocked_opt_out": 0}

    for item in outbox:
        if item.get("communication_reviewed"):
            continue
        if item.get("status") not in {"ready", "needs_verified_contact"}:
            continue
        stats["reviewed"] += 1
        target = str(item.get("contact") or "").strip().lower()
        if target and target in opt_out:
            item["status"] = "blocked"
            item["communication_reviewed"] = True
            item["communication_note"] = "blocked_opt_out"
            stats["blocked_opt_out"] += 1
            record_decision(
                state, engine="Communication Director", object_type="message", object_id=str(item.get("id") or ""),
                decision="do_not_contact", reason="La contraparte pidió no recibir más comunicaciones.",
                action="block_outbound", confidence=1.0, evidence_refs=[],
            )
            continue

        original = str(item.get("body") or "")
        ctx = _context(state, item)
        polished = _friendly_body(str(item.get("kind") or "general"), original, str(item.get("counterparty") or ""), ctx)
        item["body"] = polished
        item["communication_reviewed"] = True
        item["communication_profile"] = PROFILE["tone"]
        item["communication_context"] = {k: v for k, v in ctx.items() if v not in (None, "", [], {})}
        item["communication_reviewed_at"] = utcnow()
        stats["polished"] += 1
        if ctx.get("category") or ctx.get("demand_title") or ctx.get("delivery_location"):
            stats["personalized"] += 1
        record_decision(
            state, engine="Communication Director", object_type="message", object_id=str(item.get("id") or ""),
            decision="professional_contextual_tone_applied",
            reason="Se aplicó el estándar relacional de LUMEN con contexto verificable de empresa/categoría/demanda cuando estaba disponible, sin presión artificial ni datos inventados.",
            action="polish_outbound_message", confidence=0.98, evidence_refs=[],
        )

    state["communication_policy"] = {**PROFILE, "updated_at": utcnow()}
    state["communication_stats"] = {**stats, "updated_at": utcnow()}
    return stats
